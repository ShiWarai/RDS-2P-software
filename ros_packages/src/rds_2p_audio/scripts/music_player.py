#!/usr/bin/env python3
"""Плеер аудиофайлов в ROS2-шину /audio/output.

Декодирует файл (mp3/wav/flac/...) через ffmpeg в PCM16 44100 Hz stereo и
публикует в /audio/output с header.frame_id='music'. Узел audio_player
микширует этот поток с TTS.

Примеры:
    python3 music_player.py "/home/orangepi/RDS-2P-software/Log/Мираж Электричество.mp3"
    python3 music_player.py track.mp3 --loop --gain 0.7
"""

from __future__ import annotations

import argparse
import array
import signal
import shutil
import subprocess
import threading
import time

import numpy as np
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.signals import SignalHandlerOptions

from audio_common_msgs.msg import AudioInfo, AudioStamped

RATE = 44100
CHANNELS = 2
PA_INT16 = 8
TICK_S = 0.02
FRAMES_PER_TICK = int(round(RATE * TICK_S))
FRAME_ID = "music"


class MusicPlayer(Node):
    def __init__(self, path: str, topic: str, gain: float, loop: bool) -> None:
        super().__init__("music_player")
        if shutil.which("ffmpeg") is None:
            raise SystemExit("ffmpeg не найден")

        self._loop = loop
        self._gain = gain
        self._stop = threading.Event()

        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        self._pub = self.create_publisher(AudioStamped, topic, qos)

        t0 = time.monotonic()
        self._pcm = self._decode(path)
        dur = self._pcm.size / (RATE * CHANNELS)
        self.get_logger().info(
            f"«{path}»: {dur:.1f} с, gain={gain:g}, loop={'да' if loop else 'нет'}, "
            f"декодировано за {time.monotonic() - t0:.1f} с"
        )
        self._thread = threading.Thread(target=self._play, daemon=True)
        self._thread.start()

    def _decode(self, path: str) -> np.ndarray:
        cmd = [
            "ffmpeg", "-nostdin", "-v", "error", "-i", path,
            "-f", "s16le", "-acodec", "pcm_s16le",
            "-ac", str(CHANNELS), "-ar", str(RATE), "-",
        ]
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0:
            err = proc.stderr.decode(errors="replace").strip()
            raise SystemExit(f"ffmpeg: {err}")
        pcm = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32)
        if self._gain != 1.0:
            pcm = np.clip(pcm * self._gain, -32768.0, 32767.0)
        usable = (pcm.size // CHANNELS) * CHANNELS
        return pcm[:usable]

    def _play(self) -> None:
        block = FRAMES_PER_TICK * CHANNELS
        pos = 0
        ticks = 0
        t0 = time.monotonic()
        warned_sub = False

        while not self._stop.is_set():
            chunk = self._pcm[pos:pos + block]
            if chunk.size == 0:
                if self._loop:
                    pos = 0
                    ticks = 0
                    t0 = time.monotonic()
                    continue
                self.get_logger().info("Конец трека")
                break

            msg = AudioStamped()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = FRAME_ID
            msg.audio.info = AudioInfo(
                format=PA_INT16, channels=CHANNELS, rate=RATE, chunk=FRAMES_PER_TICK
            )
            msg.audio.audio_data.int16_data = array.array(
                "h", chunk.astype(np.int16).tobytes()
            )
            try:
                self._pub.publish(msg)
            except Exception:
                if self._stop.is_set() or not rclpy.ok():
                    break
                raise

            if (
                not warned_sub
                and time.monotonic() - t0 > 2.0
                and self._pub.get_subscription_count() == 0
            ):
                warned_sub = True
                self.get_logger().warn(
                    "на топик никто не подписан — audio_player не запущен?"
                )

            pos += chunk.size
            ticks += 1
            delay = t0 + ticks * TICK_S - time.monotonic()
            if delay > 0:
                self._stop.wait(delay)

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

    @property
    def finished(self) -> bool:
        return not self._thread.is_alive()


def main() -> None:
    parser = argparse.ArgumentParser(description="ROS2-плеер аудиофайлов")
    parser.add_argument("path", help="аудиофайл (mp3/wav/flac/...)")
    parser.add_argument("--loop", action="store_true", help="повторять трек")
    parser.add_argument(
        "--gain", type=float, default=1.0, help="усиление сэмплов (1.0 = без изменений)"
    )
    parser.add_argument(
        "--topic", default="/audio/output", help="топик AudioStamped (по умолчанию /audio/output)"
    )
    args = parser.parse_args()

    def _on_term(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _on_term)

    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    player = MusicPlayer(args.path, args.topic, args.gain, args.loop)
    try:
        while rclpy.ok() and not player.finished:
            rclpy.spin_once(player, timeout_sec=0.1)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        player.shutdown()
        player.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()