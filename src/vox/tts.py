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
import queue
import subprocess
import tempfile
import threading
import wave

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


def speak(text: str) -> None:
    if not _setting("tts_enabled", CONFIG.tts_enabled) or not text.strip():
        return
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
        except Exception:
            pass  # any Kokoro failure → fall through to the always-available `say` path
    _speak_say(text)


def speak_with(text: str, *, engine: str = "", say_voice=None, kokoro_voice=None,
               rate=None, speed=None) -> None:
    """Speak `text` with EXPLICIT engine/voice overrides, bypassing the active persona's voice and
    the global tts_enabled gate. Used by the vox-speak MCP so the assistant's heads-up voice can be
    DIFFERENT from the system's (and can independently use the neural Kokoro engine). `engine` "" =
    follow the live system setting; a say/kokoro value pins it. Any Kokoro failure falls back to
    `say`, exactly like speak(). Always speaks when asked (it's a deliberate tool call)."""
    if not text.strip():
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
    """Cut the in-flight streaming Kokoro reply immediately: signal the player to stop, which halts
    the OutputStream and drops every unplayed chunk so speak() returns promptly. This is how the
    user talks over a reply (loop 3). No-op when nothing is speaking or on the `say`/afplay path
    (afplay isn't a flushable queue) — interruptible speaking in loop.py is gated to the kokoro
    engine. Guarded so it can never raise into the caller."""
    player = _ACTIVE_PLAYER
    if player is not None:
        try:
            player.stop()
        except Exception:
            pass


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
    cmd.append(text)
    try:
        subprocess.run(cmd, capture_output=True, timeout=30)
    except Exception:
        pass  # never let a TTS hiccup (or hang) break the loop


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
        subprocess.run(["afplay", wav_path], capture_output=True, timeout=60)
        return True
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass


# --- Killable streaming Kokoro player (loop 3) -------------------------------------------------
# Splits the reply into sentence/clause chunks, synthesizes each with Kokoro, and plays the PCM
# through a sounddevice OutputStream fed by a bounded queue — so audio starts after the first
# sentence and stop() halts playback + drops the unplayed queue within a few hundred ms.

_ACTIVE_PLAYER = None  # the _StreamingPlayer currently speaking (for stop_speaking()); None when idle

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


