"""Бэкенды OSM и LLM для RAG-моста: ``api`` и ``local``.

``api`` — прежний HTTP RAG API: OSM (/systemone), ретривал (/search) и LLM
(/ask_llm_stream, /chat_stream, /ask_stream) на удалённом сервере.

``local`` — локальный ROS-стек:
  * OSM  — сервис system-one: ``llm_msgs_ros/srv/SystemOne``
           (``/system_one/ask``) или legacy ``/system_one/systemone``
           (``/system_one/ask``); выбирается автоматически/параметром;
  * LLM  — action ``llm_msgs_ros/action/ChatCompletion``
           (``/rkllm_ros/complete``), токены идут в feedback;
  * поиск — локальный BM25 по запечённому bundle
            (``local_search_backend:=bundle``). ``api`` оставляет удалённый
            ``/search``, ``none`` отключает ретривал.

Выбор бэкенда — ROS-параметр ``backend`` у ноды (``api`` по умолчанию).
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
import time
from typing import Iterator

log = logging.getLogger(__name__)

from . import rag_client as rc

# Персона локального RKLLM. Пустая строка — не менять system-промпт ноды RKLLM.
# Согласована с серверным SYSTEM_PROMPT (src/rag/answer.py): сведения — только
# если отвечают на вопрос, нерелевантные не пересказывать, не выдумывать.
DEFAULT_LOCAL_SYSTEM_PROMPT = (
    "Ты - робот-панда, помощник для студентов и абитуриентов РТУ МИРЭА. "
    "Отвечай кратко по-русски, без Markdown и списков: сразу суть. "
    "Используй историю диалога и материалы перед вопросом, только если они "
    "отвечают на текущий вопрос; не пересказывай материалы, которые к нему не относятся. "
    "Если вопрос - продолжение диалога, отвечай по истории. "
    "Не выдумывай имена, должности, даты, телефоны, суммы и адреса. "
    "Если ответа нет, честно скажи, что не знаешь. "
    "Не называй себя ботом и не пиши как языковая модель - ты робот-панда."
)

# Короткая инструкция для RAG-ветки: факты лежат в user-сообщении.
_RAG_INSTRUCTION = (
    "Ответь на текущий вопрос, используя материалы ниже, только если они "
    "отвечают на вопрос. Отвечай кратко, одним-двумя предложениями, без "
    "Markdown, списков и пересказа материалов. Не выдумывай факты. "
    "Если ответа в материалах нет, скажи, что не знаешь."
)


class ApiBackend:
    """Обёртка над прежним HTTP RAG API (поведение не меняется)."""

    name = "api"

    def __init__(self) -> None:
        self.osm_enabled = rc.OSM_ENABLED
        self.osm_gate_timeout = rc.OSM_GATE_TIMEOUT
        self.search_enabled = True

    def osm_classify(self, question: str, timeout: float) -> dict:
        return rc.osm_classify(question, timeout)

    def search(self, question: str, history: list) -> dict:
        return rc.search(question, history)

    def ask_llm_stream(self, question: str, sr: dict, history: list):
        return rc.ask_llm_stream(question, sr, history)

    def chat_stream(self, question: str, history: list, on_token=None):
        return rc.direct_chat_stream(question, history, on_token=on_token)

    def ask_stream(self, question: str, history: list):
        return rc.ask_stream(question, history)

    def reset_history(self) -> None:
        """API-бэкенд stateless: чистится только история в ноде."""
        return

    def describe(self) -> str:
        return (f"api: RAG_API_URL={rc.BASE} · OSM={rc.OSM_MODEL} "
                f"enabled={rc.OSM_ENABLED}")


class LocalBackend:
    """Локальные OSM (ROS-сервис) и LLM (RKLLM action)."""

    name = "local"

    def __init__(
        self,
        node,
        *,
        osm_service: str = "",
        osm_service_type: str = "auto",
        osm_model: str = "kev-0.8b",
        osm_timeout: float = 5.0,
        osm_max_state_chars: int = 0,
        llm_action: str = "/rkllm_ros/complete",
        clear_kv_service: str = "/rkllm_ros/clear_kv_cache",
        llm_keep_history: bool = True,
        clear_kv_before_query: bool = False,
        llm_max_new_tokens: int = 0,
        system_prompt: str = "",
        wait_server_sec: float = 5.0,
        llm_timeout: float = 180.0,
        search_backend: str = "bundle",
        bundle_dir: str = "",
    ) -> None:
        # Импорты ROS — только при создании локального бэкенда: API-режим
        # не требует собранных llm_msgs_ros.
        from rclpy.action import ActionClient
        from rclpy.callback_groups import ReentrantCallbackGroup
        from llm_msgs_ros.action import ChatCompletion
        from llm_msgs_ros.srv import Ask, SystemOne
        from std_srvs.srv import Trigger

        self._node = node
        self._group = ReentrantCallbackGroup()
        self._Ask = Ask
        self._SystemOne = SystemOne
        self._ChatCompletion = ChatCompletion
        self._Trigger = Trigger

        self.osm_enabled = True
        self.osm_gate_timeout = max(0.1, float(osm_timeout))
        self._osm_model = (osm_model or "kev-0.8b").strip()
        self._osm_timeout = max(0.1, float(osm_timeout))
        self._osm_max_state_chars = int(osm_max_state_chars) or \
            rc._OSM_STATE_CHARS.get(self._osm_model, rc.OSM_MAX_STATE_CHARS)

        self._llm_action = llm_action
        self._clear_kv_service = clear_kv_service
        self._llm_keep_history = bool(llm_keep_history)
        self._clear_kv_before_query = bool(clear_kv_before_query)
        self._llm_max_new_tokens = int(llm_max_new_tokens)
        self._system_prompt = (system_prompt or "").strip()
        self._wait_server_sec = max(0.5, float(wait_server_sec))
        self._llm_timeout = max(5.0, float(llm_timeout))

        search_backend = (search_backend or "bundle").strip().lower()
        if search_backend not in ("api", "bundle", "bm25", "local", "none"):
            search_backend = "bundle"
        self._search_backend = search_backend
        self.search_enabled = search_backend != "none"
        self._bundle_dir = (bundle_dir or os.environ.get(
            "MIREA_RAG_BUNDLE", "")).strip()
        self._local_search = None
        self._search_lock = threading.Lock()

        # OSM-клиенты. auto + пустое имя — пробуем оба штатных сервиса;
        # auto + явное имя — клиенты обоих типов на этом имени.
        kind = (osm_service_type or "auto").strip().lower()
        self._osm_clients: list[tuple[str, object]] = []
        if osm_service:
            if kind in ("auto", "ask"):
                self._add_osm("ask", osm_service)
            if kind in ("auto", "systemone"):
                self._add_osm("systemone", osm_service)
            if not self._osm_clients:
                self._add_osm("systemone", osm_service)
        else:
            if kind in ("auto", "ask"):
                self._add_osm("ask", "/system_one/ask")
            if kind in ("auto", "systemone"):
                self._add_osm("systemone", "/system_one/systemone")
            if not self._osm_clients:
                self._add_osm("systemone", "/system_one/systemone")

        self._llm_client = ActionClient(
            node, ChatCompletion, self._llm_action,
            callback_group=self._group)
        self._clear_kv_client = (
            node.create_client(Trigger, clear_kv_service,
                               callback_group=self._group)
            if clear_kv_service else None
        )

    # --- OSM ---------------------------------------------------------------
    def _add_osm(self, kind: str, name: str) -> None:
        srv_type = self._Ask if kind == "ask" else self._SystemOne
        cli = self._node.create_client(
            srv_type, name, callback_group=self._group)
        self._osm_clients.append((kind, cli))

    @staticmethod
    def _safe_ready(cli) -> bool:
        try:
            return bool(cli.service_is_ready())
        except Exception:  # noqa: BLE001 — контекст/граф могут мигнуть
            return False

    def _ready_osm(self, timeout: float) -> list[tuple[str, object]]:
        deadline = time.monotonic() + timeout
        while True:
            ready = [(kind, cli) for kind, cli in self._osm_clients
                     if self._safe_ready(cli)]
            if ready:
                return ready
            if time.monotonic() >= deadline:
                return []
            time.sleep(0.1)

    def _call_service(self, cli, request, timeout: float, label: str):
        if not self._safe_ready(cli):
            raise RuntimeError(f"{label}: сервис недоступен")
        done = threading.Event()
        future = cli.call_async(request)
        future.add_done_callback(lambda _f: done.set())
        if not done.wait(timeout):
            raise RuntimeError(f"{label}: нет ответа за {timeout:.1f} с")
        result = future.result()
        if result is None:
            raise RuntimeError(f"{label}: пустой ответ")
        return result

    def _searcher(self):
        if self._local_search is None:
            with self._search_lock:
                if self._local_search is None:
                    if not self._bundle_dir:
                        raise RuntimeError(
                            "MIREA_RAG_BUNDLE не задан: локальный поиск недоступен")
                    from .local_search import BundleSearcher
                    self._local_search = BundleSearcher(self._bundle_dir)
        return self._local_search

    def search(self, question: str, history: list) -> dict:
        """Ретривал: api — HTTP /search; bundle/bm25/local — локальный BM25."""
        if not self.search_enabled:
            raise RuntimeError("RAG-поиск отключён (local_search_backend:=none)")
        if self._search_backend == "api":
            return rc.search(question, history)
        return self._searcher().search(question, history)

    def osm_ready(self, timeout: float) -> bool:
        """Дождаться, пока ROS-сервис OSM появится в графе."""
        return bool(self._ready_osm(timeout))

    def osm_classify(self, question: str, timeout: float) -> dict:
        state = rc.fix_asr_aliases(question)[:self._osm_max_state_chars]
        candidates = self._ready_osm(min(self._osm_timeout, timeout))
        if not candidates:
            names = ", ".join(str(getattr(cli, "srv_name", "?"))
                              for _k, cli in self._osm_clients) or "—"
            raise RuntimeError(f"локальный OSM недоступен ({names})")

        last_error = "нет ответа"
        for kind, cli in candidates:
            try:
                if kind == "ask":
                    payload = {
                        "model": self._osm_model,
                        "state": state,
                        "questions": rc._osm_questions(),
                    }
                    request = self._Ask.Request()
                    request.request_json = json.dumps(payload, ensure_ascii=False)
                    result = self._call_service(
                        cli, request, self._osm_timeout, "OSM Ask")
                    if not result.success:
                        raise RuntimeError(f"OSM Ask: {result.message}")
                    data = json.loads(result.response_json or "{}")
                    return rc._parse_osm_response(data, self._osm_model, payload)

                question_spec = rc._osm_questions()["mirea"]
                payload = {
                    "model": self._osm_model,
                    "state": state,
                    "questions": {"mirea": question_spec},
                }
                request = self._SystemOne.Request()
                request.model = self._osm_model
                request.state = state
                request.type = "choice"
                request.instructions = question_spec["instructions"]
                request.labels = list(question_spec["criteria"].keys())
                request.descriptions = list(question_spec["criteria"].values())
                result = self._call_service(
                    cli, request, self._osm_timeout, "OSM SystemOne")
                if not result.success:
                    raise RuntimeError(f"OSM SystemOne: {result.message}")
                probabilities = json.loads(result.probabilities_json or "{}")
                data = {
                    "model": self._osm_model,
                    "answers": {"mirea": {
                        "type": "choice",
                        "choice": result.choice,
                        "confidence": result.confidence,
                        "probabilities": probabilities,
                    }},
                }
                return rc._parse_osm_response(data, self._osm_model, payload)
            except Exception as e:  # noqa: BLE001 — пробуем следующий клиент
                last_error = str(e)
        raise RuntimeError(f"локальный OSM: {last_error}")

    # --- LLM ---------------------------------------------------------------
    def _wait_llm_server(self) -> bool:
        deadline = time.monotonic() + self._wait_server_sec
        while time.monotonic() < deadline:
            try:
                if self._llm_client.server_is_ready():
                    return True
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.1)
        return False

    def _clear_kv(self) -> None:
        cli = self._clear_kv_client
        if cli is None:
            return
        request = self._Trigger.Request()
        result = self._call_service(
            cli, request, min(5.0, self._wait_server_sec + 1.0),
            "RKLLM clear_kv")
        if not result.success:
            raise RuntimeError(f"RKLLM clear_kv: {result.message}")

    def warmup_search(self) -> None:
        """Загрузить эмбеддер/индекс заранее, а не на первом вопросе."""
        if not self.search_enabled:
            return
        self._searcher()
        self.search("привет", [])

    def warmup_llm(self) -> None:
        """Короткий goal с system prompt: прогреть и оставить system prompt в KV.

        Dummy-ход минимальный (max_new_tokens=1), чтобы не тратить время;
        system prompt остаётся в KV, и первый реальный вопрос не префилит его заново.
        """
        cli = self._llm_client
        if not self._wait_llm_server():
            raise RuntimeError(f"RKLLM action {self._llm_action} недоступен")
        goal = self._ChatCompletion.Goal()
        goal.user_message = "."
        goal.keep_history = True
        goal.max_new_tokens = 1
        if self._system_prompt:
            goal.system_prompt = self._system_prompt
        send_future = cli.send_goal_async(goal)
        sent = threading.Event()
        send_future.add_done_callback(lambda _f: sent.set())
        if not sent.wait(self._wait_server_sec + 10.0):
            raise RuntimeError("warmup: goal не отправлен")
        handle = send_future.result()
        if handle is None or not handle.accepted:
            raise RuntimeError("warmup: goal отклонён")
        finished = threading.Event()
        handle.get_result_async().add_done_callback(lambda _f: finished.set())
        if not finished.wait(self._llm_timeout):
            raise RuntimeError("warmup: LLM не ответил")

    def _llm_body(self, prompt: str, keep_history: bool) -> dict:
        goal = {
            "user_message": prompt,
            "keep_history": keep_history,
            "max_new_tokens": self._llm_max_new_tokens,
        }
        if self._system_prompt:
            goal["system_prompt"] = self._system_prompt
        return {"backend": "local", "action": self._llm_action, "goal": goal}

    def _llm_events(self, prompt: str) -> Iterator[dict]:
        """Один goal RKLLM → поток событий token/done/error."""
        cli = self._llm_client
        if not self._wait_llm_server():
            yield {"type": "error",
                   "error": f"RKLLM action {self._llm_action} недоступен"}
            return
        if self._clear_kv_before_query:
            try:
                self._clear_kv()
            except Exception as e:  # noqa: BLE001
                yield {"type": "error", "error": str(e)}
                return

        goal = self._ChatCompletion.Goal()
        goal.user_message = (prompt or "").strip() or " "
        goal.keep_history = bool(self._llm_keep_history)
        goal.max_new_tokens = int(self._llm_max_new_tokens)
        if self._system_prompt:
            goal.system_prompt = self._system_prompt

        tokens: queue.Queue = queue.Queue()

        def feedback(msg) -> None:
            token = getattr(msg.feedback, "token", "") or ""
            if token:
                tokens.put(token)

        send_future = cli.send_goal_async(goal, feedback_callback=feedback)
        sent = threading.Event()
        send_future.add_done_callback(lambda _f: sent.set())
        if not sent.wait(self._wait_server_sec + 10.0):
            yield {"type": "error", "error": "RKLLM: goal не отправлен"}
            return
        try:
            goal_handle = send_future.result()
        except Exception as e:  # noqa: BLE001
            yield {"type": "error", "error": f"RKLLM send_goal: {e}"}
            return
        if not goal_handle.accepted:
            yield {"type": "error",
                   "error": "RKLLM goal отклонён (нода занята?)"}
            return

        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(lambda _f: tokens.put(None))
        started = time.monotonic()
        first_token_at = None
        raw = ""
        n_tokens = 0
        while True:
            try:
                item = tokens.get(timeout=1.0)
            except queue.Empty:
                if result_future.done():
                    break
                if time.monotonic() - started > self._llm_timeout:
                    yield {"type": "error",
                           "error": f"RKLLM: нет ответа за {self._llm_timeout:.0f} с"}
                    return
                continue
            if item is None:
                break
            if first_token_at is None:
                first_token_at = time.monotonic()
            raw += item
            n_tokens += 1
            yield {"type": "token", "content": item}

        try:
            result = result_future.result().result
        except Exception as e:  # noqa: BLE001
            yield {"type": "error", "error": f"RKLLM result: {e}"}
            return
        total = time.monotonic() - started
        if not getattr(result, "success", False):
            yield {"type": "error",
                   "error": f"RKLLM: {getattr(result, 'message', 'ошибка')}"}
            return

        answer = (getattr(result, "text", "") or "").strip()
        if not answer:
            answer = raw.strip()
        if answer.startswith(raw) and len(answer) > len(raw):
            tail = answer[len(raw):]
            if tail:
                yield {"type": "token", "content": tail}
        elif not raw and answer:
            yield {"type": "token", "content": answer}

        prefill = float(getattr(result, "prefill_time_ms", 0.0) or 0.0) / 1000.0
        decode = float(getattr(result, "generate_time_ms", 0.0) or 0.0) / 1000.0
        ttft = (first_token_at - started) if first_token_at else (prefill or None)
        yield {
            "type": "done",
            "answer": answer,
            "ttft": ttft,
            "generation_time": decode or total,
            "n_tokens": int(getattr(result, "generate_tokens", 0) or n_tokens),
            "timings": {
                "llm_ttft": ttft,
                "llm_decode": decode,
                "total": total,
            },
            "llm_body": self._llm_body(prompt, bool(self._llm_keep_history)),
        }

    # --- prompts / streams -------------------------------------------------
    @staticmethod
    def _rag_prompt(question: str, sr: dict) -> str:
        chunks = (sr or {}).get("chunks") or []
        facts = rc._build_facts_block(chunks) if chunks else ""
        query = (sr or {}).get("clean_query") or question
        if not facts:
            return query
        return f"{_RAG_INSTRUCTION}\n\n{facts}\n\nВопрос: {query}"

    @staticmethod
    def _history_prompt(question: str, history: list) -> str:
        parts: list[str] = []
        for msg in history or []:
            if not isinstance(msg, dict):
                continue
            role = "Пользователь" if msg.get("role") == "user" else "Ассистент"
            parts.append(f"{role}: {msg.get('content') or ''}")
        parts.append(f"Пользователь: {question}")
        parts.append("Ассистент:")
        return "\n".join(parts)

    def _prompt(self, question: str, history: list, sr: dict | None = None) -> str:
        base = self._rag_prompt(question, sr) if sr is not None else question
        if self._llm_keep_history:
            return base
        return self._history_prompt(base, history)

    def ask_llm_stream(self, question: str, sr: dict, history: list):
        prompt = self._prompt(question, history, sr)
        for event in self._llm_events(prompt):
            if event.get("type") == "done":
                event = dict(event)
                event["confidence_score"] = (sr or {}).get("conf_score")
                event["query"] = (sr or {}).get("clean_query") or question
            yield event

    def chat_stream(self, question: str, history: list, on_token=None):
        prompt = self._prompt(question, history)
        return self._consume(prompt, on_token)

    def ask_stream(self, question: str, history: list):
        prompt = self._prompt(question, history)
        for event in self._llm_events(prompt):
            if event.get("type") == "done":
                event = dict(event)
                event["query"] = question
            yield event

    def _consume(self, prompt: str, on_token=None):
        """Как direct_chat_stream: печать (без on_token) и возврат статистики."""
        answer = ""
        raw = ""
        n_tokens = 0
        started = False
        total_start = time.time()
        stats = {"ttft": None, "total": 0.0, "n_tokens": 0}
        done_event = None
        for event in self._llm_events(prompt):
            etype = event.get("type")
            if etype == "token":
                piece = event.get("content", "")
                answer += piece
                raw += piece
                n_tokens += 1
                if on_token is not None:
                    on_token(piece)
                elif not started:
                    print(rc.bot_style("Бот:"), end="  ", flush=True)
                    started = True
                    print(piece, end="", flush=True)
                else:
                    print(piece, end="", flush=True)
            elif etype == "done":
                done_event = event
                answer = event.get("answer") or answer
                stats["ttft"] = event.get("ttft")
                stats["total"] = (
                    (event.get("timings") or {}).get("total")
                    or event.get("generation_time")
                    or (time.time() - total_start))
                stats["n_tokens"] = event.get("n_tokens") or n_tokens
                if on_token is None:
                    if not started:
                        print(rc.bot_style("Бот:"), answer)
                    else:
                        print()
            elif etype == "error":
                print()
                print(rc.err_style(f"ошибка  {event.get('error')}"))
        return (raw if raw else answer.strip(), stats, done_event)

    def reset_history(self) -> None:
        """Сбросить KV-кэш локальной RKLLM (историю чистит нода)."""
        if self._clear_kv_client is None:
            return
        try:
            self._clear_kv()
            log.info("RKLLM clear_kv: история сброшена")
        except Exception as e:  # noqa: BLE001
            log.warning("RKLLM clear_kv при сбросе истории не сработал: %s", e)

    def describe(self) -> str:
        names = ", ".join(str(getattr(cli, "srv_name", "?"))
                          for _k, cli in self._osm_clients) or "—"
        return (f"local: OSM={names} · RKLLM={self._llm_action} · "
                f"search={self._search_backend}"
                f"({self._bundle_dir or 'bundle не задан'}) · KV="
                f"{'keep' if self._llm_keep_history else 'replay'}")


def create_backend(kind: str, node=None, **kwargs):
    """Фабрика: ``api`` (по умолчанию) или ``local``."""
    kind = (kind or "api").strip().lower()
    if kind in ("api", "http", "remote"):
        return ApiBackend()
    if kind in ("local", "ros", "rkllm"):
        if node is None:
            raise ValueError("локальный backend требует ROS-ноду")
        return LocalBackend(node, **kwargs)
    raise ValueError(f"неизвестный backend: {kind!r} (ожидается api|local)")
