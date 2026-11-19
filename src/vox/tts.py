"""Voice output (TTS).

Two engines behind one `speak()` seam, selected by `tts_engine` (config / dashboard):
  • "say"    — macOS `say`: local, zero-install, instant, no model download (kind to disk +
               compute). THE DEFAULT and unchanged from before — the daemon runs exactly as today.
  • "kokoro" — Kokoro 82M neural local TTS (ONNX Runtime, Apple-Silicon-friendly, Apache-2.0,
               offline after first download). Opt-in. Lazy: nothing is imported or downloaded
               unless tts_engine=="kokoro". ANY Kokoro failure (missing package, model download,
               synth, playback) silently falls back to the `say` path, so it can never break the
               loop.

speak() BLOCKS until the phrase finishes so the mic doesn't capture Vox's own voice (a simple
echo guard until barge-in lands — see docs/plan/ideas.md #19).

Voice-upgrade loop 3 — KILLABLE STREAMING TTS (Kokoro path only):
  Instead of synthesizing the whole reply then blocking on afplay, the Kokoro path splits the
  reply into sentence/clause chunks, synthesizes each with Kokoro, and plays the PCM through a
  sounddevice OutputStream fed by a queue — so audio starts after the FIRST sentence (lower
  latency) and a `stop_speaking()` call can halt playback + drop the unplayed queue within a few
  hundred ms (the mechanism that lets the user talk over a reply — pipecat's `_audio_queue.reset()`
  pattern). speak() still BLOCKS until the phrase finishes (or is stopped), preserving its contract.
  ANY failure in the streaming path falls back to the previous synth-whole-then-afplay path, which
  in turn falls back to `say`. stop_speaking() is a no-op for the `say` engine (afplay isn't a
  flushable queue) — interruptible speaking in loop.py is gated to tts_engine=="kokoro".
"""

import os
import re
import subprocess
import tempfile
import time
import wave

from vox import speech_lock
from vox.config import CONFIG


def _setting(key: str, fallback):
    """Read a runtime override from the dashboard's settings_store, else fall back to Config.
    Fully guarded (mirrors assistant/executor._setting): if vox.web.settings_store is missing or
    errors, return the fallback so TTS behaves exactly as before. Lets the engine/voice toggles
    take effect without a restart."""
    try:
        from vox.web import settings_store
        val = settings_store.get(key)
        return fallback if val is None else val
    except Exception:
        return fallback


def _persona_voice(field: str) -> str:
    """The ACTIVE persona's voice for `field` ("kokoroVoice" for the Kokoro engine, or
    "suggestedVoice" for `say`) — so each personality speaks in a fitting voice. Returns "" if
    there's no active persona (or it set no voice, or vox.web is missing), and the caller then
    falls back to the configured global voice. Fully guarded; never raises."""
    try:
        from vox.web import personalities
        p = personalities.get_active_personality()
        if p:
            return (p.get(field) or "").strip()
    except Exception:
        pass
    return ""


_RECENT_SPEECH: list[dict] = []  # what Vox said lately: [{text, start, end}], for the echo guard


# Units the voices read letter by letter ("16 m m"): spoken as words (logged issue 3a049a57). Only a
# number followed by the unit, so "mm" in a word or "MB" in a sentence about files is left alone.
_UNITS = [
    (r"°\s?C\b", " degrees Celsius"), (r"°\s?F\b", " degrees Fahrenheit"), (r"°", " degrees"),
    (r"km/h\b", " kilometres per hour"), (r"mph\b", " miles per hour"), (r"m/s\b", " metres per second"),
    (r"mm\b", " millimetres"), (r"cm\b", " centimetres"), (r"km\b", " kilometres"), (r"m\b", " metres"),
    (r"kg\b", " kilograms"), (r"g\b", " grams"), (r"ml\b", " millilitres"), (r"l\b", " litres"),
    (r"hPa\b", " hectopascals"), (r"mb\b", " millibars"), (r"KB\b", " kilobytes"), (r"MB\b", " megabytes"),
    (r"GB\b", " gigabytes"), (r"TB\b", " terabytes"), (r"%", " percent"),
]
# Case-sensitive on purpose: "5 MB" is megabytes, "5 mb" millibars.
_UNIT_RE = [(re.compile(r"(?<=\d)\s?" + pat), word) for pat, word in _UNITS]


def speakable(text: str) -> str:
    """Text as it should be SAID: numbers' units spelled out."""
    out = text
    for rx, word in _UNIT_RE:
        out = rx.sub(word, out)
    return out


