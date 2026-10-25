"""Labels for the test set (task C1). File: `<data>/labels.json`:
`{"images/2026-10-25/120000_0.jpg": {"volume": "000170.861", "flow": "0.000"}, ...}` (flow may be absent)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence


def load_labels(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_label(path: Path, image: str, volume: str, flow: str | None) -> None:
    """Add or replace one label; writes atomically (temp file + replace)."""
    labels = load_labels(path)
    entry = {"volume": volume}
    if flow is not None:
        entry["flow"] = flow
    labels[image] = entry
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(labels, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def consecutive_run(raws: Sequence[str | None], labelled: Sequence[bool], start: int) -> range:
    """Indices after `start` that belong to its run: the following bursts with the same raw reading, not labelled yet,
    up to the first one that breaks the run (a different reading or an already labelled burst). Oldest first."""
    end = start + 1
    while end < len(raws) and not labelled[end] and raws[end] == raws[start]:
        end += 1
    return range(start + 1, end)
