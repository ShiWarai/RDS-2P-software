#!/usr/bin/env python3
"""Предсжатие статики gzip-копиями (для раздачи из docker-образа).

Рядом с подходящим файлом появляется ``file.gz``, если gzip реально уменьшает
размер. serve.py отдаёт ``.gz`` при ``Accept-Encoding: gzip`` и обычный файл
во всех остальных случаях, поэтому скрипт безопасен и для dev-сервера:
без ``.gz`` всё работает как раньше.

Запускается на этапе сборки образа (docker/web.Dockerfile):
    python3 tools/precompress_assets.py . /app/urdf_src

Сжатие выгоднее всего для mujoco_wasm.js (11 МБ), ORT-вариантов wasm,
blockly и obj-мешей. Уже сжатые форматы и каталоги ``models/`` (Laya 646 МБ,
Vosk tar.gz) пропускаются; файлы меньше 1 КБ не трогаем.
"""
from __future__ import annotations

import gzip
import sys
from pathlib import Path

COMPRESS_EXT = {
    ".js", ".mjs", ".cjs", ".css", ".html", ".htm", ".json", ".wasm",
    ".svg", ".xml", ".txt", ".obj", ".mtl", ".csv",
}
MIN_SIZE = 1024


def iter_candidates(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if "models" in path.relative_to(root).parts:
            continue
        if path.name.endswith(".gz"):
            continue
        if path.suffix.lower() not in COMPRESS_EXT:
            continue
        if path.stat().st_size < MIN_SIZE:
            continue
        yield path


def main(argv: list[str]) -> int:
    roots = [Path(a) for a in argv] or [Path(".")]
    count = raw_total = gz_total = 0
    for root in roots:
        if not root.is_dir():
            print(f"пропускаю (нет каталога): {root}", file=sys.stderr)
            continue
        for path in iter_candidates(root):
            raw = path.read_bytes()
            packed = gzip.compress(raw, compresslevel=9, mtime=0)
            if len(packed) >= len(raw):
                continue
            path.with_name(path.name + ".gz").write_bytes(packed)
            count += 1
            raw_total += len(raw)
            gz_total += len(packed)
    print(
        f"предсжато {count} файлов: {raw_total / 1048576:.1f} МБ → "
        f"{gz_total / 1048576:.1f} МБ (передача меньше на "
        f"{(raw_total - gz_total) / 1048576:.1f} МБ)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))