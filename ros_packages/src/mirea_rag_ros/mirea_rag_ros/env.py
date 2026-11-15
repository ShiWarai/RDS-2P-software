"""Минимальный загрузчик .env без зависимости от python-dotenv."""
from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str | Path | None) -> None:
    if not path:
        return
    p = Path(path)
    try:
        if not p.is_file():
            return
        text = p.read_text(encoding="utf-8")
    except OSError:
        # Нечитаемый файл/каталог — работаем на дефолтах окружения.
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)
