#!/usr/bin/env python3
"""ROS2-нода-мост: микрофонная транскрипция → RAG-ответ робота → TTS.

Цепочка (конвенции взяты из rds_2p_commands/llm_layer_node.py):
    /audio/input/transcription (rds_2p_audio/Transcription, поле .text)  — текст с микрофона
                     │  (наш узел)
                     ▼
    mirea_rag_ros.rag_client.ask_gated(..., on_token=…)  — та же ветка RAG + OSM-гат
                     │  (сырые токены по мере генерации)
                     ▼
    /audio/output/speak (rds_2p_audio/srv/Speak)  — request.text = «кусок», request.volume

Ответ произносится ПОТОКОВО: TtsChunker режет сырой текст на куски по знакам
препинания (первый кусок — первое предложение/запятая, не дожидаясь конца
генерации) и шлёт их в Speak последовательно. Сервис TTS блокирует вызов
до конца озвучки куска, поэтому куски звучат по порядку без наложений.
stream_tts:=false возвращает прежний режим «весь ответ одним вызовом».

Глушение собственного эха (то, что просил заказчик): пока идёт генерация и
произнесение, узел флаг `_busy` и новые транскрипции отбрасывает; в момент,
когда последний кусок произнесён, фиксируется `_speech_end`, и ещё
SPEAK_ECHO_SECONDS (по умолчанию 3 с) любая транскрипция игнорируется — это
«хвост» голоса, который робот поймал своим микрофоном.
"""
import os
import re
import threading
import time
from pathlib import Path

from .env import load_env

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rds_2p_audio.msg import Transcription
from rds_2p_audio.srv import Speak


def _package_dir() -> Path:
    try:
        from ament_index_python.packages import get_package_share_directory
        return Path(get_package_share_directory("mirea_rag_ros"))
    except Exception:
        return Path(__file__).resolve().parent.parent


_PACKAGE_DIR = _package_dir()


def _find_env_file() -> Path | None:
    explicit = os.environ.get("MIREA_RAG_ENV", "").strip()
    candidates = [
        Path(explicit).expanduser() if explicit else None,
        Path.home() / ".config" / "mirea_rag" / "mirea_rag.env",
        _PACKAGE_DIR / "config" / "mirea_rag.env",
        _PACKAGE_DIR / "mirea_rag.env",
    ]
    for path in candidates:
        if not path:
            continue
        try:
            if path.is_file():
                return path
        except OSError:
            # Каталог без прав на обход (например, чужой ~/.config) — не повод
            # падать на старте: пробуем следующий кандидат.
            continue
    return None


_ENV_FILE = _find_env_file()
if _ENV_FILE is not None:
    load_env(_ENV_FILE)

from .rag_client import ask_gated, speakable  # noqa: E402
from . import rag_client as _rc  # noqa: E402  # диагностика конфигурации
from .backends import DEFAULT_LOCAL_SYSTEM_PROMPT, create_backend  # noqa: E402
from .nospeak import ANY_GROUP_RE, GROUPS  # noqa: E402

# Артефакт транскрипции: gigaam слышит «МИРЭА» как «МИРА». В нашем пакете
# нормализуем до канонического написания перед отправкой в RAG.
_MIREA_ARTIFACT = re.compile(r"рту\s+мира", re.IGNORECASE)
_MIREA_CANON = "РТУ МИРЭА"

# Локальные модели иногда отвечают Markdown-разметкой; вслух её читать нельзя.
_TTS_MARKDOWN_RE = re.compile(r"[*_`#>|]+")


def _tts_clean(text: str) -> str:
    text = _TTS_MARKDOWN_RE.sub(" ", text or "")
    return re.sub(r"[ \t]{2,}", " ", text).strip()


