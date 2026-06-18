"""Semantic end-of-turn detection (voice-upgrade loop 4).

Replaces a blunt fixed-silence end-of-turn wait with a LOCAL model that decides whether the user
is actually DONE talking, from the acoustics of their speech (intonation/rhythm), not just silence.

Model: **pipecat-ai/smart-turn-v3** (`smart-turn-v3.0.onnx`) — a Whisper-Tiny encoder + a shallow
linear classifier head, ~8M params, int8 ONNX (~8 MB), BSD-2-clause. It takes the last ~8 s of
16 kHz mono audio and emits ONE logit; sigmoid(logit) = P(the turn is COMPLETE).

Everything here is LAZY and FULLY GUARDED. Nothing is imported or downloaded unless
turn_detection=="smart_turn" and `is_complete()` is actually called. ANY failure (missing
huggingface_hub, download error, onnxruntime error, bad audio) raises a SmartTurnUnavailable so the
caller can fall back to the existing fixed-silence behavior — the daemon must run with or without
this model present.

Preprocessing mirrors pipecat-ai/smart-turn's `inference.py` (WhisperFeatureExtractor(chunk_length=8),
padding to 8 s, do_normalize=True), reimplemented in pure numpy so we don't add the heavy
`transformers` dependency. Cross-checked numerically against transformers' WhisperFeatureExtractor
(see scripts/smart_turn_probe.py) — max feature delta < 1e-4, identical probabilities.
"""

import os

import numpy as np

# Whisper feature-extractor constants (feature_size=80, n_fft=400, hop=160 @ 16 kHz).
SAMPLE_RATE = 16_000
N_FFT = 400
HOP_LENGTH = 160
N_MELS = 80
MAX_SECONDS = 8
MAX_SAMPLES = MAX_SECONDS * SAMPLE_RATE  # 128000 → 800 mel frames

_MODEL_REPO = "pipecat-ai/smart-turn-v3"
_MODEL_FILE = "smart-turn-v3.0.onnx"

_SESSION = None      # cached onnxruntime.InferenceSession
_MEL_FILTERS = None  # cached (80, 201) slaney mel filterbank


class SmartTurnUnavailable(Exception):
    """Raised when the smart-turn model can't be loaded or run, so the caller falls back."""


def _cache_dir() -> str:
    d = os.path.expanduser("~/.cache/vox/smart-turn")
    os.makedirs(d, exist_ok=True)
    return d


def _model_path() -> str:
    """Ensure smart-turn-v3.0.onnx is in ~/.cache/vox/smart-turn/ (download once); return its path."""
    path = os.path.join(_cache_dir(), _MODEL_FILE)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    try:
        from huggingface_hub import hf_hub_download
    except Exception as exc:  # huggingface_hub missing
        raise SmartTurnUnavailable(f"huggingface_hub unavailable: {exc}") from exc
    try:
        src = hf_hub_download(_MODEL_REPO, _MODEL_FILE)
        # Copy into our own cache dir so the model lives at the documented path regardless of HF cache.
        import shutil
        tmp = path + ".part"
        shutil.copyfile(src, tmp)
        os.replace(tmp, path)
    except Exception as exc:
        raise SmartTurnUnavailable(f"smart-turn download failed: {exc}") from exc
    return path


def _get_session():
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    try:
        import onnxruntime as ort
    except Exception as exc:
        raise SmartTurnUnavailable(f"onnxruntime unavailable: {exc}") from exc
    try:
        path = _model_path()
        so = ort.SessionOptions()
        so.inter_op_num_threads = 1
        so.intra_op_num_threads = 1
        _SESSION = ort.InferenceSession(path, sess_options=so, providers=["CPUExecutionProvider"])
    except SmartTurnUnavailable:
        raise
    except Exception as exc:
        raise SmartTurnUnavailable(f"onnx session init failed: {exc}") from exc
    return _SESSION


# --- Whisper-compatible log-mel features (pure numpy) -----------------------------------------

def _hz_to_mel_slaney(freq: np.ndarray) -> np.ndarray:
    f_min, f_sp = 0.0, 200.0 / 3
    mels = (freq - f_min) / f_sp
    min_log_hz, min_log_mel = 1000.0, (1000.0 - f_min) / f_sp
    logstep = np.log(6.4) / 27.0
    above = freq >= min_log_hz
    with np.errstate(divide="ignore"):  # freq=0 bin → log(0); masked out by `above` anyway
        log_part = min_log_mel + np.log(np.where(above, freq, min_log_hz) / min_log_hz) / logstep
    mels = np.where(above, log_part, mels)
    return mels


def _mel_to_hz_slaney(mels: np.ndarray) -> np.ndarray:
    f_min, f_sp = 0.0, 200.0 / 3
    freqs = f_min + f_sp * mels
    min_log_hz, min_log_mel = 1000.0, (1000.0 - f_min) / f_sp
    logstep = np.log(6.4) / 27.0
    above = mels >= min_log_mel
    freqs = np.where(above, min_log_hz * np.exp(logstep * (mels - min_log_mel)), freqs)
    return freqs


