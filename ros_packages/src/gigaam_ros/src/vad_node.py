#!/usr/bin/env python3
"""VAD-шлюз (Silero VAD): микрофон → только речь → gigaam.

Подписка: ``audio_topic`` (``audio_common_msgs/AudioStamped``). Публикация:
``output_topic`` — кадры **одной фразы целиком**: копятся от начала речи
(с пред-роллом) до паузы ``min_silence_duration``, затем отдаются склеенным
куском + хвост тишины (``hangover_sec``). Тишина и шум в распознавание не идут.

Бэкенд ``backend``:
  * ``cpu`` (по умолчанию) — Silero VAD v4 через ``sherpa-onnx`` (проверен, out-of-box).
  * ``npu`` — Silero VAD v4, экспортированный в ``.rknn`` (RKNN-Toolkit2 2.3.2),
    гоняется по NPU через общий ``rknn_engine.SileroVadRknn`` (экспериментально:
    требует ваш статичный экспорт silero_vad.onnx → .rknn; при старте логируются
    имена/формы тензоров для подгонки под экспорт).

Модели (по умолчанию в share/gigaam_ros/models):
  * CPU: ``silero_vad.onnx`` (параметр ``vad_model_path``).
  * NPU: ``silero_vad*.rknn`` (параметры ``vad_rknn_path`` / ``rknn_lib``).

  ros2 run gigaam_ros vad_node
  ros2 launch gigaam_ros vad.launch.py backend:=npu vad_rknn_path:=/path/silero_vad.rknn
"""

from __future__ import annotations

import collections
import math
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import numpy as np
import rclpy
from ament_index_python.packages import get_package_share_directory
from audio_common_msgs.msg import AudioStamped
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)

VAD_WINDOW = 512  # silero v4 @16 кГц
VAD_SR = 16000


