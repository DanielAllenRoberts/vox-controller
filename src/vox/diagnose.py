"""Microphone + wake-word diagnostic.

Run:  uv run vox-diagnose              # uses the system default input
      uv run vox-diagnose 3            # test a specific device index

Shows per-channel input level + live wake score (for the control phrase),
transcribes the capture with Whisper, saves it to vox-capture.wav, and sweeps
software gain. Pinpoints permission / wiring / format / wake-model issues.
"""

import sys
import time

import numpy as np
import sounddevice as sd

from vox.config import CONFIG
from vox.stt.whisper_transcriber import WhisperTranscriber
from vox.wakeword.openwakeword_detector import OpenWakeWordDetector

WAKE = CONFIG.control_wake
SPOKEN = CONFIG.control_spoken


def _list_devices() -> None:
    print("Input devices:")
    default_in = sd.default.device[0]
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            mark = " (system default)" if i == default_in else ""
            print(f"  [{i}] {dev['name']}  ({dev['max_input_channels']} in){mark}")
    print()


def _max_score(audio_int16: np.ndarray) -> float:
    """Run the wake model over a clip in 80 ms frames and return the peak score."""
    det = OpenWakeWordDetector([WAKE], CONFIG.wake_threshold)
    step = CONFIG.frame_samples
    best = 0.0
    for i in range(0, len(audio_int16) - step, step):
        best = max(best, det.scores(audio_int16[i:i + step])[WAKE])
    return best


def main() -> None:
    _list_devices()

    device = int(sys.argv[1]) if len(sys.argv) > 1 else CONFIG.input_device
    info = sd.query_devices(device, kind="input")
    n_ch = min(int(info["max_input_channels"]), 8)
    label = "system default" if device is None else f"index {device}"
    print(f"Using input device: {info['name']}  ({label}), capturing {n_ch} channel(s)\n")

    print("Loading wake model…")
    detector = OpenWakeWordDetector([WAKE], CONFIG.wake_threshold)
    probe = detector._model.predict(np.zeros(CONFIG.frame_samples, dtype=np.int16))
    print(f"  score keys = {list(probe.keys())} | testing '{WAKE}'\n")

    seconds = 12
    print(f'Say "{SPOKEN}" a few times — listening {seconds}s.')
    print(f"Per-channel level + wake score (fires at {CONFIG.wake_threshold}).\n")

    state = {"rms": np.zeros(n_ch), "score": 0.0}
    captured: list[np.ndarray] = []

    def callback(indata, frames, time_info, status):
        if status:
            print(f"\n[audio status] {status}", file=sys.stderr)
        captured.append(indata.copy())
        rms = np.sqrt(np.mean(indata.astype(np.float32) ** 2, axis=0))
        state["rms"] = rms
        hot = int(np.argmax(rms))
        state["score"] = detector.scores(indata[:, hot].copy())[WAKE]

    peak_rms = np.zeros(n_ch)
    peak_score = 0.0
    with sd.InputStream(samplerate=CONFIG.sample_rate, channels=n_ch, dtype="int16",
                        blocksize=CONFIG.frame_samples, device=device, callback=callback):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            rms, score = state["rms"], state["score"]
            peak_rms = np.maximum(peak_rms, rms)
            peak_score = max(peak_score, score)
            chans = "  ".join(f"ch{i}={int(r):4d}" for i, r in enumerate(rms))
            hit = "  <-- WAKE!" if score >= CONFIG.wake_threshold else ""
            print(f"\r{chans}  | score={score:0.2f}{hit}   ", end="", flush=True)
            time.sleep(0.05)

    print("\n\nPeak level: " + ", ".join(f"ch{i}={int(r)}" for i, r in enumerate(peak_rms)))
    print(f"Peak live wake score: {peak_score:0.2f}")

    if not captured:
        print("\n→ No audio captured at all (permission / device).")
        return

    audio = np.concatenate(captured, axis=0)
    best = int(np.argmax((audio.astype(np.float32) ** 2).mean(axis=0)))
    mono = audio[:, best]

    try:
        from scipy.io import wavfile
        wavfile.write("vox-capture.wav", CONFIG.sample_rate, mono)
        print("Saved capture -> vox-capture.wav")
    except Exception as exc:
        print(f"(could not save wav: {exc})")

    print("\nTranscribing (Whisper)…")
    heard = WhisperTranscriber(CONFIG.whisper_model, CONFIG.whisper_compute_type).transcribe(mono)
    print(f"Whisper heard: {heard!r}")

    print("\nWake score vs software gain (re-run on the capture):")
    scores = {}
    for g in (1, 2, 4, 8, 16):
        boosted = np.clip(mono.astype(np.float32) * g, -32768, 32767).astype(np.int16)
        scores[g] = _max_score(boosted)
        print(f"  gain x{g:2d}: max score = {scores[g]:0.2f}")

    print()
    if peak_rms.max() < 50:
        print("→ Almost no audio captured — permission/device issue.")
    elif not heard or len(heard) < 3:
        print("→ Audio captured but Whisper heard ~nothing: format/sample-rate problem.")
    elif scores.get(1, 0.0) >= 0.5:
        print("→ Working at normal gain — the wake word fires. You're good: `uv run vox`.")
    elif max(scores.values()) >= 0.5:
        good = min(g for g, s in scores.items() if s >= 0.5)
        print(f"→ Fires only when boosted (gain x{good}). Your input is quiet — turn up the")
        print(f"  interface gain, or I can apply ~{good}x software gain in capture.")
    else:
        print("→ Even boosted, the model won't match. Check onnxruntime is <1.21, or retune.")


if __name__ == "__main__":
    main()
