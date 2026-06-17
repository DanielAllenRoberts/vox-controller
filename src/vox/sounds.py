"""Audio cues for mode transitions, so you get feedback without watching the terminal.

Plays a sound via macOS `afplay`, non-blocking (fire-and-forget). Swap the files in
config for custom sounds later (e.g. made in Logic).
"""

import subprocess


def play(path: str) -> None:
    if not path:
        return
    try:
        subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass  # a missing/blocked sound must never break the loop
