"""Microphone capture. Yields fixed-size int16 frames from the default input device."""

import queue
from collections import deque

import numpy as np
import sounddevice as sd


class MicStream:
    """Streams mono int16 audio frames from the microphone via a callback queue."""

    def __init__(self, sample_rate: int, frame_samples: int, device: int | None = None):
        self._sample_rate = sample_rate
        self._frame_samples = frame_samples
        self._device = device
        self._queue: "queue.Queue[np.ndarray]" = queue.Queue()
        self._stream = self._make_stream()

    def _make_stream(self):
        return sd.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self._frame_samples,
            device=self._device,
            callback=self._callback,
        )

    def _callback(self, indata, frames, time_info, status) -> None:
        # indata: shape (frame_samples, 1) int16 — copy out of the driver buffer.
        self._queue.put(indata[:, 0].copy())

    def frames(self):
        """Generator yielding one int16 frame at a time. Healthy streams deliver a frame every
        ~80 ms (even silence), so if nothing arrives for a few seconds the input stalled (e.g. the
        audio device changed) — restart it so Vox keeps listening instead of hanging silently."""
        while True:
            try:
                yield self._queue.get(timeout=3.0)
            except queue.Empty:
                print("⚠️  mic input stalled — restarting the audio stream…")
                self._restart()

    def _restart(self) -> None:
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass
        try:
            self._stream = self._make_stream()
            self._stream.start()
        except Exception as exc:
            print(f"⚠️  couldn't restart mic stream ({exc}); will retry…")

    def flush(self) -> None:
        """Drop buffered frames (e.g. audio captured while Vox was speaking) so the next read
        starts fresh — stops Vox from hearing and re-processing its own TTS."""
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass

    def __enter__(self) -> "MicStream":
        self._stream.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stream.stop()
        self._stream.close()


