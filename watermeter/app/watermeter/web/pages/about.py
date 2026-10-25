"""Example page (B0): shows version and the main settings. Copy this pattern for the other pages."""
from __future__ import annotations

from aiohttp import web


async def handler(request: web.Request) -> web.Response:
    from ..app import context, esc, render_page

    ctx = context(request)
    s = ctx.settings
    rows = [
        ("Version", ctx.version),
        ("Capture interval", f"{s.capture.interval_s} s, {s.capture.frames} frames"),
        ("Model", s.recognition.model),
        ("Direction", s.validation.direction),
        ("Max rate", f"{s.validation.max_rate_lph / 1000:g} m³/h"),
    ]
    body = "<table>" + "".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in rows) + "</table>"
    return render_page(request, "about", "About", body)
