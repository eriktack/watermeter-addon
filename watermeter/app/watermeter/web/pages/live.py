"""Live page (task B3, card `docs/plans/cards/B3.md`). Page `live`, API (relative for ingress):
- `GET api/latest.jpg` → the newest captured frame (404 if none).
- `POST api/capture` → capture a burst now (503 if the service has not set `capture_now`).
"""
from __future__ import annotations

from pathlib import Path

from aiohttp import web

from ...storage import ImageStore


def _data_dir(request: web.Request):
    from ..app import context

    return context(request).data_dir


def _latest_file(data_dir) -> Path | None:
    """The newest captured frame on disk. `ImageStore.latest()` is relative to the data folder."""
    latest = ImageStore(data_dir).latest()
    return data_dir / latest if latest is not None else None


def _body(request: web.Request) -> str:
    from ..app import context, esc

    ctx = context(request)
    decision, raw = ctx.last_decision, ctx.last_raw
    interval = ctx.settings.capture.interval_s
    disabled = "" if ctx.capture_now is not None else " disabled"

    if decision is None or raw is None:
        reading = '<p class="muted">No reading yet.</p>'
    else:
        value = "—" if decision.value_l is None else f"{decision.value_l / 1000:.3f} m³"
        status_class = "ok" if decision.accepted else "bad"
        detail = f' <span class="muted">{esc(decision.detail)}</span>' if decision.detail else ""
        reading = f"""\
<dl class="reading">
  <dt>Volume</dt><dd class="value">{esc(value)}</dd>
  <dt>Raw reading</dt><dd>{esc(raw.volume.text)}</dd>
  <dt>Status</dt><dd class="{status_class}">{esc(decision.status.value)}{detail}</dd>
  <dt>Last reading</dt><dd>{esc(raw.captured_at.isoformat(timespec="seconds"))}</dd>
  <dt>Confidence</dt><dd>{raw.volume.confidence * 100:.1f} %</dd>
</dl>"""

    latest = _latest_file(ctx.data_dir)
    if latest is None:
        image = '<p class="muted">No image yet.</p>'
    else:
        stamp = int(latest.stat().st_mtime)
        image = f'<img id="latest" src="api/latest.jpg?t={stamp}" alt="Latest camera image">'

    return f"""\
<div class="live" data-interval="{interval}">
  {image}
  {reading}
  <div class="toolbar">
    <button id="capture" type="button" class="primary"{disabled}>Capture now</button>
    <span id="status" class="muted"></span>
  </div>
</div>
"""


async def handler(request: web.Request) -> web.Response:
    from ..app import render_page

    return render_page(request, "live", "Live", _body(request), script="live.js")


async def api_latest(request: web.Request) -> web.StreamResponse:
    path = _latest_file(_data_dir(request))
    if path is None:
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "no-store"})


async def api_capture(request: web.Request) -> web.Response:
    from ..app import context

    capture_now = context(request).capture_now
    if capture_now is None:
        raise web.HTTPServiceUnavailable()
    try:
        await capture_now()
    except Exception as e:  # camera offline (CameraError) or a failed cycle: say so instead of a bare 500
        return web.json_response({"ok": False, "error": str(e)}, status=503)
    return web.json_response({"ok": True})
