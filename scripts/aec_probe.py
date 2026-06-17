"""AEC probe — does macOS Voice Processing clean up the mic?  (standalone; does NOT touch Vox.)

Records two short clips while you PLAY AUDIO (a video / music) through your speakers AND speak a
test sentence:
  1) raw        — a normal capture, like Vox uses today
  2) processed  — a capture through macOS Voice Processing (echo-cancel + noise suppression)
Then compare them. If the background/video is much quieter in 'processed' while your voice stays
clear, Voice Processing is worth wiring into Vox.

Run it (the --with installs the audio bridge without touching the project):

    uv run --with pyobjc-framework-AVFoundation python scripts/aec_probe.py

Notes:
- macOS may prompt to grant your terminal Microphone permission the first time — allow it.
- This is a PROTOTYPE to settle one question (does Voice Processing help?). It may need a tweak
  or two on first run — tell me whatever it prints / what the two clips sound like.
"""

import time

from AVFoundation import AVAudioEngine, AVAudioFile
from Foundation import NSURL

SECONDS = 6
RAW = "/tmp/vox_raw.caf"
AEC = "/tmp/vox_aec.caf"


def record(voice_processing: bool, path: str) -> None:
    engine = AVAudioEngine.alloc().init()
    inp = engine.inputNode()
    if voice_processing:
        ok, err = inp.setVoiceProcessingEnabled_error_(True, None)
        print("  voice processing:", "ON" if ok else f"FAILED ({err})")
    fmt = inp.outputFormatForBus_(0)  # get the format AFTER enabling VP (it may change)
    url = NSURL.fileURLWithPath_(path)
    audio_file, err = AVAudioFile.alloc().initForWriting_settings_error_(url, fmt.settings(), None)
    if audio_file is None:
        print("  ! couldn't open output file:", err)
        return

    def tap(buf, when):
        audio_file.writeFromBuffer_error_(buf, None)  # write each captured buffer straight to disk

    inp.installTapOnBus_bufferSize_format_block_(0, 4096, fmt, tap)
    engine.prepare()
    ok, err = engine.startAndReturnError_(None)
    if not ok:
        print("  ! couldn't start engine:", err)
        return
    print(f"  ● recording {SECONDS}s → {path}   (play your video AND speak a sentence now)")
    time.sleep(SECONDS)
    engine.stop()
    inp.removeTapOnBus_(0)
    print("  ✓ done")


def main() -> None:
    print("AEC probe — play a video/music through your speakers, and speak during BOTH clips.\n")
    print("[1/2] RAW capture (no processing):")
    record(False, RAW)
    time.sleep(1)
    print("\n[2/2] PROCESSED capture (macOS Voice Processing):")
    record(True, AEC)
    print("\nNow listen and compare:")
    print(f"  afplay {RAW}")
    print(f"  afplay {AEC}")
    print("\nIf the video is much quieter in the processed clip (and your voice still clear),")
    print("Voice Processing helps and I'll wire it into Vox. Tell me what you hear.")


if __name__ == "__main__":
    main()
