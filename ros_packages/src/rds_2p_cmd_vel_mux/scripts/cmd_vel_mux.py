#!/usr/bin/env python3
"""
Мультиплексор команд скорости RDS-2P с явным выбором источника.

Принимает geometry_msgs/msg/Twist от нескольких независимых источников
(джойстик, клавиатура, голосовые команды, ...), но публикует в /cmd_vel
только команды выбранного источника.

Текущий источник задаётся именем через топик /cmd_vel_mux/select
(std_msgs/msg/String): например, "joy", "keyboard" или "voice". Пустая
строка или "none" отключает передачу команд (в /cmd_vel идёт нулевая Twist).

Каждый источник задаётся именем, топиком и таймаутом. Источник считается
свежим, пока от него приходят сообщения. Если выбранный источник перестал
присылать сообщения дольше таймаута, публикуется нулевая Twist, а
/cmd_vel_mux/active = false.

Состояние публикуется в /cmd_vel_mux/state (JSON, TRANSIENT_LOCAL).
Топик /cmd_vel_mux/active (std_msgs/Bool, TRANSIENT_LOCAL) нужен watchdog'у
inference: без активного выбранного источника политика не запускается.

Пример запуска:
    ros2 run rds_2p_joystick cmd_vel_mux.py \
        --ros-args --params-file config/cmd_vel_mux.yaml

Пример выбора источника:
    ros2 topic pub --once /cmd_vel_mux/select std_msgs/msg/String "{data: joy}"
"""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from diagnostic_msgs.msg import DiagnosticStatus
from std_msgs.msg import Bool, String


@dataclass
class CmdVelSource:
    """Один источник команд скорости."""

    name: str
    topic: str
    timeout_sec: float
    last_twist: Twist = field(default_factory=Twist)
    last_msg_time: Optional[float] = None
    fresh: bool = False
    subscription: Any = None
    present: bool = True  # «жив» по DiagnosticStatus (level==OK); fail-open
    status_subscription: Any = None


