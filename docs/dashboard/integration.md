# Dashboard Integration (existing daemon ↔ web bridge)

> Iteration 1 — the **integration agent** owns all additive edits to the existing voice daemon
> so it can host and be driven by the dashboard. Everything here is additive and **fully
> guarded**: the macOS voice daemon must keep working even if `vox.web.*` is missing or raises.
> Follows `docs/dashboard/CONTRACT.md` exactly (paths, labels, routes, data shapes, signatures).

## Files touched (existing files — integration agent only)

| File | Change |
|------|--------|
| `src/vox/config.py` | Added `dashboard_enabled`, `dashboard_host`, `dashboard_port`, `open_dashboard_phrases`. Removed nothing. |
| `src/vox/wakeword/backends.py` | `make_backend` (whisper backend) now includes the `("dashboard", cfg.open_dashboard_phrases)` wake label. |
| `src/vox/core/loop.py` | Starts the web server in the background on startup (guarded); handles the `"dashboard"` wake label by opening the browser. |
| `src/vox/assistant.py` | Records usage after each provider call (lazy, guarded); reads brain provider/model via `settings_store.get(...)` with Config fallback. |

## Contract details honoured

### config.py
```python
dashboard_enabled: bool = True
dashboard_host: str = "127.0.0.1"
dashboard_port: int = 8765
open_dashboard_phrases: tuple[str, ...] = (
    "open dashboard", "open the dashboard", "show dashboard",
    "launch dashboard", "open vox dashboard",
)
```

### backends.py
The whisper wake backend's label list gained one entry:
```python
("dashboard", cfg.open_dashboard_phrases),
```
`be.match("open dashboard") == "dashboard"` (also "show dashboard please", "launch dashboard now", …).
The openwakeword backend is untouched (it only maps trained per-phrase models).

### core/loop.py
- **Startup:** after models load, `_start_dashboard(cfg, out)` calls
  `vox.web.server.start_in_background(cfg)` — but **only if `cfg.dashboard_enabled`**, and inside a
  `try/except`. A missing/broken `vox.web` package logs (in debug) and is otherwise a no-op; the
  daemon proceeds normally.
- **Wake handling:** a `"dashboard"` label from the idle wake loop calls `_open_dashboard(cfg, out)`
  → `webbrowser.open("http://{dashboard_host}:{dashboard_port}")`, prints a line, and **stays idle**
  (mirrors the existing one-shot `do:` handling — it does not enter a mode). Also guarded.

### assistant.py
- **Brain selection override.** `_brain(name)` now reads each field through `_setting(key, fallback)`:
  ```python
  _setting("small_brain_provider", CONFIG.small_brain_provider)
  _setting("small_brain_model",    CONFIG.small_brain_model)
  _setting("big_brain_provider",   CONFIG.big_brain_provider)
  _setting("big_brain_model",      CONFIG.big_brain_model)
  ```
  `_setting` does a lazy guarded `from vox.web import settings_store; settings_store.get(key)`.
  `None` (unset) **or any exception/missing module** → the Config fallback. So dashboard toggles
  take effect on the **next** LLM call without a restart, and the daemon is unchanged when the
  store is absent.
