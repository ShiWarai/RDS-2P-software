#!/usr/bin/env python3
"""
ROS2 узел распознавания речи на GigaAM CTC (RKNN, RK3588 NPU).

Зеркаляет интерфейс ``vosk_ros/vosk_node``: подписывается на аудио-топик
(``audio_common_msgs/AudioStamped``), публикует ``rds_2p_audio/msg/Transcription``
и держит action ``STT`` (имя ``listen``). Загрузка модели — по аналогии с Vosk:
параметр ``model_path`` указывает на каталог модели (или напрямую на ``.rknn``),
контекст ``librknnrt`` инициализируется один раз в ``__init__``.

Отличие от Vosk: GigaAM CTC НЕ потоковый — модель имеет статичное окно 500
log-mel фреймов (≈5.02 с @16 кГц). Поэтому фраза (выход VAD, одно сообщение на
фразу) режется на окна ≤500 фреймов, каждое прогоняется по NPU, схлопнутые CTC-id
склеиваются и декодируются по ``multilingual_vocab.txt``. Рекомендуемый источник —
``vad_node`` этого пакета (``audio_topic:=/audio/vad``).

Модель берётся с https://huggingface.co/ShiWarai/gigaam-ctc-rknn.
"""

import os
import sys

# rknn_engine.py ставится рядом с этой нодой в lib/gigaam_ros.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import queue
import threading
import time

import numpy as np
import rclpy
from ament_index_python.packages import get_package_share_directory
from audio_common_msgs.msg import AudioStamped
from rclpy.action import ActionServer
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)

# Общие интерфейсы распознавания (используют и vosk_ros, и потребители
# llm_layer / command_parser / telegram_bot) живут в rds_2p_audio.
from rds_2p_audio.action import STT
from rds_2p_audio.msg import Transcription as TranscriptionMsg

from rknn_engine import (
    SR,
    Engine,
    GigaamFrontend,
    allowed_ids_for_lang,
    decode_ids,
    load_vocab,
    resolve_model_rknn,
)


