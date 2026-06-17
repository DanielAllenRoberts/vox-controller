"""Central configuration. Kept as plain values for M0; can move to env/file later."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # Identity
    assistant_name: str = "Vox"

    # Wake word (M0 uses a stock openWakeWord model to prove the loop;
    # a custom "Hey Vox" model is trained as the follow-up).
    wake_word_model: str = "hey_jarvis"
    wake_word_spoken: str = "Hey Jarvis"  # what actually triggers the stock M0 model; → "Hey Vox" after training
    wake_threshold: float = 0.5

    # Audio capture — openWakeWord expects 16 kHz mono int16, 80 ms frames.
    sample_rate: int = 16_000
    frame_samples: int = 1280

    # Utterance capture (simple energy-based endpointing)
    max_utterance_seconds: float = 8.0
    silence_seconds: float = 0.8
    silence_rms: float = 300.0

    # Speech-to-text (faster-whisper). int8 runs well on Apple-Silicon CPU.
    whisper_model: str = "base.en"
    whisper_compute_type: str = "int8"


CONFIG = Config()
