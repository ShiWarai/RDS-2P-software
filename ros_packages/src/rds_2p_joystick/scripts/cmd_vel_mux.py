#!/usr/bin/env python3
"""
Мультиплексор команд скорости RDS-2P.

Принимает geometry_msgs/msg/Twist от нескольких независимых источников
(джойстик, клавиатура, голосовые команды, ...) и публикует в /cmd_vel только
одну выбранную команду.

Каждый источник задаётся именем, топиком, таймаутом и приоритетом.
Источник считается свежим, пока от него приходят сообщения. Ненулевая
команда удерживается до прихода нулевой Twist или до истечения таймаута.

Правила выбора:
- среди свежих источников с ненулевой командой выбирается источник с
  наибольшим приоритетом (при равенстве — более свежий);
- нулевая Twist от источника немедленно снимает его команду;
- если ненулевых команд нет, в /cmd_vel публикуется нулевая Twist;
- если свежих источников нет совсем, /cmd_vel_mux/active = false.

Топик /cmd_vel_mux/active (std_msgs/Bool, TRANSIENT_LOCAL) нужен watchdog'у
inference: без активного источника политика не запускается.
Состояние источников публикуется в /cmd_vel_mux/state (JSON, TRANSIENT_LOCAL).

Пример запуска:
    ros2 run rds_2p_joystick cmd_vel_mux.py \
        --ros-args --params-file config/cmd_vel_mux.yaml
"""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool, String


@dataclass
class CmdVelSource:
    """Один источник команд скорости."""

    name: str
    topic: str
    timeout_sec: float
    priority: int
    last_twist: Twist = field(default_factory=Twist)
    last_msg_time: Optional[float] = None
    command_active: bool = False
    fresh: bool = False
    subscription: Any = None


