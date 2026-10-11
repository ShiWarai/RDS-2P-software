#!/usr/bin/env python3
"""Пример multimodal ChatCompletion: картинка с топика ROS или из файла (без cv_bridge).

  Камера (по умолчанию топик Orbbec при camera_name:=camera):
    ros2 run rkllm_ros2 example_vision.py "Что на камере?"

  Файл на диске (нужен Pillow / python3-pil):
    ros2 run rkllm_ros2 example_vision.py --image photo.jpg "Опиши кратко"

  Другой топик:
    ros2 run rkllm_ros2 example_vision.py --topic /my_cam/color/image_raw "Вопрос"
"""

from __future__ import annotations

import argparse
import array
import sys
import time

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image as RosImage

from rkllm_ros2.action import ChatCompletion


def _try_clear_kv(node: Node, action_name: str) -> float | None:
    """Длительность вызова сервиса в секундах или None."""
    from std_srvs.srv import Trigger

    base = action_name.rpartition('/')[0]
    srv_name = base + '/clear_kv_cache'
    cli = node.create_client(Trigger, srv_name)
    if not cli.wait_for_service(timeout_sec=5.0):
        node.get_logger().warn(f'{srv_name} недоступен')
        return None
    t0 = time.monotonic()
    fut = cli.call_async(Trigger.Request())
    rclpy.spin_until_future_complete(node, fut)
    dt = time.monotonic() - t0
    res = fut.result()
    if res is None or not res.success:
        msg = res.message if res else 'нет ответа'
        node.get_logger().warn(f'clear_kv_cache: {msg}')
    return dt


def _image_to_rgb8_bytes(msg: RosImage) -> tuple[RosImage, bytes]:
    """Новое сообщение rgb8 + байты RGB."""
    enc = msg.encoding.lower().replace('_', '')
    h, w = msg.height, msg.width

    if enc == 'rgb8':
        raw = bytes(msg.data)
        need = h * w * 3
        if len(raw) != need:
            raise ValueError(f'rgb8: ожидалось {need} байт, получено {len(raw)}')
        out = RosImage(header=msg.header)
        out.height = h
        out.width = w
        out.encoding = 'rgb8'
        out.is_bigendian = msg.is_bigendian
        out.step = w * 3
        out.data = array.array('B', raw)
        return out, raw

    if enc == 'bgr8':
        raw_l = array.array('B', msg.data)
        need = h * w * 3
        if len(raw_l) != need:
            raise ValueError(f'bgr8: ожидалось {need} байт, получено {len(raw_l)}')
        for i in range(0, need, 3):
            raw_l[i], raw_l[i + 2] = raw_l[i + 2], raw_l[i]
        out = RosImage(header=msg.header)
        out.height = h
        out.width = w
        out.encoding = 'rgb8'
        out.is_bigendian = msg.is_bigendian
        out.step = w * 3
        out.data = raw_l
        return out, raw_l.tobytes()

    raise ValueError(
        f'Кодировка "{msg.encoding}" не поддерживается без cv_bridge; '
        'для топика используйте rgb8/bgr8 или камеру в режиме RGB.'
    )


