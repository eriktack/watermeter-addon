"""TFLite recognizer (haverland models). Task C4b; preprocessing exactly as specified in the C4b card (from C4a)."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

import cv2
import numpy as np
from ai_edge_litert.interpreter import Interpreter

from ..models import DigitResult, Image

NOT_A_NUMBER_CLASS = 10  # haverland dig-class11: classes 0-9 are digits, 10 is "not a number"


def preprocess(crop: Image) -> np.ndarray:
    """Crop → model input tensor `[1, 32, 20, 3]` float32, NHWC, raw 0..255 (no normalisation)."""
    resized = cv2.resize(crop, (20, 32), interpolation=cv2.INTER_LINEAR)
    return resized.astype(np.float32)[np.newaxis, ...]


class TfliteRecognizer:
    def __init__(self, model_path: Path, min_confidence: float) -> None:
        self._interpreter = Interpreter(model_path=str(model_path))
        self._interpreter.allocate_tensors()
        self._input = self._interpreter.get_input_details()[0]["index"]
        self._output = self._interpreter.get_output_details()[0]["index"]
        self._min_confidence = min_confidence

    def recognize(self, crops: Sequence[Image]) -> list[DigitResult]:
        results = []
        for crop in crops:
            self._interpreter.set_tensor(self._input, preprocess(crop))
            self._interpreter.invoke()
            probs = self._interpreter.get_tensor(self._output)[0]  # already softmax
            top = int(np.argmax(probs))
            confidence = float(probs[top])
            if top == NOT_A_NUMBER_CLASS or confidence < self._min_confidence:
                results.append(DigitResult(None, confidence))
            else:
                results.append(DigitResult(top, confidence))
        return results
