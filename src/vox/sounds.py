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


def play_n(path: str, times: int = 1) -> None:
    """Play a sound `times` in a row, BLOCKING between plays so they don't overlap — for an alarm
    that should be more than a single blip. Runs on the caller's thread (fine from the scheduler
    thread; don't call from the hot voice loop). Guarded — never raises."""
    if not path or times < 1:
        return
    for _ in range(times):
        try:
            subprocess.run(["afplay", path], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10)
        except Exception:
            return
