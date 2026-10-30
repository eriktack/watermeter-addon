"""Labels page (task C1, card `docs/plans/cards/C1.md`). Page `labels`, form posts to `labels` (relative, for ingress).

Shows the oldest burst that has no label yet: frame 0, with the volume and flow pre-filled from its raw reading. You
confirm (Enter) or correct the values. "Label as run" (on by default) also labels the following bursts with the same
raw reading, up to the first one that differs or is already labelled."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from aiohttp import web

from ...labels import consecutive_run, load_labels, save_label
from .log import Burst, load_bursts

LABELS_FILE = "labels.json"
VOLUME = re.compile(r"^\d{6}\.\d{3}$")
FLOW = re.compile(r"^\d{1,6}\.\d{3}$")


def _state(data_dir: Path) -> tuple[list[Burst], list[bool]]:
    """All bursts oldest first, and which of them already have a label."""
    bursts = list(reversed(load_bursts(data_dir)))
    labels = load_labels(data_dir / LABELS_FILE)
    return bursts, [b.image in labels for b in bursts]


def _body(bursts: list[Burst], labelled: list[bool]) -> str:
    from ..app import esc, time_html

    done = sum(labelled)
    progress = f'<p class="muted">{done} of {len(bursts)} bursts labelled</p>'
    if not bursts:
        return progress + '<p class="muted">No bursts yet. Capture some on the Live page.</p>'
    pending = next((i for i, flag in enumerate(labelled) if not flag), None)
    if pending is None:
        return progress + '<p class="ok">All bursts are labelled.</p>'

    burst = bursts[pending]
    covers = len(consecutive_run([b.raw for b in bursts], labelled, pending))
    covers_text = f"also the next {covers} burst{'s' if covers != 1 else ''} with this reading" if covers \
        else "no further bursts with this reading yet"
    image = quote(burst.image, safe="/")
    return f"""\
{progress}
<p class="muted">{time_html(burst.time)} · {esc(burst.status)} · {esc(burst.detail)}</p>
<img src="api/image?path={image}" alt="frame 0" width="480">
<form method="post" action="labels" class="toolbar">
  <input type="hidden" name="image" value="{esc(burst.image)}">
  <label>Volume (m³) <input name="volume" value="{esc(burst.raw)}" size="12" required></label>
  <label>Flow (m³/h) <input name="flow" value="{esc(burst.flow or '')}" size="12"></label>
  <label><input type="checkbox" name="run" checked> label as run: {esc(covers_text)}</label>
  <button type="submit" class="primary">Confirm</button>
</form>
"""


async def handler(request: web.Request) -> web.Response:
    from ..app import context, render_page

    bursts, labelled = _state(context(request).data_dir)
    return render_page(request, "labels", "Labels", _body(bursts, labelled))


async def save_handler(request: web.Request) -> web.Response:
    from ..app import context

    data_dir = context(request).data_dir
    form = await request.post()
    image = str(form.get("image", ""))
    volume = str(form.get("volume", "")).strip()
    flow = str(form.get("flow", "")).strip() or None
    if not VOLUME.match(volume):
        raise web.HTTPBadRequest(text="the volume must look like 000170.861")
    if flow is not None and not FLOW.match(flow):
        raise web.HTTPBadRequest(text="the flow must look like 0.000")

    bursts, labelled = _state(data_dir)
    index = next((i for i, b in enumerate(bursts) if b.image == image), None)
    if index is None:
        raise web.HTTPNotFound()
    path = data_dir / LABELS_FILE
    save_label(path, image, volume, flow)
    if form.get("run") == "on":
        for j in consecutive_run([b.raw for b in bursts], labelled, index):
            save_label(path, bursts[j].image, volume, flow)
    raise web.HTTPFound("labels")
