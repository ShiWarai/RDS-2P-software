#!/usr/bin/env python3
"""Нода для парсинга команд из Telegram и голосовых расшифровок.

Команды — share/config/commands.yaml; прерывание LLM/озвучки — **panda_dialog_interrupt**; rkllm+Paroli — **llm_commands.py**.
"""

import json
import re
import time
import yaml
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from std_msgs.msg import String
from vosk_ros2.msg import Transcription
from rds_2p_commands.action import PandaCommand
from rds_2p_commands.llm_commands import LlmCommands
from pathlib import Path
from typing import Dict, Optional, Any, Callable
from ament_index_python.packages import get_package_share_directory

# Один класс целей PandaCommand для парсера и unified_action_server (поле command_class в goal flow).
PANDA_GOAL_CLASS = 'motors'


class CommandParserNode(Node):
    """Нода для парсинга и обработки команд."""

    def __init__(self):
        super().__init__('command_parser')

        self.declare_parameter('command_debounce_sec', 3.0)
        self.declare_parameter('config_file', 'commands.yaml')

        self.command_debounce_sec = self.get_parameter('command_debounce_sec').get_parameter_value().double_value

        self.command_config = self._load_command_config()
        self._dialog_interrupt_keywords = self._load_dialog_interrupt_keywords()

        self.command_handlers: Dict[str, Callable] = {}
        self._register_command_handlers()

        self._active_goals_by_class: Dict[str, list] = {}

        self.declare_parameter('allow_parallel_same_class', False)
        self.allow_parallel_same_class = self.get_parameter('allow_parallel_same_class').get_parameter_value().bool_value

        self.declare_parameter('transcription_topics', ['/audio/transcription'])
        transcription_topics_param = self.get_parameter('transcription_topics').get_parameter_value().string_array_value
        if not transcription_topics_param:
            transcription_topics_param = ['/audio/transcription']

        self.telegram_sub = self.create_subscription(
            String,
            '/telegram/message',
            self.telegram_callback,
            10
        )

        self.voice_subs = []
        for topic in transcription_topics_param:
            sub = self.create_subscription(
                Transcription,
                topic,
                self.voice_callback,
                10
            )
            self.voice_subs.append(sub)
            self.get_logger().info(f'Подписка на топик транскрипции: {topic}')

        self.panda_command_action_client = ActionClient(self, PandaCommand, '/robot/panda_command')

        self.declare_parameter('panda_llm_tts_enabled', True)
        self.declare_parameter('panda_llm_trigger_substring', 'панда')
        self.declare_parameter('rkllm_complete_action', '/rkllm_ros2/complete')
        self.declare_parameter('rkllm_clear_kv_service', '/rkllm_ros2/clear_kv_cache')
        self.declare_parameter('paroli_speak_service', '/paroli_ros2/speak')
        self.declare_parameter('paroli_stop_speech_service', '/paroli_ros2/stop_speech')
        self.declare_parameter('rkllm_wait_server_sec', 5.0)
        self.declare_parameter('paroli_wait_service_sec', 3.0)
        self.declare_parameter('rkllm_keep_history', True)
        self.declare_parameter('rkllm_clear_kv_before_query', False)
        self.declare_parameter('rkllm_max_new_tokens', 0)
        self.declare_parameter('llm_stream_tts_by_punctuation', True)
        self.declare_parameter('llm_sanitize_user_and_reply', True)
        self.declare_parameter('llm_stream_min_chunk_chars', 2)
        self.declare_parameter('llm_reply_log_max_chars', 280)
        self.declare_parameter('paroli_speak_log_max_chars', 0)

        self._llm = LlmCommands(self)

        self._debounce_last: Dict[tuple, float] = {}
        self._active_goal_handles: Dict[str, list] = {}

        self.get_logger().info('Command Parser Node запущен')
        self._llm.log_startup_summary()

    def _load_command_config(self) -> Dict[str, Any]:
        """Загрузка конфигурации команд из YAML файла."""
        try:
            config_file = self.get_parameter('config_file').get_parameter_value().string_value
            package_share_dir = get_package_share_directory('rds_2p_commands')
            config_path = Path(package_share_dir) / 'config' / config_file

            if not config_path.exists():
                self.get_logger().warn(
                    f'Конфигурационный файл не найден: {config_path} — команды и panda_dialog_interrupt пусты'
                )
                return {}

            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}

            self.get_logger().info(f'Конфигурация загружена из {config_path}')
            return config

        except Exception as e:
            self.get_logger().error(f'Ошибка при загрузке конфигурации: {e}')
            return {}

    def _load_dialog_interrupt_keywords(self) -> list:
        """Ключевые фразы прерывания: только из panda_dialog_interrupt.keywords в YAML (без запасных в коде)."""
        block = self.command_config.get('panda_dialog_interrupt') or {}
        kws = block.get('keywords') or []
        if isinstance(kws, str):
            kws = [kws]
        return [str(k).strip().lower() for k in kws if str(k).strip()]

    def _register_command_handlers(self):
        """Регистрация обработчиков команд."""
        for cmd_name, cfg in self.command_config.get('commands', {}).items():
            if not cfg.get('keywords'):
                continue
            self.command_handlers[cmd_name] = self.handle_panda_command

    def telegram_callback(self, msg: String):
        """Обработка команд из Telegram."""
        if not msg.data:
            return

        text = msg.data

        text_lower = text.strip().lower()
        if text_lower == 'cancel' or text_lower == 'stop' or text_lower == 'отмена':
            self._handle_cancel_command('telegram')
            return

        try:
            data = json.loads(text)
            if isinstance(data, dict) and 'type' in data:
                message_type = data.get('type')
                if message_type in ['auth_request']:
                    self.get_logger().debug(f'Игнорировано системное сообщение типа: {message_type}')
                    return
        except (json.JSONDecodeError, ValueError):
            pass

        self.process_command(text, source='telegram')

    def voice_callback(self, msg: Transcription):
        """Обработка команд из голосовых расшифровок."""
        if msg.text:
            self.process_command(msg.text, source='voice')

    def _handle_cancel_command(self, source: str):
        """Обрабатывает команду отмены всех активных действий."""
        cancelled_count = 0

        for action_name, goal_handles in self._active_goal_handles.items():
            for goal_handle in goal_handles[:]:
                try:
                    from action_msgs.msg import GoalInfo
                    goal_info = GoalInfo()
                    goal_info.goal_id = goal_handle.goal_id

                    try:
                        if action_name == '/robot/panda_command':
                            self.panda_command_action_client.cancel_goal_async(goal_info)
                            cancelled_count += 1
                    except Exception as e:
                        self.get_logger().warn(f'Ошибка при отмене цели {action_name}: {e}')
                except Exception as e:
                    self.get_logger().warn(f'Ошибка при отмене цели {action_name}: {e}')

        self._active_goal_handles.clear()
        self._active_goals_by_class.clear()

        if cancelled_count > 0:
            self.get_logger().info(f'Отменено {cancelled_count} активных действий (источник: {source})')
        else:
            self.get_logger().info(f'Нет активных действий для отмены (источник: {source})')

    def process_command(self, text: str, source: str = 'unknown'):
        text = text.strip()
        if not text:
            return

        self.get_logger().info(f'Транскрипт ({source}): {text}')

        if self._match_dialog_interrupt(text):
            self.get_logger().info(f'Прерывание диалога по фразе ({source})')
            self._llm.handle_interrupt(source)
            return

        if self._llm.busy:
            self.get_logger().info(
                f'Пропуск ({source}): занят диалог LLM/озвучка Paroli (ключи panda_dialog_interrupt — стоп)'
            )
            return

        self._parse_and_execute_fallback(text, source)

    def _parse_and_execute_fallback(self, text: str, source: str):
        """Парсинг команды по ключевым словам (commands.yaml)."""
        text_lower = text.lower()

        for command_name, command_config in self.command_config.get('commands', {}).items():
            keywords = command_config.get('keywords', [])

            for keyword in keywords:
                if keyword.lower() in text_lower:
                    self.get_logger().info(
                        f'Fallback парсинг определил команду: {command_name} '
                        f'(ключевое слово: {keyword})'
                    )
                    self._execute_command(command_name, text, source)
                    return

        if self._llm.should_run(text):
            self.get_logger().info(
                f'Рутина не распознана, триггер {self._llm.enabled_trigger!r} — только LLM+Paroli'
            )
            self._llm.dispatch(text)
            return

        self.get_logger().debug(f'Не распознано ({source}): {text[:160]}{"…" if len(text) > 160 else ""}')

    def _execute_command(self, command_name: str, text: str, source: str):
        if command_name not in self.command_handlers:
            self.get_logger().error(f'Обработчик для команды "{command_name}" не найден')
            return

        debounce_sec = getattr(self, 'command_debounce_sec', 0.0) or 0.0
        if debounce_sec > 0.0:
            key = (source, command_name)
            now_m = time.monotonic()
            last = self._debounce_last.get(key)
            if last is not None and (now_m - last) < debounce_sec:
                self.get_logger().info(
                    f'Дребезг: пропуск {command_name} из {source} '
                    f'(< {debounce_sec:.2f}s)'
                )
                return
            self._debounce_last[key] = now_m

        command_class = PANDA_GOAL_CLASS

        if not self.allow_parallel_same_class:
            active_goals = self._active_goals_by_class.get(command_class, [])
            if active_goals:
                self.get_logger().warn(
                    f'Команда "{command_name}" (класс "{command_class}") отклонена: '
                    f'уже выполняется {len(active_goals)} команда(ы) того же класса'
                )
                return

        handler = self.command_handlers[command_name]

        parsed_params = self._extract_command_params(command_name, text)
        parsed_params['command_class'] = command_class

        try:
            handler(text, source, parsed_params)
        except Exception as e:
            self.get_logger().error(f'Ошибка при выполнении команды {command_name}: {e}')
            import traceback
            traceback.print_exc()

    def _register_active_goal(self, command_class: str, goal_handle):
        if command_class not in self._active_goals_by_class:
            self._active_goals_by_class[command_class] = []
        self._active_goals_by_class[command_class].append(goal_handle)

    def _unregister_active_goal(self, command_class: str, goal_handle):
        if command_class in self._active_goals_by_class:
            if goal_handle in self._active_goals_by_class[command_class]:
                self._active_goals_by_class[command_class].remove(goal_handle)
            if len(self._active_goals_by_class[command_class]) == 0:
                del self._active_goals_by_class[command_class]

    def _extract_command_params(self, command_name: str, text: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {}

        commands_dict = self.command_config.get('commands', {})
        if command_name not in commands_dict:
            self.get_logger().warn(f'Команда "{command_name}" отсутствует в конфиге')
            return params

        params['routine_id'] = command_name
        return params

    def handle_panda_command(self, text: str, source: str, parsed_params: Dict[str, Any]) -> None:
        routine_id = parsed_params.get('routine_id')
        command_class = parsed_params.get('command_class', PANDA_GOAL_CLASS)

        if not routine_id:
            self.get_logger().error('routine_id отсутствует в параметрах')
            return

        self.get_logger().info(
            f'PandaCommand "{routine_id}" из {source} (класс: {command_class})'
        )

        if not self.panda_command_action_client.wait_for_server(timeout_sec=2.0):
            self.get_logger().error('/robot/panda_command недоступен')
            return

        goal_msg = PandaCommand.Goal()
        goal_msg.routine_id = str(routine_id)
        goal_msg.source = str(source or 'unknown')

        def routine_feedback_cb(fb):
            st = fb.feedback.status
            if isinstance(st, str) and st:
                tail = st[:200] + ('…' if len(st) > 200 else '')
                self.get_logger().info(f'PandaCommand {routine_id} [сервер]: {tail}')

        send_goal_future = self.panda_command_action_client.send_goal_async(
            goal_msg, routine_feedback_cb)
        action_name = '/robot/panda_command'

        def goal_response_callback(future):
            gh = future.result()
            if not gh.accepted:
                self.get_logger().warn(f'PandaCommand {routine_id}: goal отклонён')
                return

            self._register_active_goal(command_class, gh)

            if action_name not in self._active_goal_handles:
                self._active_goal_handles[action_name] = []
            self._active_goal_handles[action_name].append(gh)

            self.get_logger().info(f'PandaCommand {routine_id}: goal принят')

            result_future = gh.get_result_async()

            def result_callback(rf_future):
                if action_name in self._active_goal_handles:
                    if gh in self._active_goal_handles[action_name]:
                        self._active_goal_handles[action_name].remove(gh)
                    if not self._active_goal_handles[action_name]:
                        del self._active_goal_handles[action_name]

                rf = rf_future.result()
                res = rf.result

                self._unregister_active_goal(command_class, gh)
                self.get_logger().info(
                    f'PandaCommand {routine_id}: завершено '
                    f'{getattr(res, "success", False)} ({getattr(res, "message", "")})'
                )

            result_future.add_done_callback(result_callback)

        send_goal_future.add_done_callback(goal_response_callback)
        self.get_logger().info(f'PandaCommand "{routine_id}" goal отправлен (source={source})')

    def _match_dialog_interrupt(self, text: str) -> bool:
        tl = (text or '').lower().strip()
        if not tl:
            return False
        tokens = re.findall(r'\w+', tl, flags=re.UNICODE)
        for kw in self._dialog_interrupt_keywords:
            raw = (kw or '').strip().lower()
            if not raw:
                continue
            if ' ' in raw:
                if raw in tl:
                    return True
                continue
            for i, tok in enumerate(tokens):
                if tok != raw:
                    continue
                if raw == 'хватит' and i > 0 and tokens[i - 1] == 'не':
                    continue
                return True
        return False


def main(args=None):
    rclpy.init(args=args)

    try:
        command_parser = CommandParserNode()
        rclpy.spin(command_parser)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f'\nОшибка: {e}')
        import traceback
        traceback.print_exc()
    finally:
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass


if __name__ == '__main__':
    main()
