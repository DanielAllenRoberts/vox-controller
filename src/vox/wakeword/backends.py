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
            if any(p in t for p in phrases):
                return label
        return None

    def listen(self, frames) -> str:
        while True:
            audio = capture_utterance(frames, self._cfg)
            if audio is None:
                continue
            text = self._transcriber.transcribe(audio, hotwords=self._cfg.command_hotwords)
            label = self.match(text)
            cmd = None if label is not None else self._oneshot(text)
            if self._cfg.debug and self._out is not None:
                tag = label or (f"do:{cmd}" if cmd else "(no match — stayed idle)")
                self._out.emit(f"  [debug] idle heard: {text!r} → {tag}")
            if label is not None:
                return label
            if cmd:
                return "do:" + cmd

    def _oneshot(self, text: str) -> str | None:
        # "Vox, <command>" from idle → run it once (no "hey" = command, not chat).
        from vox import actions
        t = normalize(text)
        if not t.startswith("vox "):
            return None
        rest = t[4:].strip()
        return rest if actions.parse(rest) else None


class OpenWakeWordBackend:
    def __init__(self, phrase_to_label, threshold, prompt):
        self._detector = OpenWakeWordDetector(list(phrase_to_label), threshold)
        self._labels = dict(phrase_to_label)
        self.prompt = prompt

    def listen(self, frames) -> str:
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
         ("quit", cfg.quit_phrases),
         ("restart", cfg.restart_phrases)],
        transcriber, cfg,
        'Say "take control", "Hey Vox", "Vox start typing", "restart Vox", or "quit Vox".',
        out,
    )
