#!/usr/bin/env python3
"""
Публикует состояние джойстика в /joy/status (diagnostic_msgs/DiagnosticStatus)
по факту Bluetooth-подключения. MAC не задаётся: перебирает `bluetoothctl
devices` и проверяет Connected у устройств с именем контроллера.

level=OK — подключён, ERROR — нет. mux гейтит source joy по level==OK.
"""

import subprocess

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from diagnostic_msgs.msg import DiagnosticStatus, KeyValue


DEFAULT_NAME_PATTERNS = ['wireless controller', 'dualshock', 'sony', 'ps4', 'controller']


class JoyStatusMonitor(Node):
    def __init__(self) -> None:
        super().__init__('joy_status_monitor')

        self.declare_parameter('status_topic', '/joy/status')
        self.declare_parameter('poll_rate', 1.0)
        self.declare_parameter('name_patterns', DEFAULT_NAME_PATTERNS)
        self.declare_parameter('ok_on_error', False)

        self._patterns = [p.lower() for p in
                          self.get_parameter('name_patterns').get_parameter_value().string_array_value
                          if str(p).strip()] or list(DEFAULT_NAME_PATTERNS)
        self._ok_on_error = bool(self.get_parameter('ok_on_error').value)
        poll_rate = max(0.2, float(self.get_parameter('poll_rate').value))
        topic = str(self.get_parameter('status_topic').value).strip() or '/joy/status'

        qos = QoSProfile(depth=1)
        qos.reliability = ReliabilityPolicy.RELIABLE
        qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self._pub = self.create_publisher(DiagnosticStatus, topic, qos)

        self._last_level = None
        self._timer = self.create_timer(1.0 / poll_rate, self._poll)
        self.get_logger().info(
            f'joy_status_monitor: -> {topic} @ {poll_rate:g} Гц; '
            f'name_patterns={self._patterns}')
        self._poll()

    def _run(self, *args):
        try:
            out = subprocess.run(
                ['bluetoothctl', *args],
                capture_output=True, text=True, timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return (out.stdout or '') + (out.stderr or '')

    def _looks_like_controller(self, name: str) -> bool:
        low = (name or '').lower()
        return any(pat in low for pat in self._patterns)

    def _find_connected_controller(self):
        """Возвращает (name, mac) подключённого контроллера или None.

        None при ошибке опроса; (None, None) при отсутствии подключённого.
        """
        listing = self._run('devices')
        if listing is None:
            return 'error', None, None
        for line in listing.splitlines():
            line = line.strip()
            if not line.startswith('Device '):
                continue
            parts = line.split(' ', 2)
            if len(parts) < 3:
                continue
            mac = parts[1]
            name = parts[2].strip()
            if not self._looks_like_controller(name):
                continue
            info = self._run('info', mac)
            if info is None:
                return 'error', None, None
            if 'Connected: yes' in info:
                return 'connected', name, mac
        return 'absent', None, None

    def _poll(self) -> None:
        state, name, mac = self._find_connected_controller()

        if state == 'error':
            level = DiagnosticStatus.OK if self._ok_on_error else DiagnosticStatus.ERROR
            message = 'Не удалось опросить BlueZ'
            name = mac = ''
        elif state == 'connected':
            level = DiagnosticStatus.OK
            message = f'Контроллер подключён: {name} ({mac})'
        else:
            level = DiagnosticStatus.ERROR
            message = 'Контроллер не подключён'
            name = mac = ''

        if level != self._last_level:
            if self._last_level is not None:
                self.get_logger().info(
                    f'joy status: {"OK" if level == DiagnosticStatus.OK else "ERROR"} — {message}')
            self._last_level = level

        msg = DiagnosticStatus()
        msg.name = 'joy_source'
        msg.hardware_id = mac or ''
        msg.level = level
        msg.message = message
        msg.values = [
            KeyValue(key='device_name', value=name or ''),
            KeyValue(key='mac', value=mac or ''),
        ]
        self._pub.publish(msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = JoyStatusMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()