"""Regions page (task C2): draw the alignment marks and the digit boxes on a reference image, preview the crops.

Page `regions`, API (all paths relative, for ingress):
- `GET api/regions` → the saved regions as JSON (`null` if none) plus the reference size.
- `POST api/regions` (JSON) → validate and save; 400 with `{"error": ...}` for invalid regions.
- `GET api/reference.jpg`; `POST api/reference` (body = JPEG) sets it; `POST api/reference/latest` copies the latest
  captured frame. Saved boxes follow a new reference of the same size: the new image is aligned on the old one and
  every box is moved by that (`move_regions`); the answer's `message` says what happened.
- `GET api/crop/<line>/<index>.png?source=reference|latest` → one digit crop (`line` = `volume` or `flow`); `latest`
  aligns the newest captured frame first.
- `GET api/alignment` → how well the newest frame aligns (scores, shift, rotation).
"""
from __future__ import annotations

import json
from dataclasses import replace

import cv2
from aiohttp import web

from ...storage import ImageStore
from ...vision.align import align
from ...vision.images import crop, decode_jpeg, enhance_contrast, rotate, with_margin
from ...vision.regions_io import (load_reference_bytes, load_regions, move_regions, regions_from_dict,
                                  regions_to_dict, save_reference, save_regions)

BODY = """\
<div class="regions">
  <div class="toolbar">
    <button id="use-latest" type="button">Use the latest camera image as reference</button>
    <label class="button">Upload an image <input id="upload" type="file" accept="image/jpeg" hidden></label>
  </div>
  <p id="no-reference" class="muted" hidden>No reference image yet. Capture one first (Live page), then use it here.</p>
  <div id="editor" hidden>
    <div class="toolbar">
      <label>Draw <select id="mode">
        <option value="mark0">alignment mark 1</option>
        <option value="mark1">alignment mark 2</option>
        <option value="volume.whole" selected>volume: whole digits</option>
        <option value="volume.decimals">volume: decimals</option>
        <option value="flow.whole">flow: whole digits</option>
        <option value="flow.decimals">flow: decimals</option>
      </select></label>
      <label>digits <input id="count" type="number" min="1" max="12" value="6"></label>
      <label>rotation ° <input id="rotation" type="number" min="-45" max="45" step="0.1" value="0.0" style="width:5em"></label>
      <button id="remove-group" type="button">Remove this group</button>
    </div>
    <p class="muted">Drag a rectangle around a group of digits: it is split into equal digit boxes. In the table, width is
    one digit's width and gap the space between digits; y is counted from the image's bottom edge to the box's bottom
    edge, so a new height keeps the bottom where it is. Hold an arrow in a field to move live. Turn the image
    (counterclockwise is positive) until the digits are level; every camera image is turned the same way. Marks are
    distinctive fixed spots (a logo, printed text), used to align every image.</p>
    <canvas id="canvas"></canvas>
    <table id="boxes"></table>
    <div class="toolbar">
      <button id="save" type="button" class="primary">Save regions</button>
      <span id="status" class="muted"></span>
    </div>
    <h2>Crop preview</h2>
    <div class="toolbar"><label>Source <select id="source">
      <option value="reference">reference image</option><option value="latest">latest camera image (aligned)</option>
    </select></label> <span id="alignment" class="muted"></span></div>
    <div id="crops"></div>
  </div>
</div>
"""


def _data_dir(request: web.Request):
    from ..app import context

    return context(request).data_dir


def _jpeg_size(jpeg: bytes) -> tuple[int, int]:
    h, w = decode_jpeg(jpeg).shape[:2]
    return w, h


def _json_error(message: str, status: int = 400) -> web.Response:
    return web.json_response({"error": message}, status=status)


async def handler(request: web.Request) -> web.Response:
    from ..app import render_page

    return render_page(request, "regions", "Regions", BODY, script="regions.js")


async def api_get_regions(request: web.Request) -> web.Response:
    data_dir = _data_dir(request)
    regions = load_regions(data_dir)
    reference = load_reference_bytes(data_dir)
    width, height = _jpeg_size(reference) if reference else (0, 0)
    return web.json_response({"regions": regions_to_dict(regions) if regions else None,
                              "reference": {"width": width, "height": height} if reference else None})


async def api_save_regions(request: web.Request) -> web.Response:
    data_dir = _data_dir(request)
    try:
        regions = regions_from_dict(await request.json())
    except (ValueError, json.JSONDecodeError) as e:
        return _json_error(str(e))
    reference = load_reference_bytes(data_dir)
    if reference is None:
        return _json_error("set a reference image first")
    if (regions.reference_width, regions.reference_height) != _jpeg_size(reference):
        return _json_error("the regions were drawn on another reference image: reload the page")
    save_regions(data_dir, regions)
    return web.json_response({"ok": True})


async def api_reference(request: web.Request) -> web.Response:
    jpeg = load_reference_bytes(_data_dir(request))
    if jpeg is None:
        raise web.HTTPNotFound()
    return web.Response(body=jpeg, content_type="image/jpeg", headers={"Cache-Control": "no-cache"})


