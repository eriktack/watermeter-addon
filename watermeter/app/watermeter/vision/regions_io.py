"""Saving, loading and validating the regions drawn in the Regions page (task C2).

Files in the data folder: `regions.json` (the `Regions`, JSON below) and `reference.jpg` (the image they are drawn on).

    {"reference_width": 640, "reference_height": 480, "rotation_deg": -1.5,
     "marks": [{"name": "logo", "box": [x, y, w, h]}, ...],
     "volume": {"whole": {"x": 150, "y": 205, "width": 36, "height": 70, "count": 6, "gap": 0},
                "decimals": null | {"x": ..., "y": ..., "width": ..., "height": ..., "count": 3, "gap": 0}},
     "flow": null | {"whole": ..., "decimals": ...}}

A line is two groups, the whole digits and the decimals. A group is `count` digit boxes of `width` x `height`, the
first at (x, y) (top left), each next one `width + gap` further right. The boxes are in the coordinates of the
reference turned by `rotation_deg`. Older forms are still read: a group as one box split into equal digits
(`{"box": [x, y, w, h], "count": 6}`) and a line as a list of boxes (`{"digits": [[x, y, w, h], ...], "decimals": 3}`).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import Box, Line, Mark, Regions

REGIONS_FILE = "regions.json"
REFERENCE_FILE = "reference.jpg"
MAX_MARKS = 2
MAX_DIGITS = 12
MAX_ROTATION_DEG = 45


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


def _group(value: Any, width: int, height: int, what: str) -> list[Box]:
    if not isinstance(value, dict):
        raise ValueError(f"{what}: missing")
    count = value.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= MAX_DIGITS:
        raise ValueError(f"{what}: the digit count must be between 1 and {MAX_DIGITS}")
    if "box" in value:   # older form: one box split into equal digits
        box = _box(value.get("box"), width, height, what)
        if box.w < count:
            raise ValueError(f"{what}: narrower than one pixel per digit")
        return split_line(box.x, box.y, box.w, box.h, count)
    x, y, w, h, gap = (value.get(k) for k in ("x", "y", "width", "height", "gap"))
    gap = 0 if gap is None else gap
    if not isinstance(gap, int) or isinstance(gap, bool) or gap < 0:
        raise ValueError(f"{what}: the gap must be a whole number of at least 0")
    first = _box([x, y, w, h], width, height, f"{what} digit 1")
    return [_box([first.x + i * (first.w + gap), first.y, first.w, first.h], width, height, f"{what} digit {i + 1}")
            for i in range(count)]


def _line(value: Any, width: int, height: int, what: str) -> Line:
    if not isinstance(value, dict):
        raise ValueError(f"{what}: missing")
    if "digits" not in value:
        whole = _group(value.get("whole"), width, height, f"{what} digits")
        fraction = _group(value["decimals"], width, height, f"{what} decimals") if value.get("decimals") else []
        return Line(tuple(whole + fraction), len(fraction))
    digits = value.get("digits")   # the older form: a list of boxes
    if not isinstance(digits, list) or not digits:
        raise ValueError(f"{what}: needs at least one digit box")
    decimals = value.get("decimals", 0)
    if not isinstance(decimals, int) or isinstance(decimals, bool) or not 0 <= decimals < len(digits):
        raise ValueError(f"{what}: decimals must be fewer than the digits")
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
    rotation = data.get("rotation_deg", 0.0)
    if not isinstance(rotation, (int, float)) or isinstance(rotation, bool) or abs(rotation) > MAX_ROTATION_DEG:
        raise ValueError(f"rotation must be a number between -{MAX_ROTATION_DEG} and {MAX_ROTATION_DEG} degrees")
    flow = data.get("flow")
    return Regions(width, height, tuple(marks), _line(data.get("volume"), width, height, "volume"),
                   _line(flow, width, height, "flow") if flow is not None else None, round(float(rotation), 1))


def _group_dict(boxes: tuple[Box, ...]) -> dict | None:
    """The group of these boxes: the first box, the count and the gap between the first two; None for no boxes."""
    if not boxes:
        return None
    first = boxes[0]
    gap = max(boxes[1].x - first.x - first.w, 0) if len(boxes) > 1 else 0
    return {"x": first.x, "y": first.y, "width": first.w, "height": first.h, "count": len(boxes), "gap": gap}


def _line_dict(line: Line) -> dict:
    whole = len(line.digits) - line.decimals
    return {"whole": _group_dict(line.digits[:whole]), "decimals": _group_dict(line.digits[whole:])}


def regions_to_dict(regions: Regions) -> dict:
    return {
        "reference_width": regions.reference_width,
        "reference_height": regions.reference_height,
        "rotation_deg": regions.rotation_deg,
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
