"""Сценарии PandaCommand: звук (AudioStamped), морда (sensor_msgs Image), моторы — лог pos по calibrate.json."""

from __future__ import annotations

import array
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import yaml
from ament_index_python.packages import get_package_share_directory

import numpy as np
from PIL import Image as PILImage

from rclpy.node import Node
from rclpy.qos import (
    QoSProfile,
    ReliabilityPolicy,
    HistoryPolicy,
    DurabilityPolicy,
)

from sensor_msgs.msg import Image
from audio_common_msgs.msg import AudioStamped

from rds_2p_commands.action import PandaCommand
from rds_2p_commands.face_assets import resolve_face_png
from rds_2p_commands.servo_constants import SERVO_IDS
from rds_2p_commands.motor_calibration import calculate_position, load_calibration_json

# PortAudio paInt16
PA_INT16 = 8


def _np_int16_to_ros_sequence(samples: np.ndarray) -> array.array:
    flat = np.asarray(samples, dtype=np.int16).reshape(-1)
    out = array.array("h")
    out.frombytes(flat.tobytes())
    return out


def _mono_float_from_wav(path: Path) -> tuple[np.ndarray, int]:
    """WAV → mono float32 [-1,1], sample rate."""
    with wave.open(str(path), "rb") as wf:
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        sr = wf.getframerate()
        n = wf.getnframes()
        raw = wf.readframes(n)
    if sw == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {sw}")
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data, sr


