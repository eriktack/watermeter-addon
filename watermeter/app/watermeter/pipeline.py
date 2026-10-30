"""From a capture burst to a validator input (plan §4.3, task C6)."""
from __future__ import annotations

from typing import Sequence

from .models import DigitResult, Frame, Image, LineReading, RawReading, Regions, ValidatorInput
from .recognize.base import Recognizer
from .recognize.vote import vote_line
from .vision.align import align
from .vision.images import crop, decode_jpeg, enhance_contrast


def _recognize(recognizer: Recognizer, crops: list[Image], enhance: bool = False) -> list[DigitResult]:
    """Recognize the non-empty crops (with `enhance_contrast` first if `enhance`); a box outside the image (empty
    crop) is an unknown digit."""
    empty = [getattr(c, "size", None) == 0 for c in crops]
    filled = [enhance_contrast(c) if enhance else c for c, e in zip(crops, empty) if not e]
    results = iter(recognizer.recognize(filled) if filled else [])
    return [DigitResult(None, 0.0) if e else next(results) for e in empty]


def read_burst(frames: Sequence[Frame], reference: Image, regions: Regions, recognizer: Recognizer,
               min_mark_score: float, enhance: bool = False) -> RawReading:
    """Per frame: decode → align → crop the volume (and flow) boxes → recognize. Frames that fail alignment are
    dropped. Then vote per line over the remaining frames (`vote_line`). If no frame aligned: a RawReading with
    aligned=False and the volume line all unknown. `captured_at` = the first frame's time."""
    if not frames:
        raise ValueError("read_burst needs at least one frame")
    volume_boxes = list(regions.volume.digits)
    flow_boxes = list(regions.flow.digits) if regions.flow is not None else []

    volume_votes: list[list[DigitResult]] = []
    flow_votes: list[list[DigitResult]] = []
    for frame in frames:
        try:
            image = decode_jpeg(frame.jpeg)
        except ValueError:
            continue  # a broken frame counts as one that did not align
        aligned = align(image, reference, regions, min_mark_score).image
        if aligned is None:
            continue
        volume_votes.append(_recognize(recognizer, crop(aligned, volume_boxes), enhance))
        if flow_boxes:
            flow_votes.append(_recognize(recognizer, crop(aligned, flow_boxes), enhance))

    captured_at = frames[0].captured_at
    if not volume_votes:
        unknown = LineReading(tuple(DigitResult(None, 0.0) for _ in volume_boxes), regions.volume.decimals)
        return RawReading(captured_at, unknown, None, aligned=False)

    volume = vote_line(volume_votes, regions.volume.decimals)
    flow = vote_line(flow_votes, regions.flow.decimals) if flow_votes else None
    return RawReading(captured_at, volume, flow, aligned=True)


def to_validator_input(raw: RawReading) -> ValidatorInput:
    """RawReading → ValidatorInput: time, volume litres/text/confidence, flow l/h (None if no flow line or
    unreadable), aligned."""
    return ValidatorInput(
        time=raw.captured_at,
        volume_l=raw.volume.litres,
        volume_text=raw.volume.text,
        confidence=raw.volume.confidence,
        flow_lph=raw.flow.litres if raw.flow is not None else None,
        aligned=raw.aligned,
    )
