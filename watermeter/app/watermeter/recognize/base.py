"""The recognizer interface. Implementations: `tflite.py`, `onnx.py` (C4b, per the C4a preprocessing spec)."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence

from ..models import DigitResult, Image


class Recognizer(Protocol):
    def recognize(self, crops: Sequence[Image]) -> list[DigitResult]:
        """One DigitResult per crop, same order. A crop is one digit box cut from an aligned frame (RGB uint8,
        any size; the recognizer resizes). "Not a number" or confidence below the threshold → value None."""
        ...


def load_recognizer(model_path: Path, min_confidence: float) -> Recognizer:
    """Pick the implementation by file extension (`.tflite` or `.onnx`)."""
    suffix = Path(model_path).suffix.lower()
    if suffix == ".tflite":
        from .tflite import TfliteRecognizer
        return TfliteRecognizer(Path(model_path), min_confidence)
    if suffix == ".onnx":
        from .onnx import OnnxRecognizer
        return OnnxRecognizer(Path(model_path), min_confidence)
    raise ValueError(f"no recognizer for model file {model_path}")
