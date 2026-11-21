#!/usr/bin/env python3
"""Интерактивный RAG-чат со стримингом, историей и текстом найденных чанков.

Обе ветки — RAG (/search + /ask_llm_stream) и direct-чат (/chat_stream) — идут
через сервер, поэтому используют один LLM_CONFIG. Своего доступа к LLM-шлюзу у
клиента нет: иначе модель direct-чата бралась бы из .env хоста, а RAG-ветки —
из env контейнера (он фиксируется при создании), и половины молча расходились
по моделям и скорости.

    python3 -m mirea_rag_ros.rag_client
    RAG_API_URL=http://localhost:8090 python3 -m mirea_rag_ros.rag_client
"""
import json
import os
import queue
import re
import secrets
import shutil
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .env import load_env

# .env с токенами OSM/адресом API. Нода грузит его до импорта этого модуля;
# при автономном запуске клиента берём MIREA_RAG_ENV.
_ENV_FILE = os.environ.get("MIREA_RAG_ENV", "").strip()
if _ENV_FILE:
    load_env(_ENV_FILE)
from .nospeak import GROUPS, strip_nospeak, unwrap_nospeak
from .query_normalization import fix_asr_aliases

BASE = os.environ.get("RAG_API_URL", "http://localhost:8090").rstrip("/")

_SESSION_FILE = Path.home() / ".mirea_rag_session"
def _get_session_id() -> str:
    if _SESSION_FILE.exists():
        return _SESSION_FILE.read_text().strip()
    sid = secrets.token_hex(8)
    _SESSION_FILE.write_text(sid)
    return sid
SESSION_ID = _get_session_id()
# История уходит ЦЕЛИКОМ и строго append-only: старые байты не меняются,
# иначе RKLLM не найдёт exact prefix match и пересчитает весь prompt. Поэтому
# историю нельзя ни резать по ходам, ни переформатировать/сжимать старые блоки.
# RAG_CHAT_LOG=путь → в файл дописывается один ЧИТАЕМЫЙ текстовый блок
# на ход: OSM-решение, ветка, найденные чанки, ушедшая история, ответ, тайминги
# (не JSON). RAG_CHAT_DEBUG=1 → тот же блок и в консоль.
RAG_CHAT_LOG = os.environ.get("RAG_CHAT_LOG", "").strip()
RAG_CHAT_DEBUG = os.environ.get("RAG_CHAT_DEBUG", "0").strip().lower() in (
    "1", "true", "yes", "on")
MIN_CONFIDENCE = 0.45  # мин. уверенность поиска, иначе ответ не учитываем
                        # (сверено с серверным guard'ом: config.CONFIDENCE_THRESHOLD
                        # 0.45, шкала Qwen3-0.6B bi / CE-rerank; старая e5-шкала
                        # 0.80 на новом стеке флаговала бы почти всё)

# Политика непроизносимого контента — решение потребителя; сервер её не придумывает,
# а получает в запросе (поле nospeak у /ask, /ask_stream, /ask_llm_stream).
#   strip  (дефолт) — вырезать помеченные группы. Этот клиент печатает текст,
#                     который робот произнесёт вслух, поэтому телефоны/почта/часы
#                     в ответ попадать не должны.
#   unwrap — значение видно, разметка убрана (текстовый UI / отладка).
#   off    — отдать корпус как есть.
# ВАЖНО: фильтр применяется к КОНТЕКСТУ, который уходит в LLM, а не к готовому
# ответу. Если теги доехали до промпта, модель перескажет номер обычной прозой,
# и никакой фильтр вывода его уже не поймает.
NOSPEAK_MODE = os.environ.get("NOSPEAK_MODE", "strip").strip().lower()
if NOSPEAK_MODE not in ("strip", "unwrap", "off"):
    NOSPEAK_MODE = "strip"


def speakable(text: str) -> str:
    """Политика потребителя, применённая к тексту для показа: что видишь = что
    получит модель."""
    if NOSPEAK_MODE == "strip":
        return strip_nospeak(text, GROUPS)
    if NOSPEAK_MODE == "unwrap":
        return unwrap_nospeak(text, GROUPS)
    return text

# --- OSM System One — классификатор «относится ли запрос к РТУ МИРЭА?»
# (off-topic gate). Гонится ПАРАЛLEЛЬНО с RAG-поиском, до отправки на LLM:
# «да» (модель увереннее) → идём по RAG как usual; «нет» → контекст RAG
# пропущен, поток не ждём. Base URL + токен — из окружения (см. .env.example),
# как и LLM. В будущем — локальный инстанс вместо удалёного OSM_BASE_URL.
# В OSM уходит ТОЛЬКО текущая фраза — история диалога не передаётся.
OSM_ENABLED = os.environ.get("OSM_ENABLED", "1").strip().lower() in (
    "1", "true", "yes", "on",
)
OSM_BASE_URL = os.environ.get(
    "OSM_BASE_URL", "https://osm.robotics-rtuitlab.ru/api/v1"
).rstrip("/")
OSM_AUTH_TOKEN = os.environ.get("OSM_AUTH_TOKEN", "")
# kev-0.8b (дефолт): лимит state 4096 символов (серверный). laya-multilingual:
# 512 токена всего и системное затирание МИРЭА-вопросов в «нет» — переключить:
# OSM_MODEL=laya-multilingual (потолок state подтянется из _OSM_STATE_CHARS).
OSM_MODEL = os.environ.get("OSM_MODEL", "kev-0.8b")
# Решение — как choice самой модели: P(да) >= 50% → РТУ МИРЭА, иначе direct-чат
# (argmax для двух классов: да — это да, нет — это нет). Никакого ручного
# сдвига порога: 0.5 по умолчанию, переопределяется OSM_YES_THRESHOLD.
OSM_YES_THRESHOLD = float(os.environ.get("OSM_YES_THRESHOLD", "0.5"))
# Потолок state в символах: длиннее фраза обрезается (для голосового ввода не
# достижимо). Для неизвестных моделей — OSM_MAX_STATE_CHARS.
OSM_MAX_STATE_CHARS = int(os.environ.get("OSM_MAX_STATE_CHARS", "1400"))
# с: максимум ждём классификатор, потом идём по RAG без gating (OSM ~1 с)
OSM_GATE_TIMEOUT = float(os.environ.get("OSM_GATE_TIMEOUT", "3.0"))

