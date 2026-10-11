"""rkllm (ChatCompletion) + Paroli /speak: стрим, очередь фраз, прерывание диалога."""

from __future__ import annotations

import re
import unicodedata
from collections import deque
from typing import List, Optional, Tuple

from rclpy.action import ActionClient
from rclpy.node import Node
from paroli_ros2.srv import Speak
from rkllm_ros2.action import ChatCompletion
from std_srvs.srv import Trigger


class LlmCommands:
    """LLM+Paroli; параметры на node должны быть объявлены до __init__."""

    def __init__(self, node: Node) -> None:
        self._node = node
        rkllm_action = (
            node.get_parameter('rkllm_complete_action').get_parameter_value().string_value or ''
        ).strip()
        clear_kv_name = (
            node.get_parameter('rkllm_clear_kv_service').get_parameter_value().string_value or ''
        ).strip()
        paroli_name = (
            node.get_parameter('paroli_speak_service').get_parameter_value().string_value or ''
        ).strip()
        stop_speech_name = (
            node.get_parameter('paroli_stop_speech_service').get_parameter_value().string_value or ''
        ).strip()

        self._rkllm_wait_sec = node.get_parameter('rkllm_wait_server_sec').get_parameter_value().double_value
        if self._rkllm_wait_sec <= 0.0:
            self._rkllm_wait_sec = 5.0
        self._paroli_wait_sec = node.get_parameter('paroli_wait_service_sec').get_parameter_value().double_value
        if self._paroli_wait_sec <= 0.0:
            self._paroli_wait_sec = 3.0

        self._rkllm_keep_history = (
            node.get_parameter('rkllm_keep_history').get_parameter_value().bool_value
        )
        self._rkllm_clear_kv_before = (
            node.get_parameter('rkllm_clear_kv_before_query').get_parameter_value().bool_value
        )
        self._rkllm_max_new_tokens = (
            node.get_parameter('rkllm_max_new_tokens').get_parameter_value().integer_value
        )
        self._llm_stream_tts_enabled = (
            node.get_parameter('llm_stream_tts_by_punctuation').get_parameter_value().bool_value
        )
        self._llm_sanitize_enabled = (
            node.get_parameter('llm_sanitize_user_and_reply').get_parameter_value().bool_value
        )
        mc = node.get_parameter('llm_stream_min_chunk_chars').get_parameter_value().integer_value
        self._llm_stream_min_chunk_chars = max(1, int(mc))
        self._llm_reply_log_max_chars = int(
            node.get_parameter('llm_reply_log_max_chars').get_parameter_value().integer_value
        )
        self._paroli_speak_log_max_chars = int(
            node.get_parameter('paroli_speak_log_max_chars').get_parameter_value().integer_value
        )

        self._panda_llm_tts_enabled = (
            node.get_parameter('panda_llm_tts_enabled').get_parameter_value().bool_value
        )
        self._panda_llm_trigger = (
            node.get_parameter('panda_llm_trigger_substring').get_parameter_value().string_value
            or ''
        ).strip()

        self._rkllm_action_client: Optional[ActionClient] = (
            ActionClient(node, ChatCompletion, rkllm_action) if rkllm_action else None
        )
        self._clear_kv_client = (
            node.create_client(Trigger, clear_kv_name) if clear_kv_name else None
        )
        self._paroli_speak_client = (
            node.create_client(Speak, paroli_name) if paroli_name else None
        )
        self._paroli_stop_client = (
            node.create_client(Trigger, stop_speech_name) if stop_speech_name else None
        )

        self._panda_dialog_busy = False
        self._abort_dialog = False
        self._rkllm_goal_handle = None
        self._tts_chunk_queue: deque = deque()
        self._tts_inflight = False
        self._stream_flush_upto = 0
        self._llm_stream_complete = False
        self._tts_session = 0
        self._tts_paroli_seq = 0

    @property
    def busy(self) -> bool:
        return self._panda_dialog_busy

    @property
    def enabled_trigger(self) -> str:
        return self._panda_llm_trigger

    @property
    def enabled(self) -> bool:
        return bool(self._panda_llm_tts_enabled and self._panda_llm_trigger)

    @property
    def rkllm_client_ok(self) -> bool:
        return self._rkllm_action_client is not None

    @property
    def paroli_client_ok(self) -> bool:
        return self._paroli_speak_client is not None

    def sanitize_llm_text(self, s: Optional[str]) -> str:
        if s is None:
            return ''
        if not self._llm_sanitize_enabled:
            return str(s).strip()
        s = unicodedata.normalize('NFKC', str(s))
        out: List[str] = []
        for ch in s:
            cat = unicodedata.category(ch)
            if cat.startswith('L') or cat.startswith('N') or cat.startswith('P') or cat.startswith('Z'):
                out.append(ch)
            elif cat.startswith('M'):
                out.append(ch)
        t = ' '.join(''.join(out).split())
        t = re.sub(r'[*_`#|]+', ' ', t)
        t = re.sub(r'\s+', ' ', t).strip()
        return t

    def should_run(self, text: str) -> bool:
        if not self._panda_llm_tts_enabled:
            return False
        if not self._panda_llm_trigger:
            return False
        if self._rkllm_action_client is None or self._paroli_speak_client is None:
            return False
        return self._panda_llm_trigger.lower() in (text or '').lower()

    def log_startup_summary(self) -> None:
        log = self._node.get_logger()
        if self.enabled:
            log.info(
                f'LLM+Paroli: вкл; триггер подстрока {self._panda_llm_trigger!r}; '
                f"rkllm={'да' if self._rkllm_action_client else 'нет'} "
                f"paroli={'да' if self._paroli_speak_client else 'нет'}"
            )

    def _log_paroli_speak_payload(self, seq: int, text: str) -> None:
        lim = self._paroli_speak_log_max_chars
        n = len(text)
        if lim <= 0:
            preview = text
            clipped = ''
        else:
            preview = text[:lim]
            clipped = '…' if n > lim else ''
        self._node.get_logger().info(f'Paroli /speak фр.{seq} ({n} симв.): {preview}{clipped}')

    @staticmethod
    def _split_stream_chunks_tail(tail: str, min_chunk: int) -> Tuple[List[str], int]:
        chunks: List[str] = []
        segment_start = 0
        i = 0
        n = len(tail)
        while i < n:
            ch = tail[i]
            is_punct = ch in '.,;:!?…'
            if (
                ch == '.'
                and i > 0
                and i + 1 < n
                and tail[i - 1].isdigit()
                and tail[i + 1].isdigit()
            ):
                is_punct = False
            if (
                ch == ','
                and i > 0
                and i + 1 < n
                and tail[i - 1].isdigit()
                and tail[i + 1].isdigit()
            ):
                is_punct = False
            if is_punct:
                piece = tail[segment_start : i + 1].strip()
                strong = ch in '!?…'
                if piece and (len(piece) >= min_chunk or strong):
                    chunks.append(piece)
                    segment_start = i + 1
                elif not piece:
                    segment_start = i + 1
            i += 1
        return chunks, segment_start

    def _reset_stream_for_new_dialog(self) -> None:
        self._tts_session += 1
        self._tts_chunk_queue.clear()
        self._tts_inflight = False
        self._stream_flush_upto = 0
        self._llm_stream_complete = False
        self._tts_paroli_seq = 0

    def _process_llm_stream_accum(self, raw_accum: str) -> None:
        if self._abort_dialog or not self._llm_stream_tts_enabled:
            return
        clean = self.sanitize_llm_text(raw_accum)
        if len(clean) < self._stream_flush_upto:
            self._stream_flush_upto = 0
        tail = clean[self._stream_flush_upto :]
        chunks, consumed = self._split_stream_chunks_tail(tail, self._llm_stream_min_chunk_chars)
        self._stream_flush_upto += consumed
        for c in chunks:
            self._tts_chunk_queue.append(c)
        if chunks:
            self._node.get_logger().debug(
                f'LLM stream → Paroli: +{len(chunks)} фраз(ы) из накопленного текста'
            )
        self._pump_tts_queue()

    def _finalize_llm_reply_to_tts(self, raw_reply: str) -> None:
        if self._abort_dialog:
            return
        if self._llm_stream_tts_enabled:
            full = self.sanitize_llm_text(raw_reply)
            if len(full) < self._stream_flush_upto:
                self._stream_flush_upto = 0
            tail = full[self._stream_flush_upto :].strip()
            if tail:
                self._tts_chunk_queue.append(tail)
            self._stream_flush_upto = len(full)
        else:
            one = self.sanitize_llm_text(raw_reply).strip() or raw_reply.strip()
            if one:
                self._tts_chunk_queue.append(one)
        self._llm_stream_complete = True
        body = self.sanitize_llm_text(raw_reply).strip()
        pending = len(self._tts_chunk_queue)
        lim = self._llm_reply_log_max_chars
        if lim <= 0:
            preview = body
            clipped = ''
        else:
            preview = body[:lim]
            clipped = '…' if len(body) > lim else ''
        self._node.get_logger().info(
            f'Ответ LLM: {len(body)} симв., в очереди Paroli {pending} фр. '
            f'(в динамик пойдёт текст из строк «Paroli /speak фр.»); '
            f'сводка ответа: {preview}{clipped}'
        )
        self._pump_tts_queue()

    def _pump_tts_queue(self) -> None:
        if self._abort_dialog:
            return
        if self._tts_inflight:
            return
        if not self._tts_chunk_queue:
            self._try_release_after_stream_done()
            return
        cli = self._paroli_speak_client
        if cli is None:
            self._tts_chunk_queue.clear()
            self._llm_stream_complete = True
            self._release_busy()
            return
        if not cli.wait_for_service(timeout_sec=self._paroli_wait_sec):
            self._node.get_logger().warn('Paroli /speak: сервис недоступен')
            self._tts_chunk_queue.clear()
            self._llm_stream_complete = True
            self._release_busy()
            return
        chunk = self._tts_chunk_queue.popleft()
        self._tts_paroli_seq += 1
        self._log_paroli_speak_payload(self._tts_paroli_seq, chunk)
        sid = self._tts_session
        self._tts_inflight = True
        req = Speak.Request()
        req.text = chunk
        req.volume = 1.5
        sfut = cli.call_async(req)

        def _on_done(fut) -> None:
            self._tts_inflight = False
            try:
                res = fut.result()
            except Exception as exc:
                self._node.get_logger().error(f'Paroli speak: {exc}')
                self._pump_tts_queue()
                return
            if sid != self._tts_session:
                self._node.get_logger().debug(
                    f'Paroli speak: ответ для устаревшей сессии {sid} (текущая {self._tts_session}), '
                    'продолжаю очередь'
                )
            elif not res.success:
                self._node.get_logger().warn(f'Paroli speak: {res.message}')
            self._pump_tts_queue()

        sfut.add_done_callback(_on_done)

    def _try_release_after_stream_done(self) -> None:
        if self._abort_dialog:
            return
        if not self._llm_stream_complete:
            return
        if self._tts_inflight or self._tts_chunk_queue:
            return
        self._node.get_logger().info('LLM+Paroli: озвучка завершена, приём команд возобновлён')
        self._release_busy()

    def _rkllm_feedback_callback(self, msg) -> None:
        if self._abort_dialog or not self._llm_stream_tts_enabled:
            return
        acc = getattr(msg.feedback, 'text', None) or ''
        self._process_llm_stream_accum(acc)

    def dispatch(self, user_text: str) -> None:
        self._abort_dialog = False
        self._panda_dialog_busy = True
        self._reset_stream_for_new_dialog()
        self._node.get_logger().info(
            f'LLM+Paroli: триггер по подстроке {self._panda_llm_trigger!r}, запрос к rkllm'
        )
        if self._rkllm_clear_kv_before and self._clear_kv_client is not None:
            if not self._clear_kv_client.wait_for_service(timeout_sec=min(2.0, self._rkllm_wait_sec)):
                self._node.get_logger().warn('clear_kv_cache недоступен, отправляю goal без сброса KV')
                self._send_rkllm_goal(user_text)
                return
            clear_future = self._clear_kv_client.call_async(Trigger.Request())

            def _on_clear_done(_fut) -> None:
                try:
                    _fut.result()
                except Exception as exc:
                    self._node.get_logger().warn(f'clear_kv_cache: {exc}')
                if self._abort_dialog:
                    self._release_busy()
                    return
                self._send_rkllm_goal(user_text)

            clear_future.add_done_callback(_on_clear_done)
        else:
            self._send_rkllm_goal(user_text)

    def _send_rkllm_goal(self, user_text: str) -> None:
        if self._abort_dialog:
            self._release_busy()
            return
        cli = self._rkllm_action_client
        if cli is None:
            self._release_busy()
            return
        if not cli.wait_for_server(timeout_sec=self._rkllm_wait_sec):
            self._node.get_logger().warn('rkllm ChatCompletion: сервер недоступен (таймаут)')
            self._release_busy()
            return

        goal = ChatCompletion.Goal()
        raw_msg = (user_text or '').strip()
        if self._llm_sanitize_enabled:
            sm = self.sanitize_llm_text(raw_msg)
            if not sm and raw_msg:
                self._node.get_logger().warn(
                    'После санитизации user_message пуст — отправляю усечённый исходный текст'
                )
                sm = raw_msg[:4000]
            goal.user_message = (sm.strip() or raw_msg[:4000] or ' ').strip() or ' '
        else:
            goal.user_message = raw_msg or ' '
        goal.keep_history = bool(self._rkllm_keep_history)
        goal.max_new_tokens = int(self._rkllm_max_new_tokens)

        send_future = cli.send_goal_async(goal, feedback_callback=self._rkllm_feedback_callback)

        def _on_goal_sent(fut) -> None:
            try:
                goal_handle = fut.result()
            except Exception as exc:
                self._node.get_logger().error(f'rkllm send_goal: {exc}')
                self._llm_stream_complete = True
                self._release_busy()
                return
            if not goal_handle.accepted:
                self._node.get_logger().warn('rkllm goal отклонён (нода занята или отказ)')
                self._llm_stream_complete = True
                self._release_busy()
                return
            self._rkllm_goal_handle = goal_handle
            result_future = goal_handle.get_result_async()

            def _on_result(rfut) -> None:
                self._rkllm_goal_handle = None
                if self._abort_dialog:
                    return
                try:
                    wrapped = rfut.result()
                    result = wrapped.result
                except Exception as exc:
                    self._node.get_logger().error(f'rkllm result: {exc}')
                    self._llm_stream_complete = True
                    self._try_release_after_stream_done()
                    return
                if not getattr(result, 'success', False):
                    self._node.get_logger().warn(f'rkllm: {getattr(result, "message", "")}')
                    self._llm_stream_complete = True
                    self._try_release_after_stream_done()
                    return
                reply = (getattr(result, 'text', None) or '').strip()
                if not reply:
                    self._node.get_logger().warn('rkllm вернул пустой text')
                    self._llm_stream_complete = True
                    self._try_release_after_stream_done()
                    return
                self._finalize_llm_reply_to_tts(reply)

            result_future.add_done_callback(_on_result)

        send_future.add_done_callback(_on_goal_sent)

    def handle_interrupt(self, source: str) -> None:
        self._node.get_logger().debug(f'Сброс диалога: stop rkllm/Paroli (источник: {source})')
        self._abort_dialog = True
        self._tts_session += 1
        self._tts_chunk_queue.clear()
        self._tts_inflight = False
        self._llm_stream_complete = True
        gh = self._rkllm_goal_handle
        self._rkllm_goal_handle = None
        if gh is not None:
            try:
                gh.cancel_goal_async()
            except Exception as exc:
                self._node.get_logger().warn(f'rkllm cancel_goal: {exc}')
        if self._paroli_stop_client is not None:
            if self._paroli_stop_client.wait_for_service(timeout_sec=0.5):
                self._paroli_stop_client.call_async(Trigger.Request())
        self._release_busy()

    def _release_busy(self) -> None:
        self._panda_dialog_busy = False