async def api_set_reference(request: web.Request) -> web.Response:
    jpeg = await request.read()
    try:
        _jpeg_size(jpeg)
    except ValueError:
        return _json_error("that is not a JPEG image")
    message = _set_reference(_data_dir(request), jpeg, context_min_score(request))
    return web.json_response({"ok": True, "message": message})


async def api_reference_from_latest(request: web.Request) -> web.Response:
    data_dir = _data_dir(request)
    latest = ImageStore(data_dir).latest()
    if latest is None:
        return _json_error("no camera image yet", 404)
    message = _set_reference(data_dir, (data_dir / latest).read_bytes(), context_min_score(request))
    return web.json_response({"ok": True, "message": message})


def _follow(new, old, regions, min_score: float):
    """`regions` moved onto the new reference image `new`: its tilt against `old` goes into the rotation offset (so
    the boxes stay level with the digits), then the boxes are shifted by where the marks are found."""
    tilt = align(new, old, regions, min_score)
    if tilt.image is None:
        raise ValueError("the alignment marks were not found in it")
    rotation = round(regions.rotation_deg - tilt.rotation_deg, 1)
    level = replace(regions, rotation_deg=0.0)  # both images are turned already
    found = align(rotate(new, rotation), rotate(old, regions.rotation_deg), level, min_score)
    if found.image is None:
        raise ValueError("the alignment marks were not found in it")
    return move_regions(regions, round(-found.shift[0]), round(-found.shift[1]), rotation)


def _set_reference(data_dir, jpeg: bytes, min_score: float) -> str:
    """Save `jpeg` as the reference; saved boxes follow it when it has the old reference's size. Returns a message."""
    regions, old = load_regions(data_dir), load_reference_bytes(data_dir)
    message = "Reference updated."
    if regions is not None and old is not None:
        if _jpeg_size(jpeg) != _jpeg_size(old):
            message = "Reference updated. It has another size than the old one: draw the boxes again."
        else:
            try:
                moved = _follow(decode_jpeg(jpeg), decode_jpeg(old), regions, min_score)
                save_regions(data_dir, moved)
                message = (f"Reference updated; the boxes moved with the image "
                           f"({moved.volume.digits[0].x - regions.volume.digits[0].x:+d}, "
                           f"{moved.volume.digits[0].y - regions.volume.digits[0].y:+d} px, rotation "
                           f"{regions.rotation_deg:.1f}° → {moved.rotation_deg:.1f}°). Check them in the crop preview.")
            except ValueError as e:
                message = f"Reference updated, but the boxes could not follow it ({e}): check and move them."
    save_reference(data_dir, jpeg)
    return message


def _latest_frame(data_dir):
    latest = ImageStore(data_dir).latest()
    return decode_jpeg((data_dir / latest).read_bytes()) if latest else None


async def api_crop(request: web.Request) -> web.Response:
    data_dir = _data_dir(request)
    regions, reference = load_regions(data_dir), load_reference_bytes(data_dir)
    if regions is None or reference is None:
        raise web.HTTPNotFound()
    line = {"volume": regions.volume, "flow": regions.flow}.get(request.match_info["line"])
    try:
        index = int(request.match_info["index"])
        box = line.digits[index]
    except (ValueError, IndexError, AttributeError):
        raise web.HTTPNotFound()
    image = rotate(decode_jpeg(reference), regions.rotation_deg)
    if request.query.get("source") == "latest":
        frame = _latest_frame(data_dir)
        if frame is None:
            raise web.HTTPNotFound()
        image = align(frame, decode_jpeg(reference), regions, context_min_score(request)).image
        if image is None:
            raise web.HTTPNotFound()  # alignment failed: the page shows the scores from api/alignment
    (piece,) = crop(image, with_margin([box]))   # exactly what the model gets
    if context_settings(request).recognition.enhance_contrast:   # as the model gets it
        piece = enhance_contrast(piece)
    ok, png = cv2.imencode(".png", cv2.cvtColor(piece, cv2.COLOR_RGB2BGR))
    return web.Response(body=png.tobytes(), content_type="image/png", headers={"Cache-Control": "no-cache"})


def context_settings(request: web.Request):
    from ..app import context

    return context(request).settings


def context_min_score(request: web.Request) -> float:
    return context_settings(request).recognition.min_mark_score


async def api_alignment(request: web.Request) -> web.Response:
    data_dir = _data_dir(request)
    regions, reference = load_regions(data_dir), load_reference_bytes(data_dir)
    frame = _latest_frame(data_dir)
    if regions is None or reference is None or frame is None:
        return web.json_response({"available": False})
    result = align(frame, decode_jpeg(reference), regions, context_min_score(request))
    return web.json_response({"available": True, "ok": result.image is not None, "scores": result.scores,
                              "shift": list(result.shift), "rotation_deg": result.rotation_deg,
                              "min_score": context_min_score(request)})
