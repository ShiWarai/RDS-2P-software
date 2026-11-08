"""Калибровка сервоприводов: загрузка JSON и перевод долей в целевые pos (единицы регистра, как leg/utils.py)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


def load_calibration_json(path: str) -> Optional[Dict[str, Any]]:
    p = Path(path).expanduser()
    if not p.is_file():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def calculate_position(
    data: dict, device_id: int, percent: float, no_limit: bool = False
) -> int:
    """percent в долях [0..1] или без ограничения при no_limit=True (как voice_control)."""
    device_ids = {}
    for leg_number in range(1, 4 + 1):
        for cur_device_id in data[f"leg_{leg_number}"]["positions"]:
            device_ids[cur_device_id] = data[f"leg_{leg_number}"]["positions"][cur_device_id]
    min_p = device_ids[f"device_id-{device_id}"]["min"]
    max_p = device_ids[f"device_id-{device_id}"]["max"]
    if not no_limit:
        percent = max(0.0, min(1.0, percent))
    position = min_p + (max_p - min_p) * percent
    return int(position)
