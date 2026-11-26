#!/usr/bin/env python3
"""
CLI-пример вызова system_one_ros/srv/Ask с готовым JSON-телом.

    ros2 run system_one_ros example_ask '{"model":"kev-0.8b","state":"…","questions":{…}}'
    ros2 run system_one_ros example_ask --file /tmp/systemone_request.json
    cat /tmp/systemone_request.json | ros2 run system_one_ros example_ask

Один вызов может содержать несколько вопросов: `questions` — объект,
где ключ — имя вопроса, значение — объект с `type` (`choice`, `noul`, `score`),
`instructions` и `criteria`.
"""

from __future__ import annotations

import argparse
import json
import sys

import rclpy
from rclpy.node import Node

from llm_msgs_ros.srv import Ask


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Вызов system-one-rknn через ROS 2 сервис system_one_ros/srv/Ask')
    parser.add_argument(
        'request_json', nargs='?',
        help='JSON-тело POST /v1/systemone; пусто — читать stdin')
    parser.add_argument(
        '--file', help='файл с JSON-телом (альтернатива позиционному аргументу)')
    parser.add_argument(
        '--service', default='/system_one/ask', help='имя сервиса Ask')
    parser.add_argument(
        '--timeout', type=float, default=30.0,
        help='ожидание сервиса и ответа, с')
    args = parser.parse_args()

    if args.request_json and args.file:
        parser.error('укажите либо JSON-аргумент, либо --file')
    if args.file:
        try:
            with open(args.file, encoding='utf-8') as handle:
                args.request_json = handle.read()
        except OSError as exc:
            parser.error(f'не удалось прочитать {args.file}: {exc}')
    if not args.request_json:
        args.request_json = sys.stdin.read()
    if not args.request_json.strip():
        parser.error('пустое JSON-тело запроса')

    try:
        payload = json.loads(args.request_json)
    except json.JSONDecodeError as exc:
        parser.error(f'некорректный JSON: {exc}')
    if not isinstance(payload, dict):
        parser.error('JSON-тело должно быть объектом')
    args.request_json = json.dumps(payload, ensure_ascii=False)
    return args


def main() -> int:
    args = parse_args()
    rclpy.init()
    node = Node('system_one_example')
    try:
        client = node.create_client(Ask, args.service)
        if not client.wait_for_service(timeout_sec=args.timeout):
            print(f'сервис {args.service} не найден', file=sys.stderr)
            return 2

        request = Ask.Request()
        request.request_json = args.request_json
        future = client.call_async(request)
        rclpy.spin_until_future_complete(node, future, timeout_sec=args.timeout)
        if future.result() is None:
            print(f'нет ответа от {args.service}', file=sys.stderr)
            return 3
        response = future.result()
        try:
            body = json.loads(response.response_json or '{}')
        except json.JSONDecodeError:
            body = response.response_json
        print(json.dumps({
            'success': bool(response.success),
            'message': response.message,
            'http_status': int(response.http_status),
            'latency_ms': int(response.latency_ms),
            'response': body,
        }, ensure_ascii=False, indent=2))
        return 0 if response.success else 1
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
