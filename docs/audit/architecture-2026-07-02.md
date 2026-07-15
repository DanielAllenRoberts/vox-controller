# Vox Controller — Python Core Architecture Audit

**Date:** 2026-07-02
**Scope:** `src/vox/` (the Python daemon + embedded dashboard bridge). Read-only analysis; no source modified.
**Branch:** `command-db`

---

## 0. Correction to the audit brief (verify-before-assert)

Several premises in the tasking were inaccurate against the actual tree, so this report audits the *real* code:

- **The package is NOT flat.** `src/vox/` contains subpackages `core/`, `web/`, `stt/`, `wakeword/`, `io/` in addition to the flat modules. The single biggest module is **`web/server.py` (1333 LOC)**, not `actions.py`.
- **Real size is ~10,800 LOC, not ~6k.** Flat modules total 6,128; the subpackages add 4,683 (chiefly `web/` at 3,485 and `core/loop.py` at 860).
- **The entry points RESOLVE.** `pyproject.toml` maps `vox = vox.core.loop:main` and `vox-diagnose = vox.diagnose:main`; both targets exist (`core/loop.py:708`, `diagnose.py:45`). They are **not** broken.
- **`command_store` vs `command_cache` are NOT two overlapping command systems.** `command_cache` is an in-memory caching *facade* over the SQLite `command_store` — clean layering (see §Findings D).
- **The real "second config system" is `web/settings_store.py` vs `config.py`** — an intentional runtime-override layer, not a duplicate (see §Findings D).
- The README's `src/vox/{wakeword,stt,io,core}/` layout does exist, but the doc is stale in other ways (omits `web/`, still says "M0 scope … No actions yet"). See §Findings F.

---

## TL;DR

**Overall health: good-to-strong for a solo research codebase, with real but bounded structural debt.** The core is unusually well-engineered for its stage: a crisp state-machine daemon (`core/loop.py`), a resilient "additive + lazy-guarded" design where every optional subsystem (dashboard, scheduler, command-DB, Kokoro TTS, smart-turn, AEC) fails soft so the voice loop always runs, and several exemplary modules (`memory.py`, `ax.py`, `audio.py`, `turn_detector.py`). There are no true circular imports — the pervasive function-local imports both provide the guard *and* break would-be cycles. The debt is concentrated in two god-modules, a lot of copy-pasted cross-cutting glue, and — most importantly for the stated open-source distribution goal — a filesystem-path assumption that breaks when the package is installed as a wheel, plus a complete absence of automated tests behind ~131 silent exception swallows.

**Top 5 issues (ranked):**

1. **No test suite + ~131 silent `except Exception` swallows** → regressions are structurally invisible. *(High)*
2. **Runtime data paths use `Path(__file__).parents[2|3]/"data"` (9 copies)** → breaks when installed as a wheel; blocks the open-source download-distribution direction. *(High)*
3. **Two god-modules: `web/server.py` (1333) and `actions.py` (1174)** — mixing routing/content/adapters and 12 responsibilities respectively; ~200 lines of now-cold-path duplicated AppleScript in `actions`. *(Med-High)*
4. **Heavy duplication of cross-cutting glue**: `_setting()` ×6, `normalize()` ×2 ("MUST stay identical"), `resolve()` ×2, repo-root path walk ×9, WS pub/sub machinery ×2, permission-error boilerplate ×8. *(Med)*
5. **Latent hot-loop hazards**: no-timeout `subprocess.run` for `screencapture`/`sips`/`open` on the synchronous voice thread; unlocked `command_cache` globals reassigned by the web thread mid-`resolve()`. *(Med)*

---

## Architecture map

### Layering (dependencies point downward; `web/*` is a lazy-guarded side-car)

