"""Saving, loading and validating the regions drawn in the Regions page (task C2).

Files in the data folder: `regions.json` (the `Regions`, JSON below) and `reference.jpg` (the image they are drawn on).

    {"reference_width": 640, "reference_height": 480,
     "marks": [{"name": "logo", "box": [x, y, w, h]}, ...],
     "volume": {"digits": [[x, y, w, h], ...], "decimals": 3},
     "flow": null | {"digits": [...], "decimals": 3}}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import Box, Line, Mark, Regions

REGIONS_FILE = "regions.json"
REFERENCE_FILE = "reference.jpg"
MAX_MARKS = 2


def _box(value: Any, width: int, height: int, what: str) -> Box:
    if not (isinstance(value, (list, tuple)) and len(value) == 4 and all(isinstance(v, int) and not isinstance(v, bool)
                                                                          for v in value)):
        raise ValueError(f"{what}: a box is four whole numbers [x, y, w, h]")
    x, y, w, h = value
    if w < 1 or h < 1:
        raise ValueError(f"{what}: width and height must be at least 1")
    if x < 0 or y < 0 or x + w > width or y + h > height:
        raise ValueError(f"{what}: the box is outside the {width}x{height} reference image")
    return Box(x, y, w, h)


def _line(value: Any, width: int, height: int, what: str) -> Line:
    if not isinstance(value, dict):
        raise ValueError(f"{what}: missing")
    digits = value.get("digits")
    if not isinstance(digits, list) or not digits:
        raise ValueError(f"{what}: needs at least one digit box")
    decimals = value.get("decimals", 0)
    if not isinstance(decimals, int) or isinstance(decimals, bool) or not 0 <= decimals <= len(digits):
        raise ValueError(f"{what}: decimals must be between 0 and the number of digits")
    return Line(tuple(_box(b, width, height, f"{what} digit {i + 1}") for i, b in enumerate(digits)), decimals)


def regions_from_dict(data: Any) -> Regions:
    """Validate and build `Regions` from the JSON form; raises ValueError with a message for the user."""
    if not isinstance(data, dict):
        raise ValueError("regions must be an object")
    width, height = data.get("reference_width"), data.get("reference_height")
    if not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in (width, height)):
        raise ValueError("reference_width and reference_height must be positive whole numbers")
    raw_marks = data.get("marks", [])
    if not isinstance(raw_marks, list) or len(raw_marks) > MAX_MARKS:
        raise ValueError(f"at most {MAX_MARKS} alignment marks")
    marks, names = [], set()
    for i, m in enumerate(raw_marks):
        name = m.get("name") if isinstance(m, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"mark {i + 1} needs a name")
        if name in names:
            raise ValueError(f"two marks are named {name!r}")
        names.add(name)
        marks.append(Mark(name.strip(), _box(m.get("box"), width, height, f"mark {name}")))
    flow = data.get("flow")
    return Regions(width, height, tuple(marks), _line(data.get("volume"), width, height, "volume"),
                   _line(flow, width, height, "flow") if flow is not None else None)


def _line_dict(line: Line) -> dict:
    return {"digits": [[b.x, b.y, b.w, b.h] for b in line.digits], "decimals": line.decimals}


def regions_to_dict(regions: Regions) -> dict:
    return {
        "reference_width": regions.reference_width,
        "reference_height": regions.reference_height,
        "marks": [{"name": m.name, "box": [m.box.x, m.box.y, m.box.w, m.box.h]} for m in regions.marks],
        "volume": _line_dict(regions.volume),
        "flow": _line_dict(regions.flow) if regions.flow else None,
    }


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def load_regions(data_dir: Path) -> Regions | None:
    """The saved regions, or None when none are saved (or the file is damaged)."""
    try:
        return regions_from_dict(json.loads((data_dir / REGIONS_FILE).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def save_regions(data_dir: Path, regions: Regions) -> None:
    _write(data_dir / REGIONS_FILE, json.dumps(regions_to_dict(regions), indent=2).encode("utf-8"))


def load_reference_bytes(data_dir: Path) -> bytes | None:
    try:
        return (data_dir / REFERENCE_FILE).read_bytes()
    except OSError:
        return None


def save_reference(data_dir: Path, jpeg: bytes) -> None:
    _write(data_dir / REFERENCE_FILE, jpeg)


def split_line(x: int, y: int, w: int, h: int, count: int) -> list[Box]:
    """Divide a rectangle drawn around a whole display line into `count` equally wide digit boxes."""
    if count < 1:
        raise ValueError("count must be at least 1")
    edges = [x + round(w * i / count) for i in range(count + 1)]
    return [Box(edges[i], y, edges[i + 1] - edges[i], h) for i in range(count)]
