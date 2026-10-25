"""ONNX recognizer (nliaudat v16, for the benchmark). Task C4b; preprocessing per the C4b card (from C4a)."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

import cv2
import numpy as np
import onnxruntime as ort

from ..models import DigitResult, Image


def preprocess(crop: Image) -> np.ndarray:
    """Crop → model input tensor `[1, 3, 32, 20]` float32, NCHW, scaled to 0..1."""
    resized = cv2.resize(crop, (20, 32), interpolation=cv2.INTER_LINEAR)
    chw = np.transpose(resized, (2, 0, 1)).astype(np.float32) / 255.0
    return chw[np.newaxis, ...]


class OnnxRecognizer:
    def __init__(self, model_path: Path, min_confidence: float) -> None:
        self._session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self._input = self._session.get_inputs()[0].name
        self._min_confidence = min_confidence

    def recognize(self, crops: Sequence[Image]) -> list[DigitResult]:
        if not crops:
            return []
        batch = np.concatenate([preprocess(crop) for crop in crops], axis=0)
        probs_batch = self._session.run(None, {self._input: batch})[0]  # [N, 10], already softmax
        results = []
        for probs in probs_batch:
            top = int(np.argmax(probs))
            confidence = float(probs[top])
            if confidence < self._min_confidence:
                results.append(DigitResult(None, confidence))
            else:
                results.append(DigitResult(top, confidence))
        return results
