"""Wake-word backends. Both implement `listen(frames) -> label` ('control' | 'assistant').

- WhisperWakeBackend: VAD-gated transcription matched against phrases. No training,
  any phrase (incl. custom names); transcribes nearby speech, so a bit more compute.
- OpenWakeWordBackend: cheap always-on per-frame detection; needs trained models.

Pick via `config.wake_backend`. See docs/plan/modes.md.
"""

import re

from vox.audio import capture_utterance
from vox.wakeword.openwakeword_detector import OpenWakeWordDetector


def normalize(text: str) -> str:
    """Lowercase + strip punctuation so phrase matching survives Whisper's commas/periods."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


def phrase_match(t: str, phrases) -> bool:
    """True if any phrase occurs in the already-normalized text `t`. Also matches when Whisper
    drops the inter-word space ("quit vox" heard as "quitvox") by comparing space-stripped too."""
    t2 = t.replace(" ", "")
    return any(p in t or p.replace(" ", "") in t2 for p in phrases)


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
            text = self._transcriber.transcribe(audio, hotwords=self._cfg.command_hotwords)
            # Passing/ambient audio that piled up in the mic buffer WHILE we were transcribing is
            # stale — drop it so idle stays synced to LIVE audio instead of working through a growing
            # backlog. In a talky room that backlog would otherwise lag, accumulate, and pile on
            # needless transcriptions (and, if the CPU is throttled, grow the queue unbounded).
            if mic is not None:
                mic.flush()
            label = self.match(text)
            cmd = None if label is not None else self._oneshot(text)
            if self._cfg.debug and self._out is not None and text.strip():
                # Skip silence captures (empty transcription) — they're pure noise. Real
                # transcriptions (incl. no-match mishears) still log.
                tag = label or (f"do:{cmd}" if cmd else "(no match — stayed idle)")
                self._out.emit(f"  [debug] idle heard: {text!r} → {tag}")
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