```
                       ┌──────────────────────────────────────────┐
  ORCHESTRATION        │  core/loop.py  (daemon state machine)      │
                       │  IDLE → control / assistant / dictation    │
                       └───────┬───────────────┬───────────────────┘
                               │               │
  ROUTING              ┌───────▼───────┐        │
                       │  dispatch.py  │  "one place all modes route through"
                       └───┬───────┬───┘        │
                           │       │            │
  BRAIN            ┌───────▼──┐ ┌──▼───────────▼──┐
                   │ executor │ │   assistant.py   │  (LLM providers, memory/persona
                   │  .py     │ │  respond_turn /  │   injection, [OPEN]/[DONE]/[BIG])
                   └────┬─────┘ │  complete / look │
                        │       └──────┬───────────┘
  CAPABILITIES   ┌──────▼──────────────▼───────────────────────────┐
                 │ actions │ scheduler │ memory │ command_cache→store │
                 │  (+ ax) │           │        │  (SQLite)           │
                 └──────┬──────────────────────────────────────────┘
  I/O            ┌──────▼───────────────────────────────────────────┐
                 │ audio (MicStream/VPIO) │ stt/whisper │ tts │       │
                 │ turn_detector │ wakeword/backends │ sounds │       │
                 └──────┬───────────────────────────────────────────┘
  LEAF INFRA     ┌──────▼───────────────────────────────────────────┐
                 │ config (frozen CONFIG) │ stats │ io/console │ ax   │
                 └──────────────────────────────────────────────────┘

  SIDE-CAR (additive; core imports it LAZILY + guarded, it imports core LAZILY):
        web/{server(uvicorn thread), settings_store, usage, conversation,
             personalities, rules, commands, axtree, diagnostics}
```

### Control flow (one utterance)

```
mic frames ─► wakeword.WhisperWakeBackend.listen ─► label
   ("control"|"assistant"|"dictation"|"do:<cmd>"|"quit"|"restart"|"dashboard")
        │
   core/loop.main state machine ─► _control_mode / _assistant_mode / _dictation_mode
        │  capture_utterance ─► WhisperTranscriber.transcribe
        ▼
   dispatch.try_deterministic(text)                     ── returns (acted,msg) | None
        1. what-app?      (instant)
        2. scheduler      (timers/alarms/reminders create·cancel·read)
        3. command-DB     (command_cache.resolve; gated, off by default)
        4. actions.parse ─► actions.handle   (regex → osascript/AX)
        │
        └─ None ─► escalate:
                     control/one-shot ─► executor.execute ─► assistant.complete
                                          (translate-to-command: TYPE/EDIT/LOOK/
                                           CLICK/SCHEDULE/DICTATE/command) ─► actions.*
                     assistant chat    ─► assistant.respond_turn (LLM)
        ▼
   tts.speak ─► mic.flush ─► loop._record_turn ─► web.conversation (ephemeral feed)
```

**Import-graph health:** No true circular imports. `executor`→`{actions,assistant}` and `dispatch`→`actions` are eager, but `actions` imports `assistant`/`ax` only lazily (`actions.py:475,484,500,576`), and `command_store` imports `actions` only inside `seed()` (`command_store.py:207`). The core↔web relationship is genuinely bidirectional (core reads `web.settings_store`/`conversation`/`personalities`/`rules`/`usage`; web reads `config`/`memory`/`scheduler`/`command_store`) but is fully decoupled at load time by lazy imports, which is what keeps the daemon bootable without the web package.

---

## Findings

### A. Module boundaries & responsibilities

**A1. `actions.py` is a 12-responsibility god-module. — Med-High**
1,174 lines, ~54 top-level functions spanning intent parsing, osascript plumbing, app/URL navigation, environment sensing, AX clicking, tab/window/desktop/profile switching, sidebar control, dashboard-window management, dictation/text insertion, and LLM handoff. Natural split seams exist along those clusters, with `_osa`-based osascript plumbing (`actions.py:228`) as the shared base extraction. Why it matters: the file is CONTROL mode's entire surface, and result-string wording is now load-bearing coupling (see A5). *Fix: extract `intent/parser`, `osa`, `nav`, `context`, `tabs`, `windows`, `dictation`, `dashboard` submodules under an `actions/` package, starting with the osascript layer.*

**A2. `web/server.py` is a borderline god-module. — Med-High**
1,333 lines; ~40 routes all defined as closures inside a single ~630-line `create_app()` (`server.py:121-750`), plus **~250 lines of hardcoded handbook prose** (`_handbook_static`, `server.py:999-1224`) that is content, not server logic, plus cross-module adapters (`_job_to_api` `:773`, `_mcp_config` `:822`, memory tier shims `:786-819`). Why it matters: everything-in-one-function inhibits navigation and testing. *Fix: split into `APIRouter` modules per feature group; move the handbook catalog to a data file (JSON/Markdown) loaded at startup.*

**A3. Most other modules are cohesive and correctly sized.** `executor.py` (translate-to-command LLM executor), `dispatch.py` (shared deterministic router), `scheduler.py` (timers/alarms/reminders), `memory.py`, `audio.py`, `tts.py`, `turn_detector.py`, `ax.py`, `command_store.py`/`command_cache.py`, `config.py`, `focus_watch.py`, and the `stt`/`wakeword`/`io` Protocol seams are each single-purpose. This is the codebase's strength.