class VPIOMicStream:
    """Mic capture via the native macOS VoiceProcessingIO audio unit (voice-upgrade loop 5 / R7).

    Drop-in replacement for `MicStream` — SAME interface (constructor signature, `frames()`
    generator yielding 16 kHz mono int16 frames of `frame_samples`, `flush()`, context manager).
    The difference is the capture path: an `AVAudioEngine` with `setVoiceProcessingEnabled(True)`
    on its input node, which turns on the system's acoustic echo canceller + AGC + noise suppression
    referencing the speaker output. That cancels Vox's own TTS (and other speaker audio) from the
    mic, so Vox stops hearing itself (fixes O1 on speakers + O7).

    Implementation: PyObjC + AVFoundation, imported LAZILY in __init__ (nothing native loads unless
    audio_aec is on). The input node's native format (typically 48 kHz float32) is tapped; each tap
    buffer is resampled to 16 kHz mono float32 via an `AVAudioConverter`, converted to int16, sliced
    into exact `frame_samples` frames, and pushed onto a queue the `frames()` generator drains — so
    downstream code sees byte-identical frames to the sounddevice backend.

    Construction raises if PyObjC/AVFoundation is unavailable or the engine fails to start (e.g. mic
    permission denied); `open_mic_stream` catches that and falls back to the sounddevice MicStream.
    """

    def __init__(self, sample_rate: int, frame_samples: int, device: int | None = None):
        # device is accepted for interface parity; VPIO uses the system default input node.
        self._sample_rate = sample_rate
        self._frame_samples = frame_samples
        # Lazy import — only on the AEC path. Any ImportError propagates to the caller's fallback.
        import AVFoundation as AV

        self._queue: "queue.Queue[np.ndarray]" = queue.Queue()
        # Carries leftover int16 samples between tap callbacks so we can emit exact frame_samples frames.
        self._residual = np.empty(0, dtype=np.int16)
        self._residual_lock = __import__("threading").Lock()

        self._engine = AV.AVAudioEngine.alloc().init()
        self._input = self._engine.inputNode()

        ok, err = self._input.setVoiceProcessingEnabled_error_(True, None)
        if not ok:
            raise RuntimeError(f"setVoiceProcessingEnabled failed: {err}")

        # Voice processing DUCKS other audio output (it treats the session like a call) — that's why
        # the speakers go quiet while AEC is on ("loud then softer"). Set ducking to its MINIMUM level
        # so AEC keeps cancelling echo WITHOUT noticeably dimming playback. Guarded: older macOS lacks
        # this API (macOS 14+), and a failure just means the (louder) default ducking stays.
        try:
            duck = AV.AVAudioVoiceProcessingOtherAudioDuckingConfiguration(
                False, AV.AVAudioVoiceProcessingOtherAudioDuckingLevelMin)
            self._input.setVoiceProcessingOtherAudioDuckingConfiguration_(duck)
        except Exception as exc:
            print(f"⚠️  couldn't lower AEC audio ducking ({exc}); speakers may dim while AEC is on")

        self._in_fmt = self._input.outputFormatForBus_(0)
        if self._in_fmt is None or self._in_fmt.sampleRate() == 0:
            raise RuntimeError("VPIO input node has no valid format (mic unavailable?)")
        self._in_sr = float(self._in_fmt.sampleRate())
        self._in_ch = max(1, int(self._in_fmt.channelCount()))
        self._in_interleaved = bool(self._in_fmt.isInterleaved())

        # The input node delivers float32 at the hardware rate, and this device exposes it as MULTIPLE
        # channels (e.g. 6ch @ 48 kHz). We take channel 0 (the primary, echo-cancelled mic) and
        # down-sample to 16 kHz ourselves in numpy (see _resample_to_16k). The previous AVAudioConverter
        # asked it to do 6→1 channels AND 48k→16k in ONE step, which it refused (returned status=Error →
        # all-zero frames: the "AEC captures nothing" bug); doing it directly is simpler and robust.
        self._install_tap()

    def _install_tap(self) -> None:
        def tap_block(buffer, when):
            try:
                frames_in = buffer.frameLength()
                if frames_in == 0:
                    return
                channels = buffer.floatChannelData()
                if channels is None:
                    return
                # Take channel 0 (the primary, echo-cancelled mic). Non-interleaved → channel 0 is a
                # contiguous block of `frames_in` floats; interleaved → stride by the channel count.
                if self._in_interleaved and self._in_ch > 1:
                    inter = np.frombuffer(channels[0].as_buffer(frames_in * self._in_ch * 4),
                                          dtype=np.float32, count=frames_in * self._in_ch)
                    mono = inter[0::self._in_ch].astype(np.float32)
                else:
                    mono = np.frombuffer(channels[0].as_buffer(frames_in * 4),
                                         dtype=np.float32, count=frames_in).astype(np.float32)
                mono = self._resample_to_16k(mono)
                if mono.size == 0:
                    return
                # float32 [-1,1] -> int16, matching sounddevice's int16 capture.
                i16 = np.clip(mono * 32768.0, -32768, 32767).astype(np.int16)
                self._emit(i16)
            except Exception as exc:  # never let an exception escape into the CoreAudio render thread
                print(f"⚠️  VPIO tap error ({exc}); continuing…")

        self._input.installTapOnBus_bufferSize_format_block_(0, 4096, self._in_fmt, tap_block)

    def _resample_to_16k(self, mono: np.ndarray) -> np.ndarray:
        """Down-sample channel-0 float32 audio from the input node's rate to the target 16 kHz. For an
        integer ratio (typically 48k→16k = 3) this box-averages each group of `factor` samples — a
        cheap anti-aliasing decimation that's ample for speech — otherwise it linearly resamples."""
        in_sr, target = self._in_sr, float(self._sample_rate)
        if in_sr == target or mono.size == 0:
            return mono
        factor = in_sr / target
        nearest = int(round(factor))
        if nearest >= 1 and abs(factor - nearest) < 1e-6:  # exact integer ratio (e.g. 48k→16k = 3)
            m = (mono.size // nearest) * nearest
            if m == 0:
                return np.empty(0, dtype=np.float32)
            return mono[:m].reshape(-1, nearest).mean(axis=1).astype(np.float32)
        n = int(round(mono.size * target / in_sr))  # non-integer ratio → linear resample
        if n <= 0:
            return np.empty(0, dtype=np.float32)
        return np.interp(np.linspace(0, mono.size, n, endpoint=False),
                         np.arange(mono.size), mono).astype(np.float32)

    def _emit(self, i16: np.ndarray) -> None:
        """Buffer incoming samples and slice them into exact frame_samples int16 frames."""
        fs = self._frame_samples
        with self._residual_lock:
            buf = np.concatenate((self._residual, i16)) if self._residual.size else i16
            n_full = buf.size // fs
            for k in range(n_full):
                self._queue.put(buf[k * fs:(k + 1) * fs].copy())
            self._residual = buf[n_full * fs:].copy()

    def frames(self):
        """Generator yielding one 16 kHz mono int16 frame at a time (mirrors MicStream.frames).
        On a multi-second stall the VPIO engine is restarted so Vox keeps listening."""
        while True:
            try:
                yield self._queue.get(timeout=3.0)
            except queue.Empty:
                print("⚠️  VPIO mic input stalled — restarting the audio engine…")
                self._restart()

    def _restart(self) -> None:
        try:
            self._engine.stop()
            self._input.removeTapOnBus_(0)
        except Exception:
            pass
        try:
            self._install_tap()
            self._engine.startAndReturnError_(None)
        except Exception as exc:
            print(f"⚠️  couldn't restart VPIO engine ({exc}); will retry…")

    def flush(self) -> None:
        """Drop buffered frames (e.g. audio captured while Vox was speaking)."""
        with self._residual_lock:
            self._residual = np.empty(0, dtype=np.int16)
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass

    def __enter__(self) -> "VPIOMicStream":
        ok, err = self._engine.startAndReturnError_(None)
        if not ok:
            raise RuntimeError(f"VPIO engine failed to start: {err}")
        return self

    def __exit__(self, *exc) -> None:
        try:
            self._engine.stop()
            self._input.removeTapOnBus_(0)
        except Exception:
            pass


def open_mic_stream(cfg):
    """Open the mic backend chosen by config, with a hard fallback to the sounddevice MicStream.

    When `cfg.audio_aec` is true, try the native VoiceProcessingIO backend (system AEC). On ANY
    failure — PyObjC missing, mic permission denied, engine/tap/convert error — log a warning and
    fall back to the sounddevice `MicStream`, so the daemon never loses its mic. Default
    (`audio_aec` false) returns the sounddevice MicStream directly — byte-for-byte today's behavior.

    Returns an UNSTARTED stream; the caller enters it as a context manager exactly like MicStream.
    """
    if _setting("audio_aec", cfg.audio_aec):
        try:
            stream = VPIOMicStream(cfg.sample_rate, cfg.frame_samples, cfg.input_device)
            print("🎙️  mic: native VoiceProcessingIO (AEC) backend active")
            return stream
        except Exception as exc:
            print(f"⚠️  VPIO/AEC mic unavailable ({exc}); falling back to sounddevice mic")
    return MicStream(cfg.sample_rate, cfg.frame_samples, cfg.input_device)


def rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))