class CmdVelMuxNode(Node):
    """Пропускает в /cmd_vel команды только выбранного источника."""

    def __init__(self) -> None:
        super().__init__('cmd_vel_mux')

        self.declare_parameter('output_topic', '/cmd_vel')
        self.declare_parameter('active_topic', '/cmd_vel_mux/active')
        self.declare_parameter('state_topic', '/cmd_vel_mux/state')
        self.declare_parameter('select_topic', '/cmd_vel_mux/select')
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
        self.declare_parameter('source_status_topics', ['/joy/status', '', '', ''])
        self.declare_parameter('default_source', 'joy')
        # Авто-обнаружение: любой топик с префиксом auto_discover_prefix и типом
        # Twist (напр. /cmd_vel/neiry) добавляется источником на лету.
        self.declare_parameter('auto_discover', True)
        self.declare_parameter('auto_discover_prefix', '/cmd_vel/')
        self.declare_parameter('auto_discover_rate', 1.0)
        self.declare_parameter('auto_source_timeout', 0.5)

        self._output_topic = self._param_str('output_topic')
        self._zero_epsilon = max(0.0, self._param_double('zero_epsilon'))
        publish_rate = max(1.0, self._param_double('publish_rate'))
        state_rate = max(0.1, self._param_double('state_rate'))
        self._state_period = 1.0 / state_rate

        self._default_source_name = self._param_str('default_source')
        self._auto_discover = bool(self.get_parameter('auto_discover').value)
        self._auto_prefix = self._param_str('auto_discover_prefix')
        auto_rate = max(0.1, self._param_double('auto_discover_rate'))
        self._auto_timeout = max(0.05, self._param_double('auto_source_timeout'))

        names = self._param_str_array('source_names')
        topics = self._param_str_array('source_topics')
        timeouts = self._param_double_array('source_timeouts')
        status_topics = self._param_str_array('source_status_topics')
        if len(status_topics) < len(names):
            status_topics += [''] * (len(names) - len(status_topics))
        self._validate_sources(names, topics, timeouts)

        state_qos = QoSProfile(depth=1)
        state_qos.reliability = ReliabilityPolicy.RELIABLE
        state_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL

        self._cmd_pub = self.create_publisher(Twist, self._output_topic, 10)
        self._active_pub = self.create_publisher(
            Bool, self._param_str('active_topic'), state_qos)
        self._state_pub = self.create_publisher(
            String, self._param_str('state_topic'), state_qos)

        self._sources = []
        self._known_topics = set()
        for name, topic, timeout_sec, status_topic in zip(
                names, topics, timeouts, status_topics):
            self._add_source(name, topic, timeout_sec, status_topic)

        self._selected: Optional[CmdVelSource] = None
        self._active = False
        self._selected_stale_logged = False
        self._next_state_time = 0.0
        self._last_active_published: Optional[bool] = None

        self.create_subscription(
            String,
            self._param_str('select_topic'),
            self._on_select,
            10,
        )
        self._timer = self.create_timer(1.0 / publish_rate, self._tick)

        sources_text = ', '.join(
            f'{source.name}({source.topic}, timeout={source.timeout_sec:g}s)'
            for source in self._sources
        )
        self.get_logger().info(
            f'cmd_vel mux: {len(self._sources)} источников -> '
            f'{self._output_topic}; выбор: '
            f'{self._param_str("select_topic")} (String); {sources_text}'
        )

        if self._auto_discover:
            self.create_timer(1.0 / auto_rate, self._discover_sources)
            self._discover_sources()

        if self._default_source_name:
            self._select_source(
                self._default_source_name, 'параметр default_source', reset=False)
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

    def _validate_sources(self, names, topics, timeouts) -> None:
        if not names:
            raise ValueError('cmd_vel_mux: список source_names пуст')
        if not (len(names) == len(topics) == len(timeouts)):
            raise ValueError(
                'cmd_vel_mux: source_names, source_topics и source_timeouts '
                'должны быть одинаковой длины')
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

    def _add_source(self, name: str, topic: str, timeout_sec: float,
                    status_topic: str = '') -> 'CmdVelSource':
        source = CmdVelSource(name=name, topic=topic, timeout_sec=timeout_sec)
        source.subscription = self.create_subscription(
            Twist,
            topic,
            lambda msg, src=source: self._on_twist(src, msg),
            10,
        )
        if status_topic:
            source.status_subscription = self.create_subscription(
                DiagnosticStatus,
                status_topic,
                lambda msg, src=source: self._on_status(src, msg),
                10,
            )
        self._sources.append(source)
        self._known_topics.add(topic)
        return source

    def _discover_sources(self) -> None:
        """Добавляет как источники любые новые топики <prefix><N> типа Twist."""
        if not self._auto_prefix:
            return
        try:
            topics = self.get_topic_names_and_types()
        except Exception:
            return
        added = False
        for topic, types in topics:
            if topic in self._known_topics or len(topic) <= len(self._auto_prefix):
                continue
            if not topic.startswith(self._auto_prefix):
                continue
            if 'geometry_msgs/msg/Twist' not in types:
                continue
            name = topic[len(self._auto_prefix):].strip('/')
            if not name or self._find_source(name) is not None:
                continue
            self._add_source(name, topic, self._auto_timeout)
            self.get_logger().info(
                f'cmd_vel mux: авто-источник {name} ({topic})')
            added = True
            if (self._selected is None and self._default_source_name
                    and name == self._default_source_name):
                self._select_source(name, 'auto default_source', reset=False)
        if added:
            self._publish_state()

    def _find_source(self, value: str) -> Optional[CmdVelSource]:
        for source in self._sources:
            if value == source.name or value == source.topic:
                return source
        return None

    def _on_select(self, msg: String) -> None:
        self._select_source(msg.data, f'топик {self.get_parameter("select_topic").value}')

    def _select_source(self, value: str, source: str, reset: bool = True) -> None:
        name = (value or '').strip()
        if name.startswith('/cmd_vel/'):
            name = name[len('/cmd_vel/'):]

        if not name or name.lower() in ('none', 'off', 'stop'):
            if self._selected is None:
                return
            self._selected = None
            self._active = False
            self._cmd_pub.publish(Twist())
            self._publish_active(False)
            self.get_logger().warn(
                f'cmd_vel mux: источник снят ({source}) — публикуется нулевая Twist')
            self._publish_state()
            return

        selected = self._find_source(name)
        if selected is None:
            known = ', '.join(src.name for src in self._sources)
            self.get_logger().warn(
                f'cmd_vel mux: неизвестный источник "{value}" ({source}); '
                f'доступны: {known}')
            return
        if selected is self._selected:
            return

        self._selected = selected
        self._active = False
        self._selected_stale_logged = False
        if reset:
            selected.last_twist = Twist()
            selected.last_msg_time = None
            selected.fresh = False
        self._cmd_pub.publish(Twist())
        self._publish_active(False)
        self.get_logger().info(
            f'cmd_vel mux: выбран источник {selected.name} '
            f'({selected.topic}) ({source})')
        self._publish_state()

    def _is_fresh(self, source: CmdVelSource, now: float) -> bool:
        return (
            source.last_msg_time is not None
            and (now - source.last_msg_time) <= source.timeout_sec
        )

    def _on_twist(self, source: CmdVelSource, msg: Twist) -> None:
        source.last_twist = msg
        source.last_msg_time = time.monotonic()
        source.fresh = True

    def _on_status(self, source: CmdVelSource, msg: DiagnosticStatus) -> None:
        present = (msg.level == DiagnosticStatus.OK)
        if present != source.present:
            self.get_logger().info(
                f'cmd_vel mux: источник {source.name} '
                f'{"доступен" if present else "недоступен"} ({msg.message})')
        source.present = present

    def _tick(self) -> None:
        now = time.monotonic()

        for source in self._sources:
            source.fresh = self._is_fresh(source, now) and source.present

        selected = self._selected
        selected_fresh = selected is not None and selected.fresh

        self._cmd_pub.publish(
            selected.last_twist if selected_fresh else Twist())

        active = selected_fresh
        self._active = active

        if active != self._last_active_published:
            self.get_logger().info(f'cmd_vel mux: active={active}')
            self._last_active_published = active
        # active публикуется каждый тик, чтобы watchdog inference видел
        # свежее состояние, а не только переход.
        self._publish_active(active)

        if selected is not None and not selected_fresh:
            if not self._selected_stale_logged:
                self.get_logger().warn(
                    f'cmd_vel mux: источник {selected.name} не присылает '
                    f'команды дольше {selected.timeout_sec:g} с — '
                    f'публикуется нулевая Twist')
                self._selected_stale_logged = True
        else:
            self._selected_stale_logged = False

        if now >= self._next_state_time:
            self._publish_state(now, active)
            self._next_state_time = now + self._state_period

    def _publish_active(self, active: bool) -> None:
        msg = Bool()
        msg.data = active
        self._active_pub.publish(msg)

    def _publish_state(
        self,
        now: Optional[float] = None,
        active: Optional[bool] = None,
    ) -> None:
        if now is None:
            now = time.monotonic()
        if active is None:
            active = self._active

        sources_state = {}
        for source in self._sources:
            age_sec = None
            if source.last_msg_time is not None:
                age_sec = round(max(0.0, now - source.last_msg_time), 3)
            sources_state[source.name] = {
                'topic': source.topic,
                'fresh': source.fresh,
                'timeout_sec': source.timeout_sec,
                'age_sec': age_sec,
            }

        state = {
            'active': active,
            'selected_source': (
                self._selected.name if self._selected is not None else ''),
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