### B. Core control flow & mode separation

**B1. The two modes are cleanly separated. — Good**
`core/loop.py` owns the mode *loops* (`_control_mode` `:332`, `_assistant_mode` `:440`, `_dictation_mode` `:583`); `dispatch.try_deterministic` (`dispatch.py:111`) is the single shared deterministic layer both modes call first; `executor.execute` is the control/one-shot LLM path; `assistant.respond_turn` is the chat path. `assistant.py` is purely the provider-agnostic LLM layer (+ memory/persona/rules injection). There is no logic bleed between the mode loops and the brain — a clean split.

**B2. `core/loop.py` barge-in / interrupt handling is intricate but well-factored. — Good (with a caution)**
`_run_interruptible` (`:233`) and `_speak_interruptible` (`:283`) run blocking LLM/TTS work on worker threads while the main thread keeps capturing, returning a small `(result, interrupt)` protocol. It's genuinely complex (redirect/sleep/quit/restart mid-call) but each branch is documented and gated. *Caution: an abandoned LLM thread finishes in the background and its result is silently dropped (`:238`) — acceptable, but it means a slow provider call keeps a thread + tokens alive after the user moved on.*

**B3. `os._exit(0)` on quit/restart/mic-death is deliberate and correct.** `core/loop.py:842,850,854` skip `MicStream.__exit__` to dodge a documented CoreAudio teardown deadlock. Well-reasoned; keep the comments.

### C. Coupling & testability

**C1. No automated tests exist. — High**
There is no `tests/` directory and no pytest config in `pyproject.toml` (the only `test_*.py` are inside `.venv`). The closest thing is `command_store.py`'s built-in `_selftest`/`_BATTERY` (`command_store.py:386-417`) and REPL — a good pattern, but it covers one module. For a ~10.8k-LOC codebase heading toward public distribution this is the single largest risk. *Fix: add a `tests/` suite starting with the pure, side-effect-free seams that are already test-shaped — `wakeword.normalize`/`phrase_match`, `scheduler` NL parsing (`_digitize`, `parse_and_create`), `memory` parse/score/recall, `assistant.split_say`/`_split_signal`, `executor._parse_pick`, `command_store` resolution, `tts._split_chunks`, `turn_detector` (already cross-validated in `scripts/`).* 

**C2. ~131 `except Exception:` swallows hide failures. — High (compounds C1)**
Verified via grep: 131 bare `except Exception:` blocks, concentrated in `web/server.py` (25), `memory.py` (12), `web/diagnostics.py` (11), `ax.py` (10), `assistant.py` (10); broader forms (`except (A,B):`, `except X as e:`) push the true count higher (~46 in `server.py` alone). This is a deliberate "the daemon must never crash / the dashboard must never 500" philosophy and is *appropriate at the outer boundary of each optional subsystem*, but it is applied so widely that a real bug in a store is indistinguishable from an empty result (e.g. `server.py:206-209`). *Fix: keep the outer guard, but log the swallowed exception (even at debug) instead of silent `pass`, and tighten inner `try` scopes so only the truly-optional call is guarded.*

**C3. Global singleton state is broad but mostly justified. — Low-Med**
Process-wide mutable singletons: `CONFIG` (frozen — fine), `assistant._anthropic_client`/`_openai_clients` (`assistant.py:61-62`), `tts._ACTIVE_PLAYER`/`_KOKORO` (`tts.py:149,228`), `command_cache._BASE`/`_APP_CACHE`/`_ACTION_INTENTS` (`command_cache.py:26-29`), `scheduler._THREAD`, `focus_watch._THREAD`, and the on-disk `settings_store` overrides. Most are lazy caches with clear ownership. The one with a real thread-safety gap is `command_cache` (see E2). Import-time side effects are minimal and benign (`config.py:342` `CONFIG=Config()`; `stats.py` primes `psutil` at import; `web/diagnostics.py:45` records an import timestamp).

**C4. `cfg` is threaded through the loop, but capabilities read the `CONFIG` global directly.** `core/loop` passes `cfg` explicitly (testable), but `actions`/`assistant`/`executor`/`scheduler`/`tts`/`audio` import and read `CONFIG` at module scope — so they can't be exercised against an alternate config without monkeypatching. Minor, but worth noting for C1.

### D. State & data management

