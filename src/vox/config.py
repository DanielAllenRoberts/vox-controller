"""Central configuration. Plain values for now; can move to env/file later."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # Identity
    assistant_name: str = "Vox"

    # Preferred browser for opening URLs as a new tab in the existing window
    # (Arc / Google Chrome / Safari / Brave Browser / Microsoft Edge).
    browser: str = "Arc"

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

    # Quit the whole program by voice — keyed to "vox" so idle speech can't trigger it.
    quit_phrases: tuple[str, ...] = (
        "quit vox", "quit fox", "quit box", "quick vox", "quick fox", "quick box",
        "close vox", "close fox", "close box", "exit vox", "exit fox", "exit box",
        "shut down vox",
    )

    # Restart the running process (re-exec — picks up code changes) by voice.
    restart_phrases: tuple[str, ...] = ("restart vox", "reboot vox", "restart yourself")

    # Enter DICTATION (speak-to-type at the cursor) from control mode.
    dictate_phrases: tuple[str, ...] = ("start typing", "start dictation", "begin typing", "dictate")

    # Tee all output to a log file so sessions are reviewable (gitignored *.log). "" = off.
    log_file: str = "vox.log"

    # --- Audio capture --- openWakeWord expects 16 kHz mono int16, 80 ms frames.
    sample_rate: int = 16_000
    frame_samples: int = 1280
    input_device: int | None = None  # None = system default; index from `uv run vox-diagnose`

    # --- Utterance capture (energy-based) ---
    speech_rms: float = 150.0            # speech-onset threshold; calibrate via `vox-diagnose`
    silence_seconds: float = 0.8         # trailing silence that ends a CONTROL command
    assistant_silence_seconds: float = 1.2  # pause allowed in ASSISTANT mode before it sends
    max_utterance_seconds: float = 8.0
    listen_timeout_seconds: float = 6.0  # assistant mode: give up waiting (control mode keeps listening)
    preroll_frames: int = 3              # ~240 ms kept before onset so word attacks ("stand…") aren't clipped

    # --- Speech-to-text (faster-whisper). int8 runs well on Apple-Silicon CPU. ---
    whisper_model: str = "base.en"
    whisper_compute_type: str = "int8"
    # Bias CONTROL-mode recognition toward command vocabulary + app names so
    # "Cursor"/"Arc" win over phonetic neighbours ("Casa"). Tune freely.
    command_hotwords: str = (
        "open go to search switch stand down take control hey vox quit close exit shut down "
        "tab window next previous first last desktop space screen swipe new profile dictate "
        "cursor arc safari chrome github youtube gmail spotify notion chatgpt linkedin trello amazon netflix "
        "calculator terminal finder notes slack figma"
    )

    # --- Assistant (LLM) brain — provider-agnostic ---  key(s) go in .env. Presets:
    #   Anthropic : provider="anthropic", model="claude-haiku-4-5-20251001", key_env="ANTHROPIC_API_KEY"
    #   DeepSeek  : provider="openai", model="deepseek-chat", base_url="https://api.deepseek.com", key_env="DEEPSEEK_API_KEY"
    #   OpenAI    : provider="openai", model="gpt-4o-mini", key_env="OPENAI_API_KEY"
    #   Claude SDK: provider="claude_sdk"  (Claude Code via the Agent SDK; uses your subscription, no key)
    #   Claude CLI: provider="claude_cli"  (Claude Code via `claude -p`; uses your subscription, no key)
    llm_provider: str = "anthropic"      # "anthropic" | "openai" | "claude_sdk" | "claude_cli"
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_base_url: str = ""               # for openai-compatible providers (e.g. DeepSeek)
    llm_api_key_env: str = "ANTHROPIC_API_KEY"
    llm_max_tokens: int = 400

    # Audio cues for mode transitions (macOS system sounds as placeholders — swap for
    # custom files later, e.g. made in Logic). Set "" to disable a cue.
    sound_control: str = "/System/Library/Sounds/Hero.aiff"
    sound_assistant: str = "/System/Library/Sounds/Glass.aiff"   # entered assistant mode (listening)
    sound_send: str = "/System/Library/Sounds/Pop.aiff"          # assistant prompt captured / sent to the AI
    sound_sleep: str = "/System/Library/Sounds/Bottle.aiff"      # back to idle (stand down)
    sound_dictate_start: str = "/System/Library/Sounds/Tink.aiff"    # started dictation (typing)
    sound_dictate_stop: str = "/System/Library/Sounds/Sosumi.aiff"   # stopped dictation


CONFIG = Config()
