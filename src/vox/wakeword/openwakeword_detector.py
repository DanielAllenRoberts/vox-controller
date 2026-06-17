"""openWakeWord-backed detector. Open source, so we can adapt/contribute upstream."""

import numpy as np
import openwakeword
from openwakeword.model import Model


class OpenWakeWordDetector:
    def __init__(self, model_name: str, threshold: float):
        # Idempotent: downloads the feature extractors + named model on first run.
        openwakeword.utils.download_models([model_name])
        self._model = Model(wakeword_models=[model_name], inference_framework="onnx")
        self._key = model_name
        self._threshold = threshold

    def detect(self, frame: np.ndarray) -> bool:
        scores = self._model.predict(frame)
        return scores.get(self._key, 0.0) >= self._threshold

    def reset(self) -> None:
        reset = getattr(self._model, "reset", None)
        if callable(reset):
            reset()