# Потолки state в СИМВОЛАХ (серверный лимит OSM): kev-0.8b принимает до 4096
# символов (проверено 2026-11-10); laya-multilingual — 512 токена суммарно,
# ≈750 символов с запасом на схему вопросов.
_OSM_STATE_CHARS = {
    "laya-multilingual": 750,
    "kev-0.8b": 4096,
}

_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, text: str) -> str:
    if not _COLOR or not text:
        return text
    return f"\033[{code}m{text}\033[0m"


def dim(text: str) -> str:
    return _c("2", text)


def bold(text: str) -> str:
    return _c("1", text)


def user_style(text: str) -> str:
    return _c("1;36", text)


def bot_style(text: str) -> str:
    return _c("1;32", text)


def meta_style(text: str) -> str:
    return _c("33", text)


def err_style(text: str) -> str:
    return _c("1;31", text)


def width() -> int:
    return max(60, min(shutil.get_terminal_size((100, 24)).columns, 100))


def wrap(text: str, indent: str = "    ") -> str:
    cols = max(40, width() - len(indent))
    lines = []
    for para in (text or "").splitlines() or [""]:
        if not para.strip():
            lines.append("")
            continue
        lines.extend(textwrap.wrap(para, width=cols) or [""])
    return "\n".join(indent + line if line else "" for line in lines)


def _post_event_stream(url, payload, timeout):
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json", "X-Session-Id": SESSION_ID}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if not data:
                continue
            try:
                yield json.loads(data)
            except ValueError:
                continue


def _log_turn(question: str, osm, branch: str, history: list, answer: str,
              chunks=None, sr=None, stats=None, done=None,
              osm_ms=None, osm_err=None, timings_out=None) -> None:
    """Один читаемый текстовый блок на ход → ``RAG_CHAT_LOG``.

    Видно: решение OSM, какая ветка сработала, что вернул поиск (чанки +
    уверенность), какая история ушла на сервер, ответ бота, тайминги и —
    главное — РЕАЛЬНЫЕ JSON-тела: то, что ушло на OSM-сервер (``osm["request"]``)
    и то, что сервер отправил на LLM-шлюз (``done["llm_body"]``: model,
    temperature, max_tokens, messages — включая system-персону, rag-контекст и
    историю). ``RAG_CHAT_DEBUG=1`` — тот же блок и в консоль.
    """
    if not RAG_CHAT_LOG and not RAG_CHAT_DEBUG:
        return
    hist = history or []
    rag_turns = sum(1 for m in hist
                    if isinstance(m, dict) and m.get("role") == "user"
                    and "\n\nВопрос: " in str(m.get("content") or ""))
    lines = [
        "─" * 66,
        f"{time.strftime('%Y-%m-%d %H:%M:%S')} · «{question}»",
    ]
    if osm:
        probs = osm.get("probabilities") or {}
        prob_s = " · ".join(f"{k} {v:.0%}" for k, v in probs.items()
                            if isinstance(v, (int, float))) or "?"
        dec = "МИРЭА" if osm.get("yes") else "не МИРЭА"
        osm_line = f"  OSM [{osm.get('model')}] {prob_s} → {dec}"
        conf = osm.get("confidence")
        if isinstance(conf, (int, float)):
            osm_line += f" · conf {conf:.0%}"
        if isinstance(osm_ms, (int, float)):
            osm_line += f" · {osm_ms:.0f}мс"
        lines.append(osm_line)
    elif osm_err:
        lines.append(f"  OSM недоступен: {osm_err}")
    lines.append(f"  ветка: {branch}")
    sr_chunks = (sr or {}).get("chunks") if isinstance(sr, dict) else None
    if isinstance(sr, dict) and sr.get("refuse"):
        guarded = "низкая уверенность" if sr["refuse"].get("guarded") else "нет контекста"
        lines.append(f"  поиск: отказ ({guarded})")
    elif sr_chunks:
        conf = sr.get("conf_score")
        conf_s = f" · уверенность {conf:.0%}" if isinstance(conf, (int, float)) else ""
        lines.append(f"  поиск: {len(sr_chunks)} {_chunks_word(len(sr_chunks))}{conf_s}")
        for i, ch in enumerate(sr_chunks[:5], 1):
            score = ch.get("score")
            score_s = f"{score:.0%}" if isinstance(score, (int, float)) else "?"
            title = ch.get("title") or ch.get("section") or "?"
            sec = ch.get("section") or ""
            lines.append(f"    {i}. {score_s}  {title}"
                         + (f"  ({sec})" if sec and sec != title else ""))
    elif chunks:
        lines.append(f"  поиск: {len(chunks)} {_chunks_word(len(chunks))}")
    lines.append(f"  история: {len(hist)} сообщ. ({rag_turns} с фактами)")
    ans = " ".join((answer or "").split())
    if ans:
        lines.append(f"  бот: {ans}")
    tparts = []
    if isinstance(osm_ms, (int, float)):
        tparts.append(f"osm {_fmt_dur(osm_ms / 1000)}")
    if isinstance(stats, dict):
        if isinstance(stats.get("ttft"), (int, float)):
            tparts.append(f"ttft {stats['ttft']:.1f}с")
        if isinstance(stats.get("total"), (int, float)):
            tparts.append(f"llm {stats['total']:.1f}с")
        if stats.get("n_tokens"):
            tparts.append(f"{stats['n_tokens']} ток.")
    if isinstance(done, dict):
        tm = done.get("timings")
        if isinstance(tm, dict):
            for key, label in (("embed", "embed"), ("search", "search"),
                               ("llm_ttft", "prefill"), ("llm_decode", "decode"),
                               ("total", "всего")):
                if isinstance(tm.get(key), (int, float)):
                    tparts.append(f"{label} {_fmt_dur(tm[key])}")
    # Сводный словарь таймингов (с) для вызывающего: нода пишет его в ROS-лог,
    # чтобы разбивка по этапам видна без RAG_CHAT_LOG. retrieval-этапы берём из
    # sr (ответ /search), LLM-этапы — из done; в direct-ветке LLM-цифры из stats.
    if timings_out is not None:
        merged: dict = {}
        if isinstance(sr, dict):
            stm = sr.get("timings")
            if isinstance(stm, dict):
                for k in ("preprocess", "embed", "search"):
                    v = stm.get(k)
                    if isinstance(v, (int, float)):
                        merged[k] = round(v, 3)
        if isinstance(done, dict):
            dtm = done.get("timings")
            if isinstance(dtm, dict):
                for k in ("preprocess", "embed", "search", "prompt",
                          "llm_ttft", "llm_decode", "llm_total", "total"):
                    v = dtm.get(k)
                    if isinstance(v, (int, float)) and k not in merged:
                        merged[k] = round(v, 3)
        if isinstance(stats, dict):
            if isinstance(stats.get("ttft"), (int, float)):
                merged.setdefault("llm_ttft", round(stats["ttft"], 3))
            if isinstance(stats.get("total"), (int, float)):
                merged.setdefault("llm_total", round(stats["total"], 3))
            if stats.get("n_tokens"):
                merged["n_tokens"] = stats["n_tokens"]
        if merged:
            timings_out.update(merged)
    if tparts:
        lines.append("  ⏱ " + " · ".join(tparts))
    # Реальные JSON-тела, ушедшие на сервера.
    osm_body = (osm or {}).get("request") if isinstance(osm, dict) else None
    if isinstance(osm_body, dict):
        lines.append(f"  ОSM-тело  → POST {OSM_BASE_URL}/systemone")
        lines.extend("    " + ln
                     for ln in json.dumps(osm_body, ensure_ascii=False,
                                          indent=2).splitlines())
    llm_body = (done or {}).get("llm_body") if isinstance(done, dict) else None
    if isinstance(llm_body, dict):
        lines.append("  LLM-тело  → POST /chat/completions (шлюз)")
        lines.extend("    " + ln
                     for ln in json.dumps(llm_body, ensure_ascii=False,
                                          indent=2).splitlines())
    block = "\n".join(lines) + "\n"
    if RAG_CHAT_LOG:
        try:
            with open(RAG_CHAT_LOG, "a", encoding="utf-8") as f:
                f.write(block)
        except OSError as e:
            print(err_style(f"  лог не записан: {e}"))
    if RAG_CHAT_DEBUG:
        for ln in lines[1:]:
            print(dim(ln))


