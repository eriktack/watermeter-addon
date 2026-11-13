"""Decoding and cropping (task C3 together with alignment; OpenCV)."""
from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np

from ..models import Box, Image


def decode_jpeg(jpeg: bytes) -> Image:
    """JPEG bytes → RGB uint8 HxWx3. Raises ValueError for data that is not a decodable image."""
    if not jpeg:
        raise ValueError("empty image data")
    bgr = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("data is not a decodable image")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def rotate(image: Image, degrees: float) -> Image:
    """Turn the image about its centre (counterclockwise for positive degrees), same size, edges repeated."""
    if not degrees:
        return image
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), degrees, 1.0)
    return cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def enhance_contrast(image: Image) -> Image:
    """Local contrast (CLAHE on the lightness) of a digit crop: the LCD's dark digits on a dark, unevenly lit
    background come out clearly (2026-10-30: lifted the haverland models from 2-3 to 7-9 of 9 digits on a real image)."""
    if image.size == 0:
        return image
    lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB)
    lab[..., 0] = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(2, 2)).apply(lab[..., 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)


DIGIT_MARGIN = 0.15  # each digit box is widened by this share of its size on every side before recognition


def with_margin(boxes: Sequence[Box]) -> list[Box]:
    """The boxes the digit model gets cropped: each with `DIGIT_MARGIN` around it. The haverland models are trained on
    digits with some space around them; on boxes drawn tight to the digit their answer flipped with a 3 px shift
    (2026-11-13: 79 of 1316 digit reads changed, a decimal 3 read as 9 or "not a number"). On 47 frames with known
    values: 39 right with 10 %, 47 with 15 % (and with every margin from 10 to 20 % around it)."""
    return [Box(b.x - round(b.w * DIGIT_MARGIN), b.y - round(b.h * DIGIT_MARGIN),
                b.w + 2 * round(b.w * DIGIT_MARGIN), b.h + 2 * round(b.h * DIGIT_MARGIN)) for b in boxes]


def crop(image: Image, boxes: Sequence[Box]) -> list[Image]:
    """Cut the boxes out of an image that is already in reference coordinates. Boxes are clipped to the image;
    a box fully outside gives an empty (0-size) array."""
    height, width = image.shape[:2]
    out = []
    for box in boxes:
        x0, y0 = max(box.x, 0), max(box.y, 0)
        x1, y1 = min(box.x + box.w, width), min(box.y + box.h, height)
        if x1 <= x0 or y1 <= y0:
            out.append(image[0:0, 0:0])
        else:
            out.append(image[y0:y1, x0:x1].copy())
    return out
