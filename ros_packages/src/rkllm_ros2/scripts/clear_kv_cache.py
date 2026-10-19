#!/usr/bin/env python3
"""Сброс KV-кэша (истории диалога) на ноде rkllm_ros2 — std_srvs/Trigger ~/clear_kv_cache.

  ros2 run rkllm_ros2 clear_kv_cache.py
  ros2 run rkllm_ros2 clear_kv_cache.py --service /my_ns/clear_kv_cache

Сервис отвечает success=false, если нода занята goal. Требуется запущенная нода
(ros2 launch rkllm_ros2 rkllm.launch.py ...).
"""

from __future__ import annotations

import argparse
import sys

import rclpy
from rclpy.node import Node
from std_srvs.srv import Trigger


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--service',
        default='/rkllm_ros2/clear_kv_cache',
        help='Имя сервиса Trigger (по умолчанию /rkllm_ros2/clear_kv_cache)',
    )
    parser.add_argument(
        '--timeout',
        type=float,
        default=5.0,
        help='Ожидание сервиса и ответа, сек',
    )
    args = parser.parse_args()

    rclpy.init()
    node = Node('rkllm_clear_kv_cache')
    try:
        cli = node.create_client(Trigger, args.service)
        if not cli.wait_for_service(timeout_sec=args.timeout):
            node.get_logger().error(
                f'нет сервиса {args.service} (запущен ли rkllm_node?)')
            sys.exit(2)

        fut = cli.call_async(Trigger.Request())
        rclpy.spin_until_future_complete(node, fut, timeout_sec=args.timeout)
        res = fut.result()
        if res is None:
            node.get_logger().error('нет ответа от сервиса (таймаут)')
            sys.exit(3)

        if res.success:
            print(f'ok: {res.message}')
            sys.exit(0)
        node.get_logger().error(res.message)
        sys.exit(1)
    finally:
        try:
            node.destroy_node()
        except Exception:
            pass
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass


if __name__ == '__main__':
    main()