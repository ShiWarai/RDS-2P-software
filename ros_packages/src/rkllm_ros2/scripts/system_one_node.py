#!/usr/bin/env python3
"""Тонкая ROS 2 обёртка system-one-rknn: POST /v1/systemone как сервис ~/systemone.

  ros2 launch rkllm_ros2 system_one.launch.py
  ros2 service call /system_one/systemone rkllm_ros2_msgs/srv/SystemOne \
    "{model: kev-0.8b, type: choice, state: '…', labels: [a, b], descriptions: ['', '']}"

Нода — только HTTP-клиент (stdlib); сам сервис инференса поднимается отдельным
контейнером (см. scripts/system_one_docker.sh и README пакета).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import rclpy
from rclpy.node import Node

from rkllm_ros2_msgs.srv import SystemOne


class SystemOneNode(Node):
    def __init__(self) -> None:
        super().__init__('system_one')
        self.declare_parameter('server_url', 'http://127.0.0.1:8080')
        self.declare_parameter('timeout_sec', 30.0)
        self.declare_parameter('default_model', 'kev-0.8b')
        self.declare_parameter('health_check', True)

        self.server_url = (
            self.get_parameter('server_url').get_parameter_value().string_value.rstrip('/')
        )
        self.timeout_sec = self.get_parameter('timeout_sec').get_parameter_value().double_value
        self.default_model = (
            self.get_parameter('default_model').get_parameter_value().string_value
        )
        health_check = self.get_parameter('health_check').get_parameter_value().bool_value

        self.create_service(SystemOne, '~/systemone', self.on_systemone)
        self.get_logger().info(
            f'system_one готов: {self.server_url}/v1/systemone '
            f'(default_model={self.default_model}, timeout={self.timeout_sec:.0f} с)'
        )
        if health_check:
            threading.Thread(target=self._check_health, daemon=True).start()

    def _check_health(self) -> None:
        try:
            with urllib.request.urlopen(self.server_url + '/health', timeout=3.0) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            self.get_logger().info(f'health ok, models={data.get("models")}')
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(
                f'health недоступен ({exc}); контейнер system-one-rknn поднят? '
                '(scripts/system_one_docker.sh run)'
            )

    def _build_payload(self, request: SystemOne.Request) -> dict:
        """Request сервиса → тело POST /v1/systemone (одна questions-запись "q")."""
        kind = request.type.strip().lower()
        if kind not in ('choice', 'noul', 'score'):
            raise ValueError('type должен быть choice, noul или score')

        question: dict = {'type': kind}
        if request.instructions:
            question['instructions'] = request.instructions

        labels = list(request.labels)
        descriptions = list(request.descriptions)
        if kind == 'choice':
            if not labels:
                raise ValueError('choice: нужен непустой labels[]')
            if len(descriptions) > len(labels):
                raise ValueError('choice: descriptions длиннее labels')
            descriptions += [''] * (len(labels) - len(descriptions))
            question['criteria'] = dict(zip(labels, descriptions))
        elif kind == 'score':
            if not descriptions:
                raise ValueError('score: нужен непустой descriptions[] (пункты шкалы)')
            question['criteria'] = descriptions
        else:  # noul
            criteria = {}
            if len(descriptions) >= 1 and descriptions[0]:
                criteria['false'] = descriptions[0]
            if len(descriptions) >= 2 and descriptions[1]:
                criteria['true'] = descriptions[1]
            question['criteria'] = criteria

        model = request.model.strip() or self.default_model
        return {'model': model, 'state': request.state, 'questions': {'q': question}}

    def on_systemone(
        self, request: SystemOne.Request, response: SystemOne.Response
    ) -> SystemOne.Response:
        response.success = False

        try:
            payload = self._build_payload(request)
        except ValueError as exc:
            response.message = str(exc)
            return response

        body_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        http_request = urllib.request.Request(
            self.server_url + '/v1/systemone',
            data=body_bytes,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )

        started = time.monotonic()
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout_sec) as resp:
                response.http_status = resp.status
                body = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            response.http_status = exc.code
            try:
                detail = exc.read().decode('utf-8', 'replace')
            except Exception:  # noqa: BLE001
                detail = ''
            response.message = f'HTTP {exc.code}: {detail}'[:400]
            return response
        except Exception as exc:  # noqa: BLE001
            response.message = f'нет ответа от {self.server_url}: {exc}'[:400]
            return response
        response.latency_ms = int((time.monotonic() - started) * 1000)

        usage = body.get('usage') or {}
        response.input_tokens = int(usage.get('input_tokens', 0))
        response.output_tokens = int(usage.get('output_tokens', 0))

        answer = (body.get('answers') or {}).get('q')
        if not isinstance(answer, dict):
            response.message = f'неожиданный ответ: {json.dumps(body, ensure_ascii=False)}'[:400]
            return response

        response.probabilities_json = json.dumps(
            answer.get('probabilities', {}), ensure_ascii=False
        )
        answer_type = answer.get('type', request.type.strip().lower())
        if answer_type == 'choice':
            response.choice = answer.get('choice', '')
            response.confidence = float(answer.get('confidence', 0.0))
        elif answer_type == 'noul':
            response.noul = float(answer.get('noul', 0.0))
        elif answer_type == 'score':
            response.score = float(answer.get('score', 0.0))
            response.confidence = float(answer.get('confidence', 0.0))
            response.legend_json = json.dumps(
                answer.get('legend') or {}, ensure_ascii=False
            )
        else:
            response.message = f'неизвестный type в ответе: {answer_type}'
            return response

        response.success = True
        response.message = 'ok'
        self.get_logger().info(
            f'{payload["model"]} {answer_type} за {response.latency_ms} ms '
            f'(tokens={response.input_tokens})'
        )
        return response


def main() -> None:
    rclpy.init()
    node = SystemOneNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
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