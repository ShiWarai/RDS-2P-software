#!/usr/bin/env python3
"""AudioStamped (шина воспроизведения) → RMS + EMA → PNG лица по манифесту → sensor_msgs/Image."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import rclpy
from ament_index_python.packages import get_package_share_directory
from audio_common_msgs.msg import AudioStamped
from rclpy.node import Node
from rclpy.time import Time
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None  # type: ignore[misc, assignment]

PA_FLOAT32 = 1
PA_INT16 = 8


@dataclass
class MouthLevel:
    id: str
    file: str
    rms_min: float
    rms_max: float
    zcr_min: float = 0.0
    zcr_max: float = 1.0
    hf_min: float = 0.0
    hf_max: float = 1.0


def _pil_resample():
    if PILImage is None:
        return None
    return getattr(PILImage.Resampling, "LANCZOS", PILImage.LANCZOS)


class LipSyncFaceNode(Node):
    def __init__(self) -> None:
        super().__init__("lip_sync_face")

        self.declare_parameter("audio_topic", "/audio/output")
        self.declare_parameter("audio_frame_id", "tts.paroli")
        self.declare_parameter("face_topic", "/face/image")
        self.declare_parameter("manifest_path", "")
        self.declare_parameter("output_width", 280)
        self.declare_parameter("output_height", 240)
        self.declare_parameter("audio_qos_depth", 50)
        self.declare_parameter("rms_floor", 0.002)
        self.declare_parameter("rms_ceiling", 0.12)
        self.declare_parameter("mouth_gain", 1.0)
        self.declare_parameter("smooth_alpha", 0.35)
        self.declare_parameter("silence_rms", 0.004)
        self.declare_parameter("silence_hold_chunks", 3)
        self.declare_parameter("max_face_hz", 24.0)
        # Если true — при старте сразу шлёт neutral в face_topic и затирает то, что уже было на дисплее.
        self.declare_parameter("publish_initial_neutral", False)
        # Нет сообщений на дорожке дольше — считаем речь закончилась, закрываем рот.
        self.declare_parameter("audio_idle_timeout_sec", 0.2)
        self.declare_parameter("idle_poll_hz", 30.0)
        self.declare_parameter("use_zcr_feature", True)
        self.declare_parameter("use_hf_ratio_feature", True)
        self.declare_parameter("zcr_floor", 0.02)
        self.declare_parameter("zcr_ceiling", 0.55)
        self.declare_parameter("hf_ratio_ceiling", 8.0)
        self.declare_parameter("feature_smooth_alpha", 0.4)

        share = get_package_share_directory("rds_2p_face")
        default_manifest = os.path.join(share, "config", "lip_sync_manifest.json")
        mp = (self.get_parameter("manifest_path").get_parameter_value().string_value or "").strip()
        manifest_path = mp if mp else default_manifest

        ow = int(self.get_parameter("output_width").value)
        oh = int(self.get_parameter("output_height").value)

        self._neutral_id = ""
        self._levels: List[MouthLevel] = []
        self._images: Dict[str, Tuple[bytes, int, int]] = {}
        self._assets_dir = ""

        self._load_manifest(manifest_path, ow, oh, share)

        self._smooth_mouth = 0.0
        self._smooth_zcr = 0.5
        self._smooth_hf = 0.25
        self._silence_counter = 0
        self._last_pub_mono = self.get_clock().now()
        self._last_level_id: Optional[str] = None
        self._logged_first_audio = False
        self._last_audio_rcvd_mono: Optional[Time] = None
        self._track_idle_latched = False

        audio_topic = self.get_parameter("audio_topic").value
        frame_filter = (
            self.get_parameter("audio_frame_id").get_parameter_value().string_value or ""
        ).strip()

        depth = max(10, int(self.get_parameter("audio_qos_depth").value))
        sub_qos = QoSProfile(
            depth=depth,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            durability=DurabilityPolicy.VOLATILE,
        )

        self._frame_filter = frame_filter

        pub_qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            durability=DurabilityPolicy.VOLATILE,
        )

        self._pub = self.create_publisher(Image, self.get_parameter("face_topic").value, pub_qos)

        self.create_subscription(AudioStamped, audio_topic, self._on_audio, sub_qos)

        self._rms_floor = float(self.get_parameter("rms_floor").value)
        self._rms_ceiling = float(self.get_parameter("rms_ceiling").value)
        self._mouth_gain = float(self.get_parameter("mouth_gain").value)
        self._smooth_alpha = float(self.get_parameter("smooth_alpha").value)
        self._silence_rms = float(self.get_parameter("silence_rms").value)
        self._silence_hold = max(1, int(self.get_parameter("silence_hold_chunks").value))
        self._max_face_hz = max(0.5, float(self.get_parameter("max_face_hz").value))
        self._min_pub_period = 1.0 / self._max_face_hz
        self._audio_idle_timeout = max(0.03, float(self.get_parameter("audio_idle_timeout_sec").value))
        poll_hz = max(5.0, float(self.get_parameter("idle_poll_hz").value))
        self._use_zcr_feature = bool(self.get_parameter("use_zcr_feature").value)
        self._use_hf_ratio_feature = bool(self.get_parameter("use_hf_ratio_feature").value)
        self._zcr_floor = max(1e-6, float(self.get_parameter("zcr_floor").value))
        self._zcr_ceiling = max(self._zcr_floor + 1e-6, float(self.get_parameter("zcr_ceiling").value))
        self._hf_ratio_ceiling = max(1e-6, float(self.get_parameter("hf_ratio_ceiling").value))
        self._feat_alpha = float(self.get_parameter("feature_smooth_alpha").value)
        self._feat_alpha = max(0.01, min(1.0, self._feat_alpha))
        self._oh = oh
        self._ow = ow

        period = 1.0 / poll_hz
        self.create_timer(period, self._idle_tick)

        if bool(self.get_parameter("publish_initial_neutral").value):
            self._publish_face(self._neutral_id)
            self._last_level_id = self._neutral_id
            self._last_pub_mono = self.get_clock().now()

        self.get_logger().info(
            f"lip_sync_face: manifest={manifest_path}, assets_dir={self._assets_dir}, levels={len(self._levels)}, neutral={self._neutral_id}; "
            f"слушаю {audio_topic} (frame_id filter={frame_filter!r}); "
            f"публикация в {self.get_parameter('face_topic').value}. "
            "Кадры лица меняются только при входящем аудио (и после старта при publish_initial_neutral:=false "
            "топик не трогается). Нужны Paroli/audio_player на той же шине."
        )

    def _idle_tick(self) -> None:
        if self._last_audio_rcvd_mono is None:
            return
        now = self.get_clock().now()
        dt = (now - self._last_audio_rcvd_mono).nanoseconds / 1e9
        if dt < self._audio_idle_timeout:
            self._track_idle_latched = False
            return
        if self._track_idle_latched:
            return
        self._track_idle_latched = True
        self._smooth_mouth = 0.0
        self._smooth_zcr = 0.5
        self._smooth_hf = 0.25
        self._silence_counter = max(self._silence_hold, self._silence_counter)

        now_pub = self.get_clock().now()
        dt_pub = (now_pub - self._last_pub_mono).nanoseconds / 1e9
        if self._last_level_id == self._neutral_id and dt_pub < self._min_pub_period:
            return

        self._publish_face(self._neutral_id)
        self._last_pub_mono = now_pub
        self._last_level_id = self._neutral_id

    def _load_manifest(self, path: str, ow: int, oh: int, pkg_share: str) -> None:
        if PILImage is None:
            raise RuntimeError("Требуется Pillow (пакет python3-pil)")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"manifest не найден: {path}")
        manifest_abs = os.path.abspath(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        assets_spec = (data.get("assets_dir") or "").strip()
        if assets_spec:
            base_dir = (
                assets_spec
                if os.path.isabs(assets_spec)
                else os.path.normpath(os.path.join(pkg_share, assets_spec))
            )
        else:
            base_dir = os.path.dirname(manifest_abs)
        neutral_id = data.get("neutral_id", "")
        if not neutral_id:
            raise ValueError("neutral_id обязателен в манифесте")
        raw_levels = data.get("mouth_levels", [])
        if not raw_levels:
            raise ValueError("mouth_levels пуст")

        levels: List[MouthLevel] = []
        for row in raw_levels:
            levels.append(
                MouthLevel(
                    id=str(row["id"]),
                    file=str(row["file"]),
                    rms_min=float(row["rms_min"]),
                    rms_max=float(row["rms_max"]),
                    zcr_min=float(row.get("zcr_min", 0.0)),
                    zcr_max=float(row.get("zcr_max", 1.0)),
                    hf_min=float(row.get("hf_min", 0.0)),
                    hf_max=float(row.get("hf_max", 1.0)),
                )
            )

        images: Dict[str, Tuple[bytes, int, int]] = {}
        resample = _pil_resample()

        for lvl in levels:
            fp = os.path.join(base_dir, lvl.file)
            if not os.path.isfile(fp):
                self.get_logger().error(f"Нет файла {fp} для id={lvl.id}")
                continue
            pil = PILImage.open(fp).convert("RGB")
            pil = pil.resize((ow, oh), resample)
            raw_b = pil.tobytes()
            step = ow * 3
            images[lvl.id] = (raw_b, step, ow)

        self._neutral_id = neutral_id
        self._levels = levels

        if neutral_id not in images:
            raise RuntimeError(
                f"neutral_id={neutral_id}: изображение не загружено (проверьте file и пути PNG)"
            )

        neutral_bytes = images[neutral_id]
        for lvl in levels:
            if lvl.id not in images:
                self.get_logger().warn(f"id={lvl.id}: нет файла — используется картинка neutral")
                images[lvl.id] = neutral_bytes

        self._images = images
        self._assets_dir = base_dir

    def _samples_mono_float(self, msg: AudioStamped) -> np.ndarray:
        info = msg.audio.info
        fmt = int(info.format)
        ch = max(1, int(info.channels))

        if fmt == PA_FLOAT32:
            raw = np.asarray(msg.audio.audio_data.float32_data, dtype=np.float32)
        elif fmt == PA_INT16:
            raw = (
                np.asarray(msg.audio.audio_data.int16_data, dtype=np.int16).astype(np.float32)
                / 32768.0
            )
        else:
            self.get_logger().warn_throttle(
                5000, "lip_sync_face: формат аудио %s не поддержан (нужны int16 или float32)" % fmt
            )
            return np.array([], dtype=np.float32)

        if raw.size == 0:
            return raw
        usable = (raw.size // ch) * ch
        raw = raw[:usable]
        frames = raw.reshape(-1, ch)
        if ch == 1:
            return frames[:, 0]
        return np.mean(frames, axis=1)

    @staticmethod
    def _chunk_rms(mono: np.ndarray) -> float:
        if mono.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(mono))))

    @staticmethod
    def _chunk_zcr01(mono: np.ndarray) -> float:
        """Доля переходов через ноль (~шипящие / шум относительно чистого тона)."""
        if mono.size < 2:
            return 0.0
        zc = float(np.sum(mono[:-1] * mono[1:] < 0.0))
        return zc / float(mono.size - 1)

    @staticmethod
    def _chunk_hf_ratio(mono: np.ndarray, rms: float) -> float:
        """RMS(first diff) / RMS(signal): нажимные согласные / шипящие часто дают больший относительный наклон."""
        if mono.size < 2:
            return 0.0
        d = np.diff(mono)
        d_rms = float(np.sqrt(np.mean(np.square(d))))
        return d_rms / (rms + 1e-8)

    def _normalize_openness(self, rms: float) -> float:
        lo = max(self._rms_floor, 1e-9)
        hi = max(self._rms_ceiling, lo + 1e-9)
        t = (rms - lo) / (hi - lo)
        t = max(0.0, min(1.0, t))
        g = max(0.0, self._mouth_gain)
        return min(1.0, t * g)

    def _normalize_zcr(self, zcr_raw: float) -> float:
        lo = self._zcr_floor
        hi = self._zcr_ceiling
        t = (zcr_raw - lo) / (hi - lo)
        return max(0.0, min(1.0, t))

    def _normalize_hf_ratio(self, hf_raw: float) -> float:
        t = hf_raw / self._hf_ratio_ceiling
        return max(0.0, min(1.0, t))

    def _level_matches(self, lvl: MouthLevel, openness: float, z_n: float, hf_n: float) -> bool:
        if not (lvl.rms_min <= openness <= lvl.rms_max):
            return False
        if self._use_zcr_feature:
            if not (lvl.zcr_min <= z_n <= lvl.zcr_max):
                return False
        if self._use_hf_ratio_feature:
            if not (lvl.hf_min <= hf_n <= lvl.hf_max):
                return False
        return True

    def _pick_level(self, openness: float, z_n: float, hf_n: float) -> str:
        chosen = self._neutral_id
        for lvl in self._levels:
            if self._level_matches(lvl, openness, z_n, hf_n):
                chosen = lvl.id
        return chosen

    def _on_audio(self, msg: AudioStamped) -> None:
        fid = (msg.header.frame_id or "").strip()
        if self._frame_filter and fid != self._frame_filter:
            return

        self._last_audio_rcvd_mono = self.get_clock().now()
        self._track_idle_latched = False

        mono = self._samples_mono_float(msg)
        rms = self._chunk_rms(mono)
        z_raw = self._chunk_zcr01(mono)
        hf_raw = self._chunk_hf_ratio(mono, rms)

        if not self._logged_first_audio and mono.size > 0:
            self._logged_first_audio = True
            self.get_logger().info(
                f"первый аудио-чанк (frame_id={fid!r}), samples={mono.size} — липсинк активен"
            )

        if rms < self._silence_rms:
            self._silence_counter += 1
        else:
            self._silence_counter = 0

        openness_raw = self._normalize_openness(rms)
        z_n_raw = self._normalize_zcr(z_raw)
        hf_n_raw = self._normalize_hf_ratio(hf_raw)
        a = self._smooth_alpha
        fa = self._feat_alpha
        self._smooth_mouth = a * openness_raw + (1.0 - a) * self._smooth_mouth
        self._smooth_zcr = fa * z_n_raw + (1.0 - fa) * self._smooth_zcr
        self._smooth_hf = fa * hf_n_raw + (1.0 - fa) * self._smooth_hf

        if self._silence_counter >= self._silence_hold:
            level_id = self._neutral_id
        else:
            level_id = self._pick_level(self._smooth_mouth, self._smooth_zcr, self._smooth_hf)

        now = self.get_clock().now()
        dt = (now - self._last_pub_mono).nanoseconds / 1e9
        if (
            self._last_level_id is not None
            and dt < self._min_pub_period
            and level_id == self._last_level_id
        ):
            return

        self._publish_face(level_id)
        self._last_pub_mono = now
        self._last_level_id = level_id

    def _publish_face(self, level_id: str) -> None:
        payload = self._images.get(level_id) or self._images[self._neutral_id]
        data, step, width = payload

        out = Image()
        out.header.stamp = self.get_clock().now().to_msg()
        out.header.frame_id = "lip_sync_face"
        out.height = self._oh
        out.width = width
        out.encoding = "rgb8"
        out.is_bigendian = False
        out.step = step
        out.data = data
        self._pub.publish(out)


def main(args: Optional[list[str]] = None) -> None:
    rclpy.init(args=args)
    node: Optional[LipSyncFaceNode] = None
    try:
        node = LipSyncFaceNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
