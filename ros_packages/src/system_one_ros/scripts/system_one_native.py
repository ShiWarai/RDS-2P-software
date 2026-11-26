#!/usr/bin/env python3
"""Нативный ROS 2 сервер system-one: Kev-0.8B на RKLLM/NPU, без HTTP и Docker.

Сервис: ``~/ask`` (``llm_msgs_ros/srv/Ask``) — тот же JSON, что POST /v1/systemone.
``~/health`` — Trigger.

Модель и библиотеки задаются параметрами:
  model_root  — каталог с kev-*.rkllm, tokenizer.json, pointer.json, *.npy
  rkllm_lib   — librkllmrt-1.3.1.so
  rknpu_lib   — librknnrt-2.3.2.so (грузится RTLD_GLOBAL до RKLLM)
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_srvs.srv import Trigger

from llm_msgs_ros.srv import Ask

_HERE = os.path.dirname(os.path.realpath(__file__))
for _path in (_HERE, os.path.dirname(_HERE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from osm_app.api import (  # noqa: E402
    ApiError, LimitError, assemble, parse_request, response, softmax)
from osm_app.kev_engine import KevEngine  # noqa: E402


class SystemOneNative(Node):
    def __init__(self) -> None:
        super().__init__('system_one')

        self.declare_parameter(
            'model_root', '/home/orangepi/models/kev-0.8b-rknn')
        self.declare_parameter(
            'rkllm_lib', '/opt/npu/librkllmrt-1.3.1.so')
        self.declare_parameter(
            'rknpu_lib', '/opt/npu/librknnrt-2.3.2.so')
        self.declare_parameter('model', 'kev-0.8b')
        # Потолок строки Kev; файл держит 16384, но арена ~1 MiB/токен.
        self.declare_parameter('max_context', 2048)

        root = self._string_param('model_root')
        rkllm_lib = self._string_param('rkllm_lib')
        rknpu_lib = self._string_param('rknpu_lib')
        self._model = self._string_param('model') or 'kev-0.8b'
        self._max_context = int(self.get_parameter('max_context').value)

        if not os.path.isdir(root):
            raise RuntimeError(f'нет каталога модели: {root}')
        if not os.path.isfile(rkllm_lib):
            raise RuntimeError(f'нет RKLLM-библиотеки: {rkllm_lib}')
        if os.path.isfile(rknpu_lib):
            ctypes.CDLL(rknpu_lib, mode=ctypes.RTLD_GLOBAL)
        os.environ['KEV_MAX_CONTEXT'] = str(self._max_context)
        self.get_logger().info(
            f'загружаю Kev из {root} ({rkllm_lib}), max_context={self._max_context}')
        self._engine = KevEngine(root, rkllm_lib)
        self._known = {self._engine.name}
        self._lock = threading.Lock()

        self._group = ReentrantCallbackGroup()
        self.create_service(
            Ask, '~/ask', self._on_ask, callback_group=self._group)
        self.create_service(
            Trigger, '~/health', self._on_health, callback_group=self._group)
        self.get_logger().info(
            f'system_one native готов: /system_one/ask, model={self._model}, '
            f'max_context={self._max_context}')

    def _string_param(self, name: str) -> str:
        return self.get_parameter(name).get_parameter_value().string_value

    def _on_health(
        self, _request: Trigger.Request, response_msg: Trigger.Response
    ) -> Trigger.Response:
        response_msg.success = True
        response_msg.message = (
            f'models={sorted(self._known)}; native; '
            f'root={self._string_param("model_root")}')
        return response_msg

    def _on_ask(
        self, request: Ask.Request, response_msg: Ask.Response
    ) -> Ask.Response:
        response_msg.success = False
        response_msg.http_status = 0
        started = time.monotonic()

        try:
            payload = json.loads(request.request_json or 'null')
        except json.JSONDecodeError as exc:
            response_msg.message = f'request_json: {exc}'[:400]
            return response_msg
        if not isinstance(payload, dict):
            response_msg.message = 'request_json должен быть JSON-объектом'
            return response_msg

        try:
            model, state, items = parse_request(payload, self._known)
            answers = {}
            tokens = 0
            with self._lock:
                for item in items:
                    logits, used, _elapsed = self._engine.forward(state, item)
                    probs = softmax(logits, self._engine.temperature(item['kind']))
                    answers[item['id']] = assemble(item, probs)
                    tokens += used
            body = response(model, answers, tokens, 0)
        except ApiError as exc:
            response_msg.http_status = int(exc.status)
            response_msg.message = str(exc)[:400]
            response_msg.response_json = json.dumps(
                {'detail': exc.detail}, ensure_ascii=False)
            return response_msg
        except LimitError as exc:
            response_msg.http_status = 422
            response_msg.message = str(exc)[:400]
            response_msg.response_json = json.dumps(
                {'detail': [{'loc': ['body'], 'msg': str(exc),
                             'type': 'value_error'}]},
                ensure_ascii=False)
            return response_msg
        except Exception as exc:  # noqa: BLE001
            response_msg.http_status = 500
            response_msg.message = f'{type(exc).__name__}: {exc}'[:400]
            return response_msg

        response_msg.success = True
        response_msg.message = 'ok'
        response_msg.http_status = 200
        response_msg.response_json = json.dumps(body, ensure_ascii=False)
        response_msg.latency_ms = int((time.monotonic() - started) * 1000)
        self.get_logger().info(
            f'native ask за {response_msg.latency_ms} ms (tokens={tokens})')
        return response_msg


def main() -> None:
    rclpy.init()
    node = None
    try:
        node = SystemOneNative()
        executor = MultiThreadedExecutor(num_threads=3)
        executor.add_node(node)
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()