class CmdVelMuxNode(Node):
    """Выбирает одну ненулевую команду из N источников и публикует в /cmd_vel."""

    def __init__(self) -> None:
        super().__init__('cmd_vel_mux')

        self.declare_parameter('output_topic', '/cmd_vel')
        self.declare_parameter('active_topic', '/cmd_vel_mux/active')
        self.declare_parameter('state_topic', '/cmd_vel_mux/state')
        self.declare_parameter('publish_rate', 20.0)
        self.declare_parameter('state_rate', 2.0)
        self.declare_parameter('zero_epsilon', 1.0e-6)
        self.declare_parameter('source_names', ['joy', 'keyboard', 'voice', 'ball_follow'])
        self.declare_parameter('source_topics', [
            '/cmd_vel/joy',
            '/cmd_vel/keyboard',
            '/cmd_vel/voice',
            '/cmd_vel/ball_follow',
        ])
        self.declare_parameter('source_timeouts', [0.5, 0.5, 2.5, 0.5])
        self.declare_parameter('source_priorities', [100, 90, 50, 40])

        self._output_topic = self._param_str('output_topic')
        self._zero_epsilon = max(0.0, self._param_double('zero_epsilon'))
        publish_rate = max(1.0, self._param_double('publish_rate'))
        state_rate = max(0.1, self._param_double('state_rate'))
        self._state_period = 1.0 / state_rate

        names = self._param_str_array('source_names')
        topics = self._param_str_array('source_topics')
        timeouts = self._param_double_array('source_timeouts')
        priorities = self._param_int_array('source_priorities')
        self._validate_sources(names, topics, timeouts, priorities)

        state_qos = QoSProfile(depth=1)
        state_qos.reliability = ReliabilityPolicy.RELIABLE
        state_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL

        self._cmd_pub = self.create_publisher(Twist, self._output_topic, 10)
        self._active_pub = self.create_publisher(
            Bool, self._param_str('active_topic'), state_qos)
        self._state_pub = self.create_publisher(
            String, self._param_str('state_topic'), state_qos)

        self._sources = []
        for name, topic, timeout_sec, priority in zip(
                names, topics, timeouts, priorities):
            source = CmdVelSource(
                name=name,
                topic=topic,
                timeout_sec=timeout_sec,
                priority=priority,
            )
            source.subscription = self.create_subscription(
                Twist,
                topic,
                lambda msg, src=source: self._on_twist(src, msg),
                10,
            )
            self._sources.append(source)

        self._active = False
        self._selected_name = ''
        self._next_state_time = 0.0
        self._no_source_logged = False
        self._last_active_published = False

        self._timer = self.create_timer(1.0 / publish_rate, self._tick)

        sources_text = ', '.join(
            f'{source.name}({source.topic}, timeout={source.timeout_sec:g}s, '
            f'priority={source.priority})'
            for source in self._sources
        )
        self.get_logger().info(
            f'cmd_vel mux: {len(self._sources)} источников -> '
            f'{self._output_topic}; {sources_text}'
        )
        self._publish_active(False)
        self._publish_state()

    def _param_str(self, name: str) -> str:
        return self.get_parameter(name).get_parameter_value().string_value.strip()

    def _param_double(self, name: str) -> float:
        return self.get_parameter(name).get_parameter_value().double_value

    def _param_str_array(self, name: str) -> list:
        value = self.get_parameter(name).get_parameter_value()
        return [str(item).strip() for item in value.string_array_value]

    def _param_double_array(self, name: str) -> list:
        value = self.get_parameter(name).get_parameter_value()
        return list(value.double_array_value)

    def _param_int_array(self, name: str) -> list:
        value = self.get_parameter(name).get_parameter_value()
        return [int(item) for item in value.integer_array_value]

    def _validate_sources(self, names, topics, timeouts, priorities) -> None:
        if not names:
            raise ValueError('cmd_vel_mux: список source_names пуст')
        if not (len(names) == len(topics) == len(timeouts) == len(priorities)):
            raise ValueError(
                'cmd_vel_mux: source_names, source_topics, source_timeouts и '
                'source_priorities должны быть одинаковой длины')
        seen = set()
        for name, topic, timeout_sec in zip(names, topics, timeouts):
            if not name or not topic:
                raise ValueError('cmd_vel_mux: имя и топик источника не могут быть пустыми')
            if not 0.0 < timeout_sec < 60.0:
                raise ValueError(
                    f'cmd_vel_mux: timeout источника {name} должен быть в (0, 60) с')
            if name in seen:
                raise ValueError(f'cmd_vel_mux: повторяющееся имя источника {name}')
            seen.add(name)

    def _is_zero(self, twist: Twist) -> bool:
        eps = self._zero_epsilon
        return (
            abs(twist.linear.x) < eps
            and abs(twist.linear.y) < eps
            and abs(twist.linear.z) < eps
            and abs(twist.angular.x) < eps
            and abs(twist.angular.y) < eps
            and abs(twist.angular.z) < eps
        )

    def _on_twist(self, source: CmdVelSource, msg: Twist) -> None:
        source.last_twist = msg
        source.last_msg_time = time.monotonic()
        source.command_active = not self._is_zero(msg)
        source.fresh = True

    def _tick(self) -> None:
        now = time.monotonic()
        active_sources = []
        commanding_sources = []

        for source in self._sources:
            source.fresh = (
                source.last_msg_time is not None
                and (now - source.last_msg_time) <= source.timeout_sec
            )
            if not source.fresh:
                continue
            active_sources.append(source)
            if source.command_active:
                commanding_sources.append(source)

        selected: Optional[CmdVelSource] = None
        if commanding_sources:
            selected = max(
                commanding_sources,
                key=lambda source: (source.priority, source.last_msg_time),
            )

        self._cmd_pub.publish(
            selected.last_twist if selected is not None else Twist())

        active = bool(active_sources)
        selected_name = selected.name if selected is not None else ''
        self._active = active

        if active != self._last_active_published:
            self.get_logger().info(f'cmd_vel mux: active={active}')
            self._last_active_published = active
        # active публикуется каждый тик, чтобы watchdog inference видел
        # свежее состояние, а не только переход.
        self._publish_active(active)

        if selected_name != self._selected_name:
            if selected is not None:
                self.get_logger().info(
                    f'cmd_vel: управление от {selected.name} ({selected.topic}), '
                    f'priority={selected.priority}')
            else:
                self.get_logger().info(
                    'cmd_vel: ненулевых команд нет — публикуется нулевая Twist')
            self._selected_name = selected_name

        if not active_sources and not self._no_source_logged:
            self.get_logger().warn(
                'Нет свежих источников cmd_vel — публикуется нулевая Twist, '
                'active=false')
            self._no_source_logged = True
        elif active_sources:
            self._no_source_logged = False

        if now >= self._next_state_time:
            self._publish_state(now, active, selected)
            self._next_state_time = now + self._state_period

    def _publish_active(self, active: bool) -> None:
        msg = Bool()
        msg.data = active
        self._active_pub.publish(msg)

    def _publish_state(
        self,
        now: Optional[float] = None,
        active: Optional[bool] = None,
        selected: Optional[CmdVelSource] = None,
    ) -> None:
        if now is None:
            now = time.monotonic()
        if active is None:
            active = self._active
        if selected is None:
            selected = next(
                (source for source in self._sources
                 if source.name == self._selected_name),
                None,
            )

        sources_state = {}
        for source in self._sources:
            age_sec = None
            if source.last_msg_time is not None:
                age_sec = round(max(0.0, now - source.last_msg_time), 3)
            sources_state[source.name] = {
                'topic': source.topic,
                'fresh': source.fresh,
                'command_active': source.command_active,
                'priority': source.priority,
                'timeout_sec': source.timeout_sec,
                'age_sec': age_sec,
            }

        state = {
            'active': active,
            'selected_source': selected.name if selected is not None else '',
            'output_topic': self._output_topic,
            'sources': sources_state,
        }
        msg = String()
        msg.data = json.dumps(state, ensure_ascii=False)
        self._state_pub.publish(msg)

    def stop(self) -> None:
        """Публикует нулевую команду и active=false при завершении узла."""
        if self._cmd_pub is None:
            return
        self._cmd_pub.publish(Twist())
        self._publish_active(False)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = CmdVelMuxNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            node.destroy_node()
        except Exception:  # noqa: BLE001
            pass
        try:
            rclpy.shutdown()
        except Exception:  # noqa: BLE001
            pass


if __name__ == '__main__':
    main()
