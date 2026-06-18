"""Read-only system + configuration health snapshot for the dashboard bridge.

Dashboard iteration 7. A single ``snapshot()`` that gathers a lightweight,
read-only picture of the running voice daemon: process CPU / memory / uptime,
the configured STT (whisper) model, the small/big brain provider+model, the TTS
setup, and a platform string. The dashboard polls this to render a "system
health" panel alongside live usage.

Design guarantees (same contract as the rest of ``vox.web``):
- **Never raises.** Every probe is independently guarded; on any failure that
  field degrades to a zero / "unknown" sentinel rather than propagating. The
  voice daemon must keep working even if every probe fails.
- **Self-contained.** No new dependencies and no imports of other ``vox.web``
  modules at import time — ``vox.stats`` (already a dep via ``psutil``),
  ``settings_store``, and the frozen ``Config`` are all read lazily inside the
  guarded probes so importing this module can never break the server boot.
- **Read-only.** Nothing here mutates config, settings, or any file.

Public API: ``snapshot() -> dict``. The shape (camelCase to match the other
``/api`` responses) is::

    {
      "capturedAt": str,                       # ISO-8601 UTC
      "platform": str,                         # e.g. "macOS-14.5-arm64 / CPython 3.12.3"
      "process": {"cpuPercent": float, "memMb": float, "uptimeSeconds": float},
      "stt":  {"model": str, "computeType": str, "sampleRate": int},
      "smallBrain": {"provider": str, "model": str},
      "bigBrain":   {"provider": str, "model": str},
      "tts":  {"enabled": bool, "voice": str},
    }

Any field that can't be read falls back to ``0`` / ``"unknown"`` (or ``False`` /
``""`` for the booleans/strings where that reads better).
"""

from __future__ import annotations

import platform as _platform
from datetime import datetime, timezone

# Import-time monotonic anchor — a last-resort uptime baseline if the process
# creation time can't be read (non-psutil platforms, sandboxes). It measures
# "since this module was first imported", which for the daemon is effectively
# process start since the web bridge is wired up during startup.
_IMPORTED_AT = __import__("time").monotonic()


def _process_health() -> dict:
    """Return ``{cpuPercent, memMb, uptimeSeconds}`` for this process.

    CPU + memory reuse ``vox.stats.process_stats()`` (which primes the CPU%
    counter at its import) when present; else a direct ``psutil`` read; else
    zeros. Uptime prefers ``psutil`` create-time, falling back to the import-time
    monotonic anchor. Each piece is guarded independently so one failure doesn't
    zero the others.
    """
    cpu_percent = 0.0
    mem_mb = 0.0
    try:
        from .. import stats

        cpu_percent, mem_mb = stats.process_stats()
    except Exception:
        try:
            import psutil

            proc = psutil.Process()
            cpu_percent = proc.cpu_percent(interval=None)
            mem_mb = proc.memory_info().rss / 1e6
        except Exception:
            cpu_percent, mem_mb = 0.0, 0.0

    uptime_seconds = 0.0
    try:
        import time as _time

        import psutil

        uptime_seconds = max(0.0, _time.time() - psutil.Process().create_time())
    except Exception:
        try:
            import time as _time

            uptime_seconds = max(0.0, _time.monotonic() - _IMPORTED_AT)
        except Exception:
            uptime_seconds = 0.0

    return {
        "cpuPercent": round(_as_float(cpu_percent), 1),
        "memMb": round(_as_float(mem_mb), 1),
        "uptimeSeconds": round(_as_float(uptime_seconds), 1),
    }


def _platform_string() -> str:
    """Human-readable OS + Python string, e.g. ``macOS-14.5-arm64 / CPython 3.12.3``."""
    try:
        os_part = _platform.platform(aliased=True, terse=True)
    except Exception:
        os_part = "unknown"
    try:
        py_part = f"{_platform.python_implementation()} {_platform.python_version()}"
    except Exception:
        py_part = "unknown"
    if os_part == "unknown" and py_part == "unknown":
        return "unknown"
    return f"{os_part} / {py_part}"


def _cfg_get(key: str, default):
    """Read an effective setting via ``settings_store`` (override → Config), and
    if that whole path fails, fall back to the frozen ``Config`` default, then to
    ``default``. Never raises."""
    try:
        from . import settings_store

        value = settings_store.get(key)
        if value is not None:
            return value
    except Exception:
        pass
    try:
        from ..config import CONFIG

        value = getattr(CONFIG, key, None)
        if value is not None:
            return value
    except Exception:
        pass
    return default


def _brain(prefix: str) -> dict:
    """Resolve a brain's ``{provider, model}`` (settings_store → Config → unknown)."""
    return {
        "provider": _as_str(_cfg_get(f"{prefix}_provider", "unknown"), "unknown"),
        "model": _as_str(_cfg_get(f"{prefix}_model", "unknown"), "unknown"),
    }


def _stt() -> dict:
    """Configured STT (faster-whisper) model, compute type, and sample rate."""
    return {
        "model": _as_str(_cfg_get("whisper_model", "unknown"), "unknown"),
        "computeType": _as_str(_cfg_get("whisper_compute_type", "unknown"), "unknown"),
        "sampleRate": _as_int(_cfg_get("sample_rate", 0), 0),
    }


def _tts() -> dict:
    """TTS enabled flag + configured voice (empty string = system default)."""
    return {
        "enabled": bool(_cfg_get("tts_enabled", False)),
        "voice": _as_str(_cfg_get("tts_voice", ""), ""),
    }


# --- Small coercion helpers: keep the response types stable even if a probe
# hands back something unexpected (e.g. a setting override of the wrong type). --

def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_str(value, default: str = "unknown") -> str:
    try:
        if value is None:
            return default
        return str(value)
    except Exception:
        return default


def snapshot() -> dict:
    """Return a read-only health snapshot (see module docstring for the shape).

    Never raises: every section is independently guarded and degrades to
    zeros / "unknown" on failure.
    """
    captured_at = "unknown"
    try:
        captured_at = datetime.now(timezone.utc).isoformat()
    except Exception:
        pass

    def _safe(fn, fallback):
        try:
            return fn()
        except Exception:
            return fallback

    return {
        "capturedAt": captured_at,
        "platform": _safe(_platform_string, "unknown"),
        "process": _safe(
            _process_health,
            {"cpuPercent": 0.0, "memMb": 0.0, "uptimeSeconds": 0.0},
        ),
        "stt": _safe(
            _stt, {"model": "unknown", "computeType": "unknown", "sampleRate": 0}
        ),
        "smallBrain": _safe(
            lambda: _brain("small_brain"),
            {"provider": "unknown", "model": "unknown"},
        ),
        "bigBrain": _safe(
            lambda: _brain("big_brain"),
            {"provider": "unknown", "model": "unknown"},
        ),
        "tts": _safe(_tts, {"enabled": False, "voice": ""}),
    }


if __name__ == "__main__":  # python -m vox.web.diagnostics — quick manual check
    import json

    print(json.dumps(snapshot(), indent=2))