class GigaamNode(Node):
    """ROS2 узел распознавания речи на основе GigaAM CTC (RKNN NPU)."""

    def __init__(self):
        super().__init__('gigaam_node')

        self.declare_parameter('model_path', "")
        self.declare_parameter('model_file', "")
        self.declare_parameter('vocab_path', "")
        self.declare_parameter('rknn_lib', "")
        self.declare_parameter('audio_topic', '/audio/input')
        self.declare_parameter('transcription_topic', '/audio/transcription')
        self.declare_parameter('max_audio_time', 30.0)
        self.declare_parameter('torch_threads', 4)
        self.declare_parameter('speech_pause_enabled', False)
        self.declare_parameter('speech_bus_topic', '/audio/output')
        self.declare_parameter('speech_bus_frame_ids', [])
        self.declare_parameter('speech_pause_tail_sec', 0.8)
        self.declare_parameter('reliable_audio', True)
        self.declare_parameter('decode_lang', 'ru+en')

        model_path = self._param('model_path').string_value.strip()
        model_file = self._param('model_file').string_value.strip()
        vocab_path = self._param('vocab_path').string_value.strip()
        rknn_lib = self._param('rknn_lib').string_value.strip() or os.environ.get(
            'RKNN_LIB', 'librknnrt.so')
        audio_topic = self._param('audio_topic').string_value.strip()
        transcription_topic = self._param('transcription_topic').string_value.strip()
        self.        max_audio_time = self._param('max_audio_time').double_value
        self._reliable_audio = self._param('reliable_audio').bool_value
        torch_threads = int(self._param('torch_threads').integer_value)
        self._speech_pause_enabled = self._param('speech_pause_enabled').bool_value
        self._speech_bus_topic = self._param('speech_bus_topic').string_value.strip()
        self._speech_frame_ids = {
            str(x).strip()
            for x in self._param('speech_bus_frame_ids').string_array_value
            if str(x).strip()
        }
        self._speech_pause_tail = self._param('speech_pause_tail_sec').double_value
        if self._speech_pause_tail <= 0.0:
            self._speech_pause_tail = 0.8
        self._speech_until = 0.0
        self._speech_pause_active = False
        self._paused_dropped = 0

        # Путь к модели: параметр → по умолчанию share/gigaam_ros/models
        # (как у vosk: директория модели внутри пакета).
        if not model_path:
            model_path = os.path.join(
                get_package_share_directory('gigaam_ros'), 'models')

        # Загружаем модель (NPU-контекст) один раз — аналог vosk.Model(model_path).
        try:
            rknn_path, model_dir = resolve_model_rknn(model_path, model_file)
            if not vocab_path:
                vocab_path = os.path.join(model_dir, 'multilingual_vocab.txt')
            if not os.path.isfile(vocab_path):
                raise FileNotFoundError(
                    f'не найден vocab: {vocab_path} '
                    '(положите multilingual_vocab.txt рядом с .rknn или задайте vocab_path)')
            self.vocab = load_vocab(vocab_path)
            self.engine = Engine(rknn_path, rknn_lib)
            decode_lang = self._param('decode_lang').string_value.strip()
            allowed_ids = allowed_ids_for_lang(self.vocab, decode_lang)
            self.frontend = GigaamFrontend(
                num_threads=torch_threads, allowed_ids=allowed_ids)
            self.get_logger().info(
                f'Модель GigaAM загружена: {rknn_path} (vocab {vocab_path}, '
                f'lib {rknn_lib}); входы NPU: {self.engine.input_names()}')
            self.get_logger().info(
                f'Язык декодера: {decode_lang or "all"} '
                f'({"ограничение " + str(len(allowed_ids)) + " токенов" if allowed_ids is not None else "без ограничения"})')
        except Exception as e:  # noqa: BLE001
            self.get_logger().fatal(f'Ошибка загрузки модели GigaAM: {e}')
            raise

        # Параметры аудио придут из первого сообщения.
        self.sample_rate = None
        self.channels = None

        self.audio_queue = queue.Queue()

        self.transcription_pub = self.create_publisher(
            TranscriptionMsg, transcription_topic, 10)

        self._action_server = ActionServer(
            self, STT, 'listen', self.execute_callback)

        # Входной аудио-QoS: приватный топик vad→gigaam несёт длинные фразы одним
        # большим сообщением — нужен RELIABLE (ретрансляция UDP-фрагментов), иначе
        # длинные фразы теряются. Шина речи (/audio/output) остаётся BEST_EFFORT.
        audio_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE if self._reliable_audio
            else ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        self.audio_subscription = self.create_subscription(
            AudioStamped, audio_topic, self.audio_callback, audio_qos)

        sensor_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        if self._speech_pause_enabled and self._speech_bus_topic:
            self.create_subscription(
                AudioStamped, self._speech_bus_topic,
                self._speech_bus_callback, sensor_qos)

        self.running = True
        self.recognition_thread = threading.Thread(
            target=self._recognition_thread, daemon=True)
        self.recognition_thread.start()

        self.get_logger().info(
            f'Узел GigaAM запущен (топик аудио: {audio_topic}, '
            f'топик транскрипции: {transcription_topic}, '
            f'msg: {TranscriptionMsg.__module__})')
        if self._speech_pause_enabled and self._speech_bus_topic:
            src = ', '.join(sorted(self._speech_frame_ids)) or 'любой источник'
            self.get_logger().info(
                f'Пауза распознавания на речь робота: {self._speech_bus_topic} ({src}), '
                f'хвост {self._speech_pause_tail:.1f} с')

    def _param(self, name):
        return self.get_parameter(name).get_parameter_value()

    def _speech_bus_callback(self, msg):
        """Кадр воспроизведения (робот говорит) — продлевает паузу распознавания."""
        fid = getattr(msg.header, 'frame_id', '') or ''
        if self._speech_frame_ids and fid not in self._speech_frame_ids:
            return
        self._speech_until = time.monotonic() + self._speech_pause_tail

    def _extract_audio_float(self, audio_data_msg):
        """Извлечь аудио из сообщения как float32 [-1, 1] (моно-каналы ещё слиты)."""
        data = None
        if len(getattr(audio_data_msg, 'float32_data', [])) > 0:
            data = np.array(audio_data_msg.float32_data, dtype=np.float32)
        elif len(getattr(audio_data_msg, 'int16_data', [])) > 0:
            data = np.array(audio_data_msg.int16_data, dtype=np.int16).astype(
                np.float32) / 32768.0
        elif len(getattr(audio_data_msg, 'int32_data', [])) > 0:
            data = np.array(audio_data_msg.int32_data, dtype=np.int32).astype(
                np.float32) / 2147483648.0
        elif len(getattr(audio_data_msg, 'int8_data', [])) > 0:
            data = np.array(audio_data_msg.int8_data, dtype=np.int8).astype(
                np.float32) / 128.0
        elif len(getattr(audio_data_msg, 'uint8_data', [])) > 0:
            data = (np.array(audio_data_msg.uint8_data, dtype=np.uint8).astype(
                np.float32) - 128) / 128.0
        return data

    def audio_callback(self, msg):
        """Приём аудио: один вход = одна фраза (выход VAD) → в очередь распознавания."""
        try:
            if self._speech_pause_enabled:
                now = time.monotonic()
                if now < self._speech_until:
                    if not self._speech_pause_active:
                        self._speech_pause_active = True
                        self.get_logger().info(
                            'Распознавание приостановлено: говорит робот (фразы в GigaAM не идут)')
                    self._paused_dropped += 1
                    return
                if self._speech_pause_active:
                    self._speech_pause_active = False
                    self.get_logger().info(
                        f'Распознавание возобновлено (пропущено {self._paused_dropped} кадров речи робота)')
                    self._paused_dropped = 0

            audio_info = msg.audio.info
            if audio_info.rate <= 0:
                return

            if self.sample_rate is None:
                self.sample_rate = audio_info.rate
                self.channels = audio_info.channels
                self.get_logger().info(
                    f'Аудиопараметры: частота {self.sample_rate} Hz, каналы {self.channels}')

            if audio_info.rate != self.sample_rate:
                self.get_logger().warn(
                    f'Несовпадение частоты: ожидается {self.sample_rate} Hz, '
                    f'получено {audio_info.rate} Hz')
                return

            data = self._extract_audio_float(msg.audio.audio_data)
            if data is None or data.size == 0:
                return

            channels = audio_info.channels or 1
            if channels > 1:
                data = data[:(data.size // channels) * channels].reshape(-1, channels)[:, 0]

            # Защита от переполнения: обрезаем фразу по max_audio_time.
            max_samples = int(self.max_audio_time * self.sample_rate)
            if data.size > max_samples:
                self.get_logger().warn(
                    f'Фраза длиннее max_audio_time ({self.max_audio_time} с) — обрезаю')
                data = data[:max_samples]

            self.audio_queue.put((data, float(self.sample_rate)))
        except Exception as e:  # noqa: BLE001
            self.get_logger().error(f'Ошибка обработки аудио сообщения: {e}')

    def _recognition_thread(self):
        """Поток: фраза → ресемплинг в 16k → окна по NPU → CTC-текст → публикация."""
        while self.running:
            try:
                data, src_rate = self.audio_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                audio_start = time.time()
                audio16 = self._resample_to_16k(np.asarray(data, dtype=np.float32), src_rate)
                if audio16.size == 0:
                    continue
                audio_duration = audio16.size / float(SR)
                self.get_logger().debug(
                    f'фраза: {audio16.size} семплов @16k ≈ {audio_duration:.2f} с')

                t0 = time.time()
                collapsed, lat = self.frontend.run_windows(self.engine, audio16)
                transcription_time = time.time() - t0
                text = decode_ids(collapsed, self.vocab)
                self.get_logger().debug(
                    f'окон NPU: {len(lat)}, id: {len(collapsed)}, текст: {text!r}')
                if text:
                    self._publish_transcription(
                        text, min(audio_duration, self.max_audio_time), transcription_time)
                if lat:
                    self.get_logger().debug(
                        f'NPU latency_ms: {[round(x, 1) for x in lat]}')
                _ = audio_start
            except Exception as e:  # noqa: BLE001
                self.get_logger().error(f'Ошибка распознавания: {e}')

    @staticmethod
    def _resample_to_16k(x: np.ndarray, src_rate: float) -> np.ndarray:
        if src_rate == SR or x.size == 0:
            return x.astype(np.float32)
        dst_n = int(round(x.size * SR / src_rate))
        if dst_n <= 0:
            return np.zeros(0, dtype=np.float32)
        idx = np.linspace(0, x.size - 1, dst_n, dtype=np.float64)
        return np.interp(idx, np.arange(x.size), x).astype(np.float32)

    def _publish_transcription(self, text, audio_time=0.0, transcription_time=0.0):
        msg = TranscriptionMsg()
        msg.text = text
        msg.audio_time = audio_time
        msg.transcription_time = transcription_time
        self.transcription_pub.publish(msg)
        self.get_logger().info(f'Распознавание: {text}')

    def execute_callback(self, goal_handle):
        """Action ``STT``: для совместимости с whisper/vosk подтверждаем goal.

        GigaAM — оконный CTC без грамматики/промпта; интерфейс сохранён.
        """
        result_msg = STT.Result()
        goal_handle.succeed()
        result_msg.transcription = TranscriptionMsg()
        return result_msg

    def destroy_node(self):
        self.get_logger().info('Завершение работы узла GigaAM...')
        self.running = False
        if hasattr(self, 'recognition_thread') and self.recognition_thread.is_alive():
            self.recognition_thread.join(timeout=2.0)
        if hasattr(self, 'engine'):
            self.engine.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = GigaamNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except Exception as e:  # noqa: BLE001
        if node:
            node.get_logger().error(f'Ошибка в узле: {e}')
    finally:
        if node:
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