def _setting(key: str, fallback):
    """Read a runtime override from the dashboard's settings_store, else fall back. Fully guarded
    (mirrors loop/tts/assistant._setting): if vox.web.settings_store is missing or errors, return
    the fallback so capture behaves exactly as before. Lets dashboard toggles apply without restart."""
    try:
        from vox.web import settings_store
        val = settings_store.get(key)
        return fallback if val is None else val
    except Exception:
        return fallback


def _smart_turn_complete(collected, cfg) -> bool | None:
    """Ask the smart-turn model whether the turn captured so far is COMPLETE (loop 4).

    Returns True (complete → end now), False (incomplete → keep listening), or None on ANY problem
    (model unavailable / inference error) so the caller falls back to fixed-silence endpointing. Fully
    lazy + guarded: vox.turn_detector is imported only here, only on the smart_turn path."""
    try:
        from vox import turn_detector
        audio = np.concatenate(collected)
        return turn_detector.is_complete(audio, cfg.sample_rate)
    except Exception:
        return None  # SmartTurnUnavailable or anything else → fall back to fixed silence


def capture_utterance(frames, cfg, silence_seconds=None, listen_timeout=None):
    """Wait for speech onset (keeping a short pre-roll), then record until trailing
    silence. Returns int16 audio, or None if no speech arrives within listen_timeout.

    `silence_seconds` overrides how long a pause ends the utterance (default: cfg value).
    `listen_timeout` overrides how long to wait for speech to start (default: cfg value) —
    used to be more patient when Vox has just asked the user a question.
    """
    sr, fs = cfg.sample_rate, cfg.frame_samples
    sil = cfg.silence_seconds if silence_seconds is None else silence_seconds
    wait = cfg.listen_timeout_seconds if listen_timeout is None else listen_timeout
    silence_limit = int(sil * sr / fs)
    max_frames = int(cfg.max_utterance_seconds * sr / fs)
    wait_frames = int(wait * sr / fs)

    # Semantic turn-detection (loop 4): when turn_detection=="smart_turn", a trailing pause of
    # >= min_endpointing_delay triggers the smart-turn model on the audio so far. COMPLETE ends the
    # turn now; INCOMPLETE keeps listening up to max_endpointing_delay (a hard cap). DEFAULT "vad"
    # and ANY smart-turn error use the fixed silence_limit logic below, unchanged.
    smart_on = _setting("turn_detection", cfg.turn_detection) == "smart_turn"
    min_silent = max(1, int(_setting("min_endpointing_delay", cfg.min_endpointing_delay) * sr / fs))
    max_silent = max(min_silent, int(_setting("max_endpointing_delay", cfg.max_endpointing_delay) * sr / fs))

    pre_roll = deque(maxlen=cfg.preroll_frames)
    waited = 0
    while True:
        frame = next(frames)
        if rms(frame) >= cfg.speech_rms:
            break
        pre_roll.append(frame)
        waited += 1
        if waited >= wait_frames:
            return None

    collected = list(pre_roll) + [frame]
    silent = 0
    next_check = min_silent  # next trailing-silence frame-count at which to consult smart-turn
    while len(collected) < max_frames:
        frame = next(frames)
        collected.append(frame)
        if rms(frame) < cfg.speech_rms:
            silent += 1
            if smart_on:
                if silent >= max_silent:
                    break  # hard cap — end even if the model keeps saying INCOMPLETE
                if silent >= next_check:
                    done = _smart_turn_complete(collected, cfg)
                    if done is None:           # model unavailable/errored → fall back to fixed silence
                        smart_on = False
                        if silent >= silence_limit:
                            break
                    elif done:                 # model says the turn is COMPLETE → end now
                        break
                    else:                      # INCOMPLETE → keep listening, re-check after another min delay
                        next_check = silent + min_silent
            elif silent >= silence_limit:
                break
        else:
            silent = 0
            next_check = min_silent  # speech resumed → reset the smart-turn re-check cadence
    return np.concatenate(collected)
