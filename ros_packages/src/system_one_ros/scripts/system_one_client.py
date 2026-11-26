#!/usr/bin/env python3
"""
HTTP-клиент system-one-rknn: POST /v1/systemone и GET /health как ROS 2 сервисы.

Сервер инференса (Kev-0.8B на NPU) поднимается отдельно контейнером:

    ros2 launch system_one_ros system_one.launch.py mode:=http server_url:=...

Интерфейсы узла:

    ~/ask       system_one_ros/srv/Ask       — произвольное тело POST /v1/systemone
    ~/health    std_srvs/srv/Trigger         — GET /health
    ~/server_ok std_msgs/Bool                — последний результат health-check
    ~/models    std_msgs/String              — JSON-массив моделей сервера

`Ask` принимает готовый JSON-объект с `model`, `state` и `questions`, поэтому
один вызов может содержать несколько вопросов (`choice`, `noul`, `score`)
и любые поля, которые поддерживает сервер.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger

from llm_msgs_ros.srv import Ask


class SystemOneClient(Node):
    """Тонкая обёртка HTTP API system-one-rknn без сторонних зависимостей."""

    def __init__(self) -> None:
        super().__init__('system_one')

        self.declare_parameter('server_url', 'http://127.0.0.1:18477')
        self.declare_parameter('timeout_sec', 30.0)
        self.declare_parameter('health_timeout_sec', 3.0)
        self.declare_parameter('health_period_sec', 10.0)

        self.server_url = self._string_param('server_url').rstrip('/')
        self.timeout_sec = max(0.1, self._double_param('timeout_sec'))
        self.health_timeout_sec = max(0.1, self._double_param('health_timeout_sec'))
        self.health_period_sec = self._double_param('health_period_sec')

        self._group = ReentrantCallbackGroup()
        self.create_service(Ask, '~/ask', self.on_ask, callback_group=self._group)
        self.create_service(Trigger, '~/health', self.on_health, callback_group=self._group)

        status_qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self._server_ok_pub = self.create_publisher(Bool, '~/server_ok', status_qos)
        self._models_pub = self.create_publisher(String, '~/models', status_qos)
        self._last_health: tuple[bool, tuple[str, ...]] | None = None

        self._startup_timer = self.create_timer(
            0.2, self._initial_health, callback_group=self._group)
        if self.health_period_sec > 0.0:
            self.create_timer(
                self.health_period_sec, self._publish_health, callback_group=self._group)

        self.get_logger().info(
            f'system_one готов: {self.server_url}/v1/systemone '
            f'(timeout={self.timeout_sec:.0f} с)'
        )

    def _string_param(self, name: str) -> str:
        return self.get_parameter(name).get_parameter_value().string_value

    def _double_param(self, name: str) -> float:
        return self.get_parameter(name).get_parameter_value().double_value

    def _http(
        self, method: str, path: str, payload: bytes | None = None,
        timeout: float | None = None,
    ) -> tuple[int, bytes, int, str]:
        """(status, body, latency_ms, error); HTTP-ошибки возвращаются с телом."""
        headers = {'Accept': 'application/json'}
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(
            self.server_url + path, data=payload, headers=headers, method=method)
        started = time.monotonic()
        try:
            with urllib.request.urlopen(
                request, timeout=timeout if timeout is not None else self.timeout_sec
            ) as resp:
                raw = resp.read()
                latency = int((time.monotonic() - started) * 1000)
                return int(getattr(resp, 'status', 200)), raw, latency, ''
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read()
            except Exception:  # noqa: BLE001
                raw = b''
            latency = int((time.monotonic() - started) * 1000)
            return int(exc.code), raw, latency, ''
        except Exception as exc:  # noqa: BLE001
            latency = int((time.monotonic() - started) * 1000)
            return 0, b'', latency, f'нет ответа от {self.server_url}: {exc}'

    @staticmethod
    def _detail(body: object, status: int) -> str:
        if isinstance(body, dict):
            detail = body.get('detail')
            if isinstance(detail, str):
                return detail
            if isinstance(detail, list) and detail:
                parts = []
                for item in detail:
                    if isinstance(item, dict):
                        parts.append(str(item.get('msg', item)))
                    else:
                        parts.append(str(item))
                return '; '.join(parts)
        return f'HTTP {status}'

    def _post_systemone(
        self, payload: dict
    ) -> tuple[str, dict | None, int, int, str]:
        raw_payload = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        status, raw, latency, error = self._http('POST', '/v1/systemone', raw_payload)
        text = raw.decode('utf-8', 'replace')
        if error:
            return text, None, status, latency, error
        try:
            body = json.loads(text or '{}')
        except json.JSONDecodeError:
            return text, None, status, latency, f'HTTP {status}: ответ не JSON'
        if status != 200:
            return text, body, status, latency, self._detail(body, status)
        if not isinstance(body, dict):
            return text, None, status, latency, 'ответ сервера не JSON-объект'
        return text, body, status, latency, ''

    def _health_payload(self) -> tuple[bool, list[str], str, int]:
        status, raw, latency, error = self._http(
            'GET', '/health', timeout=self.health_timeout_sec)
        if error:
            return False, [], error, latency
        try:
            body = json.loads(raw.decode('utf-8', 'replace') or '{}')
        except json.JSONDecodeError:
            return False, [], f'HTTP {status}: ответ не JSON', latency
        if status != 200:
            return False, [], self._detail(body, status), latency
        models = body.get('models') if isinstance(body, dict) else None
        if not isinstance(models, list):
            models = []
        ok = bool(body.get('ok', False)) if isinstance(body, dict) else False
        return ok, [str(model) for model in models], 'ok' if ok else 'ok=false', latency

    def _publish_health(self) -> tuple[bool, list[str], str, int]:
        ok, models, message, latency = self._health_payload()
        self._server_ok_pub.publish(Bool(data=ok))
        self._models_pub.publish(String(data=json.dumps(models, ensure_ascii=False)))

        state = (ok, tuple(models))
        if state != self._last_health:
            if ok:
                self.get_logger().info(
                    f'health ok, models={models} ({latency} ms)')
            else:
                self.get_logger().warn(
                    f'health недоступен: {message} '
                    '(нужен внешний system-one-rknn)')
            self._last_health = state
        return ok, models, message, latency

    def _initial_health(self) -> None:
        timer = self._startup_timer
        self._startup_timer = None
        if timer is not None:
            self.destroy_timer(timer)
        self._publish_health()

    def on_ask(self, request: Ask.Request, response: Ask.Response) -> Ask.Response:
        response.success = False
        response.http_status = 0

        try:
            payload = json.loads(request.request_json or 'null')
        except json.JSONDecodeError as exc:
            response.message = f'request_json: {exc}'[:400]
            return response
        if not isinstance(payload, dict):
            response.message = 'request_json должен быть JSON-объектом'
            return response

        body_text, _body, status, latency, error = self._post_systemone(payload)
        response.http_status = status
        response.response_json = body_text
        response.latency_ms = latency
        if error:
            response.message = error[:400]
            return response

        response.success = True
        response.message = 'ok'
        self.get_logger().info(f'ask за {latency} ms')
        return response

    def on_health(
        self, _request: Trigger.Request, response: Trigger.Response
    ) -> Trigger.Response:
        ok, models, message, latency = self._publish_health()
        details = [message]
        if models:
            details.append(f'models={models}')
        details.append(f'{latency} ms')
        response.success = ok
        response.message = '; '.join(details)[:400]
        return response


def main() -> None:
    rclpy.init()
    node = SystemOneClient()
    executor = MultiThreadedExecutor(num_threads=3)
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