def ask_stream(q, history, timeout=300):
    obj = {"question": q, "history": history, "nospeak": NOSPEAK_MODE}
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    yield from _post_event_stream(f"{BASE}/ask_stream", payload, timeout)


def ask(q, history, timeout=300):
    obj = {"question": q, "history": history, "nospeak": NOSPEAK_MODE}
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/ask", data=payload,
        headers={"Content-Type": "application/json", "X-Session-Id": SESSION_ID}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def search(q, history=None, timeout=30):
    """Только ретривал (без LLM): /search → dict с чанками и уверенностью.
    Гонится параллельно с OSM; LLM вызывается только при «да» (/ask_llm_stream).
    История уходит в запрос, чтобы сервер разрешил анафоры в поиске
    («а кто его замы?» → по прошлой реплике о директоре ИИТ)."""
    obj = {"question": q, "history": history or [], "top_k": 6}
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/search", data=payload,
        headers={"Content-Type": "application/json", "X-Session-Id": SESSION_ID}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ask_llm_stream(q, sr, history, timeout=300):
    """LLM-половина двухэтапного пайплайна: /ask_llm_stream по уже найденным
    чанкам (sr — ответ /search). События: token | done | refused | error."""
    obj = {"question": q, "search": sr, "history": history,
           "nospeak": NOSPEAK_MODE}
    if RAG_CHAT_LOG:
        obj["debug"] = True  # done-событие вернёт точное LLM-тело для лога
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    yield from _post_event_stream(f"{BASE}/ask_llm_stream", payload, timeout)


def _osm_questions() -> dict:
    """Фиксированная схема вопросов для OSM.

    Формулировка намеренно короткая: длинный перечислительный список
    («поступление, сессия, стипендия, …») kev-0.8b воспринимает как исчерпывающий
    и уводит в «нет» всё, что в него не попало буквально — например, «Что в РТУ
    МИРЭА происходит интересного?». Проверено: с короткими criteria тот же
    вопрос даёт 66% «да» вместо 34%."""
    return {
        "mirea": {
            "type": "choice",
            "instructions": "Вопрос про университет РТУ МИРЭА (мирэа, мира, вуз)?",
            "criteria": {
                "yes": "вопрос на университетскую тему, РТУ МИРЭА (мирэа, мира, вуз)",
                "not": "обычная беседа, прочие вопросы или посторонние темы",
            },
        }
    }



# Классификатор отвечает на те ключи criteria, что мы послали, — а их язык со
# временем менялся («да»/«нет» → «yes»/«not»). Твёрдиться на одном литерале
# нельзя: probs.get("да") при ответе на английском молча даёт None, решение
# срывается в argmax-фолбэк и сравнивает choice=="да" с ответом "yes" — то есть
# весь трафик уходит как «не МИРЭА». Поэтому ищем ключ/выбор толерантно.
_YES_TOKENS = frozenset({"да", "yes", "так", "true", "1"})


def _is_yes(value) -> bool:
    return isinstance(value, str) and value.strip().lower() in _YES_TOKENS


def _prob_yes(probs: dict) -> float | None:
    for k, v in probs.items():
        if _is_yes(k) and isinstance(v, (int, float)):
            return float(v)
    return None


