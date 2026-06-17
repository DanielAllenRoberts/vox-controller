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

    # Emergency stop — drop straight to idle from any mode (more forceful than "stand down").
    # Distinctive multi-word phrases so ambient speech can't trigger them.
    abort_phrases: tuple[str, ...] = ("terminate task", "emergency stop", "abort abort", "stop stop stop")

    # Quit the whole program by voice — keyed to "vox" so idle speech can't trigger it.
    quit_phrases: tuple[str, ...] = (
        "quit vox", "quit fox", "quit box", "quick vox", "quick fox", "quick box",
        "close vox", "close fox", "close box", "exit vox", "exit fox", "exit box",
        "shut down vox", "terminate vox", "terminate fox", "terminate box",
    )

    # Restart the running process (re-exec — picks up code changes) by voice.
    restart_phrases: tuple[str, ...] = ("restart vox", "reboot vox", "restart yourself")

    # Enter DICTATION (speak-to-type at the cursor) from control mode.
    dictate_phrases: tuple[str, ...] = ("start typing", "start dictation", "begin typing", "dictate")
    # True: a long pause auto-exits dictation (can't get stuck). False: stay until "stop typing".
    dictation_exit_on_silence: bool = True

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
    # Patient wait while the model tagged its reply [OPEN] (it expects you to respond). This is a
    # safety cap so Vox can't hang forever — the LLM decides when to wait, not a hand-tuned heuristic.
    assistant_open_timeout_seconds: float = 20.0
    preroll_frames: int = 3              # ~240 ms kept before onset so word attacks ("stand…") aren't clipped

    # --- Speech-to-text (faster-whisper). int8 runs well on Apple-Silicon CPU. ---
    whisper_model: str = "base.en"
    whisper_compute_type: str = "int8"
    # Bias CONTROL-mode recognition toward command vocabulary + app names so
    # "Cursor"/"Arc" win over phonetic neighbours ("Casa"). Tune freely.
    command_hotwords: str = (
        # Only uncommon proper nouns. Biasing command verbs — or "vox" — makes Whisper regurgitate
        # this list on noise; a "vox …" hallucination then falsely fires the idle one-shot, so "vox"
        # is OUT. "switch" stays (else mis-heard as "search"); it can't fire the one-shot (no "vox").
        "switch cursor arc safari chrome github youtube gmail spotify notion "
        "chatgpt linkedin trello amazon netflix calculator terminal finder slack figma"
    )

    # --- Brains (idea #17) --- Vox routes thinking to one of two configurable "brains":
    #   • small = fast/cheap; default for chat + command execution
    #   • big   = powerful; the small brain hands complex turns here (e.g. Opus on Claude Max)
    # Each is a provider + model. For claude_sdk/claude_cli the model runs on your Claude
    # subscription (no API key); for anthropic/openai it uses the key named by llm_api_key_env.
    # Providers: "claude_sdk" | "claude_cli" | "anthropic" | "openai".  Presets:
    #   Claude (sub)  : provider="claude_sdk", model="claude-haiku-4-5-20251001" / "claude-opus-4-8"
    #   Anthropic API : provider="anthropic",  model="claude-haiku-4-5-20251001", llm_api_key_env="ANTHROPIC_API_KEY"
    #   DeepSeek      : provider="openai", model="deepseek-chat", llm_base_url="https://api.deepseek.com", llm_api_key_env="DEEPSEEK_API_KEY"
    #   Local Ollama  : provider="openai", model="llama3.1",       llm_base_url="http://localhost:11434/v1", llm_api_key_env=<any dummy>
    #   Local LM Studio: provider="openai", model="<loaded model>", llm_base_url="http://localhost:1234/v1",  llm_api_key_env=<any dummy>
    small_brain_provider: str = "claude_sdk"
    small_brain_model: str = "claude-haiku-4-5-20251001"
    big_brain_provider: str = "claude_sdk"
    big_brain_model: str = "claude-opus-4-8"
    escalate_to_big_brain: bool = True   # let the small brain defer complex turns to the big brain

    llm_base_url: str = ""               # for openai-compatible providers (DeepSeek, Ollama, LM Studio)
    llm_api_key_env: str = "ANTHROPIC_API_KEY"  # env var holding the API key (openai/anthropic providers)
    llm_max_tokens: int = 800   # headroom for composing text ("write me…"); chat stays short via the prompt

    # LLM-as-executor (idea #12): on an uncertain command, the small brain runs Vox's own
    # actions instead of just explaining. Provider-agnostic — works on the subscription/SDK and
    # local LLMs, no API key beyond whatever the small brain already uses. False = just chat.
    llm_executor_enabled: bool = True

    # Screen vision (idea #18): the brain can screenshot and "see" the screen when asked
    # ("what does this say?"). Sends ONE downscaled frame to the cloud brain — set False to disable.
    # Needs Screen Recording permission (System Settings → Privacy & Security → Screen Recording).
    screen_vision_enabled: bool = True

    # --- Voice output (TTS) --- macOS `say`: local, instant, no model download. Swap for a
    # neural local TTS (Piper) later in tts.py. Premium/Siri voices install via System Settings →
    # Accessibility → Spoken Content → System Voice → Manage Voices.
    tts_enabled: bool = True
    tts_voice: str = ""    # macOS voice name (e.g. "Samantha", "Ava (Premium)"); "" = system default
    tts_rate: int = 0      # words per minute; 0 = the voice's default

    # Audio cues for mode transitions (macOS system sounds as placeholders — swap for
    # custom files later, e.g. made in Logic). Set "" to disable a cue.
    sound_control: str = "/System/Library/Sounds/Hero.aiff"
    sound_assistant: str = "/System/Library/Sounds/Glass.aiff"   # entered assistant mode (listening)
    sound_send: str = "/System/Library/Sounds/Pop.aiff"          # assistant prompt captured / sent to the AI
    sound_sleep: str = "/System/Library/Sounds/Bottle.aiff"      # back to idle (stand down)
    sound_dictate_start: str = "/System/Library/Sounds/Tink.aiff"    # started dictation (typing)
    sound_dictate_stop: str = "/System/Library/Sounds/Sosumi.aiff"   # stopped dictation
    sound_oneshot: str = "/System/Library/Sounds/Morse.aiff"         # one-shot command ("Vox, open Safari")
    sound_abort: str = "/System/Library/Sounds/Basso.aiff"           # emergency stop / abort


CONFIG = Config()
