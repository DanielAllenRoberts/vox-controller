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
    # Exit the current mode → back to idle. Includes farewells ("bye Vox", "goodbye") so they ALWAYS
    # leave assistant mode, even when the model tagged its last reply [OPEN] (waiting for you) — a
    # farewell is caught here, before the chat path, so it never gets sent to the brain as a turn.
    sleep_phrases: tuple[str, ...] = ("stand down", "go to sleep", "go ahead and sleep", "going to sleep",
                                      "nevermind", "never mind", "cancel that", "forget it",
                                      "bye vox", "bye fox", "bye box", "goodbye", "good bye",
                                      "bye bye", "see you later", "okay bye", "ok bye", "alright bye")
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
    restart_phrases: tuple[str, ...] = (
        "restart vox", "restart fox", "restart box", "vox restart", "fox restart",
        "reboot vox", "reboot fox", "reboot box", "restart yourself",
    )

    # Enter DICTATION (speak-to-type at the cursor) from control mode.
    dictate_phrases: tuple[str, ...] = ("start typing", "start dictation", "begin typing", "dictate")
    # True: a long pause auto-exits dictation (can't get stuck). False: stay until "stop typing".
    dictation_exit_on_silence: bool = True

    # --- Dashboard (Vox Control Center) --- a local web UI served by an embedded FastAPI
    # bridge (vox.web.server), opened hands-free by an "open dashboard" wake phrase. Entirely
    # additive: if the web package is missing or errors, the voice daemon keeps running.
    dashboard_enabled: bool = True
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8765
    # Idle wake phrases (substring-matched) that open the dashboard in the browser.
    open_dashboard_phrases: tuple[str, ...] = (
        "open dashboard", "open the dashboard", "show dashboard",
        "launch dashboard", "open vox dashboard",
    )
    # Idle wake phrases that close the open dashboard window/tab. ("closed …" covers the very
    # common Whisper mishear of "close".)
    close_dashboard_phrases: tuple[str, ...] = (
        "close dashboard", "close the dashboard", "closed dashboard",
        "closed the dashboard", "hide dashboard", "close vox dashboard",
    )

    # Tee all output to a log file so sessions are reviewable (gitignored *.log). "" = off.
    log_file: str = "vox.log"

    # Debug: log every transcription (what Vox hears) in EVERY mode, including idle (which is
    # otherwise silent). Verbose — set False once a hearing/matching issue is diagnosed.
    debug: bool = True

    # --- Audio capture --- openWakeWord expects 16 kHz mono int16, 80 ms frames.
    sample_rate: int = 16_000
    frame_samples: int = 1280
    input_device: int | None = None  # None = system default; index from `uv run vox-diagnose`
    # Mic-stall self-heal: a healthy input stream delivers a frame every ~80 ms even in silence, so if
    # NO audio arrives for this long the device died (commonly an audio-device change — opening an app
    # that grabs audio, a Bluetooth/headphone switch). Vox first re-opens the stream in the background;
    # if audio still doesn't return within this window it does a clean self-restart (a fresh process
    # reliably re-acquires the mic) instead of wedging silently — the "freezes after a while" bug.
    mic_stall_restart_seconds: float = 12.0

    # --- Utterance capture (energy-based) ---
    speech_rms: float = 150.0            # speech-ONSET threshold (start capturing); calibrate via `vox-diagnose`
    # Release threshold for ENDING a turn, as a fraction of speech_rms (hysteresis / two-threshold VAD).
    # Once you've started talking, a frame only counts toward "silence" below this LOWER bar — so soft
    # passages, trailing words and breaths between words don't get mistaken for a pause and cut you off
    # mid-sentence (the "it interrupts me while I'm still speaking" report). Onset still needs the full
    # speech_rms so background never triggers. 1.0 = old single-threshold behaviour; lower = harder to
    # cut you off (but a noisy room can hold the turn open longer, up to max_utterance_seconds).
    end_rms_ratio: float = 0.5
    silence_seconds: float = 0.8         # trailing silence that ends a CONTROL command
    assistant_silence_seconds: float = 1.8  # pause allowed in ASSISTANT mode before it sends — long enough to think mid-sentence ("um…") without it cutting you off; lower (≈1.2) is snappier, higher (≈2.2) more patient. (Also used by dictation.)
    max_utterance_seconds: float = 15.0  # hard cap on one utterance — long enough not to cut off a full request/reminder
    # Idle (wake-detection) has a SHORTER cap than max_utterance_seconds: a wake phrase / "Vox, …"
    # one-shot lives at the START of the utterance, so decoding a 15s ambient monologue while idle
    # only burns CPU and spikes RAM for nothing. Capping idle capture bounds those spikes in a talky
    # room (the "doesn't idle well / freezes after a while" report) without affecting active modes.
    idle_max_utterance_seconds: float = 8.0
    listen_timeout_seconds: float = 6.0  # wake/dictation re-arm interval (control mode keeps listening)
    assistant_idle_timeout_seconds: float = 4.0   # assistant chat: drop to control/idle after this silence
    # Patient wait while the model tagged its reply [OPEN] (it expects you to respond) — a safety
    # cap so it waits a bit longer when it asked YOU something, without hanging forever.
    assistant_open_timeout_seconds: float = 8.0

    # Barge-in (idea #19): keep listening during a blocking LLM call so "go to sleep" / "stop" /
    # "quit" can cancel it (no echo worries — Vox isn't speaking then). False = wait it out.
    barge_in_enabled: bool = True
    barge_in_poll_seconds: float = 0.8   # interrupt-listener re-check interval during a call
    # Barge-in gate (loop 1): a mid-call interruption must be REAL speech, not a blip — sustained
    # ≥ interrupt_min_seconds of captured audio AND ≥ interrupt_min_words transcribed words.
    # Mirrors livekit min_interruption_duration/min_interruption_words + pipecat MinWords strategy.
    # Targets O7 (ambient/speaker audio falsely interrupting) and O8 (flaky barge-in).
    interrupt_min_words: int = 1         # ≥ this many transcribed words before a barge-in counts
    interrupt_min_seconds: float = 0.4   # captured audio must be at least this long to count
    # Only arm the interrupt-listener for SLOW calls (big-brain / vision / compose). Fast
    # small-brain/deterministic calls finish before the poll ever fires — arming barge-in there
    # just wastes a capture window and risks a spurious cancel (part of O8). True = slow-only.
    interrupt_slow_calls_only: bool = True
    preroll_frames: int = 3              # ~240 ms kept before onset so word attacks ("stand…") aren't clipped

    # Semantic turn-detection (voice-upgrade loop 4): how the END of an utterance is decided.
    #   "vad"        = DEFAULT — end on a fixed `silence_seconds` trailing pause (today's behavior,
    #                  byte-for-byte unchanged). Nothing new is loaded.
    #   "smart_turn" = run the local pipecat-ai/smart-turn-v3 ONNX model (Whisper-Tiny encoder +
    #                  linear head, ~8M, BSD-2) on the recent audio when a short pause is detected:
    #                  if it judges the turn COMPLETE → end now (snappy); if INCOMPLETE → keep
    #                  listening up to `max_endpointing_delay` (patient, won't cut you off mid-thought).
    # LAZY + GUARDED: the model is loaded only when turn_detection=="smart_turn", and ANY failure
    # (missing huggingface_hub, download/model/inference error) falls back to the fixed-silence path,
    # so the daemon always runs. Model (~8MB) downloads once to ~/.cache/vox/smart-turn/.
    turn_detection: str = "vad"
    min_endpointing_delay: float = 0.6   # pause (s) before smart-turn is consulted
    max_endpointing_delay: float = 3.0   # hard cap (s): end the turn even if smart-turn keeps saying INCOMPLETE
    # How confident smart-turn must be you're DONE before ending the turn (sigmoid prob in [0,1]).
    # NOTE: the smart-turn model is poorly discriminative on some setups (scores ~0.73 even on a
    # pause), so a HIGH threshold makes it never end early and wait out max_endpointing_delay every
    # turn (slow), while a LOW threshold ends on any pause (cuts you off). If smart_turn is unreliable
    # for you, prefer turn_detection="vad" (fixed silence) — predictable and fast. Default is a middle.
    smart_turn_threshold: float = 0.7

    # Acoustic echo cancellation (voice-upgrade loop 5 / R7): how the mic is captured.
    #   false = DEFAULT — capture via the sounddevice/PortAudio MicStream (today's behavior,
    #           byte-for-byte unchanged). Nothing native is loaded.
    #   true  = capture via the native macOS VoiceProcessingIO path (AVAudioEngine with
    #           setVoiceProcessingEnabled(True) on the input node). The system applies AEC + AGC +
    #           noise suppression referencing the speaker output, so Vox stops hearing its own TTS /
    #           ambient speaker audio (the real fix for O1 talk-over-on-speakers and O7).
    # LAZY + GUARDED: PyObjC/AVFoundation is imported only when audio_aec is true, and ANY failure
    # (missing pyobjc, mic permission denied, engine/tap/convert error) falls back to the sounddevice
    # MicStream with a logged warning — so the daemon always keeps listening. The native path can only
    # be quality-validated with a live mic + speakers (see docs/plan/VOICE_UPGRADE.md, Loop 5).
    audio_aec: bool = False

    # --- Speech-to-text (faster-whisper). int8 runs well on Apple-Silicon CPU. ---
    whisper_model: str = "small.en"   # more accurate for accents than base.en (~250MB 1-time download, ~2-3x slower STT but still <1s). Revert to "base.en" for max speed.
    whisper_compute_type: str = "int8"
    # Cap how many CPU threads CTranslate2 uses per transcription. Left at 0 (its default), it grabs
    # ~all physical cores, so back-to-back idle transcriptions in a talky room can saturate the whole
    # machine and make it beachball ("freezes after a while"). A modest cap leaves cores free for the
    # rest of the system — STT stays well under a second — so the Mac stays responsive while Vox listens.
    whisper_cpu_threads: int = 4
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
    small_brain_provider: str = "openai"       # DeepSeek via its OpenAI-compatible API (trying it as the small brain)
    small_brain_model: str = "deepseek-v4-flash"   # DeepSeek's fast tier (the old "deepseek-chat" now aliases here). Haiku: provider="anthropic", model="claude-haiku-4-5-20251001"
    big_brain_provider: str = "claude_sdk"     # big/vision stays on the Claude subscription (no per-token cost)
    big_brain_model: str = "claude-opus-4-8"
    escalate_to_big_brain: bool = True   # let the small brain defer complex turns to the big brain

    # Personality (idea #22): injected into the chat prompt to set Vox's tone. "" = default.
    # e.g. "witty and concise", "warm and encouraging", "a dry, deadpan British butler".
    personality: str = ""

    llm_base_url: str = "https://api.deepseek.com"  # openai-compatible providers (DeepSeek, Ollama, LM Studio); "" for none
    llm_api_key_env: str = "DEEPSEEK_API_KEY"   # env var holding the API key for the "openai" provider (DeepSeek etc.)
    anthropic_key_env: str = "ANTHROPIC_API_KEY"  # the "anthropic" provider's OWN key env — separate from llm_api_key_env so a DeepSeek (openai) brain + a Claude/Haiku (anthropic) brain can run at once

    # Local AI — a self-hosted OpenAI-compatible /v1 endpoint (LM Studio / Ollama / vLLM, e.g. a home
    # GPU box over a Cloudflare tunnel). Point ANY brain at it by setting that brain's provider to
    # "local_ai" (Settings dashboard or config) — it uses local_ai_model and reads the URL + key from
    # .env by the var NAMES below (kept OUT of this public repo). Cheap, private, your own hardware.
    local_ai_base_url_env: str = "LOCAL_AI1_URL"   # .env var holding the base URL (…/v1)
    local_ai_key_env: str = "LOCAL_AI1"            # .env var holding the API key
    local_ai_model: str = "google/gemma-4-e4b"     # model id the local server exposes
    llm_max_tokens: int = 800   # headroom for composing text ("write me…"); chat stays short via the prompt

    # LLM-as-executor (idea #12): on an uncertain command, the small brain runs Vox's own
    # actions instead of just explaining. Provider-agnostic — works on the subscription/SDK and
    # local LLMs, no API key beyond whatever the small brain already uses. False = just chat.
    llm_executor_enabled: bool = True

    # Escalation policy (idea #23): when control mode can't handle an utterance with its
    # deterministic parser, how does it decide whether to hand it to the brain?
    #   "auto"     = always escalate (current default; the 1-word/filler noise gate still applies).
    #   "keywords" = escalate ONLY when the utterance contains an escalation keyword below; otherwise
    #                ignore it. Strong mitigation for ambient audio tripping the LLM (issues.md O7) —
    #                you opt in by phrasing ("Vox, write me…", "make this pretty", "I need help with…").
    # A pending clarification (the brain asked YOU something) always escalates, keyword or not.
    escalation_mode: str = "auto"
    # Substring-matched (lowercased) when escalation_mode == "keywords". Grouped by what they reach:
    escalation_keywords: tuple[str, ...] = (
        "vox",                                                          # explicitly addressing Vox
        "write", "compose", "draft",                                   # compose text at the cursor
        "rewrite", "make this", "make it", "fix this", "fix the", "clean this",  # rewrite a selection
        "summarize", "summarise", "explain", "what does this", "what's on", "read this", "look at",  # screen vision
        "i need help", "help me", "learn",                             # general help / direct ask
    )

    # Screen vision (idea #18): the brain can screenshot and "see" the screen when asked
    # ("what does this say?"). Sends ONE downscaled frame to the cloud brain — set False to disable.
    # Needs Screen Recording permission (System Settings → Privacy & Security → Screen Recording).
    screen_vision_enabled: bool = True
    # How the screen is "seen": "auto" = AX tree first, screenshot fallback; "axtree" = tree only
    # (token-light text, no image); "screenshot" = image only (today's behavior). Master toggle above.
    screen_vision_mode: str = "auto"

    # --- Voice output (TTS) --- macOS `say`: local, instant, no model download. Swap for a
    # neural local TTS (Piper) later in tts.py. Premium/Siri voices install via System Settings →
    # Accessibility → Spoken Content → System Voice → Manage Voices.
    tts_enabled: bool = True
    tts_voice: str = "Daniel"  # British (en_GB). "" = system default. Premium voices sound best (System Settings)
    tts_rate: int = 0      # words per minute; 0 = the voice's default

    # TTS engine (voice-upgrade loop 2): "say" (default — macOS, zero-install, unchanged) |
    # "kokoro" (local neural ONNX, opt-in). Kokoro lazy-loads: nothing is imported/downloaded
    # unless tts_engine=="kokoro", and ANY Kokoro failure (missing package, model download,
    # synth, playback) silently falls back to the `say` path — so the daemon is never at risk.
    # Model + voices (~353MB) auto-download to ~/.cache/vox/kokoro/ on first kokoro use.
    tts_engine: str = "say"
    kokoro_voice: str = "af_heart"  # Kokoro voice id (e.g. af_heart, af_bella, am_michael, bf_emma). See voices list.
    kokoro_speed: float = 1.0       # 0.5–2.0; 1.0 = natural pace

    # Interruptible speaking (voice-upgrade loop 3): keep listening WHILE Vox speaks a reply, and
    # if a captured utterance passes the loop-1 interrupt gate, cut the voice (tts.stop_speaking())
    # and handle that new utterance as a cancel (stop/sleep) or the next turn. Only takes effect
    # when tts_engine=="kokoro" (the `say`/afplay path can't be flushed mid-utterance); OFF leaves
    # the speak path byte-for-byte unchanged (blocking speak + mic.flush after).
    # IMPORTANT: Vox has NO echo cancellation yet (loop 5 / AEC). With this ON, the mic hears the
    # TTS on SPEAKERS and will interrupt itself — so talk-over only works cleanly on HEADPHONES.
    # Stays OFF by default until AEC (VoiceProcessingIO) lands.
    tts_interruptible: bool = False

    # vox-speak MCP voice (idea #34) — the voice the IDE assistant uses to give you an audible
    # heads-up via the mcp/vox_speak_server, kept SEPARATE from the system voice above so the two
    # sound different and you can tell who's talking. Settable from the dashboard (Settings → MCP
    # voice) or env in the MCP server config. mcp_tts_engine "system" = follow tts_engine above;
    # "say"/"kokoro" pins it. Defaults differ from the system voice on purpose.
    mcp_tts_engine: str = "system"        # "system" (follow tts_engine) | "say" | "kokoro"
    mcp_tts_voice: str = "Samantha"       # macOS `say` voice for the MCP (≠ system "Daniel")
    mcp_kokoro_voice: str = "af_bella"    # Kokoro voice for the MCP when on the kokoro engine (≠ system "af_heart")
    # A short chime played just BEFORE the MCP speaks, so an IDE heads-up doesn't come out of
    # nowhere (the most-used MCP flow: "tell me out loud when you're done"). "" disables it.
    mcp_speak_cue: str = "/System/Library/Sounds/Tink.aiff"

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
    sound_thinking: str = "/System/Library/Sounds/Submarine.aiff"    # escalating to the LLM (it may take a moment)
    sound_dashboard_open: str = "/System/Library/Sounds/Blow.aiff"   # opened the dashboard
    sound_dashboard_close: str = "/System/Library/Sounds/Purr.aiff"  # closed the dashboard
    sound_reminder: str = "/System/Library/Sounds/Glass.aiff"        # a reminder fired (soft chime before the spoken line)
    sound_timer: str = "/System/Library/Sounds/Funk.aiff"            # a timer's up (played twice; sound-only by default)
    sound_alarm: str = "/System/Library/Sounds/Sosumi.aiff"          # an alarm fired — repeated a few times so it's hard to miss
    sound_alarm_repeat: int = 4                                      # how many times the alarm sound plays in a row

    # --- Scheduler (idea #16) --- Vox OWNS timers / alarms / reminders so the dashboard can show
    # and cancel them all in one place. A background thread (vox.scheduler) fires due jobs per the
    # per-kind output policy (reminder→spoken+sound, timer→sound, alarm→both). Jobs persist to
    # data/reminders.json (gitignored) and survive a restart. Entirely additive + guarded: a
    # scheduler failure can never take down the voice daemon.
    scheduler_enabled: bool = True          # run the background scheduler thread on startup
    scheduler_poll_seconds: float = 5.0     # how often the thread wakes to fire due jobs
    # OPTIONAL: also add a reminder to Apple Reminders (AppleScript-scriptable + iCloud-synced) so it
    # ALSO goes off on your phone. Default OFF — turn on to mirror. (Clock isn't used: it's neither
    # scriptable nor phone-synced.) Guarded: a mirror failure never blocks the local job.
    apple_reminders_mirror: bool = False


CONFIG = Config()
