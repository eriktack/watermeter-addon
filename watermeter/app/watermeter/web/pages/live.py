"""Live page (task B3, card `docs/plans/cards/B3.md`). Page `live`, API (relative for ingress):
- `GET api/latest.jpg` → the newest captured frame, turned by the rotation offset (404 if none).
- `POST api/capture` → capture a burst now (503 if the service has not set `capture_now`).
- `POST api/set_value` (JSON `{"value": "426.811"}`, m³) → the new current value (400 if not a value, 503 without the
  service). The same as HA's "Set current value" entity: the only way to lower or correct the published value.
"""
from __future__ import annotations

from pathlib import Path

from aiohttp import web

from ...storage import ImageStore
from ...mqtt.messages import parse_set_value
from .log import frame_response


def _data_dir(request: web.Request):
    from ..app import context

    return context(request).data_dir


def _latest_file(data_dir) -> Path | None:
    """The newest captured frame on disk. `ImageStore.latest()` is relative to the data folder."""
    latest = ImageStore(data_dir).latest()
    return data_dir / latest if latest is not None else None


def _body(request: web.Request) -> str:
    from ..app import context, esc, time_html

    ctx = context(request)
    decision, raw = ctx.last_decision, ctx.last_raw
    interval = ctx.settings.capture.interval_s
    disabled = "" if ctx.capture_now is not None else " disabled"
    set_disabled = "" if ctx.set_current_value is not None else " disabled"

    if decision is None or raw is None:
        reading = '<p class="muted">No reading yet.</p>'
    else:
        value = "—" if decision.value_l is None else f"{decision.value_l / 1000:.3f} m³"
        status_class = "ok" if decision.accepted else "bad"
        detail = f' <span class="muted">{esc(decision.detail)}</span>' if decision.detail else ""
        flow = f"\n  <dt>Flow (raw)</dt><dd>{esc(raw.flow.text)} m³/h</dd>" if raw.flow is not None else ""
        reading = f"""\
<dl class="reading">
  <dt>Volume</dt><dd class="value">{esc(value)}</dd>
  <dt>Raw reading</dt><dd>{esc(raw.volume.text)}</dd>{flow}
  <dt>Status</dt><dd class="{status_class}">{esc(decision.status.value)}{detail}</dd>
  <dt>Last reading</dt><dd>{time_html(raw.captured_at.isoformat(timespec="seconds"))}</dd>
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
  <div class="toolbar">
    <label>Set current value <input id="set-value" inputmode="decimal" placeholder="426.811" size="10"> m³</label>
    <button id="set-value-button" type="button"{set_disabled}>Set</button>
    <span id="set-status" class="muted">Corrects the published volume, e.g. after a misread was accepted.</span>
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
    return frame_response(_data_dir(request), path)


async def api_set_value(request: web.Request) -> web.Response:
    from ..app import context

    set_value = context(request).set_current_value
    if set_value is None:
        raise web.HTTPServiceUnavailable()
    try:
        body = await request.json()
    except ValueError:
        body = {}
    litres = parse_set_value(str(body.get("value", ""))) if isinstance(body, dict) else None
    if litres is None:
        return web.json_response({"ok": False, "error": "a value in m³ like 426.811"}, status=400)
    set_value(litres)
    return web.json_response({"ok": True, "litres": litres})


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
