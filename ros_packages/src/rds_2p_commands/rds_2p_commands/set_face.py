#!/usr/bin/env python3
"""Один раз публикует морду в /face/image. Файл: имя под ``share/.../data/faces/`` или абсолютный путь."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

import rclpy
from ament_index_python.packages import get_package_share_directory
from PIL import Image as PILImage
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from sensor_msgs.msg import Image

from rds_2p_commands.face_assets import resolve_face_png


def main(argv: Optional[list[str]] = None) -> int:
    if argv is None:
        argv = sys.argv

    rclpy.init(args=argv)
    node = Node("set_face")

    node.declare_parameter("face", "")
    node.declare_parameter("face_image_topic", "/face/image")
    node.declare_parameter("face_output_width", 280)
    node.declare_parameter("face_output_height", 240)
    node.declare_parameter("wait_after_publish_sec", 0.5)

    face = node.get_parameter("face").get_parameter_value().string_value.strip()
    topic = node.get_parameter("face_image_topic").get_parameter_value().string_value
    ow = node.get_parameter("face_output_width").get_parameter_value().integer_value
    oh = node.get_parameter("face_output_height").get_parameter_value().integer_value
    wait_sec = node.get_parameter("wait_after_publish_sec").get_parameter_value().double_value

    if not face:
        node.get_logger().error(
            "Задайте параметр face, например: "
            '--ros-args -p face:=smileW.png, либо -p face:=lip_sync/A.png, либо абсолютный путь к PNG'
        )
        node.destroy_node()
        rclpy.shutdown()
        return 1

    share = Path(get_package_share_directory("rds_2p_commands"))
    png_path = resolve_face_png(share, face)
    if png_path is None:
        node.get_logger().error(
            f"Нет файла морды «{face}» (искали в {share / 'data' / 'faces'} или по абсолютному пути)"
        )
        node.destroy_node()
        rclpy.shutdown()
        return 1

    qos = QoSProfile(
        depth=10,
        reliability=ReliabilityPolicy.RELIABLE,
        history=HistoryPolicy.KEEP_LAST,
        durability=DurabilityPolicy.VOLATILE,
    )
    pub = node.create_publisher(Image, topic, qos)

    pil = PILImage.open(str(png_path)).convert("RGB")
    if pil.width != ow or pil.height != oh:
        try:
            from PIL.Image import Resampling as _Resampling

            _filt = _Resampling.LANCZOS
        except ImportError:
            _filt = getattr(PILImage, "LANCZOS", 1)
        pil = pil.resize((ow, oh), _filt)

    msg = Image()
    msg.header.stamp = node.get_clock().now().to_msg()
    msg.header.frame_id = "robot_face"
    msg.height = oh
    msg.width = ow
    msg.encoding = "rgb8"
    msg.is_bigendian = False
    msg.step = ow * 3
    msg.data = list(pil.tobytes())

    # короткая прокрутка, чтобы подписчики успели подключиться
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and pub.get_subscription_count() == 0:
        rclpy.spin_once(node, timeout_sec=0.05)

    pub.publish(msg)
    node.get_logger().info(f"Опубликовано: {face} → {topic} ({ow}×{oh}, rgb8)")

    time.sleep(max(0.0, wait_sec))
    node.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
