#!/usr/bin/env python3
"""Подписка на AudioStamped (шина воспроизведения): микшер по ``header.frame_id`` + выход PortAudio.

Договор:
  - В каждом сообщении задайте непустой ``header.frame_id`` (вид ``<домен>.<ид>``).
  - ``audio.info.rate`` == ``output_sample_rate`` узла (иначе сообщение игнорируется).

На такте ``mix_period_ms`` все активные источники суммируются; при превышении ±1 —
``numpy.clip`` (без ``tanh``: тот искажал бы даже один источник в номинальном диапазоне).
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import rclpy
import sounddevice as sd
from audio_common_msgs.msg import AudioStamped
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)

PA_FLOAT32 = 1
PA_INT32 = 2
PA_INT16 = 8
PA_INT8 = 16
PA_UINT8 = 32


class SourceFifo:
    """FIFO float32 блоков ``(frames, channels)``.

    При смене числа входных каналов буфер сбрасывается новым сообщением — лог см. узел при необходимости.
    """

    def __init__(self) -> None:
        self._cur = np.empty((0, 1), dtype=np.float32)

    def push(self, frames: np.ndarray) -> None:
        if frames.size == 0:
            return
        frames = np.ascontiguousarray(frames, dtype=np.float32)
        if self._cur.shape[0] == 0:
            self._cur = frames
        elif self._cur.shape[1] != frames.shape[1]:
            self._cur = frames
        else:
            self._cur = np.concatenate((self._cur, frames), axis=0)

    def pop_frames(self, n: int, channels: int) -> np.ndarray:
        out = np.zeros((n, channels), dtype=np.float32)
        if n <= 0:
            return out
        pos = 0
        while pos < n:
            if self._cur.shape[0] == 0:
                break
            if self._cur.shape[1] != channels:
                self._cur = self._cur[:0]
                break
            take = min(n - pos, int(self._cur.shape[0]))
            out[pos : pos + take] = self._cur[:take]
            pos += take
            self._cur = self._cur[take:]
        return out

    def clear(self) -> None:
        self._cur = self._cur[:0]


@dataclass
class SourceEntry:
    fifo: SourceFifo
    last_msg_mono: float = 0.0


class AudioPlayer(Node):
    """Микширует сообщения разных источников (``frame_id``) в один PortAudio-поток."""

    def __init__(self) -> None:
        super().__init__("audio_player")

        self.declare_parameter("topic", "/audio/output")
        self.declare_parameter("device", -1)
        # Если непусто — выставить до открытия PortAudio (маршрут default → нужный sink, не USB).
        self.declare_parameter("pulse_sink", "")
        self.declare_parameter("channels", 1)
        self.declare_parameter("output_sample_rate", 44100)
        self.declare_parameter("mix_period_ms", 20.0)
        self.declare_parameter("source_evict_sec", 5.0)
        self.declare_parameter("qos_depth", 50)
        # Сколько «тихих» тактов положить в очередь до ALSA: сглаживает старт и джиттер DDS.
        self.declare_parameter("output_prime_ticks", 6)
        # Выравнивать blocksize PortAudio под mix_tick (меньше рассинхрона с микшером).
        self.declare_parameter("stream_blocksize_match", True)

        topic = self.get_parameter("topic").get_parameter_value().string_value
        self._device = self.get_parameter("device").get_parameter_value().integer_value
        self._channels = self.get_parameter("channels").get_parameter_value().integer_value

        pulse_sink = (
            self.get_parameter("pulse_sink").get_parameter_value().string_value or ""
        ).strip()
        if pulse_sink:
            os.environ["PULSE_SINK"] = pulse_sink
            self.get_logger().info(
                f"Установлено окружение PULSE_SINK={pulse_sink!r} до открытия потока PortAudio"
            )

        out_pv = self.get_parameter("output_sample_rate").get_parameter_value()
        if out_pv.integer_value > 0:
            self._output_sr = int(out_pv.integer_value)
        elif abs(out_pv.double_value) >= 1.0:
            self._output_sr = int(round(out_pv.double_value))
        else:
            self._output_sr = 0

        pv_mix = self.get_parameter("mix_period_ms").get_parameter_value()
        if pv_mix.double_value != 0.0:
            mix_ms = float(pv_mix.double_value)
        elif pv_mix.integer_value:
            mix_ms = float(pv_mix.integer_value)
        else:
            mix_ms = 20.0

        ev_pv = self.get_parameter("source_evict_sec").get_parameter_value()
        if ev_pv.double_value != 0.0:
            evict_sec = float(ev_pv.double_value)
        else:
            evict_sec = float(ev_pv.integer_value if ev_pv.integer_value else 5)

        qos_depth = max(10, self.get_parameter("qos_depth").get_parameter_value().integer_value)
        prime_ticks = max(0, self.get_parameter("output_prime_ticks").get_parameter_value().integer_value)
        blocksize_match = bool(
            self.get_parameter("stream_blocksize_match").get_parameter_value().bool_value
        )

        if self._channels <= 0:
            raise ValueError("channels must be > 0")
        if self._output_sr <= 0:
            raise ValueError("output_sample_rate must be > 0")

        self._mix_period_s = max(1e-3, mix_ms / 1000.0 if mix_ms > 0 else 0.020)
        self._frames_per_tick = max(1, int(round(self._output_sr * self._mix_period_s)))
        self._source_evict_sec = max(0.1, evict_sec)

        self._qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=qos_depth,
        )

        self._sources_lock = threading.Lock()
        self._sources: Dict[str, SourceEntry] = {}

        self._shutdown = threading.Event()
        self._chunk_lock = threading.Lock()
        self._mixed_chunks: deque = deque()

        self._last_bad_fid_log = 0.0
        self._last_rate_miss_log = 0.0
        self._rate_drop_count = 0
        self._stream: Optional[sd.OutputStream] = None
        self._last_status_log = 0.0

        silent_blk = np.zeros((self._frames_per_tick, self._channels), dtype=np.float32)
        with self._chunk_lock:
            for _ in range(prime_ticks):
                self._mixed_chunks.append(silent_blk.copy())

        dev_param = None if self._device < 0 else int(self._device)
        stream_kw: dict = {
            "samplerate": self._output_sr,
            "channels": self._channels,
            "dtype": "float32",
            "device": dev_param,
            "latency": "high",
            "callback": self._pa_callback,
        }
        if blocksize_match:
            stream_kw["blocksize"] = self._frames_per_tick
        try:
            self._stream = sd.OutputStream(**stream_kw)
            self._stream.start()
            self.get_logger().info(
                f"audio_player: OutputStream sr={self._output_sr} ch={self._channels} "
                f"mix_tick={mix_ms:g} ms ({self._frames_per_tick} fr) blocksize="
                f"{stream_kw.get('blocksize', 'default')} prime_ticks={prime_ticks} subs={topic!r}"
            )
        except Exception as exc_first:  # noqa: BLE001
            if blocksize_match and "blocksize" in stream_kw:
                stream_kw.pop("blocksize", None)
                try:
                    self._stream = sd.OutputStream(**stream_kw)
                    self._stream.start()
                    self.get_logger().warn(
                        f"OutputStream без blocksize=mix_tick (fallback после: {exc_first})"
                    )
                    self.get_logger().info(
                        f"audio_player: OutputStream sr={self._output_sr} ch={self._channels} "
                        f"mix_tick={mix_ms:g} ms ({self._frames_per_tick} fr) prime_ticks={prime_ticks} "
                        f"subs={topic!r}"
                    )
                except Exception as exc2:  # noqa: BLE001
                    self.get_logger().error(f"OutputStream failed: {exc2}")
            else:
                self.get_logger().error(f"OutputStream failed: {exc_first}")

        self._mixer = threading.Thread(target=self._mixer_loop, daemon=True)
        self._mixer.start()

        # Контракт /audio/output: непустой header.frame_id, audio.info.rate == output_sample_rate;
        # эвикт источников после source_evict_sec без сообщений; подписка BEST_EFFORT depth=qos_depth.
        self.create_subscription(AudioStamped, topic, self._audio_cb, self._qos)

    def destroy_node(self) -> bool:
        self._shutdown.set()
        self._mixer.join(timeout=5.0)
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._stream = None
        with self._chunk_lock:
            self._mixed_chunks.clear()
        return super().destroy_node()

    def _audio_cb(self, msg: AudioStamped) -> None:
        if self._shutdown.is_set():
            return

        fid_raw = getattr(msg.header, "frame_id", None) if msg.header else ""
        fid = (fid_raw or "").strip()

        sr_msg = int(msg.audio.info.rate)
        if sr_msg != self._output_sr:
            self._rate_drop_count += 1
            now = time.monotonic()
            if now - self._last_rate_miss_log >= 5.0:
                self._last_rate_miss_log = now
                self.get_logger().warn(
                    f"rate mismatch {sr_msg} != {self._output_sr} (drops≈{self._rate_drop_count})"
                )
            return

        if not fid:
            now = time.monotonic()
            if now - self._last_bad_fid_log >= 5.0:
                self._last_bad_fid_log = now
                self.get_logger().warn(
                    "Пустой header.frame_id у AudioStamped — игнорируем. Задайте идентификатор источника."
                )
            return

        try:
            audio = self._message_to_float32(msg)
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f"decode AudioStamped: {exc}")
            return

        if audio.size == 0:
            return

        now_mono = time.monotonic()
        with self._sources_lock:
            if fid not in self._sources:
                self._sources[fid] = SourceEntry(SourceFifo(), last_msg_mono=now_mono)
                self.get_logger().debug(f"источник {fid!r} зарегистрирован")

            entry = self._sources[fid]
            entry.last_msg_mono = now_mono
            entry.fifo.push(audio)

    def _mixer_loop(self) -> None:
        while not self._shutdown.is_set():
            t0 = time.monotonic()
            mono = self._mixer_tick_once(time.monotonic())
            # Сумма источников может выйти за ±1; clip без нелинейности на обычном уровне
            # (в отличие от tanh по всему сигналу — давил динамику и «мутил» звук).
            clipped = np.clip(mono, -1.0, 1.0).astype(np.float32, copy=False)

            with self._chunk_lock:
                self._mixed_chunks.append(clipped)

            elapsed = time.monotonic() - t0
            rest = max(0.002, self._mix_period_s - elapsed)
            if self._shutdown.wait(timeout=rest):
                break

    def _mixer_tick_once(self, now_mono: float) -> np.ndarray:
        n = self._frames_per_tick
        accum = np.zeros((n, self._channels), dtype=np.float32)

        with self._sources_lock:
            stale = []
            for k, ent in self._sources.items():
                if now_mono - ent.last_msg_mono > self._source_evict_sec:
                    stale.append(k)
            for k in stale:
                self._sources.pop(k, None)
                self.get_logger().debug(
                    f"источник {k!r} удалён (> {self._source_evict_sec:.1f}s тишины)"
                )

            snaps = [(k, self._sources[k].fifo.pop_frames(n, self._channels)) for k in list(self._sources)]

        for _k, block in snaps:
            accum += block
        return accum

    def _pa_callback(self, outdata: np.ndarray, frames: int, _time_info, status) -> None:
        if status:
            now = time.monotonic()
            if now - self._last_status_log >= 2.0:
                self._last_status_log = now
                self.get_logger().warn(f"sounddevice: {status}")

        need = int(frames)
        filled = 0
        ch_out = min(int(outdata.shape[1]), self._channels)

        while filled < need:
            with self._chunk_lock:
                if not self._mixed_chunks:
                    outdata[filled:] = 0.0
                    return
                blk = self._mixed_chunks[0]
                avail = int(blk.shape[0])
                take = min(need - filled, avail)
                out_seg = outdata[filled : filled + take, :ch_out]

                blk_ch = blk.shape[1]
                if blk_ch <= ch_out:
                    out_seg[:, :blk_ch] = blk[:take, :blk_ch]
                    if blk_ch < ch_out:
                        out_seg[:, blk_ch:] = 0.0
                else:
                    out_seg[:, :] = blk[:take, :ch_out]

                filled += take
                if take == avail:
                    self._mixed_chunks.popleft()
                else:
                    self._mixed_chunks[0] = blk[take:]

    def _message_to_float32(self, msg: AudioStamped) -> np.ndarray:
        info = msg.audio.info
        fmt = int(info.format)
        in_channels = max(1, int(info.channels))

        if fmt == PA_FLOAT32:
            data = np.asarray(msg.audio.audio_data.float32_data, dtype=np.float32)
        elif fmt == PA_INT32:
            data = (
                np.asarray(msg.audio.audio_data.int32_data, dtype=np.int32).astype(np.float32)
                / 2147483648.0
            )
        elif fmt == PA_INT16:
            data = (
                np.asarray(msg.audio.audio_data.int16_data, dtype=np.int16).astype(np.float32)
                / 32768.0
            )
        elif fmt == PA_INT8:
            data = (
                np.asarray(msg.audio.audio_data.int8_data, dtype=np.int8).astype(np.float32)
                / 128.0
            )
        elif fmt == PA_UINT8:
            data = (
                np.asarray(msg.audio.audio_data.uint8_data, dtype=np.uint8).astype(np.float32) - 128.0
            ) / 128.0
        else:
            raise ValueError(f"unsupported PortAudio format: {fmt}")

        if data.size == 0:
            return np.empty((0, self._channels), dtype=np.float32)

        usable = (data.size // in_channels) * in_channels
        if usable != data.size:
            data = data[:usable]

        frames_view = data.reshape(-1, in_channels)
        return self._convert_channels(frames_view, self._channels)

    @staticmethod
    def _convert_channels(frames: np.ndarray, out_channels: int) -> np.ndarray:
        ic = int(frames.shape[1])
        if ic == out_channels:
            return np.ascontiguousarray(frames, dtype=np.float32)
        if ic == 1:
            return np.ascontiguousarray(np.repeat(frames, out_channels, axis=1), dtype=np.float32)
        if out_channels == 1:
            return np.ascontiguousarray(frames.mean(axis=1, keepdims=True), dtype=np.float32)

        mono = frames.mean(axis=1, keepdims=True)
        return np.ascontiguousarray(np.repeat(mono, out_channels, axis=1), dtype=np.float32)


def main(args: Optional[list[str]] = None) -> None:
    rclpy.init(args=args)
    player: Optional[AudioPlayer] = None
    try:
        player = AudioPlayer()
        rclpy.spin(player)
    except KeyboardInterrupt:
        pass
    finally:
        if player is not None:
            player.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
