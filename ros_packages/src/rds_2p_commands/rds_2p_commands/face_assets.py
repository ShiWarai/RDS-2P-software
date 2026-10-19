"""Разрешение PNG морды: относительно ``share/<pkg>/data/faces/`` или абсолютный путь."""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def resolve_face_png(share_dir: Path, face: str) -> Optional[Path]:
    raw = str(face).strip()
    if not raw:
        return None
    expanded = Path(raw).expanduser()
    if expanded.is_absolute():
        try:
            cand = expanded.resolve()
        except OSError:
            return None
        return cand if cand.is_file() else None

    rel = Path(raw)
    if rel.is_absolute():
        return None
    if ".." in rel.parts:
        return None
    # Не делаем resolve()+relative_to(): при --symlink-install файлы в share —
    # симлинки в src; resolve() у base и у файла даёт разные префиксы, хотя путь валиден.
    candidate = share_dir / "data" / "faces" / rel
    return candidate if candidate.is_file() else None
