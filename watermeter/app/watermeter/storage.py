"""Image store and retention (task B2). Layout: `<root>/images/YYYY-MM-DD/HHMMSS_<n>.jpg` (UTC) plus one
`HHMMSS.json` per burst with the raw reading and the decision (written by the service loop, D6)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from .models import Frame
from .settings import RetentionSettings

_FRAME = re.compile(r"^(\d{6})_(\d+)\.jpg$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Frames 1..N-1 of a burst that was not rejected are kept this long, so the reading in progress can still be
# labelled or turned into a rejection before they go.
EXTRA_FRAME_GRACE = timedelta(hours=1)


def _utc(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc) if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class ImageStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.images = self.root / "images"

    def save_burst(self, frames: Sequence[Frame]) -> list[Path]:
        """Save all frames; returns their paths (relative to root)."""
        paths = []
        for frame in frames:
            at = _utc(frame.captured_at)
            rel = Path("images") / at.strftime("%Y-%m-%d") / f"{at.strftime('%H%M%S')}_{frame.index}.jpg"
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(frame.jpeg)
            tmp.replace(target)
            paths.append(rel)
        return paths

    def latest(self) -> Path | None:
        """Path (relative to root) of the newest frame 0, or None."""
        if not self.images.is_dir():
            return None
        for day in sorted((d for d in self.images.iterdir() if d.is_dir() and _DAY.match(d.name)), reverse=True):
            firsts = sorted(f.name for f in day.iterdir() if (m := _FRAME.match(f.name)) and m.group(2) == "0")
            if firsts:
                return Path("images") / day.name / firsts[-1]
        return None

    def prune(self, now: datetime, retention: RetentionSettings, rejected: set[str], labelled: set[str]) -> int:
        """Delete old images per retention; `rejected`/`labelled` are relative paths. Returns the number deleted.

        Labelled images are never deleted. A rejected burst keeps all its frames for `rejected_days`; any other burst
        keeps frame 0 for `accepted_days` and its other frames for `EXTRA_FRAME_GRACE`. Burst JSON files go with
        the last frame of their burst; empty day folders are removed."""
        if not self.images.is_dir():
            return 0
        now = _utc(now)
        deleted = 0
        for day in [d for d in self.images.iterdir() if d.is_dir() and _DAY.match(d.name)]:
            for file in sorted(day.iterdir()):
                m = _FRAME.match(file.name)
                if not m:
                    continue
                rel = file.relative_to(self.root).as_posix()
                if rel in labelled:
                    continue
                taken = datetime.strptime(f"{day.name} {m.group(1)}", "%Y-%m-%d %H%M%S").replace(tzinfo=timezone.utc)
                if rel in rejected:
                    keep = timedelta(days=retention.rejected_days)
                elif m.group(2) == "0":
                    keep = timedelta(days=retention.accepted_days)
                else:
                    keep = EXTRA_FRAME_GRACE
                if now - taken > keep:
                    file.unlink()
                    deleted += 1
            self._tidy(day)
        return deleted

    def clear(self, labelled: set[str]) -> int:
        """Delete every burst (frames and JSON) except labelled images (relative paths). Returns the frames deleted."""
        if not self.images.is_dir():
            return 0
        deleted = 0
        for day in [d for d in self.images.iterdir() if d.is_dir() and _DAY.match(d.name)]:
            for file in day.iterdir():
                if _FRAME.match(file.name) and file.relative_to(self.root).as_posix() not in labelled:
                    file.unlink()
                    deleted += 1
            self._tidy(day)
        return deleted

    @staticmethod
    def _tidy(day: Path) -> None:
        """Remove burst JSON files whose frames are all gone, then the folder if it is empty."""
        left = {m.group(1) for f in day.iterdir() if (m := _FRAME.match(f.name))}
        for f in day.glob("??????.json"):
            if f.stem not in left:
                f.unlink()
        if not any(day.iterdir()):
            day.rmdir()
