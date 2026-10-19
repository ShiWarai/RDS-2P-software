#!/usr/bin/env python3
"""TTS через paroli-cli (WAV stdout) → AudioStamped для audio_player.

Чанки идут потоком: дедлайн-пейсинг после publish, чтобы не опережать «часы» микшера.
"""

from __future__ import annotations

import array
import io
import json
import os
import re
import select
import shutil
import struct
import subprocess
import threading
import time
import wave
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import rclpy
from ament_index_python.packages import get_package_prefix, get_package_share_directory
from audio_common_msgs.msg import AudioStamped
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from paroli_ros2.srv import Speak
from scipy import signal
from std_msgs.msg import String
from std_srvs.srv import Trigger

PA_INT16 = 8

_DEFAULT_VOICE_DIR = "ruslan"
_DEFAULT_CONFIG_FILE = "ru_RU-ruslan-medium.onnx.json"


def _np_int16_to_ros_sequence(samples: np.ndarray) -> array.array:
    """Быстрее .tolist(): без списка Python на каждый сэмпл (меньше джиттера для audio_player)."""
    flat = np.asarray(samples, dtype=np.int16).reshape(-1)
    out = array.array("h")
    out.frombytes(flat.tobytes())
    return out


@dataclass(frozen=True)
class ModelPaths:
    encoder: str
    decoder: str
    config: str
    espeak_data: str


def default_model_paths(pkg_share: str, voice_dir: str = _DEFAULT_VOICE_DIR) -> ModelPaths:
    """Пути по умолчанию: models/<voice_dir>/… и общий espeak-ng-data."""
    models = os.path.join(pkg_share, "models")
    voice = os.path.join(models, voice_dir)
    return ModelPaths(
        encoder=os.path.join(voice, "encoder.onnx"),
        decoder=os.path.join(voice, "decoder.rknn"),
        config=os.path.join(voice, _DEFAULT_CONFIG_FILE),
        espeak_data=os.path.join(models, "espeak-ng-data"),
    )


def _read_exact(stream, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            raise RuntimeError(f"неожиданный EOF при чтении WAV (нужно ещё {n - len(buf)} байт)")
        buf += chunk
    return buf


def _read_all_wav_segments_from_stream(stdout, extra_wait_after_wav_sec: float) -> List[bytes]:
    """Один или несколько RIFF/WAV подряд (paroli может выдавать отдельный WAV на каждое предложение).

    Сначала сливаем всё уже лежащее в буфере (select(..., 0)); при необходимости один раз подождать
    extra_wait_after_wav_sec — если второй WAV приходит чуть позже вторым write().
    """
    segments: List[bytes] = []
    while True:
        hdr8 = _read_exact(stdout, 8)
        if hdr8[:4] != b"RIFF":
            raise RuntimeError(f"ожидался RIFF, получено: {hdr8[:16]!r}")
        rest_size = struct.unpack("<I", hdr8[4:8])[0]
        tail = _read_exact(stdout, rest_size)
        segments.append(hdr8 + tail)

        r0, _, _ = select.select([stdout], [], [], 0)
        if not r0 and extra_wait_after_wav_sec > 0:
            r0, _, _ = select.select([stdout], [], [], float(extra_wait_after_wav_sec))
        if not r0:
            return segments


def _merge_wav_segments_to_mono(wavs: List[bytes]) -> Tuple[np.ndarray, int]:
    """Склеить несколько WAV (PCM16) в один моно int16 массив; разные Fs → ресемплим к первому."""
    if not wavs:
        raise ValueError("пустой список WAV")
    pcm0, sr0 = _wav_bytes_to_mono_int16(wavs[0])
    if len(wavs) == 1:
        return pcm0, sr0
    parts: List[np.ndarray] = [pcm0]
    for blob in wavs[1:]:
        pcm, sr = _wav_bytes_to_mono_int16(blob)
        if sr != sr0:
            pcm = _resample_mono_int16(pcm, sr, sr0)
        parts.append(pcm)
    merged = np.concatenate(parts)
    return merged, sr0


def _split_for_sentence_synthesis(text: str) -> List[str]:
    """Грубое разбиение по концу предложения (. ! ? … + пробел). Обход бага paroli/piper с перезаписью буфера."""
    t = text.strip()
    if not t:
        return []
    parts = re.split(r"(?<=[.!?…])\s+", t)
    return [p.strip() for p in parts if p.strip()]


def _wav_bytes_to_mono_int16(data: bytes) -> Tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data), "rb") as w:
        ch = w.getnchannels()
        sw = w.getsampwidth()
        sr = w.getframerate()
        nframes = w.getnframes()
        raw = w.readframes(nframes)
    if sw != 2:
        raise ValueError(f"ожидается PCM16 WAV, samplewidth={sw}")
    pcm = np.frombuffer(raw, dtype=np.int16)
    if ch > 1:
        pcm = pcm.reshape(-1, ch)[:, 0].copy()
    return pcm, int(sr)


