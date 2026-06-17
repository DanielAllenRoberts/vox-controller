"""Central configuration. Plain values for now; can move to env/file later."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # Identity
    assistant_name: str = "Vox"

    # --- Activation phrases ---
    # Placeholder built-in openWakeWord models until custom "Vox" phrases are
    # trained (then point these at the trained .onnx paths). The daemon listens
    # for all of them at once.
    control_wake: str = "hey_jarvis"      # enter CONTROL mode  (placeholder for "Vox, take control")
    control_spoken: str = "Hey Jarvis"
    assistant_wake: str = "hey_mycroft"   # enter ASSISTANT mode (placeholder for "Hey Vox")
    assistant_spoken: str = "Hey Mycroft"
    wake_threshold: float = 0.5

    # Wake backend: "whisper" = no training, matches phrases in transcribed speech
    # (any phrase, incl. custom names); "openwakeword" = trained per-phrase models.
    wake_backend: str = "whisper"
    # Whisper-wake activation phrases (substring-matched in the lowercased transcript).
    # "Vox" is uncommon, so include phonetic variants Whisper may produce.
    control_phrases: tuple[str, ...] = ("take control", "control mode", "start control")
    assistant_phrases: tuple[str, ...] = ("hey vox", "hey vaux", "hey vocks", "a vox", "hey fox", "hey box")

    # Sleep / deactivate — matched in transcribed text (no model needed; we're
    # already transcribing once a mode is active).
    sleep_phrases: tuple[str, ...] = ("stand down", "go to sleep")
    sleep_spoken: str = "stand down"

    # --- Audio capture --- openWakeWord expects 16 kHz mono int16, 80 ms frames.
    sample_rate: int = 16_000
    frame_samples: int = 1280
    input_device: int | None = None  # None = system default; index from `uv run vox-diagnose`

    # --- Utterance capture (energy-based) ---
    speech_rms: float = 150.0            # speech-onset threshold; calibrate via `vox-diagnose`
    silence_seconds: float = 0.8         # trailing silence that ends an utterance
    max_utterance_seconds: float = 8.0
    listen_timeout_seconds: float = 6.0  # assistant mode: give up waiting (control mode keeps listening)
    preroll_frames: int = 3              # ~240 ms kept before onset so word attacks ("stand…") aren't clipped

    # --- Speech-to-text (faster-whisper). int8 runs well on Apple-Silicon CPU. ---
    whisper_model: str = "base.en"
    whisper_compute_type: str = "int8"


CONFIG = Config()
