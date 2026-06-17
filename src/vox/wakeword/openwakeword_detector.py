"""openWakeWord-backed detector. Open source, so we can adapt/contribute upstream."""

import os

import numpy as np
import openwakeword
from openwakeword.model import Model


class OpenWakeWordDetector:
    def __init__(self, model_name: str, threshold: float):
        # Idempotent: downloads the feature extractors + named model on first run.
        openwakeword.utils.download_models([model_name])
        self._model = Model(wakeword_models=[model_name], inference_framework="onnx")
        # openWakeWord keys predictions by basename-without-extension when given a
        # file path, or by the name itself for built-ins — match both.
        self._key = os.path.splitext(os.path.basename(model_name))[0]
        self._threshold = threshold

    def score(self, frame: np.ndarray) -> float:
        """Wake-word confidence for this frame, in [0, 1]."""
        return float(self._model.predict(frame).get(self._key, 0.0))

    def detect(self, frame: np.ndarray) -> bool:
        return self.score(frame) >= self._threshold

    def reset(self) -> None:
        reset = getattr(self._model, "reset", None)
        if callable(reset):
            reset()