def _resample_mono_int16(pcm: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return pcm
    g = np.gcd(sr_in, sr_out)
    up = sr_out // g
    down = sr_in // g
    xf = pcm.astype(np.float64) / 32768.0
    y = signal.resample_poly(xf, up, down)
    return (np.clip(y, -1.0, 1.0) * 32767.0).astype(np.int16)


def _apply_tts_volume_gain(mono_i16: np.ndarray, gain: float) -> np.ndarray:
    """Умножение амплитуды PCM16; gain 0…1 — тише, >1 — громче (с клипом)."""
    g = float(gain)
    if g == 1.0:
        return mono_i16
    if g <= 0.0:
        return np.zeros_like(mono_i16)
    y = mono_i16.astype(np.float64) * g
    return np.clip(y, -32768.0, 32767.0).astype(np.int16)


class TtsNode(Node):
    def __init__(self) -> None:
        super().__init__("paroli_ros2")

        pkg = "paroli_ros2"
        prefix = get_package_prefix(pkg)
        share = get_package_share_directory(pkg)
        paths = default_model_paths(share)
        default_cli = os.path.join(prefix, "lib", pkg, "paroli-cli")
        default_vendor_lib = os.path.join(prefix, "lib", pkg, "vendor", "lib")

        self.declare_parameter("paroli_cli_path", default_cli)
        self.declare_parameter("paroli_ld_library_path", default_vendor_lib)
        self.declare_parameter("use_stdbuf", True)
        self.declare_parameter("encoder_path", paths.encoder)
        self.declare_parameter("decoder_path", paths.decoder)
        self.declare_parameter("model_config_path", paths.config)
        self.declare_parameter("espeak_data_path", paths.espeak_data)
        self.declare_parameter("accelerator", "")
        # Скорость/тембр Piper как у paroli-cli (<0 = не передавать флаг, взять из модели):
        # length_scale: <1 быстрее, >1 медленнее (умолч. в Piper обычно 1).
        self.declare_parameter("length_scale", -1.0)
        self.declare_parameter("noise_scale", -1.0)
        self.declare_parameter("noise_w", -1.0)
        self.declare_parameter("output_topic", "/audio/output")
        self.declare_parameter("frame_id", "tts.paroli")
        self.declare_parameter("output_sample_rate", 44100)
        self.declare_parameter("chunk_frames", 4096)
        self.declare_parameter("force_stereo", False)
        self.declare_parameter("qos_depth", 50)
        self.declare_parameter("speaker_id", -1)
        # Если second (и следующие) WAV от paroli-cli приходят вторым syscall чуть позже — подождать до N с.
        # 0: только уже буферизованные байты (select 0).
        self.declare_parameter("wav_extra_wait_after_segment_sec", 0.0)
        # Обход бага piper (присваивание audioBuffer вместо insert): несколько JSON-строк по предложениям.
        # Собранный paroli-cli с патчем в piper.cpp — оставь false (одна строка на весь текст).
        self.declare_parameter("split_sentences_for_synthesis", False)
        self.declare_parameter("between_sentence_silence_sec", 0.12)
        # 1.0 = без изменений; 0…1 — ослабление; >1 — усиление (например 1.5), с клипом int16.
        self.declare_parameter("tts_volume", 1.0)

        qos_depth = max(10, int(self.get_parameter("qos_depth").value))
        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=qos_depth,
        )
        self._pub = self.create_publisher(AudioStamped, self.get_parameter("output_topic").value, qos)

        self._srv = self.create_service(Speak, "~/speak", self._on_speak)
        self._srv_stop = self.create_service(Trigger, "~/stop_speech", self._on_stop_speech)
        self._sub = self.create_subscription(String, "speak_text", self._on_speak_text, 10)

        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._paroli_key: Optional[tuple] = None

        self.get_logger().info(
            f"paroli_ros2: paroli-cli; конфиг: {self.get_parameter('model_config_path').value}"
        )

    def destroy_node(self) -> bool:
        self._stop_paroli()
        return super().destroy_node()

    def _env(self) -> dict:
        env = os.environ.copy()
        extra = (
            self.get_parameter("paroli_ld_library_path").get_parameter_value().string_value or ""
        ).strip()
        if extra:
            old = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = f"{extra}:{old}" if old else extra
        return env

    def _paroli_restart_key(self) -> tuple:
        """Смена ключа → перезапуск paroli-cli (argv фиксируются при старте процесса)."""
        return (
            str(self.get_parameter("paroli_cli_path").value),
            str(self.get_parameter("encoder_path").value),
            str(self.get_parameter("decoder_path").value),
            str(self.get_parameter("model_config_path").value),
            str(self.get_parameter("espeak_data_path").value),
            (self.get_parameter("accelerator").get_parameter_value().string_value or "").strip(),
            float(self.get_parameter("length_scale").get_parameter_value().double_value),
            float(self.get_parameter("noise_scale").get_parameter_value().double_value),
            float(self.get_parameter("noise_w").get_parameter_value().double_value),
            bool(self.get_parameter("use_stdbuf").value),
        )

    def _paroli_argv(self) -> List[str]:
        cli = self.get_parameter("paroli_cli_path").value
        if not cli or not os.path.isfile(cli):
            raise FileNotFoundError(f"paroli-cli не найден: {cli!r}")
        enc = self.get_parameter("encoder_path").value
        dec = self.get_parameter("decoder_path").value
        cfg = self.get_parameter("model_config_path").value
        espeak = self.get_parameter("espeak_data_path").value
        if not enc or not dec or not cfg or not espeak:
            raise ValueError("encoder_path, decoder_path, model_config_path, espeak_data_path обязательны")
        argv = [
            cli,
            "--encoder",
            enc,
            "--decoder",
            dec,
            "-c",
            cfg,
            "--espeak-data",
            espeak,
            "--json-input",
            "-f",
            "-",
            "-q",
        ]
        acc = (self.get_parameter("accelerator").get_parameter_value().string_value or "").strip()
        if acc:
            argv.extend(["--accelerator", acc])

        ls = float(self.get_parameter("length_scale").get_parameter_value().double_value)
        if ls >= 0.0:
            argv.extend(["--length-scale", f"{ls:.6g}"])
        ns = float(self.get_parameter("noise_scale").get_parameter_value().double_value)
        if ns >= 0.0:
            argv.extend(["--noise-scale", f"{ns:.6g}"])
        nw = float(self.get_parameter("noise_w").get_parameter_value().double_value)
        if nw >= 0.0:
            argv.extend(["--noise-w", f"{nw:.6g}"])

        use_stdbuf = self.get_parameter("use_stdbuf").value
        if use_stdbuf and shutil.which("stdbuf"):
            argv = ["stdbuf", "-o0", "-i0"] + argv
        elif use_stdbuf:
            self.get_logger().warn("stdbuf не найден — возможны зависания буфера stdout paroli-cli")
        return argv

    def _ensure_paroli(self) -> None:
        key = self._paroli_restart_key()
        proc_ok = self._proc is not None and self._proc.poll() is None
        if proc_ok and self._paroli_key == key:
            return
        if proc_ok and self._paroli_key != key:
            self.get_logger().info(
                "paroli-cli: перезапуск (length_scale / noise_* / модель / accelerator / stdbuf)"
            )
        self._stop_paroli()
        self._paroli_key = key
        argv = self._paroli_argv()
        self._proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env(),
            bufsize=0,
        )
        self.get_logger().info(f"paroli-cli запущен: {' '.join(argv[:5])} …")

    def _stop_paroli(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
        except Exception:  # noqa: BLE001
            pass
        self._proc = None

    def _synth_pcm_mono_one_line(self, text: str) -> Tuple[np.ndarray, int]:
        """Одна строка JSON в stdin paroli → WAV(ы) в stdout → моно PCM."""
        if not (text and text.strip()):
            raise ValueError("пустой text")
        self._ensure_paroli()
        assert self._proc and self._proc.stdin and self._proc.stdout

        sid = int(self.get_parameter("speaker_id").value)
        payload: dict = {"text": text.strip()}
        if sid >= 0:
            payload["speaker_id"] = sid
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        extra_wait = float(
            self.get_parameter("wav_extra_wait_after_segment_sec")
            .get_parameter_value()
            .double_value
        )
        try:
            self._proc.stdin.write(line.encode("utf-8"))
            self._proc.stdin.flush()
            wavs = _read_all_wav_segments_from_stream(
                self._proc.stdout, extra_wait_after_wav_sec=extra_wait
            )
            if len(wavs) > 1:
                self.get_logger().info(
                    f"paroli: ответ из {len(wavs)} WAV сегментов (склеиваем в один поток)"
                )
            return _merge_wav_segments_to_mono(wavs)
        except Exception as exc:  # noqa: BLE001
            err = b""
            if self._proc.stderr:
                try:
                    err = self._proc.stderr.read(4096)
                except Exception:  # noqa: BLE001
                    pass
            self._stop_paroli()
            raise RuntimeError(f"paroli-cli: {exc}; stderr: {err[:500]!r}") from exc

    def _synth_pcm_mono(self, text: str) -> Tuple[np.ndarray, int]:
        """Синтез: при split — отдельная JSON-строка на предложение (тот же paroli-процесс)."""
        if not (text and text.strip()):
            raise ValueError("пустой text")
        split = bool(
            self.get_parameter("split_sentences_for_synthesis")
            .get_parameter_value()
            .bool_value
        )
        chunks = _split_for_sentence_synthesis(text) if split else [text.strip()]
        if not chunks:
            raise ValueError("пустой text")
        if len(chunks) == 1:
            return self._synth_pcm_mono_one_line(chunks[0])

        silence_sec = float(
            self.get_parameter("between_sentence_silence_sec")
            .get_parameter_value()
            .double_value
        )
        parts: List[np.ndarray] = []
        sr0: Optional[int] = None
        for i, ch in enumerate(chunks):
            pcm, sr = self._synth_pcm_mono_one_line(ch)
            if sr0 is None:
                sr0 = sr
            elif sr != sr0:
                pcm = _resample_mono_int16(pcm, sr, sr0)
            parts.append(pcm)
            if i + 1 < len(chunks) and silence_sec > 0.0 and sr0 is not None:
                n_pad = int(round(silence_sec * sr0))
                if n_pad > 0:
                    parts.append(np.zeros(n_pad, dtype=np.int16))

        if sr0 is None:
            raise RuntimeError("синтез не дал сигнал")
        merged = np.concatenate(parts)
        self.get_logger().info(
            f"paroli: split_sentences — {len(chunks)} предложений → один поток"
        )
        return merged, sr0

    def _publish_segments(self, mono_i16: np.ndarray, sr_out: int) -> None:
        chunk = max(64, int(self.get_parameter("chunk_frames").value))
        force_stereo = bool(self.get_parameter("force_stereo").value)
        frame_id = (self.get_parameter("frame_id").value or "tts.paroli").strip()
        ch_out = 2 if force_stereo else 1

        n = mono_i16.size
        i = 0
        t_next = time.monotonic()
        while i < n:
            piece = mono_i16[i : i + chunk]
            if piece.size == 0:
                break
            n_frm = int(piece.size)
            if force_stereo:
                inter = np.empty(piece.size * 2, dtype=np.int16)
                inter[0::2] = piece
                inter[1::2] = piece
                payload = inter
            else:
                payload = piece
            msg = AudioStamped()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = frame_id
            msg.audio.info.format = PA_INT16
            msg.audio.info.channels = ch_out
            msg.audio.info.rate = sr_out
            msg.audio.info.chunk = n_frm
            msg.audio.audio_data.int16_data = _np_int16_to_ros_sequence(payload)
            self._pub.publish(msg)
            i += chunk
            t_next += n_frm / float(sr_out)
            delay = t_next - time.monotonic()
            if delay > 0:
                time.sleep(delay)

    def _effective_tts_gain(self, service_volume: Optional[float]) -> float:
        """Топик speak_text (None) — параметр ноды tts_volume; сервис /speak — поле volume запроса."""
        if service_volume is None:
            return float(self.get_parameter("tts_volume").get_parameter_value().double_value)
        return max(0.0, float(service_volume))

    def _speak(self, text: str, service_volume: Optional[float] = None) -> Tuple[bool, str]:
        sr_target = int(self.get_parameter("output_sample_rate").value)
        try:
            pcm, sr_nat = self._synth_pcm_mono(text)
            pcm_out = _resample_mono_int16(pcm, sr_nat, sr_target)
            vol = self._effective_tts_gain(service_volume)
            pcm_out = _apply_tts_volume_gain(pcm_out, vol)
            self._publish_segments(pcm_out, sr_target)
            return True, "ok"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    def _on_stop_speech(self, _request: Trigger.Request, response: Trigger.Response) -> Trigger.Response:
        """Прервать paroli-cli (и тем самым оборвать текущий синтез/выдачу в audio_player)."""
        self.get_logger().info("stop_speech: прерывание")
        acquired = self._lock.acquire(blocking=False)
        try:
            self._stop_paroli()
        finally:
            if acquired:
                self._lock.release()
        response.success = True
        response.message = "stopped"
        return response

    def _on_speak(self, request: Speak.Request, response: Speak.Response) -> Speak.Response:
        with self._lock:
            ok, msg = self._speak(request.text, request.volume)
        response.success = ok
        response.message = msg
        return response

    def _on_speak_text(self, msg: String) -> None:
        if not self._lock.acquire(blocking=False):
            self.get_logger().warn("speak_text: synth занят, сообщение отброшено")
            return
        try:
            ok, err = self._speak(msg.data, None)
            if not ok:
                self.get_logger().error(f"speak_text: {err}")
        finally:
            self._lock.release()


def main(args: Optional[list[str]] = None) -> None:
    rclpy.init(args=args)
    node: Optional[TtsNode] = None
    try:
        node = TtsNode()
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
