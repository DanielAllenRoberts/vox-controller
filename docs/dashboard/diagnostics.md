# Diagnostics — `src/vox/web/diagnostics.py`

Dashboard iteration 7. A single read-only **system + configuration health
snapshot** of the running voice daemon, for a "system health" panel on the
dashboard alongside the live usage stream.

> Scope: this doc and `src/vox/web/diagnostics.py` only. Additive — it imports
> nothing from the rest of `vox.web` at module load and never mutates anything,
> so it cannot affect the voice daemon.

## Public API

```python
from vox.web import diagnostics

diagnostics.snapshot() -> dict   # never raises
```

There is **one** function. It gathers a lightweight, read-only picture and
returns it as a plain dict (camelCase fields, matching the other `/api`
responses). It is **guaranteed never to raise** — every probe is independently
guarded and degrades to a `0` / `"unknown"` sentinel on failure.

## Response shape

```jsonc
{
  "capturedAt": "2026-06-18T06:34:59.482628+00:00", // ISO-8601 UTC
  "platform": "macOS-26.3.1 / CPython 3.12.13",     // OS (terse) + Python impl/version
  "process": {
    "cpuPercent": 12.4,        // % since last process_stats() call (float, 1dp)
    "memMb": 210.7,            // resident set size in MB (float, 1dp)
    "uptimeSeconds": 3847.2    // process uptime in seconds (float, 1dp)
  },
  "stt": {                     // configured faster-whisper STT
    "model": "small.en",
    "computeType": "int8",
    "sampleRate": 16000
  },
  "smallBrain": { "provider": "openai",     "model": "deepseek-chat" },
  "bigBrain":   { "provider": "claude_sdk", "model": "claude-opus-4-8" },
  "tts": { "enabled": true, "voice": "Daniel" }   // voice "" = system default
}
```

### Degraded snapshot (every probe failed)

Same shape, sentinels instead of values — still never raises:

```jsonc
{
  "capturedAt": "…",
  "platform": "unknown",
  "process":    { "cpuPercent": 0.0, "memMb": 0.0, "uptimeSeconds": 0.0 },
  "stt":        { "model": "unknown", "computeType": "unknown", "sampleRate": 0 },
  "smallBrain": { "provider": "unknown", "model": "unknown" },
  "bigBrain":   { "provider": "unknown", "model": "unknown" },
  "tts":        { "enabled": false, "voice": "" }
}
```

## How each field is sourced

| Field | Source | Fallback chain |
|-------|--------|----------------|
| `process.cpuPercent` / `memMb` | `vox.stats.process_stats()` | → direct `psutil.Process()` read → `0.0` |
| `process.uptimeSeconds` | `psutil.Process().create_time()` (true process age) | → module-import monotonic anchor → `0.0` |
| `platform` | `platform.platform(terse=True)` + `python_implementation()/version()` | → `"unknown"` |
| `stt.*` | `whisper_model`, `whisper_compute_type`, `sample_rate` | settings_store → Config → sentinel |
| `smallBrain` / `bigBrain` | `{small,big}_brain_{provider,model}` | settings_store → Config → `"unknown"` |
| `tts.*` | `tts_enabled`, `tts_voice` | settings_store → Config → `false` / `""` |

Config reads go through a helper (`_cfg_get`) that asks `settings_store.get(key)`
first (so a live dashboard override wins, matching `/api/status` and the
settings page), then falls back to the frozen `Config` default, then to a
hard-coded sentinel. Small `_as_float/_as_int/_as_str` coercers keep the
response types stable even if a setting override has an unexpected type.

## Design notes

- **Never raises.** `snapshot()` wraps each section in a `_safe(fn, fallback)`
  guard; the inner probes are guarded too. A total failure yields the degraded
  snapshot above, never an exception.
- **Self-contained / lazy.** No new dependencies. `vox.stats`, `psutil`,
  `settings_store`, and `Config` are all imported **inside** the probes, so
  importing `diagnostics` has zero side effects and can't break server boot.
  (Verified: importing the module pulls in none of those at module load.)
- **`cpuPercent` first-sample caveat.** `process_stats()` returns CPU% *since the
  previous call*. `vox.stats` primes the counter at its own import, so during the
  long-running daemon the value is meaningful. A snapshot taken from a fresh
  `python -m vox.web.diagnostics` process may show a large first reading — that's
  the priming artifact, not a real spike.
- **Read-only.** Nothing here writes config, settings, or files.

## Not wired into the server (yet)

This module is **standalone** for iteration 7. It is **not** yet mounted on a
route — `src/vox/web/server.py` is owned by the integration/bridge agent.

To expose it later (one guarded route, mirroring the existing `axtree`/`memory`
pattern in `server.py`), an integration iteration would add:

```python
@app.get("/api/diagnostics")
def get_diagnostics() -> dict:
    mod = _try_import("diagnostics")
    if mod is None:
        return {"error": "diagnostics module not available"}
    try:
        return mod.snapshot()
    except Exception as exc:  # snapshot() shouldn't raise, but never 500
        return {"error": f"diagnostics failed: {exc}"}
```

…and the frontend would add a matching `DiagnosticsSnapshot` type in
`dashboard/src/lib/api.ts`. Both files are owned by other agents, so this
iteration leaves them untouched.

## How to verify

```bash
# Live snapshot (pretty-printed JSON):
.venv/bin/python -m vox.web.diagnostics

# Programmatic:
.venv/bin/python -c "from vox.web import diagnostics, json; print(diagnostics.snapshot())"
```

Resilience (forcing every probe import to fail still returns the degraded shape
and never raises) is exercised in the iteration-7 verification run.
