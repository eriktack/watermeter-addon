"""aiohttp application: routing, shared context and page rendering.

Rules for every page (HA ingress serves the add-on under a path prefix, e.g. `/api/hassio_ingress/<token>/`):
- Links, form actions, fetch() URLs and image sources are **relative** (`log`, `api/latest.jpg`), never `/log`.
- A page module in `pages/` exposes `async def handler(request) -> web.Response` (and optionally `api_*`
  handlers registered in `ROUTES` below). Render HTML with `render_page(...)`.
- Page JavaScript goes in `static/<page>.js`, styles in `static/style.css`.
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Awaitable, Callable

from aiohttp import web

from ..models import Decision, RawReading, ValidatorState
from ..settings import Settings
from .pages import about, labels, live, log, regions, settings

HERE = Path(__file__).parent
CONTEXT_KEY = web.AppKey("context", object)

ACTIVE = ' class="active"'
NAV = [("live", "Live"), ("regions", "Regions"), ("log", "Log"), ("labels", "Labels"), ("settings", "Settings"),
       ("about", "About")]


@dataclass
class WebContext:
    """Shared with the service loop (D6). Pages read from it. The Settings page saves through `apply_settings`;
    "set current value" goes through `set_current_value`."""
    data_dir: Path
    settings: Settings
    version: str = "dev"
    state: ValidatorState = field(default_factory=ValidatorState)
    last_raw: RawReading | None = None
    last_decision: Decision | None = None
    capture_now: Callable[[], Awaitable[None]] | None = None   # set by the service loop
    set_current_value: Callable[[int], None] | None = None     # litres; set by the service loop
    apply_settings: Callable[[Settings], None] | None = None   # set by the service loop (saves and applies)
    models: tuple[str, ...] = ()                                # model files the Settings page offers


def context(request: web.Request) -> WebContext:
    return request.app[CONTEXT_KEY]


def render_page(request: web.Request, active: str, title: str, body_html: str, script: str | None = None
                ) -> web.Response:
    """Wrap page content in the base template. `body_html` is trusted HTML: escape user/meter data with `esc()`."""
    nav = "".join(
        f'<a href="{key}"{ACTIVE if key == active else ""}>{label}</a>' for key, label in NAV)
    version = esc(context(request).version)   # in the static URLs too: an update must not use cached files
    script_tag = f'<script src="static/{script}?v={version}"></script>' if script else ""
    page = Template((HERE / "templates" / "base.html").read_text(encoding="utf-8")).substitute(
        title=esc(title), nav=nav, body=body_html, script=script_tag, version=version)
    return web.Response(text=page, content_type="text/html")


def esc(value: object) -> str:
    return html.escape(str(value))


def time_html(iso: str) -> str:
    """A UTC ISO time as a `<time>` element; `static/time.js` shows it in the browser's local time."""
    return f'<time datetime="{esc(iso)}">{esc(iso)}</time>'


async def index(request: web.Request) -> web.Response:
    raise web.HTTPFound("live")


ROUTES = [
    ("GET", "/", index),
    ("GET", "/live", live.handler),
    ("GET", "/regions", regions.handler),
    ("GET", "/log", log.handler),
    ("GET", "/labels", labels.handler),
    ("GET", "/settings", settings.handler),
    ("POST", "/settings", settings.save_handler),
    ("GET", "/about", about.handler),
    ("GET", "/api/regions", regions.api_get_regions),
    ("POST", "/api/regions", regions.api_save_regions),
    ("GET", "/api/reference.jpg", regions.api_reference),
    ("POST", "/api/reference", regions.api_set_reference),
    ("POST", "/api/reference/latest", regions.api_reference_from_latest),
    ("GET", "/api/crop/{line}/{index}.png", regions.api_crop),
    ("GET", "/api/alignment", regions.api_alignment),
    ("GET", "/api/latest.jpg", live.api_latest),
    ("POST", "/api/capture", live.api_capture),
    ("POST", "/api/set_value", live.api_set_value),
    ("GET", "/api/image", log.api_image),
    ("POST", "/labels", labels.save_handler),
    ("POST", "/log", log.clear_handler),
]


# HA ingress proxies every request from this address; localhost is for tools/dev_web.py and the tests.
INGRESS_CLIENTS = frozenset({"172.30.32.2", "127.0.0.1", "::1"})
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # a phone photo as reference image


def _only_from(allowed: frozenset[str]):
    """Refuse requests from anything but the ingress proxy (other add-ons share the internal network)."""
    @web.middleware
    async def middleware(request: web.Request, handler):
        if request.remote not in allowed:
            raise web.HTTPForbidden(text="Only reachable through Home Assistant")
        return await handler(request)
    return middleware


def create_app(ctx: WebContext, allowed_clients: frozenset[str] = INGRESS_CLIENTS) -> web.Application:
    app = web.Application(middlewares=[_only_from(allowed_clients)], client_max_size=MAX_UPLOAD_BYTES)
    app[CONTEXT_KEY] = ctx
    for method, path, handler in ROUTES:
        app.router.add_route(method, path, handler)
    app.router.add_static("/static", HERE / "static")
    return app