def _mel_filterbank() -> np.ndarray:
    """80-band slaney-normalized mel filterbank, matching transformers' mel_filter_bank
    (num_frequency_bins=201, fmin=0, fmax=8000, norm='slaney', mel_scale='slaney')."""
    global _MEL_FILTERS
    if _MEL_FILTERS is not None:
        return _MEL_FILTERS
    num_freq_bins = N_FFT // 2 + 1  # 201
    fft_freqs = np.linspace(0.0, SAMPLE_RATE / 2.0, num_freq_bins)
    mel_min, mel_max = _hz_to_mel_slaney(np.array([0.0])), _hz_to_mel_slaney(np.array([8000.0]))
    mel_points = np.linspace(mel_min[0], mel_max[0], N_MELS + 2)
    freq_points = _mel_to_hz_slaney(mel_points)

    filters = np.zeros((N_MELS, num_freq_bins), dtype=np.float64)
    diff = np.diff(freq_points)
    for m in range(N_MELS):
        lower = (fft_freqs - freq_points[m]) / diff[m]
        upper = (freq_points[m + 2] - fft_freqs) / diff[m + 1]
        filters[m] = np.maximum(0.0, np.minimum(lower, upper))
    # Slaney normalization: scale each filter by 2/(f[m+2]-f[m]).
    enorm = 2.0 / (freq_points[2:N_MELS + 2] - freq_points[:N_MELS])
    filters *= enorm[:, None]
    _MEL_FILTERS = filters
    return _MEL_FILTERS


def _zero_mean_unit_var(waveform: np.ndarray) -> np.ndarray:
    """do_normalize=True — per-utterance zero-mean unit-variance on the raw waveform."""
    return (waveform - waveform.mean()) / np.sqrt(waveform.var() + 1e-7)


def _log_mel_features(waveform: np.ndarray) -> np.ndarray:
    """Whisper-style log-mel: returns (80, 800) float32 for an 8 s, 128000-sample input."""
    window = np.hanning(N_FFT + 1)[:-1].astype(np.float64)  # periodic Hann (matches torch.hann_window)
    # Center-padded STFT with reflect padding, power spectrogram, drop the final frame (Whisper).
    padded = np.pad(waveform, (N_FFT // 2, N_FFT // 2), mode="reflect")
    n_frames = 1 + (len(padded) - N_FFT) // HOP_LENGTH
    frames = np.lib.stride_tricks.as_strided(
        padded,
        shape=(N_FFT, n_frames),
        strides=(padded.strides[0], HOP_LENGTH * padded.strides[0]),
    )
    spec = np.fft.rfft(frames * window[:, None], axis=0)
    magnitudes = (np.abs(spec) ** 2)[:, :-1]  # drop last frame → (201, 800)

    mel_spec = _mel_filterbank() @ magnitudes
    log_spec = np.log10(np.maximum(mel_spec, 1e-10))
    log_spec = np.maximum(log_spec, log_spec.max() - 8.0)
    log_spec = (log_spec + 4.0) / 4.0
    return log_spec.astype(np.float32)


def _to_mono_float(audio, sample_rate: int) -> np.ndarray:
    """Normalize int16/float audio at `sample_rate` to a mono float32 array at 16 kHz."""
    a = np.asarray(audio)
    if a.ndim > 1:
        a = a.mean(axis=1)
    if np.issubdtype(a.dtype, np.integer):
        a = a.astype(np.float32) / 32768.0
    else:
        a = a.astype(np.float32)
    if sample_rate != SAMPLE_RATE:  # cheap linear resample (mic is 16 kHz already; this is a safety net)
        n = int(round(len(a) * SAMPLE_RATE / sample_rate))
        if n <= 0:
            raise SmartTurnUnavailable("audio too short to resample")
        a = np.interp(np.linspace(0, len(a), n, endpoint=False), np.arange(len(a)), a).astype(np.float32)
    return a


def _prepare_input(audio, sample_rate: int) -> np.ndarray:
    """Replicate pipecat's inference.py: take the last 8 s, do_normalize, log-mel → (1, 80, 800)."""
    a = _to_mono_float(audio, sample_rate)
    if a.size > MAX_SAMPLES:
        a = a[-MAX_SAMPLES:]
    a = _zero_mean_unit_var(a)
    if a.size < MAX_SAMPLES:  # right-pad with zeros to exactly 8 s (padding="max_length")
        a = np.pad(a, (0, MAX_SAMPLES - a.size))
    feats = _log_mel_features(a.astype(np.float64))
    return feats[None, :, :].astype(np.float32)


def probability_complete(audio, sample_rate: int = SAMPLE_RATE) -> float:
    """P(the user's turn is COMPLETE) in [0,1] for the given recent audio. Raises
    SmartTurnUnavailable on any model/inference problem so the caller can fall back to fixed silence."""
    session = _get_session()
    try:
        feats = _prepare_input(audio, sample_rate)
        logit = session.run(None, {"input_features": feats})[0]
        logit = float(np.asarray(logit).reshape(-1)[0])
        return 1.0 / (1.0 + float(np.exp(-logit)))
    except SmartTurnUnavailable:
        raise
    except Exception as exc:
        raise SmartTurnUnavailable(f"smart-turn inference failed: {exc}") from exc


def is_complete(audio, sample_rate: int = SAMPLE_RATE, threshold: float = 0.5) -> bool:
    """True if smart-turn judges the turn complete (probability_complete >= threshold)."""
    return probability_complete(audio, sample_rate) >= threshold