class TtsChunker:
    """Сырые токены ответа → куски для TTS по знакам препинания.

    Кусок отрезается на первом знаке препинания (. ! ? … ; : , или перевод
    строки), когда накопилось не меньше min_chars символов — робот начинает
    говорить с первой фразы, не дожидаясь конца генерации. nospeak-теги не
    рвутся: резать можно только там, где все теги закрыты; сам тег фильтруется
    speakable() уже на куске. flush() отдаёт остаток (незакрытый тег в хвосте
    потока отбрасывается).
    """

    _TAG_RE = re.compile(r"</?(?:" + "|".join(GROUPS) + r")>")
    _PUNCT_RE = re.compile(r"[.!?…;:,\n]")

    def __init__(self, min_chars: int = 20) -> None:
        self.min_chars = max(1, int(min_chars))
        self.buf = ""

    def feed(self, piece: str) -> list[str]:
        self.buf += piece
        return self._drain(final=False)

    def flush(self) -> list[str]:
        return self._drain(final=True)

    def _safe_end(self) -> int:
        """Конец префикса, в котором все nospeak-теги закрыты."""
        depth = 0
        open_at = 0
        for m in self._TAG_RE.finditer(self.buf):
            if m.group(0).startswith("</"):
                depth = max(0, depth - 1)
            else:
                if depth == 0:
                    open_at = m.start()
                depth += 1
        return open_at if depth > 0 else len(self.buf)

    def _drain(self, final: bool) -> list[str]:
        out: list[str] = []
        while True:
            safe = self._safe_end()
            region = self.buf[:safe]
            blocks = [(m.start(), m.end())
                      for m in ANY_GROUP_RE.finditer(region)]
            cut = -1
            if final:
                cut = safe
            else:
                for m in self._PUNCT_RE.finditer(region):
                    if m.end() >= self.min_chars and not any(
                            s < m.start() < e for s, e in blocks):
                        cut = m.end()
                        break
            if cut <= 0:
                break
            raw = self.buf[:cut]
            self.buf = self.buf[cut:]
            text = _tts_clean(speakable(raw))
            if text:
                out.append(text)
            if final:
                break
        if final:
            self.buf = ""
        return out