def speak(text: str) -> None:
    if not _setting("tts_enabled", CONFIG.tts_enabled) or not text.strip():
        return
    text = speakable(text)
    # Wait for any agent that's already talking — Vox and each MCP server are separate processes
    # and would otherwise speak over each other (see vox/speech_lock.py).
    with speech_lock.hold("vox"):
        entry = {"text": text, "start": time.monotonic(), "end": None}
        _RECENT_SPEECH.append(entry)
        del _RECENT_SPEECH[:-5]
        try:
            _speak_now(text)
        finally:
            entry["end"] = time.monotonic()


def is_echo(heard: str, window: float = 4.0) -> bool:
    """Is `heard` just Vox hearing ITSELF (its reply coming back through the speakers into the mic)?
    True when it was captured while Vox was speaking or within `window` seconds after, and most of its
    words are words Vox just said. That loop made Vox answer its own voice (logged issue aa508d85)."""
    import re as _re
    words = _re.findall(r"[a-z0-9']+", (heard or "").lower())
    # At least 4 words and 80% overlap: an echo replays a long run of the reply, while a person
    # answering it ("yes, search for it") reuses a few of its words and must still be heard.
    if len(words) < 4:
        return False
    now = time.monotonic()
    for e in reversed(_RECENT_SPEECH):
        if e["end"] is not None and now - e["end"] > window:
            continue
        said = set(_re.findall(r"[a-z0-9']+", e["text"].lower()))
        if sum(w in said for w in words) / len(words) >= 0.8:
            return True
    return False


def _speak_now(text: str) -> None:
    """The engine ladder, split out of speak() so the speech-queue lock wraps exactly one call and
    the kokoro→say fallthrough below stays byte-for-byte what it was."""
    if speech_lock.paused() and not _wait_resume(time.time()):
        return  # paused when our turn came, then stopped rather than resumed
    if _setting("tts_engine", CONFIG.tts_engine) == "kokoro":
        # The streaming/killable player (sounddevice OutputStream) exists ONLY for interruptible
        # speaking (talk-over). It's heavier and its stream-finish detection has hung in the field
        # (freezing the loop for up to its backstop). So engage it ONLY when tts_interruptible is on;
        # otherwise take the robust synth→afplay path (a separate afplay process with its own timeout).
        if _setting("tts_interruptible", CONFIG.tts_interruptible):
            try:
                if _speak_kokoro_streaming(text):
                    return  # spoke via the streaming/killable Kokoro player (or returned early on stop)
            except Exception:
                pass  # streaming path failed → try the simple blocking kokoro synth next
        try:
            if _speak_kokoro(text):
                return  # synth-whole-then-afplay Kokoro path (robust; can't be cut mid-utterance)
        except Exception as e:
            _warn_kokoro_fallback(e)  # any Kokoro failure → fall through to the always-available `say` path
    _speak_say(text)


_KOKORO_WARNED = False


def _warn_kokoro_fallback(e: Exception) -> None:
    """Say ONCE why Kokoro fell back to `say`. The fallback is silent by design so the daemon never
    breaks, but that also hid a failed model download (no CA certificates) behind the macOS voice."""
    global _KOKORO_WARNED
    if _KOKORO_WARNED:
        return
    _KOKORO_WARNED = True
    print(f"⚠ Kokoro voice unavailable, using macOS `say` instead: {type(e).__name__}: {e}", flush=True)


def speak_with(text: str, *, engine: str = "", say_voice=None, kokoro_voice=None,
               rate=None, speed=None, label: str = "") -> None:
    """Speak `text` with EXPLICIT engine/voice overrides, bypassing the active persona's voice and
    the global tts_enabled gate. Used by the vox-speak MCP so the assistant's heads-up voice can be
    DIFFERENT from the system's (and can independently use the neural Kokoro engine). `engine` "" =
    follow the live system setting; a say/kokoro value pins it. Any Kokoro failure falls back to
    `say`, exactly like speak(). Always speaks when asked (it's a deliberate tool call).

    `label` names this speaker in the shared speech queue (e.g. a registered agent name), so the
    lock file says who you're waiting for."""
    if not text.strip():
        return
    with speech_lock.hold(label or "mcp"):
        _speak_with_now(text, engine=engine, say_voice=say_voice, kokoro_voice=kokoro_voice,
                        rate=rate, speed=speed)


