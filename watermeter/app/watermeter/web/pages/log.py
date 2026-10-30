"""Log page (task D4, card `docs/plans/cards/D4.md`). Page `log`, API (relative for ingress):
- `GET log?all=1&page=N` → the bursts, newest first; only the non-OK ones unless `all=1`, 50 per page.
- `GET api/image?path=images/...` → one frame below the data folder's `images/` folder (400 otherwise, 404 if missing),
  turned by the regions' rotation offset like the reading does (`frame_response`).

`load_bursts` reads the burst JSON files the service loop writes next to the frames (`images/YYYY-MM-DD/HHMMSS.json`).
The labels page uses it too.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import cv2
from aiohttp import web

from ...vision.images import decode_jpeg, rotate
from ...vision.regions_io import load_regions

PAGE_SIZE = 50
OK = "ok"


@dataclass(frozen=True)
class Burst:
    image: str              # frame 0, relative to the data folder: the key used in labels.json
    frames: tuple[str, ...]
    time: str
    raw: str
    flow: str | None
    confidence: float
    status: str
    detail: str
    value_l: int | None


def load_bursts(data_dir: Path) -> list[Burst]:
    """All bursts, newest first. Files that cannot be read or have no frames are skipped."""
    bursts = []
    for path in sorted((data_dir / "images").glob("*/??????.json"), reverse=True):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict) or not doc.get("frames"):
            continue
        frames = tuple(doc["frames"])
        bursts.append(Burst(
            image=frames[0],
            frames=frames,
            time=str(doc.get("time", "")),
            raw=str(doc.get("raw", "")),
            flow=doc.get("flow"),
            confidence=float(doc.get("confidence") or 0.0),
            status=str(doc.get("status", "")),
            detail=str(doc.get("detail", "")),
            value_l=doc.get("value_l"),
        ))
    return bursts


def _data_dir(request: web.Request):
    from ..app import context

    return context(request).data_dir


def _page_link(show_all: bool, page: int) -> str:
    return f"log?{'all=1&' if show_all else ''}page={page}"


def _body(bursts: list[Burst], show_all: bool, page: int) -> str:
    from ..app import esc, time_html

    shown = bursts if show_all else [b for b in bursts if b.status != OK]
    pages = max(1, math.ceil(len(shown) / PAGE_SIZE))
    page = min(max(page, 1), pages)
    rows = []
    for b in shown[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]:
        status_class = "ok" if b.status == OK else "bad"
        thumbs = "".join(
            f'<a href="api/image?path={quote(f, safe="/")}" target="_blank" rel="noopener">'
            f'<img src="api/image?path={quote(f, safe="/")}" width="160" loading="lazy" alt="frame"></a>'
            for f in b.frames)
        flow = f'<br><span class="muted">flow {esc(b.flow)} m³/h</span>' if b.flow else ""
        rows.append(f"""\
<tr>
  <td>{time_html(b.time)}</td>
  <td class="{status_class}">{esc(b.status)}</td>
  <td>{esc(b.detail)}</td>
  <td>{esc(b.raw)}{flow}</td>
  <td>{b.confidence * 100:.1f} %</td>
  <td class="thumbs">{thumbs}</td>
</tr>""")

    if not rows:
        table = '<p class="muted">Nothing to show.</p>'
    else:
        table = ("<table><tr><th>Time</th><th>Status</th><th>Detail</th><th>Raw reading</th>"
                 "<th>Confidence</th><th>Frames</th></tr>" + "".join(rows) + "</table>")

    prev = f'<a href="{_page_link(show_all, page - 1)}">← newer</a>' if page > 1 else ""
    nxt = f'<a href="{_page_link(show_all, page + 1)}">older →</a>' if page < pages else ""
    filter_link = "log" if show_all else "log?all=1"
    filter_text = "Show only rejected readings" if show_all else "Show all readings"
    return f"""\
<div class="toolbar">
  <a href="{filter_link}">{filter_text}</a>
  <span class="muted">page {page} of {pages}, {len(shown)} bursts</span>
  {prev} {nxt}
</div>
{table}
"""


async def handler(request: web.Request) -> web.Response:
    from ..app import context, render_page

    try:
        page = int(request.query.get("page", "1"))
    except ValueError:
        page = 1
    show_all = request.query.get("all") == "1"
    bursts = load_bursts(context(request).data_dir)
    return render_page(request, "log", "Log", _body(bursts, show_all, page))


async def api_image(request: web.Request) -> web.StreamResponse:
    data_dir = _data_dir(request)
    raw = request.query.get("path", "")
    relative = Path(raw)
    if not raw or relative.is_absolute() or ".." in relative.parts:
        raise web.HTTPBadRequest(text="path must be relative and stay inside images/")
    images = (data_dir / "images").resolve()
    target = (data_dir / relative).resolve()
    if images not in target.parents:
        raise web.HTTPBadRequest(text="path must be relative and stay inside images/")
    if not target.is_file():
        raise web.HTTPNotFound()
    return frame_response(data_dir, target)


def frame_response(data_dir: Path, path: Path) -> web.StreamResponse:
    """A captured frame as the reading sees it: turned by the saved rotation offset (unchanged file if none)."""
    regions = load_regions(data_dir)
    if regions is None or not regions.rotation_deg:
        return web.FileResponse(path, headers={"Cache-Control": "no-store"})
    try:
        image = rotate(decode_jpeg(path.read_bytes()), regions.rotation_deg)
    except ValueError:
        return web.FileResponse(path, headers={"Cache-Control": "no-store"})
    ok, jpeg = cv2.imencode(".jpg", cv2.cvtColor(image, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
    return web.Response(body=jpeg.tobytes(), content_type="image/jpeg", headers={"Cache-Control": "no-store"})