class VadNode(Node):
    """Пропускает в распознавание только участки с речью (Silero VAD, CPU/NPU)."""

    def __init__(self) -> None:
        super().__init__('vad_node')

        self.declare_parameter('audio_topic', '/audio/input')
        self.declare_parameter('output_topic', '/audio/vad')
        self.declare_parameter('backend', 'cpu')
        self.declare_parameter('vad_model_path', '')       # cpu: silero_vad.onnx
        self.declare_parameter('vad_rknn_path', '')        # npu: silero_vad.rknn
        self.declare_parameter('rknn_lib', '')             # npu: librknnrt.so
        self.declare_parameter('threshold', 0.5)
        self.declare_parameter('min_silence_duration', 0.25)
        self.declare_parameter('min_speech_duration', 0.15)
        self.declare_parameter('max_speech_duration', 20.0)
        self.declare_parameter('preroll_sec', 0.3)
        self.declare_parameter('hangover_sec', 2.0)
        self.declare_parameter('max_segment_sec', 15.0)
        self.declare_parameter('num_threads', 1)
        self.declare_parameter('stats_period_sec', 30.0)
        self.declare_parameter('output_reliable', True)

        self._audio_topic = self._str('audio_topic')
        self._output_topic = self._str('output_topic')
        self._backend = (self._str('backend') or 'cpu').lower()
        self._threshold = self._float('threshold')
        self._min_silence = self._float('min_silence_duration')
        self._min_speech = self._float('min_speech_duration')
        self._max_speech = self._float('max_speech_duration')
        self._preroll_sec = self._float('preroll_sec')
        self._hangover_sec = self._float('hangover_sec')
        self._max_segment_sec = self._float('max_segment_sec')
        self._stats_period = self._float('stats_period_sec')
        self._output_reliable = (
            self.get_parameter('output_reliable').get_parameter_value().bool_value)

        share_models = os.path.join(get_package_share_directory('gigaam_ros'), 'models')

        if self._backend == 'cpu':
            self._init_cpu(share_models)
        elif self._backend == 'npu':
            self._init_npu(share_models)
        else:
            self.get_logger().fatal(f'неизвестный backend VAD: {self._backend} (cpu|npu)')
            raise RuntimeError(f'unknown vad backend: {self._backend}')

        # Вход — микрофонная шина (best_effort, как audio_capturer), иначе QoS несовместимы.
        input_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=50,
        )
        # Выход — приватный топик vad→gigaam. Длинная фраза уходит ОДНИМ склеенным
        # сообщением (сотни КБ → сотни UDP-фрагментов). На best_effort потеря любого
        # фрагмента роняет сообщение целиком → длинные фразы «не определяются».
        # RELIABLE ретранслирует фрагменты и доставляет большие сообщения.
        output_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE if self._output_reliable
            else ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        self._pub = self.create_publisher(AudioStamped, self._output_topic, output_qos)
        self.create_subscription(AudioStamped, self._audio_topic, self._on_audio, input_qos)

        # Ресемплинг источника → 16 кГц (стриминговый).
        self._src_rate = 0
        self._rs_step = 1.0
        self._rs_buf = np.zeros(0, dtype=np.float32)
        self._rs_pos = 0.0
        self._win_buf = np.zeros(0, dtype=np.float32)

        # Сегментный гейтинг (единый для cpu/npu): копим кадры фразы, отдаём по паузе.
        self._preroll: collections.deque = collections.deque()
        self._preroll_frames = 1
        self._frame_sec = 0.0
        self._chunk_seen = -1
        self._last_speech = False
        self._collecting = False
        self._segment_frames: list = []
        self._segment_sec = 0.0
        self._speech_sec = 0.0
        self._silence_sec = 0.0
        self._max_segment_frames = 1
        self._sent_frames = 0
        self._dropped_frames = 0
        self._stats_prev = time.monotonic()

        self.get_logger().info(
            f'vad_node готов: {self._audio_topic} → {self._output_topic}; '
            f'backend={self._backend}; threshold={self._threshold}; '
            f'preroll={self._preroll_sec:.2f} с, хвост={self._hangover_sec:.2f} с'
        )

    # ---- инициализация бэкендов ----------------------------------------------

    def _init_cpu(self, share_models: str) -> None:
        import sherpa_onnx
        model_path = self._str('vad_model_path')
        if not model_path:
            model_path = os.path.join(share_models, 'silero_vad.onnx')
        if not os.path.isfile(model_path):
            self.get_logger().fatal(
                f'VAD-модель не найдена: {model_path} '
                '(положите silero_vad.onnx в models/ пакета или задайте vad_model_path)')
            raise RuntimeError(f'vad model not found: {model_path}')
        config = sherpa_onnx.VadModelConfig()
        config.provider = 'cpu'
        config.num_threads = int(self._int('num_threads'))
        config.sample_rate = VAD_SR
        config.silero_vad.model = model_path
        config.silero_vad.threshold = self._threshold
        # Внутренний сегментатор sherpa не используем (сегментируем сами по
        # is_speech_detected), поэтому границы ставим минимальными.
        config.silero_vad.min_silence_duration = 0.1
        config.silero_vad.min_speech_duration = 0.1
        config.silero_vad.max_speech_duration = max(self._max_speech, self._max_segment_sec)
        config.silero_vad.window_size = VAD_WINDOW
        if not config.validate():
            self.get_logger().fatal('невалидный VadModelConfig (проверьте параметры)')
            raise RuntimeError('invalid vad config')
        self._vad = sherpa_onnx.VoiceActivityDetector(
            config, buffer_size_in_seconds=30.0)
        self.get_logger().info(f'VAD backend=cpu: {model_path}')

    def _init_npu(self, share_models: str) -> None:
        from rknn_engine import Engine, SileroVadRknn
        rknn_path = self._str('vad_rknn_path')
        if not rknn_path:
            cands = sorted(
                os.path.join(share_models, f) for f in os.listdir(share_models)
                if f.endswith('.rknn')) if os.path.isdir(share_models) else []
            if not cands:
                self.get_logger().fatal(
                    'backend=npu: не задан vad_rknn_path и в models/ нет .rknn')
                raise RuntimeError('vad_rknn_path not set and no .rknn in models/')
            rknn_path = cands[0]
        lib = self._str('rknn_lib') or os.environ.get('RKNN_LIB', 'librknnrt.so')
        engine = Engine(rknn_path, lib)
        self._vad = SileroVadRknn(engine)
        desc = self._vad.describe()
        self.get_logger().info(f'VAD backend=npu: {rknn_path} (lib {lib})')
        self.get_logger().info(f'VAD NPU тензоры: {desc}')

    # ---- параметры -----------------------------------------------------------

    def _str(self, name: str) -> str:
        return self.get_parameter(name).get_parameter_value().string_value.strip()

    def _int(self, name: str) -> int:
        return self.get_parameter(name).get_parameter_value().integer_value

    def _float(self, name: str) -> float:
        return self.get_parameter(name).get_parameter_value().double_value

    # ---- сигнал речи ---------------------------------------------------------

    def _speech_flag(self, window_16k: np.ndarray) -> bool:
        if self._backend == 'cpu':
            self._vad.accept_waveform(window_16k)
            while not self._vad.empty():
                self._vad.pop()
            return bool(self._vad.is_speech_detected())
        prob = self._vad.process_window(window_16k)
        return prob >= self._threshold

    # ---- аудио ---------------------------------------------------------------

    def _on_audio(self, msg: AudioStamped) -> None:
        info = msg.audio.info
        samples = np.asarray(msg.audio.audio_data.int16_data, dtype=np.int16)
        if samples.size == 0 or info.rate <= 0:
            return
        rate = int(info.rate)
        if info.channels > 1:
            samples = samples[: (samples.size // info.channels) * info.channels]
            samples = samples.reshape(-1, info.channels)[:, 0]

        chunk = int(info.chunk) if info.chunk > 0 else samples.size
        if chunk != self._chunk_seen:
            self._chunk_seen = chunk
            self._frame_sec = chunk / float(rate)
            self._preroll_frames = max(1, int(math.ceil(self._preroll_sec / self._frame_sec)))
            self._max_segment_frames = max(
                1, int(math.ceil(self._max_segment_sec / self._frame_sec)))

        self._ensure_resampler(rate)
        x16 = self._resample(samples.astype(np.float32) / 32768.0)

        # Кормим детектор речи окнами 16k. Речь кадра = любое речевое окно в кадре;
        # если окно ещё не накоплено (короткий кадр) — держим прошлое состояние.
        if x16.size:
            self._win_buf = (np.concatenate([self._win_buf, x16])
                             if self._win_buf.size else x16)
        speech_any = False
        fed = False
        while self._win_buf.size >= VAD_WINDOW:
            window = self._win_buf[:VAD_WINDOW]
            self._win_buf = self._win_buf[VAD_WINDOW:]
            fed = True
            if self._speech_flag(window):
                speech_any = True
        speech_now = speech_any if fed else self._last_speech
        self._last_speech = speech_now

        msg_dur = samples.size / float(rate)
        self._advance_gate(msg, speech_now, msg_dur)

        if self._collecting and len(self._segment_frames) > self._max_segment_frames:
            self.get_logger().warn(
                f'VAD: сегмент длиннее {self._max_segment_sec:.0f} с — отдаю принудительно')
            self._flush_segment()

        self._log_stats()

    def _advance_gate(self, msg: AudioStamped, speech_now: bool, dur: float) -> None:
        """Машина состояний сегментации (один вызов на кадр аудио, cpu/npu)."""
        if speech_now:
            self._silence_sec = 0.0
            if not self._collecting:
                self._collecting = True
                self._segment_frames = list(self._preroll)
                self._segment_sec = 0.0
                self._speech_sec = 0.0
                self._preroll.clear()
                self.get_logger().info('VAD: начало речи')
        else:
            self._silence_sec += dur

        if self._collecting:
            self._segment_frames.append(msg)
            self._segment_sec += dur
            if speech_now:
                self._speech_sec += dur
            if not speech_now and self._silence_sec >= self._min_silence:
                self._flush_segment()
        else:
            self._preroll.append(msg)
            while len(self._preroll) > self._preroll_frames:
                self._preroll.popleft()
            self._dropped_frames += 1

    def _flush_segment(self) -> None:
        """Отдать фразу одним склеенным сообщением + синтетический хвост тишины."""
        frames = self._segment_frames
        self._segment_frames = []
        self._collecting = False
        self._silence_sec = 0.0
        self._segment_sec = 0.0
        if not frames:
            return
        if self._speech_sec < self._min_speech:
            self.get_logger().debug(
                f'VAD: короткая вспышка речи ({self._speech_sec:.2f} с) — отброшена')
            self._speech_sec = 0.0
            return
        self._speech_sec = 0.0

        sample_arrays = [np.asarray(m.audio.audio_data.int16_data, dtype=np.int16)
                         for m in frames]
        rate = int(frames[-1].audio.info.rate) or self._src_rate or VAD_SR
        tail_samples = max(0, int(self._hangover_sec * rate))
        if tail_samples:
            sample_arrays.append(np.zeros(tail_samples, dtype=np.int16))
        merged = np.concatenate(sample_arrays)

        out = AudioStamped()
        out.header = frames[0].header
        out.audio.info.format = frames[0].audio.info.format
        out.audio.info.channels = 1
        out.audio.info.rate = rate
        out.audio.info.chunk = int(merged.size)
        out.audio.audio_data.int16_data = merged.tolist()
        self._pub.publish(out)
        self._sent_frames += len(frames)
        self.get_logger().info(
            f'VAD: фраза ({len(frames)} кадров, ~{len(frames) * self._frame_sec:.1f} с '
            f'+ хвост {self._hangover_sec:.1f} с) → распознавание одним сообщением')

    # ---- ресемплинг ----------------------------------------------------------

    def _ensure_resampler(self, rate: int) -> None:
        if rate == self._src_rate:
            return
        self._src_rate = rate
        self._rs_step = rate / float(VAD_SR)
        self._rs_buf = np.zeros(0, dtype=np.float32)
        self._rs_pos = 0.0
        if rate != VAD_SR:
            self.get_logger().info(f'ресемплинг {rate} → {VAD_SR} Гц')

    def _resample(self, x: np.ndarray) -> np.ndarray:
        if self._src_rate == VAD_SR:
            return x
        self._rs_buf = np.concatenate([self._rs_buf, x]) if self._rs_buf.size else x
        n = self._rs_buf.size
        if self._rs_pos >= n - 1:
            return np.zeros(0, dtype=np.float32)
        count = int(np.floor((n - 1 - self._rs_pos) / self._rs_step)) + 1
        idx = self._rs_pos + self._rs_step * np.arange(count, dtype=np.float64)
        i0 = idx.astype(np.int32)
        frac = (idx - i0).astype(np.float32)
        out = self._rs_buf[i0] * (1.0 - frac) + self._rs_buf[i0 + 1] * frac
        self._rs_pos = idx[-1] + self._rs_step
        drop = int(np.floor(self._rs_pos)) - 1
        if drop > 0:
            self._rs_buf = self._rs_buf[drop:]
            self._rs_pos -= drop
        return out.astype(np.float32)

    def _log_stats(self) -> None:
        now = time.monotonic()
        if self._stats_period <= 0 or now - self._stats_prev < self._stats_period:
            return
        total = self._sent_frames + self._dropped_frames
        if total:
            self.get_logger().info(
                f'VAD статистика: пропущено {self._sent_frames}/{total} кадров '
                f'({100.0 * self._sent_frames / total:.1f}% речи)')
        self._sent_frames = 0
        self._dropped_frames = 0
        self._stats_prev = now

    def destroy_node(self) -> None:
        if self._backend == 'npu' and hasattr(self, '_vad'):
            try:
                self._vad.engine.close()
            except Exception:  # noqa: BLE001
                pass
        super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = VadNode()
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