def _speak_with_now(text: str, *, engine: str = "", say_voice=None, kokoro_voice=None,
                    rate=None, speed=None) -> None:
    """The engine ladder for speak_with — split out for the same reason as _speak_now."""
    if speech_lock.paused() and not _wait_resume(time.time()):
        return
    eng = engine or _setting("tts_engine", CONFIG.tts_engine)
    if eng == "kokoro":
        try:
            if _speak_kokoro_streaming(text, voice=kokoro_voice, speed=speed):
                return
        except Exception:
            pass
        try:
            if _speak_kokoro(text, voice=kokoro_voice, speed=speed):
                return
        except Exception:
            pass
    _speak_say(text, voice=say_voice, rate=rate)


def stop_speaking() -> None:
    """Cut whatever THIS process is speaking, on any engine, and drop the rest of it. This is how
    the user talks over a reply (loop 3). No-op when nothing is speaking. (The stop button uses
    speech_lock.request_stop, which reaches every process.)"""
    global _LOCAL_STOP_AT
    _LOCAL_STOP_AT = time.time()
    proc = _PLAYER_PROC  # don't wait for the player loop's next look
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass


def is_speaking() -> bool:
    """True while a reply is playing (either engine)."""
    proc = _PLAYER_PROC
    return _STREAMING or (proc is not None and proc.poll() is None)


# --- one player loop for every engine: stoppable and pausable -------------------------------------
_PLAYER_PROC: "subprocess.Popen | None" = None  # the say/afplay process making sound right now
_STREAMING = False     # inside a streaming Kokoro reply (true between its sentences too)
_LOCAL_STOP_AT = 0.0   # when stop_speaking() was last called in this process


def _stop_requested(since: float) -> bool:
    return _LOCAL_STOP_AT >= since or speech_lock.stopped_since(since)


def _run_player(cmd: list[str], timeout: float, since: float) -> tuple[str, float]:
    """Run a say/afplay command to the end, watching for stop and pause. Returns the outcome and how
    many seconds played: "done", "stopped", or "paused" (the audio was killed because speech was
    paused; the caller waits in _wait_resume and then plays what's left). `since` is the wall-clock
    time the utterance began, so a stop from before it doesn't count. `timeout` only catches a hung
    player."""
    global _PLAYER_PROC
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _PLAYER_PROC = proc
    try:
        while proc.poll() is None:
            played = time.monotonic() - t0
            if _stop_requested(since):
                proc.terminate()
                return "stopped", played
            if speech_lock.paused():
                proc.terminate()
                return "paused", played
            if played > timeout:
                proc.kill()
                break
            time.sleep(0.03)
        return "done", time.monotonic() - t0
    finally:
        _PLAYER_PROC = None


def _wait_resume(since: float) -> bool:
    """Wait out a pause. True to carry on speaking, False if it was stopped instead."""
    while speech_lock.paused():
        if _stop_requested(since):
            return False
        time.sleep(0.05)
    return not _stop_requested(since)


def _rest_after(text: str, played: float, rate=None) -> str:
    """What's left of `text` after `say` spoke it for `played` seconds, from the start of the
    sentence it was in. `say` doesn't report where it got to, so this estimates from the speaking
    rate, leaning early: hearing a sentence twice beats missing one."""
    try:
        wpm = float(rate) if rate else 175.0
    except (TypeError, ValueError):
        wpm = 175.0
    spoken = played * 0.85 * wpm / 60.0
    chunks = _split_chunks(text)
    words = 0
    for i, c in enumerate(chunks):
        words += len(c.split())
        if words > spoken:
            return " ".join(chunks[i:])
    return ""


def _speak_say(text: str, voice=None, rate=None) -> None:
    """macOS `say` — the default, zero-dependency engine. `voice`/`rate` None → resolve from the
    active persona / settings (the daemon's behavior, unchanged); a provided value overrides (used
    by speak_with for the MCP — pass "" for the system-default voice)."""
    cmd = ["say"]
    if voice is None:
        voice = _persona_voice("suggestedVoice") or _setting("tts_voice", CONFIG.tts_voice)
    if rate is None:
        rate = _setting("tts_rate", CONFIG.tts_rate)
    if voice:
        cmd += ["-v", voice]
    if rate:
        cmd += ["-r", str(rate)]
    since = time.time()
    try:
        while text:
            outcome, played = _run_player(cmd + [text], _say_timeout(text, rate), since)
            if outcome != "paused" or not _wait_resume(since):
                return
            text = _rest_after(text, played, rate)  # resumed: carry on from that sentence
    except Exception:
        pass  # never let a TTS hiccup (or hang) break the loop


