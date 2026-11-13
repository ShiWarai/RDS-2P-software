#!/usr/bin/env python3
"""Запись AudioStamped-топика(ов) в WAV + диагностика непрерывности.

Пример:
  python3 record_audio_topic.py --topics /audio/input /audio/vad --duration 20 --outdir /tmp/kilo/rec

Для каждого топика пишет WAV и печатает:
  msgs / samples / rate / ch / audio-длительность / wall / fill% / max_stamp_gap.
fill% = (принятые сэмплы / rate) / wall-clock. Для непрерывного захвата ~100%;
заметно меньше → пропуски («рвёт»). max_stamp_gap — макс. скачок штампа между
сообщениями (большой = выпавший кусок). Для VAD-топика низкий fill ожидаем (гейтинг).
"""
from __future__ import annotations

import argparse
import os
import signal
import time
import wave

import numpy as np
import rclpy
from audio_common_msgs.msg import AudioStamped
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy


class Recorder(Node):
    def __init__(self, topics):
        super().__init__("audio_recorder")
        self.data = {t: [] for t in topics}
        self.meta = {
            t: {"msgs": 0, "samples": 0, "rate": None, "ch": None,
                "prev_stamp": None, "max_gap": 0.0, "gaps_over_50ms": 0}
            for t in topics
        }
        qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT,
                         history=HistoryPolicy.KEEP_LAST, depth=500)
        for t in topics:
            self.create_subscription(AudioStamped, t,
                                     lambda m, tt=t: self._cb(m, tt), qos)
        self.t0 = time.monotonic()

    def _cb(self, m, t):
        info = m.audio.info
        if info.format == 8:  # paInt16
            arr = np.asarray(m.audio.audio_data.int16_data, dtype=np.int16)
        elif info.format == 1:  # paFloat32
            arr = (np.asarray(m.audio.audio_data.float32_data, dtype=np.float64)
                   * 32767.0).clip(-32768, 32767).astype(np.int16)
        else:
            return
        self.data[t].append(arr)
        md = self.meta[t]
        md["msgs"] += 1
        md["samples"] += arr.size
        md["rate"] = info.rate
        md["ch"] = info.channels
        stamp = m.header.stamp.sec + m.header.stamp.nanosec * 1e-9
        if md["prev_stamp"] is not None:
            gap = stamp - md["prev_stamp"]
            if gap > md["max_gap"]:
                md["max_gap"] = gap
            if gap > 0.05:
                md["gaps_over_50ms"] += 1
        md["prev_stamp"] = stamp

    def save(self, outdir):
        os.makedirs(outdir, exist_ok=True)
        wall = time.monotonic() - self.t0
        print(f"\n=== Итог (wall={wall:.2f}s) ===")
        for t in self.data:
            md = self.meta[t]
            if not self.data[t]:
                print(f"{t}: НЕТ ДАННЫХ (VAD молчал или топик пуст)")
                continue
            pcm = np.concatenate(self.data[t])
            rate = md["rate"] or 44100
            ch = md["ch"] or 1
            fname = os.path.join(outdir, t.strip("/").replace("/", "_") + ".wav")
            with wave.open(fname, "wb") as w:
                w.setnchannels(ch)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(pcm.tobytes())
            audio_dur = md["samples"] / ch / rate
            fill = audio_dur / wall * 100 if wall > 0 else 0
            print(f"{t}: msgs={md['msgs']} rate={rate} ch={ch} "
                  f"audio={audio_dur:.2f}s fill={fill:.1f}% "
                  f"max_stamp_gap={md['max_gap']*1000:.1f}ms "
                  f"gaps>50ms={md['gaps_over_50ms']} -> {fname}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topics", nargs="+", default=["/audio/input"])
    ap.add_argument("--duration", type=float, default=20.0)
    ap.add_argument("--outdir", default="/tmp/kilo/rec")
    args = ap.parse_args()

    rclpy.init()
    node = Recorder(args.topics)
    stop = {"flag": False}

    def _sig(_s, _f):
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)
    print(f"Запись {args.topics} (до {args.duration:.0f}s или SIGTERM) → {args.outdir}. ГОВОРИТЕ.")
    try:
        end = time.monotonic() + args.duration
        while rclpy.ok() and not stop["flag"] and time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=0.1)
    except KeyboardInterrupt:
        pass
    node.save(args.outdir)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
