"""Wake-word backends. Both implement `listen(frames) -> label` ('control' | 'assistant').

- WhisperWakeBackend: VAD-gated transcription matched against phrases. No training,
  any phrase (incl. custom names); transcribes nearby speech, so a bit more compute.
- OpenWakeWordBackend: cheap always-on per-frame detection; needs trained models.

Pick via `config.wake_backend`. See docs/plan/modes.md.
"""

import re

from vox import runtime
from vox.audio import _setting, capture_utterance, voiced_ms
from vox.wakeword.openwakeword_detector import OpenWakeWordDetector


def normalize(text: str) -> str:
    """Lowercase + strip punctuation so phrase matching survives Whisper's commas/periods."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


def phrase_match(t: str, phrases) -> bool:
    """True if any phrase occurs in the already-normalized text `t`. Also matches when Whisper
    drops the inter-word space ("quit vox" heard as "quitvox") by comparing space-stripped too."""
    t2 = t.replace(" ", "")
    return any(p in t or p.replace(" ", "") in t2 for p in phrases)


# Words at least one of which appears in every idle wake phrase and "vox, …" one-shot. "vox" is
# kept with the spellings Vosk actually produces for it; the measured best set (see
# research/listening-and-stt-2026.md R2).
_WAKE_KEYWORDS = ("vox", "vaux", "vocks", "fox", "box", "control", "dashboard", "restart", "reboot",
                  "hey", "quit", "take", "exit")


class WhisperWakeBackend:
    def __init__(self, label_phrases, transcriber, cfg, prompt, out=None):
        self._label_phrases = label_phrases  # list of (label, (phrase, ...))
        self._transcriber = transcriber
        self._cfg = cfg
        self.prompt = prompt
        self._out = out  # for debug logging of idle transcriptions

    def match(self, text: str) -> str | None:
        t = normalize(text)
        for label, phrases in self._label_phrases:
            if phrase_match(t, phrases):
                return label
        return None

    def listen(self, frames, mic=None) -> str:
        while True:
            # Idle uses a shorter capture cap than active modes: a wake phrase / "Vox, …" one-shot is
            # at the START of the utterance, so decoding a long ambient monologue here is wasted CPU
            # (and the RAM spikes that make the machine freeze while idle in a talky room).
            audio = capture_utterance(
                frames, self._cfg,
                max_seconds=getattr(self._cfg, "idle_max_utterance_seconds", self._cfg.max_utterance_seconds))
            if audio is None:
                continue
            voiced = None
            gate = _setting("idle_speech_gate", self._cfg.idle_speech_gate)
            if not runtime.is_typed(audio) and (gate or self._cfg.debug):
                voiced = voiced_ms(audio)
                try:  # a stray dashboard value must not take down the idle loop
                    min_ms = int(float(_setting("idle_speech_gate_ms", self._cfg.idle_speech_gate_ms)))
                except (TypeError, ValueError):
                    min_ms = self._cfg.idle_speech_gate_ms
                if gate and voiced < min_ms:
                    # Too little voice to hold a wake phrase: skip the ~1.4 CPU-s Whisper pass.
                    if self._cfg.debug and self._out is not None:
                        self._out.emit(f"  [debug] idle gate: skipped (voiced {voiced}ms < {min_ms}ms)")
                    continue
            if (not runtime.is_typed(audio) and not runtime.last_capture_ptt
                    and _setting("idle_wake_precheck", getattr(self._cfg, "idle_wake_precheck", False))):
                # A ~3 ms Vosk keyword check before the ~1.4 CPU-s Whisper pass: idle Whisper ran on
                # every sound and threw 99% of it away. Measured on synthetic voices: skips 58/60 of
                # the user's real ambient sentences and all filler, but drops 7/75 wakes Whisper
                # would have caught (all fast "vox open …" one-shots). Hence off by default until
                # it's measured on the user's own recordings (Voice Lab).
                try:
                    from vox.stt import vosk_recognizer
                    heard = vosk_recognizer.spot_keywords(audio, _WAKE_KEYWORDS, self._cfg.sample_rate)
                except Exception:
                    heard = None  # Vosk unavailable → behave exactly as before
                if heard is not None and not heard:
                    if self._cfg.debug and self._out is not None:
                        self._out.emit("  [debug] idle precheck: no wake word → skipped Whisper")
                    continue
            text = self._transcriber.transcribe(audio, hotwords=self._cfg.command_hotwords)
            # Passing/ambient audio that piled up in the mic buffer WHILE we were transcribing is
            # stale — drop it so idle stays synced to LIVE audio instead of working through a growing
            # backlog. In a talky room that backlog would otherwise lag, accumulate, and pile on
            # needless transcriptions (and, if the CPU is throttled, grow the queue unbounded).
            if mic is not None:
                mic.flush()
            label = self.match(text)
            cmd = None if label is not None else self._oneshot(text)
            if label is None and cmd is None and (runtime.is_typed(audio) or runtime.last_capture_ptt):
                cmd = text.strip()  # typed or hold-to-talk from idle: no need to say "vox" first
            if self._cfg.debug and self._out is not None and text.strip():
                # Skip silence captures (empty transcription) — they're pure noise. Real
                # transcriptions (incl. no-match mishears) still log.
                tag = label or (f"do:{cmd}" if cmd else "(no match — stayed idle)")
                vtag = f" · voiced={voiced}ms" if voiced is not None else ""
                self._out.emit(f"  [debug] idle heard: {text!r} → {tag}{vtag}")
            if label is not None:
                return label
            if cmd:
                return "do:" + cmd

    def _oneshot(self, text: str) -> str | None:
        # "Vox, <anything>" from idle → run it once, routed through the FULL shared dispatch
        # (deterministic command / scheduler / what-app, else the executor for compose / rewrite /
        # vision / fuzzy). We don't require it to be a known command (that gate blocked "vox what can
        # you see" / "vox set a timer"). Tolerate (a) leading filler — "um vox search…", "so vox open…"
        # — and (b) the very common "vox"→"box"/"fox" mishear. The name must still be the FIRST real
        # word (re.match anchors it), so mid-sentence "vox" doesn't fire; stray "box …" chatter that
        # slips through is IGNOREd downstream by the executor.
        t = re.sub(r"^(?:(?:um|uh|er|ah|oh|so|okay|ok|well|and|now|like|yeah|right|alright)\s+)+",
                   "", normalize(text))
        m = re.match(r"(?:vox|vocks|vaux|fox|box)\s+(.+)", t)
        if not m:
            return None
        return m.group(1).strip() or None


class OpenWakeWordBackend:
    def __init__(self, phrase_to_label, threshold, prompt):
        self._detector = OpenWakeWordDetector(list(phrase_to_label), threshold)
        self._labels = dict(phrase_to_label)
        self.prompt = prompt

    def listen(self, frames, mic=None) -> str:
        # mic accepted for interface parity with WhisperWakeBackend; openWakeWord drains frames
        # continuously and per-frame, so there's no transcription backlog to flush.
        for frame in frames:
            typed = runtime.take()
            if typed is not None:
                return "do:" + typed.text
            if runtime.paused:
                continue
            fired = self._detector.fired(frame)
            if fired is not None:
                self._detector.reset()
                return self._labels[fired]


def make_backend(cfg, transcriber, out=None):
    if cfg.wake_backend == "openwakeword":
        return OpenWakeWordBackend(
            {cfg.control_wake: "control", cfg.assistant_wake: "assistant"},
            cfg.wake_threshold,
            f'Say "{cfg.control_spoken}" for control, "{cfg.assistant_spoken}" for the assistant.',
        )
    # From idle, dictation must be prefixed with the wake word ("Vox start typing") so a
    # bare "start typing" in conversation can't trigger it. Inside control mode the bare
    # dictate_phrases still apply (see loop._is_dictate). vox/fox/box covers Whisper mishears.
    dictate_from_idle = tuple(
        f"{w} {p}" for w in ("vox", "fox", "box") for p in cfg.dictate_phrases
    )
    return WhisperWakeBackend(
        [("control", cfg.control_phrases),
         ("assistant", cfg.assistant_phrases),
         ("dictation", dictate_from_idle),
         ("dashboard", cfg.open_dashboard_phrases),
         ("close_dashboard", cfg.close_dashboard_phrases),
         ("quit", cfg.quit_phrases),
         ("restart", cfg.restart_phrases)],
        transcriber, cfg,
        'Say "take control", "Hey Vox", "Vox start typing", "restart Vox", or "quit Vox".',
        out,
    )