class MireaRagNode(Node):
    def __init__(self) -> None:
        super().__init__("mirea_rag")

        self.declare_parameter("transcription_topic", "/audio/input/transcription")
        self.declare_parameter("speak_service", "/audio/output/speak")
        self.declare_parameter("speak_echo_seconds", 3.0)
        self.declare_parameter("tts_volume", 3.0)
        self.declare_parameter("min_query_chars", 2)
        self.declare_parameter("service_call_timeout", 5.0)
        self.declare_parameter("stream_tts", True)
        self.declare_parameter("tts_min_chunk_chars", 20)
        self.declare_parameter("speak_timeout", 120.0)
        # «Хм...» параллельно с расчётом LLM, чтобы не было тишины.
        self.declare_parameter("filler_enabled", True)
        self.declare_parameter("filler_text", "Хм...")
        # Прогрев тяжёлых моделей при старте, а не на первом вопросе.
        self.declare_parameter("warmup_on_start", True)
        self.declare_parameter("warmup_search", True)
        self.declare_parameter("warmup_llm", True)
        # Реагируем только на обращение по имени (STT путает «панда/банда»).
        self.declare_parameter("wake_word_required", True)
        self.declare_parameter("force_rag", False)
        # OSM-гат «это про МИРЭА?» стоит 1.5–2.5 с. Для wake-word фраз он не нужен:
        # роль гата играет уверенность локального поиска.
        self.declare_parameter("osm_gate_enabled", True)
        self.declare_parameter(
            "wake_word_regex",
            r"(?i)\b(?:панда|панды|панде|панду|пандой|пандою|"
            r"пандочк\w*|банда|банды|банде|банду|бандой|бандою|"
            r"бандочк\w*)\b")
        self.declare_parameter(
            "forget_regex",
            r"(?i)\b(?:забудь|забудьте|сбрось(?:те)? историю|"
            r"очисти(?:те)? историю|сбрось(?:те)? диалог)\b")

        # Бэкенд OSM+LLM: api — прежний HTTP RAG API; local — ROS OSM + RKLLM.
        self.declare_parameter(
            "backend", os.environ.get("MIREA_RAG_BACKEND", "api"))
        self.declare_parameter("local_osm_service", "")
        self.declare_parameter("local_osm_service_type", "auto")
        self.declare_parameter("local_osm_model", "kev-0.8b")
        self.declare_parameter("local_osm_timeout", 5.0)
        self.declare_parameter("local_osm_max_state_chars", 0)
        self.declare_parameter("local_llm_action", "/rkllm_ros/complete")
        self.declare_parameter(
            "local_llm_clear_kv_service", "/rkllm_ros/clear_kv_cache")
        self.declare_parameter("local_llm_keep_history", True)
        self.declare_parameter("local_llm_clear_kv_before_query", False)
        self.declare_parameter("local_llm_max_new_tokens", 0)
        self.declare_parameter("local_llm_system_prompt", "")
        self.declare_parameter("local_llm_wait_server_sec", 5.0)
        self.declare_parameter("local_llm_timeout", 180.0)
        self.declare_parameter(
            "local_bundle_dir",
            os.environ.get("MIREA_RAG_BUNDLE", ""))
        self.declare_parameter("local_search_backend", "bundle")

        self._topic = (self.get_parameter("transcription_topic")
                       .get_parameter_value().string_value)
        self._service = (self.get_parameter("speak_service")
                         .get_parameter_value().string_value)
        self._echo_sec = (self.get_parameter("speak_echo_seconds")
                          .get_parameter_value().double_value)
        self._volume = (self.get_parameter("tts_volume")
                        .get_parameter_value().double_value)
        self._min_chars = (self.get_parameter("min_query_chars")
                           .get_parameter_value().integer_value)
        self._svc_timeout = (self.get_parameter("service_call_timeout")
                             .get_parameter_value().double_value)
        self._stream_tts = (self.get_parameter("stream_tts")
                            .get_parameter_value().bool_value)
        self._min_chunk = (self.get_parameter("tts_min_chunk_chars")
                           .get_parameter_value().integer_value)
        self._speak_timeout = (self.get_parameter("speak_timeout")
                               .get_parameter_value().double_value)
        self._filler_enabled = (self.get_parameter("filler_enabled")
                                .get_parameter_value().bool_value)
        self._filler_text = (self.get_parameter("filler_text")
                             .get_parameter_value().string_value or "").strip()
        self._warmup_enabled = (self.get_parameter("warmup_on_start")
                                .get_parameter_value().bool_value)
        self._warmup_search = (self.get_parameter("warmup_search")
                               .get_parameter_value().bool_value)
        self._warmup_llm = (self.get_parameter("warmup_llm")
                            .get_parameter_value().bool_value)
        self._wake_required = (self.get_parameter("wake_word_required")
                               .get_parameter_value().bool_value)
        self._force_rag = (self.get_parameter("force_rag")
                           .get_parameter_value().bool_value)
        self._osm_gate_enabled = (self.get_parameter("osm_gate_enabled")
                                  .get_parameter_value().bool_value)
        wake_regex = (self.get_parameter("wake_word_regex")
                      .get_parameter_value().string_value or "")
        forget_regex = (self.get_parameter("forget_regex")
                        .get_parameter_value().string_value or "")
        try:
            self._wake_re = re.compile(wake_regex)
        except re.error:
            self._wake_re = re.compile(r"(?i)\b(?:панд|банд)\w*\b")
        try:
            self._forget_re = re.compile(forget_regex)
        except re.error:
            self._forget_re = re.compile(r"(?i)\bзабудь(?:те)?\b")

        self._backend_name = (
            self.get_parameter("backend").get_parameter_value().string_value
            or "api").strip().lower()
        requested_backend = self._backend_name
        local_prompt = (
            self.get_parameter("local_llm_system_prompt")
            .get_parameter_value().string_value or "").strip()
        bundle_dir = (
            self.get_parameter("local_bundle_dir")
            .get_parameter_value().string_value or "").strip()
        if not bundle_dir:
            bundle_dir = os.environ.get("MIREA_RAG_BUNDLE", "") or str(
                _PACKAGE_DIR / "bundle")
        self._backend = None
        try:
            self._backend = create_backend(
                self._backend_name,
                self,
                osm_service=(self.get_parameter("local_osm_service")
                             .get_parameter_value().string_value or "").strip(),
                osm_service_type=(self.get_parameter("local_osm_service_type")
                                  .get_parameter_value().string_value or "auto"),
                osm_model=(self.get_parameter("local_osm_model")
                           .get_parameter_value().string_value or "kev-0.8b"),
                osm_timeout=(self.get_parameter("local_osm_timeout")
                             .get_parameter_value().double_value),
                osm_max_state_chars=(self.get_parameter("local_osm_max_state_chars")
                                     .get_parameter_value().integer_value),
                llm_action=(self.get_parameter("local_llm_action")
                            .get_parameter_value().string_value
                            or "/rkllm_ros/complete"),
                clear_kv_service=(self.get_parameter("local_llm_clear_kv_service")
                                  .get_parameter_value().string_value or ""),
                llm_keep_history=(self.get_parameter("local_llm_keep_history")
                                  .get_parameter_value().bool_value),
                clear_kv_before_query=(
                    self.get_parameter("local_llm_clear_kv_before_query")
                    .get_parameter_value().bool_value),
                llm_max_new_tokens=(self.get_parameter("local_llm_max_new_tokens")
                                    .get_parameter_value().integer_value),
                system_prompt=local_prompt or DEFAULT_LOCAL_SYSTEM_PROMPT,
                wait_server_sec=(self.get_parameter("local_llm_wait_server_sec")
                                 .get_parameter_value().double_value),
                llm_timeout=(self.get_parameter("local_llm_timeout")
                             .get_parameter_value().double_value),
                search_backend=(self.get_parameter("local_search_backend")
                                .get_parameter_value().string_value or "bundle"),
                bundle_dir=bundle_dir,
            )
        except Exception as e:  # noqa: BLE001 — не оставляем ноду без ответов
            self._backend = create_backend("api", self)
            self._backend_name = "api"
            self.get_logger().error(
                f"backend={requested_backend!r} не создан: {e}; "
                "использую api")

        # history живёт в памяти ноды и уходит в RAG целиком (без окна по ходам).
        self.history: list[dict] = []
        self._busy = False
        self._speech_end: float | None = None

        # Reentrant: обработка одного вопроса (сеть, десятки секунд) не блокирует
        # приём транскрипции — она просто отбрасывается флагами _busy/окно-эхо.
        self._group = ReentrantCallbackGroup()
        self._speak_client = self.create_client(
            Speak, self._service, callback_group=self._group)
        self.create_subscription(
            Transcription, self._topic, self._on_transcription, 10,
            callback_group=self._group)

        self.get_logger().info(
            f"мост запущен: {self._topic} → RAG → {self._service} "
            f"(окно эха после фразы {self._echo_sec:.1f} с, "
            f"volume {self._volume}, root={_PACKAGE_DIR})")
        self.get_logger().info(
            f"RAG_API={_rc.BASE} · OSM={_rc.OSM_MODEL} enabled={_rc.OSM_ENABLED} "
            f"· nospeak={_rc.NOSPEAK_MODE} (env: {_ENV_FILE or 'defaults'})")
        self.get_logger().info(f"бэкенд OSM/LLM: {self._backend.describe()}")
        # Стиль подачи фактов зеркалим с сервера (api-режим), иначе префикс
        # разъедется и RKLLM пересчитает весь префилл. В local-режиме /health
        # недоступен — остаётся значение из env или glue.
        if self._backend_name == "api":
            _rc.sync_context_style()
        self.get_logger().info(
            f"bundle для локального режима: {bundle_dir}")
        self.get_logger().info(
            f"wake word: {'вкл' if self._wake_required else 'выкл'} "
            f"({self._wake_re.pattern}) · force_rag={self._force_rag}")
        self.get_logger().info(
            f"поточный TTS: {'вкл' if self._stream_tts else 'выкл'} "
            f"(кусок от {self._min_chunk} симв., таймаут озвучки "
            f"{self._speak_timeout:.0f} с)")
        if self._warmup_enabled:
            threading.Thread(
                target=self._warmup_models, daemon=True,
                name="mirea_rag_warmup").start()

    def _warmup_models(self) -> None:
        """Заранее загрузить/прогреть поиск и LLM, чтобы первый вопрос не ждал."""
        if getattr(self._backend, "osm_enabled", False):
            self.get_logger().info("прогрев: OSM...")
            try:
                self._backend.osm_classify("привет", 5.0)
                self.get_logger().info("прогрев: OSM готов")
            except Exception as e:  # noqa: BLE001
                self.get_logger().warn(f"прогрев OSM не удался: {e}")
        if self._warmup_search and hasattr(self._backend, "warmup_search"):
            self.get_logger().info("прогрев: RAG-поиск...")
            try:
                self._backend.warmup_search()
                self.get_logger().info("прогрев: RAG-поиск готов")
            except Exception as e:  # noqa: BLE001
                self.get_logger().warn(f"прогрев RAG-поиска не удался: {e}")
        if self._warmup_llm and hasattr(self._backend, "warmup_llm"):
            self.get_logger().info("прогрев: LLM...")
            try:
                self._backend.warmup_llm()
                self.get_logger().info("прогрев: LLM готов")
            except Exception as e:  # noqa: BLE001
                self.get_logger().warn(f"прогрев LLM не удался: {e}")
        self.get_logger().info("прогрев моделей завершён")

    # --- приём транскрипции ------------------------------------------------
    @staticmethod
    def _normalize_wake_match(m: re.Match) -> str:
        """Банда/банды/... → Панда/панды/...; «панда» не трогаем."""
        word = m.group(0)
        if not word.lower().startswith("банд"):
            return word
        repl = "панд" + word[4:]
        if word.isupper():
            return repl.upper()
        if word[0].isupper():
            return repl[0].upper() + repl[1:]
        return repl

    def _normalize_wake_word(self, text: str) -> tuple[bool, str]:
        """Вернуть (найдено ли обращение, текст с банда→панда)."""
        if not self._wake_required:
            return True, self._wake_re.sub(self._normalize_wake_match, text)
        found = bool(self._wake_re.search(text))
        if not found:
            return False, text
        return True, self._wake_re.sub(self._normalize_wake_match, text)

    def _reset_history(self) -> None:
        self.history.clear()
        try:
            self._backend.reset_history()
        except Exception as e:  # noqa: BLE001
            self.get_logger().warning(f"сброс KV-кэша не сработал: {e}")

    def _on_transcription(self, msg: Transcription) -> None:
        text = (msg.text or "").strip()
        if not text:
            return
        fixed = _MIREA_ARTIFACT.sub(_MIREA_CANON, text)
        if fixed != text:
            self.get_logger().info(f"Транскрипт: {fixed}  (было: {text})")
        else:
            self.get_logger().info(f"Транскрипт: {text}")
        text = fixed

        now = time.monotonic()
        if self._busy:
            self.get_logger().info(
                f"пропуск: робот говорит/думает, себя не слушаем — «{text}»")
            return
        if (self._speech_end is not None
                and (now - self._speech_end) < self._echo_sec):
            self.get_logger().info(
                f"пропуск: хвост собственной озвучки (окно "
                f"{self._echo_sec:.1f} с, осталось "
                f"{self._echo_sec - (now - self._speech_end):.1f} с) — «{text}»")
            return
        if len(text) < self._min_chars:
            self.get_logger().debug(f"слишком коротко, отброшено: «{text}»")
            return

        if self._forget_re.search(text):
            self.get_logger().info(f"команда сброса истории: «{text}»")
            self._reset_history()
            self._busy = True
            self._speak("История диалога очищена.", text)
            return

        found, question = self._normalize_wake_word(text)
        if not found:
            self.get_logger().info(
                f"пропуск: нет обращения «панда/банда» — «{text}»")
            return
        bare = re.sub(r"\s+", " ", self._wake_re.sub("", question))
        bare = bare.strip(" \t,.;:!?—–-")
        if not bare:
            self.get_logger().info(f"обращение без вопроса: «{text}»")
            self._busy = True
            self._speak("Да?", text)
            return
        if question != text:
            self.get_logger().info(f"вопрос с обращением: «{question}»")

        self._busy = True
        try:
            # Обращение («панда/банда») — это триггер, а не часть вопроса:
            # иначе OSM-гат видит «панда» и чаще отвечает «не МИРЭА»,
            # а поиск получает лишний токен.
            self._process(bare)
        except Exception as e:  # noqa: BLE001 — узел должен пережить любую ошибку
            self._busy = False
            self.get_logger().error(f"ошибка обработки «{text}»: {e}")

    def _start_filler(self, done: threading.Event) -> None:
        """Сказать короткое «Хм...» и не ждать его — LLM считается параллельно."""
        try:
            if not self._filler_enabled or not self._filler_text:
                done.set()
                return
            cli = self._speak_client
            if cli is None or not cli.service_is_ready():
                done.set()
                return
            req = Speak.Request()
            req.text = self._filler_text
            req.volume = self._volume
            self.get_logger().info(
                f"произносим: «{self._filler_text}» (пока LLM считает)")
            future = cli.call_async(req)

            def _finished(fut) -> None:
                done.set()
                try:
                    res = fut.result()
                except Exception as e:  # noqa: BLE001
                    self.get_logger().warn(f"TTS filler: {e}")
                    return
                if res is not None and not res.success:
                    self.get_logger().warn(f"Paroli filler: {res.message}")

            future.add_done_callback(_finished)
        except Exception as e:  # noqa: BLE001
            done.set()
            self.get_logger().warn(f"filler: {e}")

    # --- генерация ответа и произнесение -----------------------------------
    def _process(self, question: str) -> None:
        self.get_logger().info(f"вопрос: «{question}»")
        chunker = TtsChunker(self._min_chunk) if self._stream_tts else None
        spoken_any = False
        filler_done = threading.Event()
        filler_started = False

        def start_filler() -> None:
            nonlocal filler_started
            if filler_started:
                return
            filler_started = True
            self._start_filler(filler_done)

        # «Хм...» сразу при входе в RAG/LLM-ветку, не дожидаясь OSM-гата/поиска:
        # дальше Speak идёт параллельно с классификацией и поиском.
        start_filler()

        def on_token(piece: str) -> None:
            # Вызывается синхронно из ask_gated по мере генерации: кусок,
            # набранный до знака препинания, сразу уходит в TTS. Пока сервис
            # озвучивает его, следующие токены копятся в очереди emit().
            nonlocal spoken_any
            if chunker is None or not piece:
                return
            for chunk in chunker.feed(piece):
                if not spoken_any and not filler_done.is_set():
                    filler_done.wait(timeout=3.0)
                self._speak_chunk(chunk)
                spoken_any = True

        try:
            answer, _rag_ctx, turn_msgs = ask_gated(
                question, self.history, on_token=on_token,
                backend=self._backend, force_rag=self._force_rag,
                on_llm_start=start_filler,
                skip_osm_gate=not self._osm_gate_enabled)
        except Exception as e:  # noqa: BLE001
            if spoken_any:
                self._speech_end = time.monotonic()
            self._busy = False
            self.get_logger().error(f"RAG не ответил на «{question}»: {e}")
            return

        if chunker is not None:
            for chunk in chunker.flush():
                if not spoken_any and not filler_done.is_set():
                    filler_done.wait(timeout=3.0)
                self._speak_chunk(chunk)
                spoken_any = True

        if turn_msgs is not None and answer:
            # В историю — дословно сообщения хода (обычно echo turn_messages с
            # сервера), assistant-реплика — сырой поток токенов. Только так
            # LLM-сервер на следующем ходу узнаёт префикс и отдаёт reuse.
            # Историю не режем и не переформатируем.
            self.history.extend(turn_msgs)
            self.history.append({"role": "assistant", "content": answer})

        if chunker is None:
            # Прежний режим: весь ответ одним асинхронным вызовом.
            if not filler_done.is_set():
                filler_done.wait(timeout=3.0)
            spoken = _tts_clean(speakable(answer or ""))
            if not spoken:
                self.get_logger().warning(f"пустой ответ на «{question}» — не произносим")
                self._busy = False
                return
            self._speak(spoken, question)
            return

        # Всё произнесено синхронно: стартует окно глушения эха.
        self._speech_end = time.monotonic()
        self._busy = False
        if spoken_any:
            self.get_logger().info(
                f"произнесено (вопрос «{question}») — окно эха {self._echo_sec:.1f} с")
        else:
            self.get_logger().warning(f"пустой ответ на «{question}» — не произносим")

    def _speak_chunk(self, text: str) -> None:
        """Синхронный вызов Speak: paroli отдаёт аудио в темпе речи и возвращает
        ответ, когда кусок озвучен, — куски идут строго последовательно."""
        cli = self._speak_client
        if not cli.service_is_ready() and not cli.wait_for_service(
                timeout_sec=self._svc_timeout):
            self.get_logger().error(
                f"сервис {self._service} недоступен — кусок не произнесён: «{text}»")
            return
        req = Speak.Request()
        req.text = text
        req.volume = self._volume
        self.get_logger().info(f"произносим: «{text}»")
        # В Humble у Future.result() нет таймаута: ждём done-колбэк через Event
        # (колбэк исполняется потоком executor'а, группа Reentrant).
        done = threading.Event()
        future = cli.call_async(req)
        future.add_done_callback(lambda _f: done.set())
        if not done.wait(timeout=self._speak_timeout):
            self.get_logger().error(
                f"TTS не ответил за {self._speak_timeout:.0f} с на «{text}»")
            return
        try:
            res = future.result()
        except Exception as e:  # noqa: BLE001
            self.get_logger().error(f"TTS-сервис вернул ошибку на «{text}»: {e}")
            return
        if res is not None and not res.success:
            self.get_logger().warn(f"Paroli speak: {res.message}")

    def _speak(self, text: str, question: str) -> None:
        cli = self._speak_client
        if not cli.service_is_ready() and not cli.wait_for_service(
                timeout_sec=self._svc_timeout):
            self._busy = False
            self.get_logger().error(
                f"сервис {self._service} недоступен — ответ не произнесён: «{text}»")
            return

        req = Speak.Request()
        req.text = text
        req.volume = self._volume
        self.get_logger().info(f"произносим: «{text}»")

        future = cli.call_async(req)
        future.add_done_callback(
            lambda fut, q=question, t=text: self._on_spoken(fut, q, t))

    def _on_spoken(self, future, question: str, text: str) -> None:
        # Произнесение закончилось (TTS-сервис ответил): стартует окно глушения
        # эха, и только теперь узел снова слушает микрофон.
        self._speech_end = time.monotonic()
        self._busy = False
        try:
            res = future.result()
        except Exception as e:  # noqa: BLE001
            self.get_logger().error(f"TTS-сервис вернул ошибку на «{text}»: {e}")
            return
        if res is not None and not res.success:
            self.get_logger().warn(f"Paroli speak: {res.message}")
        else:
            self.get_logger().info(
                f"произнесено (вопрос «{question}») — окно эха {self._echo_sec:.1f} с")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MireaRagNode()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
