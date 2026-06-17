"""openWakeWord-backed detector. Open source, so we can adapt/contribute upstream.

Loads one or more phrase models (built-in names or .onnx paths) and scores them
all per frame; `fired()` reports which phrase, if any, crossed the threshold.
"""

import os

import numpy as np
import openwakeword
from openwakeword.model import Model


class OpenWakeWordDetector:
    def __init__(self, models: list[str], threshold: float):
        # Map each identifier to openWakeWord's predict-dict key (basename without
        # extension) BEFORE constructing Model — Model() mutates the list it is given
        # (resolving names to versioned file paths), which would corrupt our keys.
        self._keys = {m: os.path.splitext(os.path.basename(m))[0] for m in models}
        for m in models:
            openwakeword.utils.download_models([m])  # idempotent; no-op for custom paths
        self._model = Model(wakeword_models=list(models), inference_framework="onnx")
        self._threshold = threshold

    def scores(self, frame: np.ndarray) -> dict[str, float]:
        preds = self._model.predict(frame)
        return {m: float(preds.get(k, 0.0)) for m, k in self._keys.items()}

    def fired(self, frame: np.ndarray) -> str | None:
        scores = self.scores(frame)
        if not scores:
            return None
        best = max(scores, key=scores.get)
        return best if scores[best] >= self._threshold else None

    def reset(self) -> None:
        reset = getattr(self._model, "reset", None)
        if callable(reset):
            reset()
