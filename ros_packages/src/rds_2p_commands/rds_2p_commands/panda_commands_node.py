#!/usr/bin/env python3
"""
Пресет «Команды Панды»: system_one_ros классифицирует фразу, нода исполняет then-цепочку.

Сценарий — config/panda_commands.yaml. Один POST /v1/systemone на фразу:
choice-варианты собираются из name/examples, ответ маппится обратно на option.id.

Исполнение:
  command -> /robot/panda_command (PandaCommand) или /cmd_vel/voice для motion_commands;
  wait    -> пауза;
  say     -> /paroli_ros/speak.

Launch: ros2 launch rds_2p_commands panda_commands.launch.py
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable

import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import Twist
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from rds_2p_audio.msg import Transcription
from rds_2p_audio.srv import Speak
from rds_2p_commands.action import PandaCommand
from std_msgs.msg import String

from llm_msgs_ros.srv import Ask

DEFAULT_MOTION_COMMANDS = {
    'step_forward': {'linear_x': 1.0, 'duration_sec': 1.8},
    'step_back': {'linear_x': -1.0, 'duration_sec': 1.8},
    'step_left': {'linear_y': 0.8, 'duration_sec': 1.8},
    'step_right': {'linear_y': -0.8, 'duration_sec': 1.8},
    'stop_running': {'stop': True},
}


class PandaCommandsNode(Node):
    """Классификатор и исполнитель дерева сценариев команд Панды."""

    def __init__(self) -> None:
        super().__init__('panda_commands')

        self.declare_parameter('config_file', 'panda_commands.yaml')
        self.declare_parameter('input_topic', '/audio/transcription')
        self.declare_parameter('system_one_service', '/system_one_client/ask')
        self.declare_parameter('model', 'kev-0.8b')
        self.declare_parameter('min_confidence', 0.0)
        self.declare_parameter('timeout_sec', 30.0)
        self.declare_parameter('panda_action', '/robot/panda_command')
        self.declare_parameter('speak_service', '/paroli_ros/speak')
        self.declare_parameter('say_enabled', True)
        self.declare_parameter('publish_cmd_vel', True)
        self.declare_parameter('cmd_vel_topic', '/cmd_vel/voice')
        self.declare_parameter('dry_run', False)
        self.declare_parameter('post_action_cooldown_sec', 1.5)
        self.declare_parameter('interrupt_keywords', 'стоп,хватит')

        self._input_topic = self._param_str('input_topic')
        self._system_one_service = self._param_str('system_one_service')
        self._model = self._param_str('model')
        self._min_confidence = self._param_double('min_confidence')
        self._timeout_sec = max(0.1, self._param_double('timeout_sec'))
        self._panda_action = self._param_str('panda_action')
        self._speak_service = self._param_str('speak_service')
        self._say_enabled = self._param_bool('say_enabled')
        self._dry_run = self._param_bool('dry_run')
        self._cooldown_sec = max(0.0, self._param_double('post_action_cooldown_sec'))
        self._interrupt_keywords = [
            item.strip().lower()
            for item in self._param_str('interrupt_keywords').split(',')
            if item.strip()
        ]

        self._scenario = self._load_scenario()
        self._motion_commands = dict(DEFAULT_MOTION_COMMANDS)
        configured_motion = self._scenario.get('motion_commands')
        if isinstance(configured_motion, dict):
            for name, config in configured_motion.items():
                if isinstance(config, dict):
                    self._motion_commands[str(name)] = config

        self._ask_client = self.create_client(Ask, self._system_one_service)
        self._panda_client = ActionClient(self, PandaCommand, self._panda_action)
        self._speak_client = (
            self.create_client(Speak, self._speak_service)
            if self._say_enabled and self._speak_service else None
        )
        self._cmd_vel_pub = (
            self.create_publisher(Twist, self._param_str('cmd_vel_topic'), 10)
            if self._param_bool('publish_cmd_vel') else None
        )
        decision_qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self._decision_pub = self.create_publisher(String, '~/decision', decision_qos)
        self.create_subscription(
            Transcription, self._input_topic, self._on_transcription, 10)

        self._busy = False
        self._generation = 0
        self._active_goal_handle: Any = None
        self._pending_timers: set = set()
        self._cooldown_until = 0.0

        question_count = sum(
            1 for node in self._scenario.get('then', [])
            if isinstance(node, dict) and node.get('kind') == 'question'
        )
        self.get_logger().info(
            f'panda_commands готов: {self._input_topic} → {self._system_one_service} '
            f'(model={self._model}, вопросов={question_count}, '
            f'dry_run={self._dry_run}, say={"вкл" if self._speak_client else "выкл"})'
        )

    def _param_str(self, name: str) -> str:
        return self.get_parameter(name).get_parameter_value().string_value.strip()

    def _param_double(self, name: str) -> float:
        return self.get_parameter(name).get_parameter_value().double_value

    def _param_bool(self, name: str) -> bool:
        return self.get_parameter(name).get_parameter_value().bool_value

    def _load_scenario(self) -> dict[str, Any]:
        raw = self._param_str('config_file')
        path = Path(raw)
        if not path.is_absolute():
            path = Path(get_package_share_directory('rds_2p_commands')) / 'config' / raw
        try:
            with open(path, encoding='utf-8') as handle:
                document = yaml.safe_load(handle) or {}
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f'Сценарий {path}: {exc}')
            return {'kind': 'start', 'then': []}

        if not isinstance(document, dict) or document.get('kind') != 'start':
            self.get_logger().error(f'Сценарий {path}: ожидается kind: start')
            return {'kind': 'start', 'then': []}
        if not isinstance(document.get('then'), list):
            self.get_logger().error(f'Сценарий {path}: then должен быть списком')
            return {'kind': 'start', 'then': []}
        self.get_logger().info(f'Сценарий загружен из {path}')
        return document

    def _on_transcription(self, msg: Transcription) -> None:
        text = (msg.text or '').strip()
        if not text:
            return

        if self._busy:
            if self._is_interrupt(text):
                self._interrupt(text)
            else:
                self.get_logger().info('Пропуск: выполняется сценарий')
            return

        if time.monotonic() < self._cooldown_until:
            self.get_logger().info('Пропуск: пауза после сценария')
            return

        self._busy = True
        self._generation += 1
        generation = self._generation
        self.get_logger().info(f'Транскрипт: {text}')
        self._run_chain(
            self._scenario.get('then', []), text, generation, 0,
            lambda: self._finish(generation),
        )

    def _finish(self, generation: int) -> None:
        if generation != self._generation:
            return
        self._busy = False
        self._cooldown_until = time.monotonic() + self._cooldown_sec
        self.get_logger().info('Сценарий завершён')

    def _is_interrupt(self, text: str) -> bool:
        lowered = text.lower().strip()
        if not lowered:
            return False
        tokens = re.findall(r'\w+', lowered, flags=re.UNICODE)
        for keyword in self._interrupt_keywords:
            if ' ' in keyword:
                if keyword in lowered:
                    return True
                continue
            for index, token in enumerate(tokens):
                if token != keyword:
                    continue
                if keyword == 'хватит' and index > 0 and tokens[index - 1] == 'не':
                    continue
                return True
        return False

    def _interrupt(self, text: str) -> None:
        self._generation += 1
        self._cancel_pending()
        goal = self._active_goal_handle
        self._active_goal_handle = None
        if goal is not None:
            try:
                goal.cancel_goal_async()
            except Exception as exc:  # noqa: BLE001
                self.get_logger().warn(f'Отмена PandaCommand: {exc}')
        self._publish_stop()
        self._busy = False
        self._cooldown_until = time.monotonic() + self._cooldown_sec
        self.get_logger().warn(f'Прерывание ({text!r}): сценарий остановлен')

    def _cancel_pending(self) -> None:
        for timer in list(self._pending_timers):
            try:
                timer.cancel()
                self.destroy_timer(timer)
            except Exception:  # noqa: BLE001
                pass
        self._pending_timers.clear()

    def _schedule(self, delay_ms: float, callback: Callable[[], None]) -> None:
        if delay_ms <= 0.0:
            callback()
            return
        timer = None

        def on_timer() -> None:
            nonlocal timer
            if timer is not None:
                try:
                    timer.cancel()
                    self.destroy_timer(timer)
                except Exception:  # noqa: BLE001
                    pass
                self._pending_timers.discard(timer)
            callback()

        timer = self.create_timer(delay_ms / 1000.0, on_timer)
        self._pending_timers.add(timer)

    def _publish_stop(self) -> None:
        if self._cmd_vel_pub is None:
            return
        self._cmd_vel_pub.publish(Twist())
        self.get_logger().debug('cmd_vel: стоп')

    def _run_chain(
        self, nodes: list[Any], state_text: str, generation: int,
        index: int, done: Callable[[], None],
    ) -> None:
        if generation != self._generation:
            return
        if index >= len(nodes):
            done()
            return

        node = nodes[index]
        if not isinstance(node, dict):
            self._run_chain(nodes, state_text, generation, index + 1, done)
            return

        def next_node() -> None:
            self._run_chain(nodes, state_text, generation, index + 1, done)

        kind = str(node.get('kind') or '').strip().lower()
        if kind == 'command':
            self._exec_command(node, generation, next_node)
        elif kind == 'wait':
            self._exec_wait(node, generation, next_node)
        elif kind == 'say':
            self._exec_say(node, generation, next_node)
        elif kind == 'question':
            self._exec_question(node, state_text, generation, next_node)
        else:
            self.get_logger().warn(f'Пропуск шага {kind!r} в {node}')
            next_node()

    def _exec_wait(self, node: dict[str, Any], generation: int,
                   next_node: Callable[[], None]) -> None:
        try:
            delay_ms = max(0.0, float(node.get('ms', 500)))
        except (TypeError, ValueError):
            delay_ms = 500.0
        if generation != self._generation:
            return
        self.get_logger().info(f'Пауза {delay_ms:.0f} мс')
        self._schedule(delay_ms, next_node)

    def _exec_command(self, node: dict[str, Any], generation: int,
                      next_node: Callable[[], None]) -> None:
        command = str(node.get('command') or '').strip()
        label = str(node.get('label') or command)
        if not command:
            next_node()
            return
        self.get_logger().info(f'Команда: {command} ({label})')
        if self._dry_run:
            next_node()
            return

        motion = self._motion_commands.get(command)
        if isinstance(motion, dict):
            self._exec_motion(command, motion, generation, next_node)
        else:
            self._exec_panda(command, generation, next_node)

    def _exec_panda(self, command: str, generation: int,
                    next_node: Callable[[], None]) -> None:
        if not self._panda_client.wait_for_server(timeout_sec=0.5):
            self.get_logger().error(
                f'{command}: action {self._panda_action} недоступен')
            next_node()
            return

        goal = PandaCommand.Goal()
        goal.routine_id = command
        goal.source = 'panda_commands'
        future = self._panda_client.send_goal_async(
            goal, feedback_callback=self._on_feedback)
        future.add_done_callback(
            lambda result: self._on_goal_response(
                result, command, generation, next_node))

    def _on_feedback(self, feedback_msg: Any) -> None:
        status = feedback_msg.feedback.status
        if status:
            self.get_logger().info(f'PandaCommand: {status}')

    def _on_goal_response(self, future: Any, command: str, generation: int,
                          next_node: Callable[[], None]) -> None:
        if generation != self._generation:
            return
        try:
            goal_handle = future.result()
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f'{command}: отправка goal: {exc}')
            next_node()
            return
        if goal_handle is None or not goal_handle.accepted:
            self.get_logger().warn(f'{command}: goal отклонён')
            next_node()
            return

        self._active_goal_handle = goal_handle
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(
            lambda result: self._on_goal_result(
                result, command, goal_handle, generation, next_node))

    def _on_goal_result(self, future: Any, command: str, goal_handle: Any,
                        generation: int, next_node: Callable[[], None]) -> None:
        if self._active_goal_handle is goal_handle:
            self._active_goal_handle = None
        if generation != self._generation:
            return
        try:
            response = future.result()
            result = response.result if response is not None else None
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f'{command}: результат: {exc}')
            next_node()
            return
        if result is None:
            self.get_logger().warn(f'{command}: нет результата (отменено?)')
            next_node()
            return
        if result.success:
            self.get_logger().info(f'{command}: ok ({result.message})')
        else:
            self.get_logger().warn(f'{command}: ошибка ({result.message})')
        next_node()

    def _exec_motion(self, command: str, motion: dict[str, Any], generation: int,
                     next_node: Callable[[], None]) -> None:
        if motion.get('stop') or self._cmd_vel_pub is None:
            self._publish_stop()
            next_node()
            return

        twist = Twist()
        try:
            twist.linear.x = float(motion.get('linear_x', 0.0))
            twist.linear.y = float(motion.get('linear_y', 0.0))
            twist.angular.z = float(motion.get('angular_z', 0.0))
            duration_sec = max(0.0, float(motion.get('duration_sec', 1.8)))
        except (TypeError, ValueError) as exc:
            self.get_logger().warn(f'{command}: motion_commands: {exc}')
            next_node()
            return

        self._cmd_vel_pub.publish(twist)
        self.get_logger().info(
            f'{self._param_str("cmd_vel_topic")} {command}: '
            f'x={twist.linear.x:.2f} y={twist.linear.y:.2f} '
            f'z={twist.angular.z:.2f} на {duration_sec:.2f} с')
        self._schedule(
            duration_sec * 1000.0,
            lambda: self._end_motion(generation, next_node),
        )

    def _end_motion(self, generation: int, next_node: Callable[[], None]) -> None:
        if generation != self._generation:
            return
        self._publish_stop()
        next_node()

    def _exec_say(self, node: dict[str, Any], generation: int,
                  next_node: Callable[[], None]) -> None:
        text = str(node.get('text') or '').strip()
        if not text:
            next_node()
            return
        if self._speak_client is None:
            self.get_logger().info(f'SAY выключен: {text!r}')
            next_node()
            return
        if self._dry_run:
            self.get_logger().info(f'SAY: {text!r}')
            next_node()
            return
        if not self._speak_client.wait_for_service(timeout_sec=0.5):
            self.get_logger().warn(f'Paroli недоступен, SAY пропущен: {text!r}')
            next_node()
            return

        request = Speak.Request()
        request.text = text
        request.volume = 1.5
        future = self._speak_client.call_async(request)
        future.add_done_callback(
            lambda result: self._on_spoken(result, text, generation, next_node))

    def _on_spoken(self, future: Any, text: str, generation: int,
                   next_node: Callable[[], None]) -> None:
        if generation != self._generation:
            return
        try:
            response = future.result()
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f'Paroli: {exc}')
        else:
            if response is not None and not response.success:
                self.get_logger().warn(f'Paroli: {response.message}')
        self.get_logger().info(f'SAY: {text!r}')
        next_node()

    def _choice_labels(self, node: dict[str, Any]) -> dict[str, dict[str, Any]]:
        labels: dict[str, dict[str, Any]] = {}
        options = node.get('options')
        if not isinstance(options, list):
            return labels
        for index, option in enumerate(options):
            if not isinstance(option, dict):
                continue
            base = str(option.get('name') or '').strip() or f'Вариант {index + 1}'
            label = base
            suffix = 2
            while label in labels:
                label = f'{base} {suffix}'
                suffix += 1
            labels[label] = option
        return labels

    @staticmethod
    def _examples_text(option: dict[str, Any]) -> str:
        examples = option.get('examples')
        if not isinstance(examples, list):
            return ''
        return ', '.join(str(item) for item in examples)

    def _exec_question(self, node: dict[str, Any], state_text: str, generation: int,
                       next_node: Callable[[], None]) -> None:
        if generation != self._generation:
            return
        qtype = str(node.get('qtype') or 'choice').strip().lower()
        qid = str(node.get('id') or 'q')
        question: dict[str, Any] = {'type': qtype}
        instructions = str(node.get('instructions') or node.get('name') or '').strip()
        if instructions:
            question['instructions'] = instructions

        labels: dict[str, dict[str, Any]] = {}
        if qtype == 'choice':
            labels = self._choice_labels(node)
            if not labels:
                self.get_logger().error(f'{qid}: нет options')
                next_node()
                return
            question['criteria'] = {
                label: self._examples_text(option)
                for label, option in labels.items()
            }
        elif qtype == 'noul':
            question['criteria'] = {}
        elif qtype == 'score':
            levels = node.get('levels')
            if not isinstance(levels, list) or not levels:
                self.get_logger().error(f'{qid}: нет levels')
                next_node()
                return
            question['criteria'] = [str(level) for level in levels]
        else:
            self.get_logger().error(f'{qid}: неизвестный qtype {qtype!r}')
            next_node()
            return

        payload = {
            'model': self._model,
            'state': state_text,
            'questions': {qid: question},
        }
        if not self._ask_client.service_is_ready() and not self._ask_client.wait_for_service(
            timeout_sec=0.5
        ):
            self.get_logger().error(
                f'{qid}: сервис {self._system_one_service} недоступен '
                '(system_one_ros запущен?)')
            next_node()
            return

        request = Ask.Request()
        request.request_json = json.dumps(payload, ensure_ascii=False)
        self.get_logger().info(f'Классификация {qid}: {state_text!r}')
        future = self._ask_client.call_async(request)
        future.add_done_callback(
            lambda result: self._on_question_response(
                result, node, qid, labels, state_text, generation, next_node))

    def _on_question_response(
        self, future: Any, node: dict[str, Any], qid: str,
        labels: dict[str, dict[str, Any]], state_text: str, generation: int,
        next_node: Callable[[], None],
    ) -> None:
        if generation != self._generation:
            return
        try:
            response = future.result()
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f'{qid}: ответ system_one: {exc}')
            next_node()
            return
        if response is None:
            self.get_logger().error(f'{qid}: пустой ответ system_one')
            next_node()
            return
        if not response.success:
            self.get_logger().warn(
                f'{qid}: system_one HTTP {response.http_status}: {response.message}')
            next_node()
            return

        try:
            body = json.loads(response.response_json or '{}')
        except json.JSONDecodeError:
            self.get_logger().error(f'{qid}: ответ не JSON')
            next_node()
            return
        answer = (body.get('answers') or {}).get(qid)
        if not isinstance(answer, dict):
            self.get_logger().error(f'{qid}: нет answers.{qid}')
            next_node()
            return

        qtype = str(answer.get('type') or node.get('qtype') or 'choice')
        confidence = float(answer.get(
            'confidence', answer.get('noul', 0.0) if qtype == 'noul' else 0.0))
        choice = str(answer.get('choice', ''))
        probabilities = answer.get('probabilities') or {}
        decision = {
            'text': state_text,
            'question': qid,
            'qtype': qtype,
            'choice': choice,
            'confidence': confidence,
            'probabilities': probabilities,
            'http_status': int(response.http_status),
            'latency_ms': int(response.latency_ms),
        }

        branch: list[Any] = []
        if qtype == 'choice':
            option = labels.get(choice)
            if option is None:
                self.get_logger().warn(f'{qid}: неизвестная метка {choice!r}')
            else:
                decision['option'] = option.get('id', '')
                branch = option.get('then') or []
                self.get_logger().info(
                    f'{qid}: {choice} → {option.get("id")} '
                    f'(conf {confidence:.3f}, {response.latency_ms} ms)')
        elif qtype == 'noul':
            noul = float(answer.get('noul', 0.0))
            decision['noul'] = noul
            branch = (
                (node.get('yes') or {}).get('then')
                if noul >= 0.5 else (node.get('no') or {}).get('then')
            ) or []
            self.get_logger().info(
                f'{qid}: noul={noul:.3f} → {"да" if noul >= 0.5 else "нет"}')
        elif qtype == 'score':
            levels = node.get('levels') or []
            score = float(answer.get('score', 0.0))
            index = self._score_index(answer, len(levels))
            decision['score'] = score
            decision['level'] = index
            outcomes = node.get('outcomes') or []
            outcome = outcomes[index] if index < len(outcomes) else None
            branch = (outcome or {}).get('then') or []
            level_text = levels[index] if index < len(levels) else index
            self.get_logger().info(
                f'{qid}: score={score:.3f} → уровень {level_text} ({index})')

        self._decision_pub.publish(
            String(data=json.dumps(decision, ensure_ascii=False)))

        if confidence < self._min_confidence:
            self.get_logger().info(
                f'{qid}: conf {confidence:.3f} < {self._min_confidence:.3f} — ветка пропущена')
            next_node()
            return

        if branch:
            self._run_chain(branch, state_text, generation, 0, next_node)
        else:
            next_node()

    @staticmethod
    def _score_index(answer: dict[str, Any], levels: int) -> int:
        if levels <= 0:
            return 0
        probabilities = answer.get('probabilities') or {}
        best_index = 0
        best_probability = -1.0
        for index in range(levels):
            try:
                probability = float(probabilities.get(str(index), 0.0))
            except (TypeError, ValueError):
                probability = 0.0
            if probability > best_probability:
                best_probability = probability
                best_index = index
        if best_probability <= 0.0:
            try:
                best_index = int(round(float(answer.get('score', 0.0))))
            except (TypeError, ValueError):
                best_index = 0
        return min(levels - 1, max(0, best_index))


def main() -> None:
    rclpy.init()
    node = PandaCommandsNode()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        try:
            node.destroy_node()
        except Exception:  # noqa: BLE001
            pass
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:  # noqa: BLE001
            pass


if __name__ == '__main__':
    main()