- **Usage recording.** Each provider/look function is timed and calls `_record_usage(...)` on
  success, which lazily does `from vox.web import usage; usage.record_usage(...)`. Mapping to the
  contract's `UsageEvent`:

  | provider fn | `provider` | `kind` | tokens source |
  |-------------|-----------|--------|---------------|
  | `_anthropic` | `anthropic` | `chat` | `resp.usage.input_tokens / output_tokens` |
  | `_openai` | `openai` | `chat` | `resp.usage.prompt_tokens / completion_tokens` |
  | `_claude_sdk` | `claude_sdk` | `chat` | SDK `ResultMessage.usage` dict if present, else `None` (subscription → cost 0) |
  | `_claude_cli` | `claude_cli` | `chat` | `None` (CLI doesn't surface tokens → subscription) |
  | `_sdk_look` | `claude_sdk` | `vision` | SDK usage dict if present, else `None` |
  | `_anthropic_look` | `anthropic` | `vision` | `resp.usage.input_tokens / output_tokens` |

  `record_usage` is called with keyword args matching the contract `UsageEvent` shape:
  ```python
  usage_mod.record_usage(
      provider=..., model=..., brain="small"|"big", kind="chat"|"vision",
      input_tokens=<int|None>, output_tokens=<int|None>, latency_ms=<float>,
  )
  ```
  `id` and `ts` are assigned by `usage.py`; `costUsd` is computed there from `PRICES`. `None`
  tokens signal a subscription call (the usage store renders cost as subscription per the contract).
  `_record_usage` swallows **all** exceptions — telemetry never breaks a reply.

  `complete()` and `look()` thread `brain` (and `kind` for `complete`) into the provider functions
  so each usage record is correctly tagged small vs big. `_claude_cli` accepts the extra params for a
  uniform call signature even though it records subscription-only usage.

## How the daemon stays safe if the web package fails

Every touch point uses a **lazy import inside a guard**:
- `loop._start_dashboard` / `loop._open_dashboard` → `try/except`, debug-logged, non-fatal.
- `assistant._setting` → `try/except` returning the Config fallback.
- `assistant._record_usage` → `try/except: pass` (telemetry only).

There are **no top-level imports of `vox.web`** in any of the four files. So if `vox/web/` is
missing, half-built, or raises on import, the voice daemon runs exactly as before — only the
dashboard convenience is unavailable.

## What `vox.web` must provide (consumed by this integration; built by other agents)

- `vox.web.server.start_in_background(cfg)` — start uvicorn in a daemon thread (CONTRACT "File layout").
- `vox.web.usage.record_usage(*, provider, model, brain, kind, input_tokens, output_tokens, latency_ms)`
  — persist a `UsageEvent` (assign `id`/`ts`, compute `costUsd` from `PRICES`, push to WS subscribers).
- `vox.web.settings_store.get(key)` — return the override for `key` or `None` if unset.

These names/signatures are what the integration calls; sibling agents implement them per the contract.

## How to verify (this part)

```bash
# 1. Static + guarded-degradation (web modules may be absent):
uv run python - <<'PY'
import vox.config as c, vox.assistant as a, vox.core.loop as loop
cfg = c.CONFIG
assert (cfg.dashboard_enabled, cfg.dashboard_host, cfg.dashboard_port) == (True, "127.0.0.1", 8765)
assert "open dashboard" in cfg.open_dashboard_phrases
class O:  # noqa
    def emit(self,*a,**k): pass
loop._start_dashboard(cfg, O())                 # no raise when vox.web.server missing
a._record_usage("anthropic","m","small","chat",(1,2),3.0)   # no-op when vox.web.usage missing
assert a._brain("small") == (cfg.small_brain_provider, cfg.small_brain_model)  # Config fallback
print("integration guards OK")
PY

# 2. Wake phrase routing:
uv run python - <<'PY'
import vox.config as c
from vox.wakeword.backends import WhisperWakeBackend
cfg = c.CONFIG
be = WhisperWakeBackend([("dashboard", cfg.open_dashboard_phrases)], None, cfg, "p")
assert be.match("open dashboard") == "dashboard"
print("wake routing OK")
PY
```

Both blocks pass with `vox.web` containing only `axtree.py` (no server/usage/settings_store yet).

## TODOs for later iterations
- **Iteration 2** builds `vox.web.usage` (PRICES, `record_usage`, `recent`, `summary`, WS) — must
  accept the keyword signature above. SDK token extraction here is best-effort
  (`ResultMessage.usage` dict); refine once the live SDK shape is confirmed.
- **Iteration 3** builds `vox.web.settings_store` (`SCHEMA`, `get`/`set`/`all`). Once present, the
  Settings page's brain provider/model selects drive `_brain` live. Other flags
  (`escalate_to_big_brain`, `llm_executor_enabled`, `screen_vision_enabled`, `tts_enabled`,
  `barge_in_enabled`, `dictation_exit_on_silence`, `debug`) still read straight from `Config`; the
  contract assigns wiring those at their call sites (`executor.py`, `actions.py`, `loop.py`,
  `tts.py`) to the integration agent in a **later** iteration — not done in iteration 1 (foundation).
- `kind` is currently `"chat"`/`"vision"` only; `"command"`/`"rewrite"` tagging can be threaded
  through `executor`/text-rewrite call sites in a later iteration.
- `vox.web.server.start_in_background` must be non-blocking (daemon thread) so daemon startup isn't
  delayed; the guard tolerates it raising but not it blocking.