**D1. `config.py` (frozen defaults) + `web/settings_store.py` (runtime overrides) is a coherent two-layer model. — Good, with a DRY smell**
`config.py:342` is one frozen `Config()` dataclass — an exhaustively documented single source of truth. `settings_store.get(key)` returns `override → getattr(CONFIG, key)` (`settings_store.py:397-408`), persisted to `data/settings.json`, and the daemon reads toggleable flags through it so UI changes apply live with no restart. This is a legitimate override layer, **not** a competing config. Two smells: (a) a few keys are *schema-only* with no backing `Config` field, so `settings_store` is their sole source of truth (`memory_autocapture` `:170`, `audio_aec` `:233`) — silent-drift risk; (b) `get()` re-reads and re-parses the JSON file on **every** hot-path `_setting()` call (`:404`), i.e. a disk read + parse per setting lookup on the audio/LLM loop. *Fix: cache overrides in memory with an mtime check.*

**D2. `command_store` → `command_cache` is clean cache-over-SQLite. — Good**
`command_store.py` owns the schema/seed/read-API for `data/commands.db`; `command_cache.py` loads it into memory (base at boot, per-app on focus change) so the hot path never hits SQLite (`command_cache.py:51-93`). The safety-floor design (mode/system commands stay hardcoded in the loop even though they're seeded) is sound. *One duplication: `command_store.resolve` (`:353`) and `command_cache.resolve` (`:125`) both re-implement the exact→contains→regex walk — the cache version even comments "Mirrors command_store.resolve".* Consolidate to one matcher used by both.

**D3. `memory.py` is exemplary. — Good**
Tiered, human-editable Markdown store, one process-wide `RLock` (`:59`), a documented "read never raises" invariant, stable line-hash ids that survive hand-edits, and a one-time idempotent JSONL→Markdown migration. This is the model the rest of the persistence layer should follow.

**D4. Persistence idioms are re-implemented per module.** The atomic `tmp.replace` write appears independently in `scheduler.py:133-139`, `settings_store.py:389-394`, `personalities.py`, `rules.py`; each also re-derives `_DATA_DIR`. See D-adjacent quick win in §Quick wins.

### E. Error handling, logging & concurrency

**E1. Threading model is broad but generally careful. — Good**
Live threads: main voice loop; uvicorn dashboard thread (`server.py:1321`); scheduler (`scheduler.py:632`); focus-watch (`focus_watch.py:23`); mic-recovery daemon thread (`audio.py:94`); barge-in/speak worker threads (`loop.py:257,309`); Kokoro synth+playback threads (`tts.py:298`). Shared JSON stores use `RLock` + atomic writes; cross-thread WS fan-out correctly uses `loop.call_soon_threadsafe` (`usage.py:122`, `conversation.py:78`).

**E2. `command_cache` module globals are read/written across threads without a lock. — Med**
The web thread reassigns `_BASE`/`_APP_CACHE`/`_ACTION_INTENTS` in `refresh()` (`command_cache.py:110-119`, triggered by dashboard command edits via `web/commands.py`) while the focus thread writes `_APP_CACHE` in `on_focus` (`:88`) and the dispatch/voice thread reads them in `resolve()` (`:140-155`). CPython makes each reassignment atomic (no crash), but a multi-step `resolve` can observe a half-cleared cache mid-refresh. *Fix: guard the three globals with a lock, or snapshot them into locals at the top of `resolve`.*

**E3. No-timeout `subprocess.run` on the synchronous voice thread. — Med**
`actions.capture_screen` shells `screencapture` and `sips` with **no timeout** (`actions.py:320,323`), and `_open_url`/`_navigate` shell `open` with no timeout (`actions.py:609,615`). These run on the single voice-loop thread; a hung child process freezes the daemon (the same class of freeze the AX rewrite in `ax.py` was built to eliminate). *Fix: add a bounded `timeout=` to each, mirroring `_osa`'s 20 s default (`actions.py:228`).* Note the AppleScript click fallbacks already carry 25–30 s timeouts (`actions.py:494,585`), which is a long worst-case stall but only reached when native `vox.ax` is unavailable.

**E4. Two threads can drive the Kokoro TTS singleton at once. — Low**
`scheduler._announce` (`scheduler.py:191`) calls `tts.speak` on the scheduler thread; the voice loop also calls `tts.speak`. In the interruptible-Kokoro path both would contend for the `tts._ACTIVE_PLAYER` singleton (`tts.py:228`). Rare (interruptible TTS is off by default) but unguarded.

**E5. Latent WS-subscribe race.** The subscriber queue's target event loop is bound *after* `subscribe()` returns (`server.py:186-188`); in that window `_publish` calls `put_nowait` directly from the daemon thread onto an asyncio queue (`usage.py:118-120`). Tiny window, real. *(Low)*

### F. Consistency / stale docs

**F1. README is stale. — Low (but public-facing)**
`README.md:29-44` documents only `wakeword/stt/io/core/audio/config` and still states "M0 scope: … No actions yet — opening apps arrives in M1" (`:59`), while the app has control/assistant/dictation modes, a dashboard, scheduler, memory, command-DB, vision, and native AX. It omits `web/` and every flat capability module. The entry points it implies are correct; the layout/scope narrative is years behind. *Fix: regenerate the layout section and status.*

**F2. Two intent sources of truth in `actions.py`. — Med**
`parse()` emits intent *strings* via a ~120-line ordered regex cascade (`actions.py:90-211`), while `run_intent()` maps those strings to handlers via a dispatch dict rebuilt on each call (`actions.py:70-79`). A rename in one silently breaks the other — there's no shared enum/constant. *Fix: define the intent names once (an `IntentName` enum or a module constant) and reference both sides from it.*

**F3. Fragile string-based escalation control flow. — Med**
CONTROL-mode escalation to the LLM is decided by `failed()` doing substring checks against `_FAIL_MARKERS` (`actions.py:1158-1168`). Marker `"to click"` (`:1161`) is a very loose substring — any future result string containing "…to click…" would be misread as a failure. Result-string wording across ~30 functions is now load-bearing. *Fix: return a structured `(ok, message)` from handlers instead of sniffing prose.*

### G. Dead code / duplication (concrete)

- **~200 lines of now-cold-path AppleScript in `actions.py`.** `_CLICK_SCRIPT` (`:344-460`) and `_CLICKABLE_LIST_SCRIPT` (`:511-567`) are near-duplicate recursion engines, and both are only reached if the native `vox.ax` import fails (`actions.py:477,578`). Since `ax.py` is now the primary path, this is legacy fallback that could be slimmed or deleted once native AX is trusted. *(Med)*
- **`_setting()` copy-pasted in 6 places** — `core/loop.py:42`, `assistant.py:94`, `executor.py:22`, `tts.py:37`, `audio.py:343`, plus `dispatch.py:70-84`'s `_db_enabled` variant. Same 8–10 line guarded lazy-import block. *(Med)*
- **`normalize()` duplicated** — `wakeword/backends.py:16` and `command_store.py:317`, the latter carrying a "MUST stay identical" warning (a maintenance landmine). *(Med)*
- **Repo-root path walk duplicated ×9** — `memory.py:49`, `command_store.py:26`, `scheduler.py:48`, `core/loop.py:618`, `web/server.py:42`, `settings_store.py:27`, `personalities.py:32`, `rules.py:31`, `usage.py:34`. *(Med — and see High #2 below)*
- **WS subscriber/publish machinery duplicated verbatim** — `usage.py:85-133` and `conversation.py:42-89` ("Mirrors usage.py exactly"). *(Low)*
- **Permission-error boilerplate ×8** in `actions.py` (`:845,886,895,904,914,921,928,940,948`), with `_sidebar` re-inlining the check instead of calling `_is_perm_err`/`_perm_msg` (`:1006-1008`). *(Low)*
- **`_brain()` duplicated** — `server.py:53-58` and `diagnostics.py:133-138`. *(Low)*
- **`server._apply_suggested_voice` is a guaranteed no-op today** — it only persists a voice `if any(... key == "tts_voice" ...)` (`server.py:115`) but there is no `tts_voice` key in `settings_store._SCHEMA_META`, so the persona→voice sync at `server.py:254` does nothing. *(Low — a genuine dead branch / latent bug)*
- **Model/pricing identifiers spread across three places** — `settings_store._MODEL_OPTIONS` (`:43-50`), `usage.PRICES` (`usage.py:44-48`), and `config.py` brain defaults. A model rename must touch all three. *(Low)*
- **Redundant guard** — `server.get_budget` calls `_try_import("usage")` though `usage` is already imported unconditionally at `server.py:35`. *(Low)*

### H. The packaging/data-path bug (called out separately — High)

Every runtime store computes its data directory as `Path(__file__).resolve().parents[2 or 3] / "data"` (see the 9 sites in G). This assumes the code lives at `<repo>/src/vox/...` with a sibling `<repo>/data/`. But `pyproject.toml` declares a Hatch **wheel** build (`[tool.hatch.build.targets.wheel] packages = ["src/vox"]`). When installed as a wheel, `__file__` resolves inside `site-packages/vox/...`, so `parents[2]/data` points at a path inside (or above) `site-packages` — read-only and wrong. Every persistent feature — `commands.db`, `memory/`, `reminders.json`, `settings.json`, `usage.jsonl`, `personalities.json`, `rules.json`, `vox.pid` — would break or write to the wrong place. This directly blocks the documented open-source download-distribution direction. *Fix: introduce one `vox/paths.py` that resolves a user data dir (e.g. `~/Library/Application Support/Vox` on macOS, honoring an env override), defaulting to the repo `data/` only in a source checkout; route all stores through it.*

---

## Quick wins (cheap, high value)

1. **Add `timeout=` to the three no-timeout subprocess calls** (`actions.py:320,323,609,615`). One-line each; removes a real freeze class. *(E3)*
2. **Extract one `vox/paths.py`** and replace the 9 `parents[N]/"data"` walks. Prerequisite for distribution; also DRY. *(H, G)*
3. **Extract one shared `settings.setting(key, fallback)` helper** and delete the 6 `_setting` copies. *(G)*
4. **Have `command_store` import `normalize` from `wakeword.backends`** (or move `normalize` to a tiny `text.py` both import) to kill the "MUST stay identical" duplication. *(G)*
5. **Log swallowed exceptions at debug** instead of silent `pass` in the guarded blocks — turns 131 blind spots into diagnosable events with near-zero risk. *(C2)*
6. **Snapshot/lock `command_cache` globals in `resolve()`.** A 2-line local snapshot removes the mid-refresh torn-read. *(E2)*
7. **Regenerate the README layout + status section.** *(F1)*
8. **Move `server._handbook_static` prose (~250 lines) to a data file.** Shrinks the god-module immediately. *(A2)*

## Larger refactors (higher effort, higher payoff)

1. **Stand up a `tests/` suite** targeting the pure seams first (C1) — the highest-leverage investment; unlocks safe refactoring of everything below.
2. **Split `actions.py` into an `actions/` package** along the 12 clusters (A1), and delete/slim the cold-path AppleScript once native AX is trusted (G).
3. **Split `web/server.py` into `APIRouter` modules per feature group** (A2); consolidate the duplicated WS pub/sub into one helper (G).
4. **Introduce a shared intent identifier** (enum/const) referenced by both `parse` and `run_intent`, and move handlers to structured `(ok, message)` returns to retire the fragile `_FAIL_MARKERS` string-sniffing (F2, F3).
5. **Give `settings_store.get()` an in-memory cache with mtime invalidation** so hot-path `_setting()` reads stop hitting disk (D1).

---

## What's already good (credit where due)

- **The "additive + lazy-guarded" architecture is genuinely well done.** Dashboard, scheduler, focus-watch, command-DB, Kokoro, smart-turn, and AEC are each imported lazily and wrapped so a missing/broken subsystem can never take down the voice loop (`core/loop.py:64-121`). This also incidentally prevents import cycles. It's real resilience engineering, not accidental.
- **`core/loop.py`** — a legible state machine with thorough, honest comments explaining hard-won fixes (mic-death self-restart, CoreAudio deadlock avoidance, barge-in gating, single-instance guard). Complex domain, clean expression.
- **`memory.py`** — thread-safe, never-raises-on-read, human-editable, tiered, with stable ids and an idempotent migration. Exemplary.
- **`ax.py`** — a focused, dependency-free native Accessibility engine (~77 ms full Slack tree) that replaced the slow AppleScript path and eliminated a 25 s freeze class; the encoding rationale is documented.
- **`audio.py`** — robust mic self-heal (background re-open + watchdog restart), CoreAudio-deadlock-aware teardown, and two backends (sounddevice + native VoiceProcessingIO/AEC) behind one interface.
- **`turn_detector.py`** — a careful pure-numpy reimplementation of Whisper log-mel features, numerically cross-validated against `transformers` (per `scripts/smart_turn_probe.py`), fully lazy/guarded.
- **`config.py`** — a single frozen dataclass with outstanding inline documentation; a strong single source of truth for defaults.
- **`dispatch.py` + `executor.py`** — the "one deterministic place all three modes route through" and the provider-agnostic translate-to-command executor are elegant, genuinely reusable abstractions.
- **Protocol seams** (`io/base.py`, `stt/base.py`, `wakeword/base.py`) keep backends swappable.

---

*Prepared by static reading of the `command-db` branch working tree; every `file:line` citation was checked against the source as read.*
