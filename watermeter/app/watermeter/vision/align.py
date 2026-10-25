"""Alignment on the two marks (plan §5.2, task C3, Sonnet).

Each mark is searched by template matching in a window around its reference position. The camera is fixed in the
cone, so the frame is only slightly shifted and rotated: two marks give a rigid correction (rotation + shift, no
scaling), one mark a shift only. Template matching is not rotation invariant, so it works for small rotations
(a few degrees), which is what a loose cone gives.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from ..models import Box, Image, Regions

SEARCH_PAD_MIN = 40  # pixels searched around the reference box on each side, at least (or the box's longer side)


@dataclass(frozen=True)
class AlignResult:
    image: Image | None             # the frame warped into reference coordinates; None if alignment failed
    scores: dict[str, float]        # template-match score per mark name
    shift: tuple[float, float]      # applied correction in pixels (dx, dy)
    rotation_deg: float


def _gray(image: Image) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image


def _find(gray: np.ndarray, template: np.ndarray, box: Box) -> tuple[float, tuple[float, float]]:
    """Best match of `template` near `box`: (score 0..1, centre of the match in image coordinates)."""
    pad = max(SEARCH_PAD_MIN, box.w, box.h)
    x0, y0 = max(box.x - pad, 0), max(box.y - pad, 0)
    x1, y1 = min(box.x + box.w + pad, gray.shape[1]), min(box.y + box.h + pad, gray.shape[0])
    window = gray[y0:y1, x0:x1]
    th, tw = template.shape[:2]
    if window.shape[0] < th or window.shape[1] < tw or th == 0 or tw == 0:
        return 0.0, (box.x + box.w / 2, box.y + box.h / 2)
    result = cv2.matchTemplate(window, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(result)
    if not math.isfinite(score):  # a flat window or template has no variance
        score = 0.0
    return float(max(score, 0.0)), (x0 + loc[0] + tw / 2, y0 + loc[1] + th / 2)


def align(image: Image, reference: Image, regions: Regions, min_score: float) -> AlignResult:
    """Find each mark of `regions` (cut from `reference`) in `image` by template matching near its reference
    position, estimate shift + rotation from the mark positions, and warp `image` into reference coordinates.
    Any mark below `min_score` → image None."""
    ref_h, ref_w = reference.shape[:2]
    if image.shape[:2] != (ref_h, ref_w):
        image = cv2.resize(image, (ref_w, ref_h), interpolation=cv2.INTER_LINEAR)
    if not regions.marks:
        return AlignResult(image, {}, (0.0, 0.0), 0.0)

    gray, ref_gray = _gray(image), _gray(reference)
    scores: dict[str, float] = {}
    found: list[tuple[float, float]] = []   # where each mark is in the frame
    expected: list[tuple[float, float]] = []  # where it is in the reference
    for mark in regions.marks:
        b = mark.box
        template = ref_gray[b.y:b.y + b.h, b.x:b.x + b.w]
        scores[mark.name], centre = _find(gray, template, b)
        found.append(centre)
        expected.append((b.x + b.w / 2, b.y + b.h / 2))
    if any(s < min_score for s in scores.values()):
        return AlignResult(None, scores, (0.0, 0.0), 0.0)

    # rigid transform frame → reference from the first two marks (rotation about their midpoint, then shift)
    (fx0, fy0), (ex0, ey0) = found[0], expected[0]
    angle = 0.0
    if len(found) >= 2:
        (fx1, fy1), (ex1, ey1) = found[1], expected[1]
        angle = math.atan2(ey1 - ey0, ex1 - ex0) - math.atan2(fy1 - fy0, fx1 - fx0)
        fmx, fmy, emx, emy = (fx0 + fx1) / 2, (fy0 + fy1) / 2, (ex0 + ex1) / 2, (ey0 + ey1) / 2
    else:
        fmx, fmy, emx, emy = fx0, fy0, ex0, ey0
    cos, sin = math.cos(angle), math.sin(angle)
    # p_ref = R (p_frame - f_mid) + e_mid
    matrix = np.array([[cos, -sin, emx - (cos * fmx - sin * fmy)],
                       [sin, cos, emy - (sin * fmx + cos * fmy)]], dtype=np.float64)
    warped = cv2.warpAffine(image, matrix, (ref_w, ref_h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return AlignResult(warped, scores, (emx - fmx, emy - fmy), math.degrees(angle))