def _parse_osm_response(data: dict, model: str, request_payload=None) -> dict:
    """Разобрать ответ system-one (HTTP JSON или ROS SystemOne) в наш формат.

    Общий код для API- и локального бэкендов: решение по вероятностям, откат на
    choice, сохранение тела запроса для лога ходов.
    """
    answers = data.get("answers") or {}
    label = next(iter(answers), None)
    ans = answers.get(label) or {} if label else {}
    probs = ans.get("probabilities") or {}
    choice = ans.get("choice")
    p_yes = _prob_yes(probs)
    # Решение совпадает с choice модели: да при P(да) >= 50% (argmax для двух
    # классов). Порог — OSM_YES_THRESHOLD (0.5 по умолчанию). Если вероятностей
    # в ответе нет, откат на choice.
    yes = (p_yes >= OSM_YES_THRESHOLD) if p_yes is not None else _is_yes(choice)
    return {
        "model": data.get("model", model),
        "label": label,
        "choice": choice,
        "yes": yes,
        "p_yes": p_yes,
        "threshold": OSM_YES_THRESHOLD,
        "probabilities": probs,
        "confidence": ans.get("confidence"),
        # Точное JSON-тело, ушедшее на OSM-сервер (для лога ходов).
        "request": request_payload,
    }


def osm_classify(question: str, timeout: float) -> dict:
    """OSM System One — one-shot классификатор. В `state` уходит ТОЛЬКО текущая
    фраза (без истории): относится ли она к РТУ МИРЭА (type: choice yes/not).
    Известные ослышки распознавания («вертумера», «рту мира») чинятся алиасами
    до отправки — иначе гейт отсекает валидные МИРЭА-вопросы как «не МИРЭА».
    Возвращает словарь: {"model", "label", "choice", "yes", "probabilities",
    "confidence"}. Токен и base URL — из окружения; без токена сервер вернёт 401."""
    state = fix_asr_aliases(question)[
        :_OSM_STATE_CHARS.get(OSM_MODEL, OSM_MAX_STATE_CHARS)]
    payload = {"model": OSM_MODEL, "state": state, "questions": _osm_questions()}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if OSM_AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {OSM_AUTH_TOKEN}"
    req = urllib.request.Request(
        f"{OSM_BASE_URL}/systemone",
        data=body,
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return _parse_osm_response(data, OSM_MODEL, payload)


def print_osm(res: dict) -> None:
    """Однорядный вывод: вероятности, принятое решение относительно порога и
    уверенность классификатора (это не вероятность «да» — confidence модели)."""
    probs = res.get("probabilities") or {}
    items = [(k, v) for k, v in probs.items() if isinstance(v, (int, float))]
    items.sort(key=lambda kv: -kv[1])
    prob_s = " · ".join(f"{k} {v:.0%}" for k, v in items) or "?"
    p_yes, thr = res.get("p_yes"), res.get("threshold")
    if isinstance(p_yes, (int, float)) and isinstance(thr, (int, float)):
        sign = "≥" if res.get("yes") else "<"
        verdict = "РТУ МИРЭА" if res.get("yes") else "не МИРЭА"
        dec_s = f" · P(да) {p_yes:.0%} {sign} {thr:.0%} → {verdict}"
    else:
        dec_s = ""
    conf = res.get("confidence")
    conf_s = f" · confidence {conf:.0%}" if isinstance(conf, (int, float)) else ""
    print(dim(f"      OSM [{res.get('model')}] {prob_s}{dec_s}{conf_s}"))


def _chunks_word(n: int) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return "чанк"
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return "чанка"
    return "чанков"


def print_chunks(chunks: list[dict], fusion: str | None = None) -> None:
    if not chunks:
        print(dim("    чанков нет"))
        return
    n = len(chunks)
    print(meta_style(f"Поиск: {n} {_chunks_word(n)}"))
    if fusion == "ltr":
        print(dim("      фьюжен: LTR (LambdaMART)"))
    elif fusion == "rrf":
        print(err_style("      фьюжен: RRF fallback ⚠ (LTR-модель недоступна)"))
    print()
    for i, ch in enumerate(chunks, 1):
        score = ch.get("score")
        score_s = f"{score:.0%}" if isinstance(score, (int, float)) else "?"
        title = ch.get("title") or ch.get("section") or "без названия"
        section = ch.get("section") or ""
        url = ch.get("url") or ""
        head = f"{i}.  {score_s}  {title}"
        print(meta_style("  " + head))
        extra = " · ".join(p for p in (section, url) if p)
        if extra:
            print(dim("     " + extra))
        arms = ch.get("arms")
        if isinstance(arms, dict):
            parts = []
            for key, label in (("D", "dense"), ("Q", "вопрос"), ("S", "предл"),
                               ("B", "bm25"), ("M", "maxsim")):
                v = arms.get(key)
                if isinstance(v, int):
                    parts.append(f"{label}#{v}")
            if arms.get("C"):
                parts.append("★чемпион")
            if parts:
                print(dim("     [" + " · ".join(parts) + "]"))
        text = speakable((ch.get("text") or "").strip())
        if text:
            print(dim(wrap(text, indent="     ")))
        else:
            print(dim("     (текст чанка не пришёл — пересоберите API)"))
        print()


def print_sources_fallback(sources: list[dict]) -> None:
    print(meta_style("Поиск: источники (без текста чанка)"))
    print()
    for i, s in enumerate(sources, 1):
        score = s.get("score")
        score_s = f"{score:.0%}" if isinstance(score, (int, float)) else "?"
        title = s.get("title") or s.get("url") or "источник"
        print(meta_style(f"  {i}.  {score_s}  {title}"))
        if s.get("url"):
            print(dim(f"     {s['url']}"))
    print()


def _fmt_dur(v) -> str:
    if not isinstance(v, (int, float)):
        return "—"
    if v < 1:
        return f"{v * 1000:.0f}мс"
    return f"{v:.2f}с"


def _print_timings(timings) -> None:
    """Однорядная разбивка задержки по этапам (приходит в поле `timings`)."""
    if not isinstance(timings, dict):
        return
    stages = [
        ("preprocess", "preprocess"),
        ("embed", "embed"),
        ("search", "search"),
        ("prompt", "prompt"),
        ("llm_ttft", "prefill"),
        ("llm_decode", "decode"),
    ]
    parts = [f"{label} {_fmt_dur(timings[k])}" for k, label in stages
             if isinstance(timings.get(k), (int, float))]
    if not parts:
        return
    line = "      ⏱ " + " · ".join(parts)
    if isinstance(timings.get("total"), (int, float)):
        line += f" · всего {_fmt_dur(timings['total'])}"
    print(dim(line))


def emit(events, ctx_out=None, on_token=None) -> str:
    """Печатает поток /ask_stream. Возвращает текст ответа для истории.
    Если передан ``ctx_out`` — складывает туда чанки retrieval-события, чтобы
    клиент сохранил RAG-данные хода в историю диалога. ``on_token`` — колбэк
    на каждый сырой кусок ответа (для потокового TTS): получает текст как
    сгенерировала модель, без speakable-фильтрации."""
    answer = ""
    raw = ""  # сырой поток токенов: байт-в-байт как сгенерировала модель.
              # В историю диалога уходит ИМЕННО он — LLM-сервер хранит сырой
              # текст и сверяет прошлые реплики побайтово (prefix-кэш). Любой
              # _format_answer/speakable/strip на этом месте даёт mismatch и
              # полный пересчёт префилла на следующем ходе.
    n_tokens = 0
    started = False
    # Потоковый TTS (on_token): токены НЕ печатаются по одному — незавершённая
    # строка «Бот: …» рвалась бы логами ноды. Ответ выводится целиком в done.
    stream_mode = on_token is not None
    confidence = None
    retrieval_time = None
    t0 = time.time()
    while True:
        ev = events.get()
        if ev is None:
            break
        etype = ev.get("type")
        if etype == "retrieval":
            retrieval_time = round(time.time() - t0, 2)
            chunks = ev.get("chunks") or []
            if ctx_out is not None:
                ctx_out.extend(chunks)
            if chunks:
                print_chunks(chunks, ev.get("fusion"))
            else:
                print_sources_fallback(ev.get("sources") or [])
            if not stream_mode:
                print(bot_style("Бот:"), end="  ", flush=True)
                started = True
        elif etype == "token":
            piece = ev.get("content", "")
            answer += piece
            raw += piece
            if on_token is not None:
                on_token(piece)
            if not stream_mode:
                if not started:
                    print(bot_style("Бот:"), end="  ", flush=True)
                    started = True
                print(piece, end="", flush=True)
            n_tokens += 1
        elif etype == "done":
            if n_tokens == 0 and ev.get("answer"):
                answer = speakable(ev["answer"])
                if on_token is not None:
                    on_token(ev["answer"])
                if started:
                    print(answer)
                else:
                    print(bot_style("Бот:"), answer)
            elif not started:
                answer = speakable(ev.get("answer") or answer)
                if on_token is not None and n_tokens == 0 and ev.get("answer"):
                    on_token(ev["answer"])
                print(bot_style("Бот:"), answer)
            else:
                print()
            conf = ev.get("confidence_score")
            parts = []
            if isinstance(conf, (int, float)):
                confidence = conf
                parts.append(f"уверенность {conf:.0%}")
            ttft = ev.get("ttft")
            if isinstance(ttft, (int, float)):
                parts.append(f"первый токен {ttft:.1f} с")
            gen = ev.get("generation_time")
            if isinstance(gen, (int, float)):
                parts.append(f"{gen:.1f} с")
            if n_tokens:
                parts.append(f"{n_tokens} ток.")
            if isinstance(retrieval_time, (int, float)):
                parts.append(f"поиск {retrieval_time} с")
            if parts:
                print(dim("      " + " · ".join(parts)))
            _print_timings(ev.get("timings"))
            if isinstance(confidence, (int, float)) and confidence < MIN_CONFIDENCE:
                print(err_style(f"      уверенность {confidence:.0%} < {MIN_CONFIDENCE:.0%} — ответ не по надежности"))
            if ev.get("answer"):
                answer = speakable(ev["answer"])
        elif etype == "refused":
            chunks = ev.get("chunks") or []
            if chunks:
                print_chunks(chunks, ev.get("fusion"))
            answer = speakable(ev.get("answer") or "(пусто)")
            if on_token is not None and ev.get("answer"):
                on_token(ev["answer"])
            conf = ev.get("confidence_score")
            if isinstance(conf, (int, float)):
                confidence = conf
            print(bot_style("Бот:"), answer)
            if ev.get("confidence_guarded"):
                print(meta_style("      ответ не сгенерирован: низкая уверенность поиска"))
            if isinstance(confidence, (int, float)) and confidence < MIN_CONFIDENCE:
                print(err_style(f"      уверенность {confidence:.0%} < {MIN_CONFIDENCE:.0%} — ответ не по надежности"))
            if isinstance(retrieval_time, (int, float)):
                print(dim(f"      поиск {retrieval_time} с"))
            _print_timings(ev.get("timings"))
        elif etype == "error":
            print()
            print(err_style(f"ошибка  {ev.get('error')}"))
        else:
            print(dim(f"[событие] {ev}"))
    print(dim("─" * min(width(), 72)))
    return raw if raw else answer.strip()


def _emit_ask_fallback(q: str, history: list, events: "queue.Queue") -> None:
    """Фолбак, когда /ask_stream недоступен (404): гоним обычный /ask и эмулируем
    события потока, чтобы emit напечатал чанки + ответ как обычно."""
    try:
        data = ask(q, history)
    except Exception as e:
        events.put({"type": "error", "error": str(e)})
        return
    chunks = data.get("chunks") or []
    if chunks:
        events.put({"type": "retrieval", "chunks": chunks})
    elif data.get("sources"):
        events.put({"type": "retrieval", "sources": data["sources"]})
    events.put({"type": "done", "answer": data.get("answer"),
                "confidence_score": data.get("confidence")})


def direct_chat_stream(q: str, history: list, on_token=None) -> tuple[str, dict]:
    """Прямой ответ модели без RAG (вопросы не про РТУ МИРЭА) — через серверный
    /chat_stream. ``on_token`` — колбэк на каждый сырой кусок (потоковый TTS).

    Клиент больше не ходит в LLM-шлюз сам: иначе direct-чат брал модель из
    своего .env, а RAG-ветка — из env контейнера (он фиксируется при создании),
    и половины молча работали на разных моделях. Теперь обе ветки идут через
    один LLM_CONFIG сервера, а персона живёт только в src/rag/answer.py.
    Печатает токены по мере генерации; возвращает (answer, stats, done_ev):
    stats — ttft/total/n_tokens, done_ev — финальное событие (несёт llm_body
    при включённом RAG_CHAT_LOG).
    """
    obj = {"question": q, "history": history}
    if RAG_CHAT_LOG:
        obj["debug"] = True  # done-событие вернёт точное LLM-тело для лога
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    t0 = time.time()
    ttft = None
    n = 0
    answer = ""
    raw = ""  # см. emit(): в историю — только сырой текст модели
    started = False
    gen = None
    done_ev = None
    stream_mode = on_token is not None
    for ev in _post_event_stream(f"{BASE}/chat_stream", payload, 300):
        etype = ev.get("type")
        if etype == "token":
            piece = ev.get("content", "")
            answer += piece
            raw += piece
            if on_token is not None:
                on_token(piece)
            if not stream_mode:
                if not started:
                    started = True
                    ttft = time.time() - t0
                    print(bot_style("Бот:"), end="  ", flush=True)
                print(piece, end="", flush=True)
            n += 1
        elif etype == "done":
            if n == 0 and on_token is not None and ev.get("answer"):
                on_token(ev["answer"])
            if stream_mode or n == 0:
                print(bot_style("Бот:"), speakable(ev.get("answer") or answer))
            else:
                print()
            done_ev = ev
            answer = speakable(ev.get("answer") or answer)
            if isinstance(ev.get("ttft"), (int, float)):
                ttft = ev["ttft"]
            if isinstance(ev.get("generation_time"), (int, float)):
                gen = ev["generation_time"]
        elif etype == "error":
            print()
            print(err_style(f"ошибка  {ev.get('error')}"))
    total = gen if isinstance(gen, (int, float)) else time.time() - t0
    return (raw if raw else answer.strip(),
            {"ttft": ttft, "total": total, "n_tokens": n},
            done_ev)


# Зеркало серверного _QA_EMPTY_ANSWER_RE: QA-чанк, у которого после nospeak
# пуст ответ («Вопрос: …\nОтвет:»), в промпт не кладём — вопрос без ответа
# провоцирует галлюцинации. Должно совпадать с сервером байт-в-байт.
_QA_EMPTY_ANSWER_RE = re.compile(r"^Вопрос:.*\nОтвет:\s*$", re.DOTALL)


def _build_facts_block(chunks) -> str:
    """Реплицирует серверный _build_context: тот же формат, те же nospeak.

    Возвращает готовый блок «[1] Раздел: ...\n...\n\n---\n\n[2] ...» —
    то, что LLM увидел в live-ходе. Клиент кладёт его дословно в историю,
    чтобы на следующем ходе сервер переиграл байт-в-байт и получил reuse.
    """
    kept = []
    for c in (chunks or []):
        if not isinstance(c, dict):
            continue
        text = str(c.get("text") or "").strip()
        if NOSPEAK_MODE == "strip":
            text = strip_nospeak(text, GROUPS)
        elif NOSPEAK_MODE == "unwrap":
            text = unwrap_nospeak(text, GROUPS)
        text = (text or "").strip()
        if not text or _QA_EMPTY_ANSWER_RE.match(text):
            continue
        section = str(c.get("section") or "")
        url = str(c.get("url") or "")
        header = f"[{len(kept) + 1}]"
        if section:
            header += f" Раздел: {section}"
        if url:
            header += f" Источник: {url}"
        kept.append(f"{header}\n{text}" if (section or url) else text)
    return "\n\n---\n\n".join(kept)


def _history_user_content(query: str, chunks) -> str:
    """Точный текст user-реплики, каким его увидел LLM в live-ходе.

    Зеркалит серверный _build_messages(style=glue): «<материалы>…\\n\\nВопрос: …»,
    а при пустом контексте — голый вопрос. ``query`` должен быть
    ``clean_query`` сервера (нормализованный), а не сырой ввод.
    """
    facts = _build_facts_block(chunks) if chunks else ""
    if not facts:
        return query
    return f"{facts}\n\nВопрос: {query}"


def _emit_rag_two_stage(q: str, history: list, sr: dict,
                        events: "queue.Queue",
                        done_state: dict | None = None,
                        on_token=None,
                        llm_stream=None) -> tuple[str, list | None]:
    """RAG-ветка «да» после /search: печатает чанки, затем стримит LLM
    (/ask_llm_stream или локальный RKLLM) по найденным чанкам. LLM не
    вызывается, если /search отказал (нет контекста / низкая уверенность /
    ошибка пайплайна).

    Возвращает (ответ, чанки этого хода) — чанки уходят в историю диалога.
    ``done_state`` — опциональный dict: туда копируется финальное событие
    done/refused (тайминги), чтобы лог хода получал цифры LLM-фазы.
    ``llm_stream`` — функция (q, sr, history) → итератор событий; по умолчанию
    API-ветка /ask_llm_stream."""
    if llm_stream is None:
        llm_stream = ask_llm_stream
    if sr.get("refuse"):
        refused = {"type": "refused",
                   "answer": sr["refuse"]["answer"],
                   "chunks": sr.get("chunks") or [],
                   "confidence_score": sr.get("conf_score"),
                   "retrieval_scores": sr.get("scores") or [],
                   "confidence_guarded": sr["refuse"].get("guarded", False),
                   "timings": sr.get("timings") or {}}
        if done_state is not None:
            done_state.update(refused)
        events.put(refused)
        events.put(None)
        return emit(events, on_token=on_token), None

    chunks = sr.get("chunks") or []
    events.put({"type": "retrieval",
                "chunks": chunks,
                "fusion": sr.get("fusion"),
                "sources": sr.get("sources") or []})

    def llm_worker():
        try:
            for ev in llm_stream(q, sr, history):
                if done_state is not None and ev.get("type") in ("done", "refused"):
                    done_state.update(ev)
                events.put(ev)
        except Exception as e:
            events.put({"type": "error", "error": str(e)})
        finally:
            events.put(None)

    threading.Thread(target=llm_worker, daemon=True).start()
    return emit(events, on_token=on_token), (chunks or None)


def ask_gated(q: str, history: list, on_token=None,
              backend=None, force_rag: bool = False,
              timings_out=None) -> tuple[str, list | None, str | None]:
    """RAG-поток сквозь OSM-гат, двухэтапный: OSM и /search (только ретривал,
    CPU) гонятся ПАРАЛЛЕЛЬНО, но LLM-запрос уходит ТОЛЬКО если OSM ответил
    «да» (LLM-ветка по найденным чанкам). При «нет» — direct-чат, а слот модели
    на общем LLM-шлюзе свободен. OSM выключен/таймаут/ошибка или /search
    недоступен → полный /ask_stream как usual.

    ``backend`` — обёртка над OSM и LLM (см. ``backends.py``): ``api`` — старый
    HTTP RAG API, ``local`` — локальные ROS OSM (system-one) и RKLLM. По
    умолчанию API-бэкенд, поведение прежнее.

    Возвращает (ответ, чанки_хода, user-реплика_для_истории). Третий элемент —
    дословный текст user-реплики, каким её увидел LLM в этом ходе; клиент кладёт
    его в историю без изменений, чтобы следующий ход совпал по префиксу и
    LLM-сервер отдал reuse KV-кэша. None — LLM не вызывался (отказ/ошибка),
    поэтому историю дополнять нельзя. Факты RAG-хода живут в промпте в
    хронологическом порядке — продолжение («а кто его замы?») отвечается по
    прошлому контексту, а не повторным поиском и не sticky-обходом гейта.
    ``on_token`` — необязательный колбэк на каждый сырой кусок ответа (для
    потокового TTS в ROS-мосте); вызывается синхронно из этого же потока."""
    backend = backend or _API_BACKEND
    events = queue.Queue()
    osm_state = {"res": None, "err": None, "ms": None}
    sr_state = {"res": None, "err": None}
    t_start = time.time()
    gate_timeout = float(backend.osm_gate_timeout)

    def osm_worker():
        if force_rag or not backend.osm_enabled:
            return
        t0 = time.time()
        try:
            osm_state["res"] = backend.osm_classify(q, gate_timeout)
        except Exception as e:
            osm_state["err"] = str(e)
        osm_state["ms"] = round((time.time() - t0) * 1000)

    def search_worker():
        if not backend.search_enabled:
            return
        if not backend.osm_enabled and not force_rag:
            return  # без гата и без force_rag — сразу LLM-ветка
        try:
            sr_state["res"] = backend.search(q, history)
        except Exception as e:
            sr_state["err"] = str(e)

    osm_t = threading.Thread(target=osm_worker, daemon=True)
    sr_t = threading.Thread(target=search_worker, daemon=True)
    osm_t.start()
    sr_t.start()

    if force_rag:
        res = {"yes": True}
        decided = True
    else:
        osm_t.join(gate_timeout + 1.0)
        decided = not osm_t.is_alive()
        res = osm_state.get("res")

    def _direct(branch: str, skip_reason: str | None = None):
        """Ответ без RAG-контекста (OSM «нет» или поиск отключён/недоступен)."""
        if skip_reason:
            print(meta_style(f"      {skip_reason}"))
        try:
            answer, stats, done_ev = backend.chat_stream(q, history, on_token)
        except Exception as e:
            print(err_style(f"      ошибка LLM: {e}"))
            print()
            return "", None, None
        parts = []
        osm_ms = osm_state.get("ms")
        if isinstance(osm_ms, (int, float)):
            parts.append(f"osm {_fmt_dur(osm_ms / 1000)}")
        if stats.get("ttft") is not None:
            parts.append(f"первый токен {stats['ttft']:.1f} с")
        parts.append(f"llm {stats['total']:.1f} с")
        if stats.get("n_tokens"):
            parts.append(f"{stats['n_tokens']} ток.")
        parts.append(f"всего {time.time() - t_start:.1f} с")
        print()
        print(dim("      ⏱ " + " · ".join(parts)))
        print(dim("─" * min(width(), 72)))
        _log_turn(q, res, branch, history, answer,
                  stats=stats, osm_ms=osm_ms, done=done_ev,
                  timings_out=timings_out)
        # direct-чат получает голый вопрос без нормализации, поэтому в
        # историю — дословно q.
        return answer, None, q

    if (backend.osm_enabled or force_rag) and res and decided:
        if not force_rag:
            print_osm(res)
        if not res.get("yes"):
            return _direct(
                f"direct-чат ({backend.name}, RAG пропущен)",
                "запрос не по РТУ МИРЭА — контекст RAG пропущен")

        if not backend.search_enabled:
            return _direct(
                f"direct-чат ({backend.name}, поиск отключён)",
                "RAG-поиск отключён — прямой ответ моделью")

        # «да» — поиск уже гонялся параллельно с OSM, обычно готов
        sr_t.join(15.0)
        if sr_state.get("res") is not None:
            done_state = {}
            sr = sr_state["res"]
            answer, chunks = _emit_rag_two_stage(
                q, history, sr, events, done_state, on_token=on_token,
                llm_stream=backend.ask_llm_stream)
            _log_turn(q, res, f"RAG двухэтапный ({backend.name})",
                      history, answer, sr=sr,
                      done=done_state or None, osm_ms=osm_state.get("ms"),
                      timings_out=timings_out)
            if sr.get("refuse") or done_state.get("type") == "refused":
                # LLM не вызывался — сервер свою историю не менял, значит и
                # клиент не должен её дополнять: иначе на следующем ходе
                # префикс разъедется и reuse не случится.
                return answer, chunks, None
            return (answer, chunks,
                    _history_user_content(sr.get("clean_query") or q, chunks))
        print(dim(f"      /search недоступен ({sr_state.get('err')}) — "
                  f"прямой ответ ({backend.name})"))
        return _direct(f"direct-чат ({backend.name}, /search недоступен)")
    elif backend.osm_enabled and osm_state.get("err"):
        print(dim(f"      OSM недоступен: {osm_state['err']} "
                  f"(фолбэк: {backend.name})"))

    ctx_out: list = []
    done_state = {}

    def _tee(ev):
        if ev.get("type") in ("done", "refused"):
            done_state.update(ev)
        events.put(ev)

    def rag_worker_tee():
        try:
            for ev in backend.ask_stream(q, history):
                _tee(ev)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                _emit_ask_fallback(q, history, events)
            else:
                body = e.read().decode("utf-8", errors="replace")[:200]
                _tee({"type": "error",
                      "error": f"ask_stream HTTP {e.code} {body}"})
        except Exception as e:
            _tee({"type": "error", "error": str(e)})
        finally:
            events.put(None)

    rag_t = threading.Thread(target=rag_worker_tee, daemon=True)
    rag_t.start()
    answer = emit(events, ctx_out, on_token)
    _log_turn(q, res, f"полный пайплайн /ask_stream ({backend.name})", history,
              answer, chunks=ctx_out or None, done=done_state or None,
              osm_ms=osm_state.get("ms"), osm_err=osm_state.get("err"),
              timings_out=timings_out)
    if done_state.get("type") == "refused":
        return answer, (ctx_out or None), None
    return (answer, (ctx_out or None),
            _history_user_content(done_state.get("query") or q, ctx_out))


class _ApiBackend:
    """Бэкенд по умолчанию: прежний HTTP RAG API (OSM + поиск + LLM)."""

    name = "api"
    osm_enabled = OSM_ENABLED
    osm_gate_timeout = OSM_GATE_TIMEOUT
    search_enabled = True

    def osm_classify(self, question: str, timeout: float) -> dict:
        return osm_classify(question, timeout)

    def search(self, question: str, history: list) -> dict:
        return search(question, history)

    def ask_llm_stream(self, question: str, sr: dict, history: list):
        return ask_llm_stream(question, sr, history)

    def chat_stream(self, question: str, history: list, on_token=None):
        return direct_chat_stream(question, history, on_token=on_token)

    def ask_stream(self, question: str, history: list):
        return ask_stream(question, history)


_API_BACKEND = _ApiBackend()


def server_model() -> str | None:
    """Модель, которую использует сервер (RAG-ветка). env контейнера
    фиксируется при его СОЗДАНИИ: правка OPENAI_MODEL в .env не попадает в
    работающий контейнер ни до `docker-compose up -d` (restart НЕ перечитывает
    env_file), поэтому direct-чат (клиент читает .env сейчас) и RAG-ветка
    (сервер) могут молча сидеть на разных моделях — отсюда «разные скорости».
    Шапка это показывает, а не прячет."""
    try:
        with urllib.request.urlopen(f"{BASE}/health", timeout=5) as r:
            return ((json.loads(r.read().decode("utf-8")).get("llm") or {})
                    .get("model"))
    except Exception:
        return None


def banner() -> None:
    print(bold("МИРЭА RAG"))
    print(dim(BASE))
    print(dim("Пользователь: — вопрос,  Поиск: — чанки,  Бот: — ответ модели"))
    if OSM_ENABLED:
        print(dim(f"OSM {OSM_BASE_URL}  · гат «про РТУ МИРЭА?» до LLM  (выкл: OSM_ENABLED=0)"))
    print(dim(f"теги непроизносимого: {NOSPEAK_MODE}  (NOSPEAK_MODE=strip|unwrap|off)"))
    sm = server_model()
    if sm:
        print(dim(f"LLM: {sm}  (обе ветки — RAG и direct-чат — через сервер)"))
    print(dim("exit / выход — выйти    /clear — забыть диалог    /help — справку"))
    print()


def main() -> None:
    banner()
    history: list[dict] = []
    while True:
        try:
            q = input(user_style("Пользователь:") + " ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        low = q.lower()
        if low in ("exit", "quit", "выход", "q"):
            break
        if low in ("/help", "help"):
            print(dim("  Вопросы про МИРЭА уходят на API вместе с последними репликами."))
            print(dim("  Перед ответом печатается текст каждого найденного чанка."))
            if OSM_ENABLED:
                print(dim("  До LLM параллельно с поиском гоним OSM: «про РТУ МИРЭА?»."))
                print(dim("  Классифицирует по всему диалогу, а не по одному вопросу."))
                print(dim("  Если нет — контекст RAG пропущен, видно в выводе."))
            print(dim("  Найденные чанки сохраняются в истории хода дословно "
                     "и идут в промпт в хронологическом порядке — продолжения "
                     "отвечаются по прошлому контексту."))
            print(dim("  История уходит целиком (без окна по ходам). "
                      "Лог ходов в текст (OSM, ветка, чанки, ответ): "
                      "RAG_CHAT_LOG=path; дублировать в консоль: RAG_CHAT_DEBUG=1."))
            print()
            continue
        if low in ("/clear", "clear"):
            history.clear()
            print(dim("  диалог сброшен"))
            print()
            continue

        print()
        try:
            answer, _rag_ctx, hist_user = ask_gated(q, history)
        except Exception as e:
            print(err_style(f"ошибка  {e}"))
            print()
            continue

        if answer and hist_user is not None:
            # В историю — дословно то, что видел LLM: user-реплика уже
            # собрана (нормализованный запрос + блок материалов в серверном
            # формате), assistant-реплика — сырой поток токенов. Только так
            # LLM-сервер на следующем ходу узнаёт префикс и отдаёт reuse.
            history.append({"role": "user", "content": hist_user})
            history.append({"role": "assistant", "content": answer})
        print()


if __name__ == "__main__":
    main()
