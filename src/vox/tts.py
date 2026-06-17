"""Voice output (TTS). macOS `say` for now — local, zero-install, instant, no model download
(kind to disk + compute). Swap for a neural local TTS (e.g. Piper) later behind this same
speak() interface.

speak() BLOCKS until the phrase finishes so the mic doesn't capture Vox's own voice (a simple
echo guard until barge-in lands — see docs/plan/ideas.md #19).
"""

import subprocess

from vox.config import CONFIG


def speak(text: str) -> None:
    if not CONFIG.tts_enabled or not text.strip():
        return
    cmd = ["say"]
    if CONFIG.tts_voice:
        cmd += ["-v", CONFIG.tts_voice]
    if CONFIG.tts_rate:
        cmd += ["-r", str(CONFIG.tts_rate)]
    cmd.append(text)
    try:
        subprocess.run(cmd, capture_output=True)
    except Exception:
        pass  # never let a TTS hiccup break the loop
