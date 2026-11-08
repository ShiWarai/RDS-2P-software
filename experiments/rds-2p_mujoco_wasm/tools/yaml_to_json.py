#!/usr/bin/env python3
"""panda_poses.yaml -> assets/poses.json.

Порядок чисел в позе: motor 1..12 = leg_1..leg_4 x (leg_block, hip, shin).
Согласованность этого порядка с порядком актуаторов MJCF — открытый вопрос
PLAN.md раздел 12.1; здесь переносим значения как есть.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def parse_simple(text: str) -> dict:
    """Минимальный парсер формата panda_poses.yaml (без зависимости от PyYAML)."""
    poses: dict[str, list[float]] = {}
    current: str | None = None
    buf: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if line.startswith("  ") and stripped.endswith("]"):
            key, _, vals = stripped.partition(":")
            nums = [float(x) for x in NUM_RE.findall(vals)]
            if len(nums) != 12:
                raise ValueError(f"pose {key}: ожидалось 12 чисел, получено {len(nums)}")
            poses[key] = nums
        elif line.startswith("  ") and ":" in stripped and not stripped.endswith("]"):
            key, _, vals = stripped.partition(":")
            current, buf = key, [vals]
        elif current is not None and line.startswith("    "):
            buf.append(stripped)
            if stripped.endswith("]"):
                nums = [float(x) for x in NUM_RE.findall(" ".join(buf))]
                if len(nums) != 12:
                    raise ValueError(f"pose {current}: ожидалось 12 чисел, получено {len(nums)}")
                poses[current] = nums
                current = None
    return poses


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    repo = root.parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--src",
        type=Path,
        default=repo / "ros_packages/src/rds_2p_commands/config/panda_poses.yaml",
    )
    parser.add_argument("--out", type=Path, default=root / "assets/poses.json")
    args = parser.parse_args()

    text = args.src.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        doc = yaml.safe_load(text) or {}
        raw_poses = doc.get("poses", {})
        poses = {k: [float(x) for x in v] for k, v in raw_poses.items() if isinstance(v, list) and len(v) == 12}
    except ImportError:
        poses = parse_simple(text)

    if not poses:
        raise SystemExit(f"позы не найдены в {args.src}")

    out = {
        "meta": {
            "source": "ros_packages/src/rds_2p_commands/config/panda_poses.yaml",
            "order": "motor 1..12 = leg_1..leg_4 x (leg_block, hip, shin)",
            "note": "значения в долях; no_limit-позы (position_3_*, position_4_*) выходят за 0..1",
            "count": len(poses),
        },
        "poses": poses,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({len(poses)} poses)")


if __name__ == "__main__":
    main()