def _resample_mono(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out or len(x) == 0:
        return x.astype(np.float32)
    new_len = max(1, int(round(len(x) * sr_out / sr_in)))
    t_old = np.arange(len(x), dtype=np.float64) / float(sr_in)
    t_new = np.arange(new_len, dtype=np.float64) / float(sr_out)
    return np.interp(t_new, t_old, x.astype(np.float64)).astype(np.float32)


def _try_import_pray_snippet():
    """Кейфреймы pray из rtulab_feetech (как voice_control)."""
    rtulab = Path("/home/orangepi/rtulab_feetech")
    root = str(rtulab)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from leg.pray_snippet_motion_embedded import (  # type: ignore[import-untyped]
            DEFAULT_RECORDING_SPEEDUP,
            POSITION_4_N,
            PRAY_SNIPPET_KEYFRAMES,
        )

        return PRAY_SNIPPET_KEYFRAMES, POSITION_4_N, DEFAULT_RECORDING_SPEEDUP
    except Exception:  # noqa: BLE001
        return None, None, 3.0


class RobotRoutineHandler:
    """Обработчик PandaCommand (долгое выполнение при MultiThreadedExecutor)."""

    def __init__(self, node: Node) -> None:
        self.node = node
        # commands_config объявляет unified_action_server на той же ноде — не дублировать
        if not self.node.has_parameter("commands_config"):
            self.node.declare_parameter("commands_config", "commands.yaml")
        self.node.declare_parameter("panda_poses_config", "panda_poses.yaml")
        self.node.declare_parameter("audio_output_topic", "/audio/output")
        self.node.declare_parameter(
            "audio_output_rate",
            44100,
        )
        self.node.declare_parameter("audio_playback_chunk_size", 2048)
        self.node.declare_parameter("audio_wait_for_subscribers_sec", 2.0)
        self.node.declare_parameter("audio_output_force_stereo", True)
        self.node.declare_parameter("face_image_topic", "/face/image")
        self.node.declare_parameter("face_output_width", 280)
        self.node.declare_parameter("face_output_height", 240)
        self.node.declare_parameter("playback_volume_percent", 100.0)
        # Подогнать уровень тихих WAV под полный float [-1,1] до умножения на volume (как «громче» TTS).
        self.node.declare_parameter("wav_peak_normalize", True)
        self.node.declare_parameter("allow_real_systemd", False)
        self.node.declare_parameter("allow_real_joystick_script", False)
        self.node.declare_parameter(
            "joystick_script_path",
            "/home/orangepi/rtulab_feetech/reconnect_joystick.sh",
        )
        self.node.declare_parameter("audio_output_qos_depth", 50)
        self.node.declare_parameter(
            "motor_calibrate_path",
            "/home/orangepi/rtulab_feetech/calibrate.json",
        )

        audio_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=max(
                10,
                self.node.get_parameter("audio_output_qos_depth")
                .get_parameter_value()
                .integer_value,
            ),
        )
        face_qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            durability=DurabilityPolicy.VOLATILE,
        )

        self._audio_pub = self.node.create_publisher(
            AudioStamped,
            self.node.get_parameter("audio_output_topic")
            .get_parameter_value()
            .string_value,
            audio_qos,
        )
        self._face_pub = self.node.create_publisher(
            Image,
            self.node.get_parameter("face_image_topic").get_parameter_value().string_value,
            face_qos,
        )

        self._share = Path(get_package_share_directory("rds_2p_commands"))
        cfg_name = (
            self.node.get_parameter("commands_config").get_parameter_value().string_value
        )
        cfg_path = self._share / "config" / cfg_name
        with open(cfg_path, "r", encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        self._routines: Dict[str, Any] = doc.get("commands", {})

        poses_name = (
            self.node.get_parameter("panda_poses_config").get_parameter_value().string_value
        )
        poses_path = self._share / "config" / poses_name
        with open(poses_path, "r", encoding="utf-8") as f:
            pdoc = yaml.safe_load(f) or {}
        raw_poses = pdoc.get("poses", {})
        self._poses: Dict[str, List[float]] = {}
        for key, val in raw_poses.items():
            if isinstance(val, list) and len(val) == 12:
                self._poses[str(key)] = [float(x) for x in val]
            else:
                self.node.get_logger().warn(
                    f"panda_poses: пропуск '{key}' — ожидается список из 12 чисел"
                )

        self._calib_params: Optional[Dict[str, Any]] = None
        self._calib_load_attempted = False

        self.node.get_logger().info(
            f"RobotRoutineHandler: загружено {len(self._routines)} сценариев из {cfg_path}, "
            f"{len(self._poses)} поз из {poses_path}"
        )

    def _pose(self, name: str) -> List[float]:
        p = self._poses.get(name)
        if p is None:
            raise KeyError(f"pose '{name}' не найдена в panda_poses.yaml")
        return p

    def _get_calib(self) -> Optional[Dict[str, Any]]:
        if self._calib_load_attempted:
            return self._calib_params
        self._calib_load_attempted = True
        p = (
            self.node.get_parameter("motor_calibrate_path")
            .get_parameter_value()
            .string_value
        )
        self._calib_params = load_calibration_json(p)
        if self._calib_params is None:
            self.node.get_logger().warn(
                f"motor_calibrate_path не загружен ({p}) — логируем только нормализованные доли"
            )
        return self._calib_params

    def _norm_to_pos(
        self, normals: Sequence[float], no_limit: bool = False
    ) -> Optional[List[int]]:
        params = self._get_calib()
        if params is None:
            return None
        return [
            calculate_position(params, motor_id, float(normals[motor_id - 1]), no_limit)
            for motor_id in SERVO_IDS
        ]

    def _log_motor(
        self,
        rid: str,
        source: str,
        label: str,
        normals: Sequence[float],
        *,
        no_limit: bool = False,
        feedback: Optional[Callable[[str], None]] = None,
        speeds: Optional[Sequence[int]] = None,
        times: Optional[Sequence[int]] = None,
        accs: Optional[Sequence[int]] = None,
    ) -> None:
        pos = self._norm_to_pos(normals, no_limit=no_limit)
        extra = ""
        if speeds is not None:
            extra += f" speeds={list(speeds)}"
        if times is not None:
            extra += f" times={list(times)}"
        if accs is not None:
            extra += f" accs={list(accs)}"
        line = (
            f"[MOTORS:{rid}:{source}] {label} norm={[round(float(x), 4) for x in normals]}"
            f"{extra}"
        )
        if pos is not None:
            line += f" pos={pos}"
        self.node.get_logger().info(line[:900])
        if feedback:
            feedback(f"motor: {label}")

    def execute_callback(self, goal_handle):  # ServerGoalHandle
        req = goal_handle.request
        rid = req.routine_id.strip()
        source = req.source.strip() if req.source else "unknown"

        result = PandaCommand.Result(success=False, message="")

        if rid not in self._routines:
            result.message = f"Неизвестный routine_id: {rid}"
            self.node.get_logger().error(result.message)
            goal_handle.abort()
            return result

        cfg_r = dict(self._routines[rid])
        self.node.get_logger().info(f"[{source}] выполнение сценария {rid}")

        def feedback(msg: str) -> None:
            fb = PandaCommand.Feedback()
            fb.status = msg[:200]
            goal_handle.publish_feedback(fb)

        def canceled() -> bool:
            try:
                return bool(goal_handle.is_cancel_requested)
            except Exception:
                return False

        try:
            self._publish_face_if_any(cfg_r, canceled, feedback, source, rid)

            wav_name = cfg_r.get("sound")
            if wav_name:
                wav_path = self._share / "data" / "sounds" / str(wav_name)
                feedback(f"sound: {wav_name}")
                self._play_wav_blocking(wav_path, canceled, rid)

            self._run_motor_program(rid, source, canceled, feedback)

            self._side_effect(rid, cfg_r, canceled, feedback)

            result.success = True
            result.message = f"{rid}: ok"
            goal_handle.succeed()
            return result
        except Exception as exc:  # noqa: BLE001
            self.node.get_logger().exception(f"{rid}: ошибка выполнения: {exc}")
            result.success = False
            result.message = str(exc)
            goal_handle.abort()
            return result

    def _run_motor_program(
        self,
        rid: str,
        source: str,
        canceled_fn,
        feedback,
    ) -> None:
        """Логика моторов из voice_control.py (без ftservo — только лог исполнителя)."""
        dispatch = {
            "give_paw": self._motor_give_paw,
            "stand_at_attention": self._motor_stand_at_attention,
            "dismiss": self._motor_dismiss,
            "lie_down": self._motor_lie_down,
            "rotate": self._motor_rotate,
            "pray": self._motor_pray,
        }
        fn = dispatch.get(rid)
        if fn is None:
            return
        fn(source, canceled_fn, feedback)

    def _motor_give_paw(self, source: str, canceled_fn, feedback) -> None:
        rid = "give_paw"
        self._log_motor(rid, source, "SyncWritePos position_give", self._pose("position_give"), feedback=feedback)
        time.sleep(0.5)
        if canceled_fn():
            return
        note = (
            f"[MOTORS:{rid}:{source}] EnableTorque(3,0); ожидание движения лапой "
            "(аппаратная петля ReadPos пропущена — нет ftservo)"
        )
        self.node.get_logger().info(note)
        feedback("motor: skip paw torque loop (simulation)")
        time.sleep(0.2)
        if canceled_fn():
            return
        note2 = f"[MOTORS:{rid}:{source}] EnableTorque(3,1)"
        self.node.get_logger().info(note2)
        self._log_motor(rid, source, "position_2", self._pose("position_2"), feedback=feedback)
        time.sleep(0.5)
        self._log_motor(rid, source, "position_1", self._pose("position_1"), feedback=feedback)

    def _motor_stand_at_attention(self, source: str, canceled_fn, feedback) -> None:
        _ = canceled_fn
        self._log_motor(
            "stand_at_attention",
            source,
            "set_position position_2",
            self._pose("position_2"),
            feedback=feedback,
        )

    def _motor_dismiss(self, source: str, canceled_fn, feedback) -> None:
        _ = canceled_fn
        self._log_motor(
            "dismiss",
            source,
            "set_position position_1",
            self._pose("position_1"),
            feedback=feedback,
        )

    def _motor_lie_down(self, source: str, canceled_fn, feedback) -> None:
        rid = "lie_down"
        self._log_motor(rid, source, "set_position position_0", self._pose("position_0"), feedback=feedback)
        for _ in range(10):
            if canceled_fn():
                return
            time.sleep(0.1)
        note = f"[MOTORS:{rid}:{source}] stop_drivers EnableTorque(all, 0)"
        self.node.get_logger().info(note)
        feedback("motor: torque off all")

    def _motor_rotate(self, source: str, canceled_fn, feedback) -> None:
        rid = "rotate"
        times = [0] * 12
        speeds_high = [30000] * 12
        accs_mid = [15] * 12
        speeds_med = [12800] * 12
        accs_hi = [20] * 12
        accs_lo = [5] * 12

        self._log_motor(
            rid,
            source,
            "step1 position_3_0",
            self._pose("position_3_0"),
            feedback=feedback,
            speeds=speeds_high,
            times=times,
            accs=accs_mid,
        )
        time.sleep(1.5)
        if canceled_fn():
            return
        note = f"[MOTORS:{rid}:{source}] stop_drivers (все); sleep 0.5; start_drivers"
        self.node.get_logger().info(note)
        time.sleep(0.5)
        self._log_motor(
            rid,
            source,
            "step2 position_3_1 no_limit",
            self._pose("position_3_1"),
            no_limit=True,
            feedback=feedback,
            speeds=speeds_high,
            times=times,
            accs=accs_mid,
        )
        time.sleep(1.0)
        if canceled_fn():
            return
        self._log_motor(
            rid,
            source,
            "step3 position_3_2 no_limit",
            self._pose("position_3_2"),
            no_limit=True,
            feedback=feedback,
            speeds=speeds_med,
            times=times,
            accs=accs_hi,
        )
        time.sleep(1.5)
        if canceled_fn():
            return
        self._log_motor(
            rid,
            source,
            "step4 position_3_0",
            self._pose("position_3_0"),
            feedback=feedback,
            speeds=speeds_med,
            times=times,
            accs=accs_hi,
        )
        time.sleep(1.0)
        if canceled_fn():
            return
        self._log_motor(
            rid,
            source,
            "step5 position_3_3 no_limit",
            self._pose("position_3_3"),
            no_limit=True,
            feedback=feedback,
            speeds=speeds_med,
            times=times,
            accs=accs_lo,
        )
        time.sleep(1.0)
        if canceled_fn():
            return
        self._log_motor(
            rid,
            source,
            "step6 position_3_4 no_limit",
            self._pose("position_3_4"),
            no_limit=True,
            feedback=feedback,
            speeds=speeds_high,
            times=times,
            accs=accs_hi,
        )
        time.sleep(1.5)
        if canceled_fn():
            return
        self._log_motor(
            rid,
            source,
            "step7 position_3_0",
            self._pose("position_3_0"),
            feedback=feedback,
            speeds=speeds_med,
            times=times,
            accs=accs_hi,
        )
        time.sleep(0.5)
        if canceled_fn():
            return
        self._log_motor(
            rid,
            source,
            "step8 position_3_5 final",
            self._pose("position_3_5"),
            feedback=feedback,
            speeds=[25600] * 12,
            times=times,
            accs=accs_hi,
        )
        time.sleep(1.0)

    def _motor_pray(self, source: str, canceled_fn, feedback) -> None:
        rid = "pray"
        times = [0] * 12
        speeds_zero = [0] * 12
        accs_zero = [0] * 12

        self._log_motor(rid, source, "init position_0", self._pose("position_0"), feedback=feedback)
        time.sleep(1.0)
        if canceled_fn():
            return

        self._log_motor(
            rid,
            source,
            "position_4_0",
            self._pose("position_4_0"),
            feedback=feedback,
            speeds=[12800] * 12,
            times=times,
            accs=[5] * 12,
        )
        time.sleep(0.6)
        if canceled_fn():
            return

        self._log_motor(
            rid,
            source,
            "position_4_1 no_limit",
            self._pose("position_4_1"),
            no_limit=True,
            feedback=feedback,
            speeds=speeds_zero,
            times=times,
            accs=accs_zero,
        )
        time.sleep(1.3)
        if canceled_fn():
            return

        keyframes, position_4_n_tuple, speedup = _try_import_pray_snippet()
        if keyframes is None or position_4_n_tuple is None:
            self.node.get_logger().warn(
                "pray: не удалось импортировать PRAY_SNIPPET_KEYFRAMES из rtulab_feetech — фрагмент пропущен"
            )
        else:
            wall0 = time.time()
            for dt, percents12 in keyframes:
                if canceled_fn():
                    return
                target = wall0 + float(dt) / float(speedup)
                while True:
                    rem = target - time.time()
                    if rem <= 0:
                        break
                    time.sleep(min(0.01, rem))
                self._log_motor(
                    rid,
                    source,
                    f"pray_snippet t={dt:.3f}s",
                    percents12,
                    no_limit=True,
                    feedback=feedback,
                    speeds=speeds_zero,
                    times=times,
                    accs=accs_zero,
                )

        self._log_motor(
            rid,
            source,
            "finish POSITION_4_N no_limit",
            position_4_n_tuple if position_4_n_tuple else self._pose("position_4_n"),
            no_limit=True,
            feedback=feedback,
            speeds=[12800] * 12,
            times=times,
            accs=[5] * 12,
        )
        time.sleep(1.0)

    def _resolve_face_asset_path(self, face: str) -> Optional[Path]:
        """PNG под ``share/.../data/faces/`` или абсолютный путь."""
        return resolve_face_png(self._share, face)

    def _publish_face_if_any(
        self,
        cfg_r: Dict[str, Any],
        canceled_fn,
        feedback,
        source: str,
        rid: str,
    ) -> None:
        face = cfg_r.get("face")
        if face in (None, "", "null"):
            return

        face_s = str(face).strip()
        png_path = self._resolve_face_asset_path(face_s)
        display = face_s.replace("\\", "/")
        feedback(f"face: {display}")
        if png_path is None:
            self.node.get_logger().warn(
                f"Нет файла морды: {face_s} (ожидается в {self._share / 'data' / 'faces'} или абсолютный путь)"
            )
            return

        pil = PILImage.open(str(png_path)).convert("RGB")
        ow = (
            self.node.get_parameter("face_output_width").get_parameter_value().integer_value
        )
        oh = (
            self.node.get_parameter("face_output_height")
            .get_parameter_value()
            .integer_value
        )
        if pil.width != ow or pil.height != oh:
            try:
                from PIL.Image import Resampling as _Resampling

                _filt = _Resampling.LANCZOS
            except ImportError:
                _filt = getattr(PILImage, "LANCZOS", 1)
            pil = pil.resize((ow, oh), _filt)

        stamp = self.node.get_clock().now().to_msg()
        msg = Image()
        msg.header.stamp = stamp
        msg.header.frame_id = "robot_face"
        msg.height = oh
        msg.width = ow
        msg.encoding = "rgb8"
        msg.is_bigendian = False
        msg.step = ow * 3
        rgb = pil.tobytes()
        msg.data = list(rgb)

        fi_init = cfg_r.get("face_init") is True
        if fi_init:
            self.node.get_logger().info(f"face_init флаг только логируется [{rid}]")

        self._face_pub.publish(msg)

    def _play_wav_blocking(self, wav_path: Path, canceled_fn, routine_id: str) -> None:
        topic = (
            self.node.get_parameter("audio_output_topic").get_parameter_value().string_value
        )
        try:
            resolved = wav_path.resolve()
        except OSError:
            resolved = wav_path

        if not wav_path.is_file():
            self.node.get_logger().error(
                f"WAV не найден по пути {wav_path} (resolve: {resolved}) — проигрывание пропущено"
            )
            return

        subs0 = self._audio_pub.get_subscription_count()
        self.node.get_logger().info(
            f"Аудио: старт воспроизведения файл={resolved} топик={topic} подписчиков_сразу={subs0}"
        )

        wait_sub = (
            self.node.get_parameter("audio_wait_for_subscribers_sec")
            .get_parameter_value()
            .double_value
        )
        if wait_sub > 0.0:
            deadline = time.monotonic() + wait_sub
            while time.monotonic() < deadline:
                if self._audio_pub.get_subscription_count() > 0:
                    break
                if canceled_fn():
                    self.node.get_logger().info("Аудио: отмена до появления подписчика")
                    return
                time.sleep(0.05)

        sr_out = (
            self.node.get_parameter("audio_output_rate").get_parameter_value().integer_value
        )
        chunk_sz = (
            self.node.get_parameter("audio_playback_chunk_size")
            .get_parameter_value()
            .integer_value
        )
        vol_pct = (
            self.node.get_parameter("playback_volume_percent")
            .get_parameter_value()
            .double_value
        )
        vol = max(0.0, min(200.0, vol_pct)) / 100.0
        force_stereo = (
            self.node.get_parameter("audio_output_force_stereo")
            .get_parameter_value()
            .bool_value
        )

        try:
            x, sr_in = _mono_float_from_wav(wav_path)
        except Exception as exc:  # noqa: BLE001
            self.node.get_logger().error(f"Не удалось прочитать WAV {resolved}: {exc}")
            return

        subs1 = self._audio_pub.get_subscription_count()
        if subs1 == 0:
            self.node.get_logger().warn(
                f"Подписчиков на {topic}: 0 после ожидания {wait_sub}s — "
                "проверь, что запущен audio_player (сообщения уйдут, звука не будет)."
            )

        x = _resample_mono(x, sr_in, sr_out)
        if (
            self.node.get_parameter("wav_peak_normalize")
            .get_parameter_value()
            .bool_value
        ):
            peak = float(np.max(np.abs(x))) if x.size else 0.0
            if peak > 1e-9:
                x = x / peak
        x = np.clip(x * vol, -1.0, 1.0)
        int16 = (x * 32767.0).astype(np.int16)

        n = len(int16)
        num_chunks = (n + chunk_sz - 1) // chunk_sz if chunk_sz > 0 else 0
        duration_sec = n / float(sr_out) if sr_out > 0 else 0.0
        if duration_sec < 0.3:
            self.node.get_logger().warn(
                f"Аудио: WAV очень короткий ({duration_sec:.3f}s), "
                "его можно почти не услышать"
            )

        self.node.get_logger().info(
            f"Аудио: frames={n} ({duration_sec:.3f}s), ресемпл {sr_in}→{sr_out} Hz, "
            f"чанков≈{num_chunks}, playback_chunk={chunk_sz}, "
            f"stereo_L=R={force_stereo}, подписчиков={subs1}"
        )

        i = 0
        dt = chunk_sz / float(sr_out) if sr_out > 0 else 0.01
        clock = self.node.get_clock()
        published = 0

        while i < n:
            if canceled_fn():
                return
            chunk_m = int16[i : i + chunk_sz]
            if chunk_m.size == 0:
                break

            if force_stereo:
                inter = np.empty(chunk_m.size * 2, dtype=np.int16)
                inter[0::2] = chunk_m
                inter[1::2] = chunk_m
                pcm = inter
                ch = 2
                n_frm = chunk_m.size
            else:
                pcm = chunk_m.flatten()
                ch = 1
                n_frm = pcm.size

            framed = AudioStamped()
            framed.header.stamp = clock.now().to_msg()
            framed.header.frame_id = f"routine.{routine_id}"
            framed.audio.info.format = PA_INT16
            framed.audio.info.channels = ch
            framed.audio.info.rate = sr_out
            framed.audio.info.chunk = int(n_frm)
            flat = np.asarray(pcm, dtype=np.int16).reshape(-1)
            framed.audio.audio_data.int16_data = _np_int16_to_ros_sequence(flat)

            self._audio_pub.publish(framed)
            published += 1
            i += chunk_sz
            if dt > 0:
                end = time.monotonic() + dt
                while time.monotonic() < end:
                    time.sleep(min(0.001, dt * 0.5))
                    if canceled_fn():
                        self.node.get_logger().info(
                            f"Аудио: отменено после {published} AudioStamped"
                        )
                        return

        time.sleep(min(0.15, dt + 0.05))
        self.node.get_logger().info(
            f"Аудио: конец воспроизведения ({published} сообщений AudioStamped → {topic})"
        )

    def _side_effect(
        self,
        rid: str,
        cfg_r: Dict[str, Any],
        canceled_fn,
        feedback,
    ) -> None:
        allow_sys = cfg_r.get("allow_real_systemd")
        if allow_sys is None:
            allow_sys = (
                self.node.get_parameter("allow_real_systemd")
                .get_parameter_value()
                .bool_value
            )
        allow_JOY = cfg_r.get("allow_real_joystick_script")
        if allow_JOY is None:
            allow_JOY = (
                self.node.get_parameter("allow_real_joystick_script")
                .get_parameter_value()
                .bool_value
            )

        if rid == "run" and allow_sys:
            feedback("systemd start inference")
            for svc in ("rds_2p_inference_sim.service", "rds_2p_inference_node.service"):
                subprocess.run(
                    ["sudo", "-n", "systemctl", "start", svc],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                )
        elif rid == "run" and not allow_sys:
            self.node.get_logger().info(
                "[RUN] симуляция: systemctl start rds_2p_inference_sim.node "
                "(allow_real_systemd=false)"
            )

        if rid == "stop_running" and allow_sys:
            feedback("systemd stop inference")
            for svc in ("rds_2p_inference_sim.service", "rds_2p_inference_node.service"):
                subprocess.run(
                    ["sudo", "-n", "systemctl", "stop", svc],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                )
            subprocess.run(
                ["sudo", "-n", "pkill", "-9", "-f", "virtual_twin_sim.launch.py"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        elif rid == "stop_running" and not allow_sys:
            self.node.get_logger().info(
                "[STOP_RUNNING] симуляция systemctl stop + pkill virtual_twin_sim "
                "(allow_real_systemd=false)"
            )

        if rid == "reconnect_joystick" and allow_JOY:
            script = (
                self.node.get_parameter("joystick_script_path")
                .get_parameter_value()
                .string_value
            )
            feedback(f"joystick script {script}")
            subprocess.run(
                ["bash", script],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        elif rid == "reconnect_joystick" and not allow_JOY:
            self.node.get_logger().info(
                "[JOYSTICK] симуляция reconnect_joystick.sh "
                "(allow_real_joystick_script=false)"
            )

        _ = canceled_fn