def _pil_file_to_ros_rgb(node: Node, path: str) -> RosImage:
    try:
        from PIL import Image
    except ImportError as e:
        raise SystemExit(
            'Для --image нужен Pillow: sudo apt install python3-pil'
        ) from e

    pil = Image.open(path).convert('RGB')
    w, h = pil.size
    raw = pil.tobytes()
    msg = RosImage()
    msg.header.stamp = node.get_clock().now().to_msg()
    msg.header.frame_id = ''
    msg.height = h
    msg.width = w
    msg.encoding = 'rgb8'
    msg.is_bigendian = 0
    msg.step = w * 3
    msg.data = array.array('B', raw)
    return msg


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--image',
        metavar='PATH',
        default=None,
        help='Файл изображения (jpg/png/…); без этого кадр берётся с --topic',
    )
    parser.add_argument(
        'prompt',
        nargs='?',
        default=None,
        help='Текстовый вопрос к модели',
    )
    parser.add_argument(
        '--topic',
        default='/camera/color/image_raw',
        help='Топик sensor_msgs/Image, если не задан --image',
    )
    parser.add_argument('--action', default='/rkllm_ros2/complete')
    parser.add_argument(
        '--timeout',
        type=float,
        default=15.0,
        help='Секунды ожидания первого кадра с топика',
    )
    parser.add_argument(
        '--no-clear-start',
        action='store_true',
        help='Не вызывать ~/clear_kv_cache перед отправкой',
    )
    parser.add_argument(
        '--keep-history',
        action='store_true',
        help='goal.keep_history=true',
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Меньше промежуточных логов',
    )
    args = parser.parse_args()

    default_prompt_cam = 'Опиши, что видишь на изображении с камеры. Кратко.'
    default_prompt_file = 'Опиши изображение кратко.'
    prompt = args.prompt
    if prompt is None:
        prompt = default_prompt_file if args.image else default_prompt_cam

    def log(msg: str) -> None:
        if not args.quiet:
            node.get_logger().info(msg)

    rclpy.init()
    node = Node('rkllm_example_vision')

    latest: list[RosImage | None] = [None]

    def cb(msg: RosImage) -> None:
        latest[0] = msg

    sub = None
    if args.image is None:
        sub = node.create_subscription(
            RosImage,
            args.topic,
            cb,
            qos_profile_sensor_data,
        )

    client = ActionClient(node, ChatCompletion, args.action)

    try:
        t_run_start = time.monotonic()
        if not client.wait_for_server(timeout_sec=60.0):
            node.get_logger().error(f'нет сервера {args.action}')
            sys.exit(1)
        log(f'action server готов за {(time.monotonic() - t_run_start) * 1000.0:.1f} ms')

        if args.image is not None:
            t_load = time.monotonic()
            rgb_msg = _pil_file_to_ros_rgb(node, args.image)
            log(
                f'файл {args.image} загружен за {(time.monotonic() - t_load) * 1000.0:.1f} ms '
                f'({rgb_msg.width}x{rgb_msg.height} rgb8)'
            )
        else:
            log(f'Жду кадр с {args.topic} …')
            t_wait_img = time.monotonic()
            deadline = time.monotonic() + args.timeout
            while latest[0] is None and time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=0.05)

            snap = latest[0]
            if snap is None:
                node.get_logger().error(
                    f'Нет кадров за {args.timeout} с. Проверьте камеру и топик '
                    f'(ros2 topic echo {args.topic} --no-arr)'
                )
                sys.exit(1)

            log(
                f'кадр получен за {(time.monotonic() - t_wait_img) * 1000.0:.1f} ms '
                f'({snap.width}x{snap.height} {snap.encoding}, {len(snap.data)} байт)'
            )

            if sub is not None:
                node.destroy_subscription(sub)
                sub = None

            t_conv = time.monotonic()
            try:
                rgb_msg, _ = _image_to_rgb8_bytes(snap)
            except ValueError as e:
                node.get_logger().error(str(e))
                sys.exit(1)
            log(f'конвертация в rgb8 за {(time.monotonic() - t_conv) * 1000.0:.1f} ms')

        rgb_msg.header.stamp = node.get_clock().now().to_msg()

        if not args.no_clear_start:
            t_clr = time.monotonic()
            clear_dt = _try_clear_kv(node, args.action)
            clr_wall_ms = (time.monotonic() - t_clr) * 1000.0
            if clear_dt is not None:
                log(f'clear_kv_cache round-trip {clear_dt * 1000.0:.1f} ms (wall {clr_wall_ms:.1f} ms)')
            else:
                log(f'clear_kv_cache не выполнен (wall {clr_wall_ms:.1f} ms)')

        goal = ChatCompletion.Goal()
        goal.image = rgb_msg
        goal.user_message = prompt
        goal.keep_history = args.keep_history
        goal.max_new_tokens = 0

        goal_payload_bytes = len(rgb_msg.data)

        first_token_mono: list[float | None] = [None]

        def feedback_cb(msg):
            t = msg.feedback.token
            if t:
                if first_token_mono[0] is None:
                    first_token_mono[0] = time.monotonic()
                print(t, end='', flush=True)

        t_send = time.monotonic()
        fut_goal = client.send_goal_async(goal, feedback_callback=feedback_cb)
        rclpy.spin_until_future_complete(node, fut_goal)
        gh = fut_goal.result()
        accepted_dt_ms = (time.monotonic() - t_send) * 1000.0
        log(
            f'goal принят за {accepted_dt_ms:.1f} ms с момента send_goal '
            f'(Image payload ~{goal_payload_bytes} байт)'
        )
        if not gh.accepted:
            print('\n[цель отклонена]', file=sys.stderr)
            sys.exit(1)

        t_result_wait = time.monotonic()
        fut_res = gh.get_result_async()
        rclpy.spin_until_future_complete(node, fut_res)
        result_wait_ms = (time.monotonic() - t_result_wait) * 1000.0
        res = fut_res.result().result
        print()
        if first_token_mono[0] is not None:
            ttft_ms = (first_token_mono[0] - t_send) * 1000.0
            log(f'первый токен (TTFT) ~{ttft_ms:.1f} ms от send_goal')

        if not res.success:
            node.get_logger().error(res.message)
            sys.exit(1)

        total_wall_ms = (time.monotonic() - t_run_start) * 1000.0
        node.get_logger().info(
            f'{res.message} | клиент: wall_total_ms={total_wall_ms:.1f} '
            f'result_wait_ms={result_wait_ms:.1f} accepted_latency_ms={accepted_dt_ms:.1f}'
        )
        node.get_logger().info(
            f'RKLLM result metrics: prefill_ms={res.prefill_time_ms:.2f} '
            f'generate_ms={res.generate_time_ms:.2f} tokens={res.generate_tokens}'
        )

    finally:
        if sub is not None:
            try:
                node.destroy_subscription(sub)
            except Exception:
                pass
        try:
            node.destroy_node()
        except Exception:
            pass
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