def _say_timeout(text: str, rate=None) -> float:
    """How long to let `say` run before assuming it has hung.

    Was a flat 30s, which SILENTLY TRUNCATED any longer speech: `subprocess.run` kills the child on
    timeout and the caller swallows the exception, so a long reply just stopped mid-word with nothing
    in the log. ~95 words is already over 30s at the default rate, and the vox-speak MCP allows 1000
    characters (~55s), so the cap contradicted what callers were allowed to send.

    The timeout exists to catch a HUNG `say`, not to cap legitimate speech — so scale it with the
    text and keep generous headroom."""
    try:
        wpm = float(rate) if rate else 175.0   # `say`'s default is ~175 wpm
    except (TypeError, ValueError):
        wpm = 175.0
    words = max(1, len(str(text).split()))
    expected = words / max(60.0, wpm) * 60.0
    return max(30.0, expected * 2.0 + 15.0)


# --- Kokoro (lazy) ----------------------------------------------------------------------------
# Everything below is only reached when tts_engine=="kokoro". Imports are deferred and the model
# is cached across calls so the load/download cost is paid once.

_KOKORO = None  # cached kokoro_onnx.Kokoro instance once loaded

# Combined model + voices files the kokoro-onnx library expects, from its GitHub release.
_KOKORO_MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
_KOKORO_VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"


def _kokoro_cache_dir() -> str:
    d = os.path.expanduser("~/.cache/vox/kokoro")
    os.makedirs(d, exist_ok=True)
    return d


def _ensure_file(url: str, name: str) -> str:
    """Download `url` to the kokoro cache as `name` on first use; return the local path."""
    path = os.path.join(_kokoro_cache_dir(), name)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    import urllib.request
    tmp = path + ".part"
    urllib.request.urlretrieve(url, tmp)  # no auth needed for public release assets
    os.replace(tmp, path)
    return path


def _get_kokoro():
    """Lazily import kokoro-onnx, ensure the model + voices are present, and cache the instance."""
    global _KOKORO
    if _KOKORO is not None:
        return _KOKORO
    from kokoro_onnx import Kokoro  # deferred: only imported on the kokoro path
    model_path = _ensure_file(_KOKORO_MODEL_URL, "kokoro-v1.0.onnx")
    voices_path = _ensure_file(_KOKORO_VOICES_URL, "voices-v1.0.bin")
    threads = CONFIG.kokoro_threads
    if threads > 0:
        # Kokoro(...) builds its InferenceSession with default options = one thread per core (all 10
        # on an M4, E-cores included), so TTS fought STT and barge-in for the whole machine. Measured
        # on a 1.8 s reply: default 0.61 s wall / 2.9 CPU-s vs 4 threads 0.54 s / 2.1 CPU-s.
        import onnxruntime as rt
        so = rt.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1  # one sequential graph; inter-op threads would only idle-spin
        sess = rt.InferenceSession(model_path, sess_options=so, providers=["CPUExecutionProvider"])
        _KOKORO = Kokoro.from_session(sess, voices_path)
    else:
        _KOKORO = Kokoro(model_path, voices_path)
    return _KOKORO