class _StreamingPlayer:
    """Synthesizes Kokoro chunks on a worker thread and plays them through one sounddevice
    OutputStream fed by a bounded float32 queue. `play()` blocks until the whole reply has played
    (preserving speak()'s contract); `stop()` sets a stop event that aborts the stream and clears
    the queue so play() returns within a few hundred ms (one block of audio)."""

    def __init__(self, kokoro, voice: str, speed: float, sample_rate: int):
        self._kokoro = kokoro
        self._voice = voice
        self._speed = speed
        self._sr = sample_rate
        self._q: "queue.Queue" = queue.Queue(maxsize=64)  # float32 PCM blocks; None = end-of-stream
        self._stop = threading.Event()
        self._done = threading.Event()

    def stop(self) -> None:
        """Halt playback immediately and drop the unplayed queue."""
        self._stop.set()
        try:  # drain whatever is buffered so the stream finishes its current block and ends
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    def play(self, chunks: list[str], seed=None) -> None:
        """Drive the OutputStream over the synthesized queue, blocking until done or stopped.
        `seed` (optional float32 PCM) is the audio for chunks[0] already synthesized by the caller
        (so the first chunk isn't synthesized twice) — it's queued first, then the worker handles
        any `chunks` that follow."""
        import time
        import numpy as np
        import sounddevice as sd

        if seed is not None and seed.size:
            for i in range(0, seed.size, 2048):
                self._q.put(seed[i:i + 2048])

        synth = threading.Thread(target=self._synth_worker, args=(chunks,), daemon=True)
        synth.start()

        buf = np.zeros(0, dtype=np.float32)
        eos = False  # end-of-stream sentinel has been seen → stop once `buf` is fully drained

        def callback(outdata, frames, time_info, status):
            nonlocal buf, eos
            if self._stop.is_set():
                raise sd.CallbackStop()
            # Top up `buf` from the queue until we have a full block (or hit end-of-stream).
            while buf.size < frames:
                try:
                    item = self._q.get_nowait()
                except queue.Empty:
                    break
                if item is None:  # end-of-stream sentinel: remember it, play out whatever remains
                    eos = True
                    break
                buf = np.concatenate([buf, item])
            n = min(frames, buf.size)
            outdata[:n, 0] = buf[:n]
            if n < frames:
                outdata[n:, 0] = 0.0  # underrun / tail → silence, keep stream alive for more chunks
            buf = buf[n:]
            # Once the sentinel was seen AND the buffer is fully drained, the reply is finished.
            # (The old code consumed the sentinel on a partial last block and then never stopped, so
            #  finished_callback never fired and play() hung forever — the daemon-freeze bug.)
            if eos and buf.size == 0:
                raise sd.CallbackStop()

        stream = sd.OutputStream(samplerate=self._sr, channels=1, dtype="float32",
                                 blocksize=1024, callback=callback,
                                 finished_callback=self._done.set)
        stream.start()
        try:
            deadline = time.monotonic() + 60.0  # absolute backstop: never hang the daemon (spoken replies are short)
            # Block until playback finishes (end-of-stream reached) or stop() fires.
            while not self._done.wait(timeout=0.05):
                if self._stop.is_set() or time.monotonic() > deadline:
                    break
        finally:
            self._stop.set()  # ensure the synth worker exits even if playback ended early
            # Tear the stream down WITHOUT Pa_StopStream. `with sd.OutputStream(...)` used to do the
            # teardown, but its __exit__ calls stop() — which WAITS for the buffers to drain and
            # deadlocks on an audio-device change (opening Spotify, a Bluetooth/headphone switch).
            # That wedged the whole voice loop with no audio and no log line, past every backstop
            # above, and left the process needing a kill. Same CoreAudio trap MicStream documents:
            # abort() is immediate, and close() runs off the loop so even a stuck close can't freeze
            # the daemon (a leaked stream object is cheap next to a dead assistant).
            try:
                stream.abort()  # Pa_AbortStream — returns at once, doesn't drain
            except Exception:
                pass
            threading.Thread(target=_close_quietly, args=(stream,), daemon=True).start()
            synth.join(timeout=2.0)

    def _synth_worker(self, chunks: list[str]) -> None:
        """Synthesize each chunk and push its PCM onto the queue; a None sentinel marks the end.
        Stops early if stop() fired so we don't synthesize audio nobody will hear."""
        import numpy as np
        try:
            for chunk in chunks:
                if self._stop.is_set():
                    break
                samples, _sr = self._kokoro.create(chunk, voice=self._voice, speed=self._speed)
                pcm = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
                if pcm.size == 0:
                    continue
                # Feed in queue-sized pieces, bailing out fast if stop() fires mid-chunk.
                for i in range(0, pcm.size, 2048):
                    if self._stop.is_set():
                        return
                    self._q.put(pcm[i:i + 2048])
        finally:
            # End-of-stream sentinel — BLOCKING put (with a timeout) so it's never dropped when the
            # queue is full. (put_nowait could drop it on a full queue, losing the sentinel → play()
            # would hang until the backstop deadline on long replies.) The player drains continuously,
            # so a slot frees in ~one audio block; the timeout is only a safety net.
            try:
                self._q.put(None, timeout=5.0)
            except queue.Full:
                pass


def _speak_kokoro_streaming(text: str, voice=None, speed=None) -> bool:
    """Streaming, killable Kokoro playback (loop 3). Synthesizes the reply sentence-by-sentence and
    plays through a sounddevice OutputStream so audio starts after the first sentence and
    stop_speaking() can cut it mid-reply. Blocks until the reply finishes or is stopped. `voice`/
    `speed` None → resolve from the active persona / settings; a provided value overrides (used by
    speak_with for the MCP). Returns True if it handled playback (including an early stop); raises
    on any failure so the caller can fall back to the simple blocking kokoro path, then to `say`."""
    global _ACTIVE_PLAYER
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

    # Synthesize the first chunk up front: it gives us Kokoro's real sample rate (so the
    # OutputStream isn't hard-coded to 24 kHz) AND becomes the seed so we don't synthesize it twice.
    samples, sample_rate = kokoro.create(chunks[0], voice=voice, speed=speed)
    seed = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)

    player = _StreamingPlayer(kokoro, voice, speed, int(sample_rate))
    _ACTIVE_PLAYER = player
    try:
        player.play(chunks[1:], seed=seed)  # worker synthesizes the rest; seed plays first
        return True
    finally:
        _ACTIVE_PLAYER = None