def _speak_kokoro(text: str, voice=None, speed=None) -> bool:
    """Synthesize `text` with Kokoro, write a temp wav, and play it (blocking) via afplay.
    `voice`/`speed` None → resolve from the active persona / settings; a provided value overrides
    (used by speak_with for the MCP). Returns True on success; raises on any failure so the caller
    can fall back to `say`."""
    import numpy as np

    kokoro = _get_kokoro()
    if voice is None:
        voice = _persona_voice("kokoroVoice") or _setting("kokoro_voice", CONFIG.kokoro_voice)
    if speed is None:
        speed = float(_setting("kokoro_speed", CONFIG.kokoro_speed))
    speed = float(speed)
    samples, sample_rate = kokoro.create(text, voice=voice, speed=speed)

    pcm16 = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm16 = (pcm16 * 32767.0).astype("<i2")
    if pcm16.size == 0:
        raise RuntimeError("kokoro produced empty audio")

    fd, wav_path = tempfile.mkstemp(prefix="vox_kokoro_", suffix=".wav")
    os.close(fd)
    try:
        with wave.open(wav_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(int(sample_rate))
            w.writeframes(pcm16.tobytes())
        # The wav's real duration is known exactly here, so the hang-guard can be derived rather
        # than guessed. A flat 60s silently truncated anything longer (afplay is killed on timeout
        # and the exception is swallowed) — the same failure the `say` path had.
        seconds = pcm16.size / float(sample_rate or 24000)
        since, offset = time.time(), 0.0
        while True:
            outcome, played = _run_player(["afplay", wav_path], max(60.0, seconds - offset + 15.0), since)
            if outcome != "paused" or not _wait_resume(since):
                return True
            # Resumed: play the rest, backing up a moment so the cut-off word is heard whole.
            offset = max(0.0, offset + played - 0.7)
            with wave.open(wav_path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(int(sample_rate))
                w.writeframes(pcm16[int(offset * sample_rate):].tobytes())
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass


# --- Killable streaming Kokoro player (loop 3) -------------------------------------------------
# Splits the reply into sentence/clause chunks, synthesizes each with Kokoro, and plays the PCM
# through a sounddevice OutputStream fed by a bounded queue — so audio starts after the first
# sentence and stop() halts playback + drops the unplayed queue within a few hundred ms.


# Sentence/clause boundary punctuation. Splitting on these lets the FIRST chunk start playing while
# later chunks are still synthesizing (lower latency) and makes the reply killable between chunks.
_CHUNK_BOUNDARY = ".!?;:\n"


def _split_chunks(text: str, max_chars: int = 200) -> list[str]:
    """Split `text` into sentence/clause chunks on boundary punctuation, then hard-wrap any chunk
    longer than max_chars at the last space so no single Kokoro synth call is huge (keeps the first
    audio fast and stop() responsive). Pure/standalone — easy to reason about and verify."""
    chunks, buf = [], ""
    for ch in text:
        buf += ch
        if ch in _CHUNK_BOUNDARY and buf.strip():
            chunks.append(buf.strip())
            buf = ""
    if buf.strip():
        chunks.append(buf.strip())

    out: list[str] = []
    for c in chunks:
        while len(c) > max_chars:
            cut = c.rfind(" ", 0, max_chars)
            if cut <= 0:
                cut = max_chars
            out.append(c[:cut].strip())
            c = c[cut:].strip()
        if c:
            out.append(c)
    return out or ([text.strip()] if text.strip() else [])


def _close_quietly(stream) -> None:
    """Close a finished OutputStream off the voice loop — see the teardown note in play()."""
    try:
        stream.close()
    except Exception:
        pass


def _speak_kokoro_streaming(text: str, voice=None, speed=None) -> bool:
    """Interruptible Kokoro playback: one sentence at a time, each through `afplay`, with the next
    sentence synthesized while the current one plays. stop_speaking() kills the playing sentence and
    drops the rest.

    It used to be a sounddevice OutputStream. Two problems: PortAudio freezes its device list at
    startup, so after switching from the Mac's speakers to headphones Vox kept talking through the
    old device (logged issue 8c19add9); and its stream-finish detection hung in the field. afplay
    starts fresh on the CURRENT output device for every sentence and is just a process to kill."""
    global _STREAMING
    import numpy as np

    kokoro = _get_kokoro()
    if voice is None:
        voice = _persona_voice("kokoroVoice") or _setting("kokoro_voice", CONFIG.kokoro_voice)
    if speed is None:
        speed = float(_setting("kokoro_speed", CONFIG.kokoro_speed))
    speed = float(speed)
    chunks = _split_chunks(text)
    if not chunks:
        return True

    since = time.time()
    stopped = False
    _STREAMING = True
    try:
        def synth(chunk):
            samples, rate = kokoro.create(chunk, voice=voice, speed=speed)
            pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767.0).astype("<i2")
            return _write_wav(pcm, int(rate)), pcm.size / float(rate or 24000)

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(1) as pool:
            nxt = pool.submit(synth, chunks[0])
            for i in range(len(chunks)):
                wav, seconds = nxt.result()
                stopped = stopped or _stop_requested(since)
                if i + 1 < len(chunks) and not stopped:
                    nxt = pool.submit(synth, chunks[i + 1])  # synthesize ahead while this one plays
                try:
                    while not stopped:
                        # +10 s: never wait forever on a wedged device
                        outcome, _played = _run_player(["afplay", wav], seconds + 10.0, since)
                        if outcome == "done":
                            break
                        # Paused then resumed: say this sentence again from its start.
                        stopped = outcome == "stopped" or not _wait_resume(since)
                finally:
                    _rm(wav)
                if stopped:
                    if i + 1 < len(chunks):
                        try:
                            _rm(nxt.result()[0])
                        except Exception:
                            pass
                    break
        return True
    finally:
        _STREAMING = False


def _write_wav(pcm16, rate: int) -> str:
    fd, path = tempfile.mkstemp(prefix="vox_kokoro_", suffix=".wav")
    os.close(fd)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm16.tobytes())
    return path


def _rm(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
