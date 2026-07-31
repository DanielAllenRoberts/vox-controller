# Vox Controller — Structure / Packaging / Non-Core Audit

Date: 2026-07-02 · Scope: everything around the Python core (`src/vox/` internals are audited separately). READ-ONLY.
Branch audited: `command-db`. All facts below verified with `git ls-files` / `git status` / `git check-ignore`.

---

## TL;DR

**Overall repo health: good.** The scary-looking artifacts at the repo root are all correctly
**untracked and gitignored** — there is **no active leak** and no secret was ever committed. The real
gaps are about **shipping** this as an open-source download, not hygiene.

### Leak/security posture (checked first, per public-repo rule)
- `vox.log` (1.8 MB), `vox-capture.wav` (381 KB), `.env`, `.DS_Store`, `data/` — **all NOT tracked**
  (`git ls-files --error-unmatch` → NOT TRACKED; `git check-ignore` confirms the rules).
- **Git history is clean**: `.env` / `*.wav` / `*.log` / `*.db` were never committed on any branch.
- **No secrets in tracked files**: grep for `absolute home paths`, `employer domains`, `sk-…`/`sk-ant-`/`AKIA…` → **zero hits**.
- `.env` (local only) holds live keys incl. `LOCAL_AI1` / `LOCAL_AI1_URL` (a private home-GPU Cloudflare tunnel). Correctly ignored. This is exactly the value that must never slip into a commit.
- **Residual risk (Low):** a future `git add -A` of a *new* artifact type not covered by `.gitignore`, or a `git add -f`, is the only realistic path to a leak. The `.gitignore` is currently thorough.

### Top 5 issues (ranked)
1. **[Leak — Low residual, listed first]** Sensitive-but-ignored artifacts live *inside the working tree* (`.env` w/ live keys + private tunnel URL, `data/` w/ personal memory & usage, `vox.log`, `vox-capture.wav`). Nothing is leaking today; keep the `.gitignore` guard and never `git add -f`.
2. **[Med-High] Not distributable to end users.** No macOS `.app` bundle, no code signing / notarization, no permission entitlements (mic / Accessibility / Screen Recording). Today it's `uv run vox` from a source checkout only.
3. **[Med] Frontend not packaged.** The wheel ships only `src/vox`; `web/server.py` locates `dashboard/dist` via a **repo-relative** path (`parents[3]`), so an installed package can't serve the UI. No automated frontend build step either.
4. **[Med] Runtime paths assume a source checkout.** `data/` and `log_file="vox.log"` are CWD/repo-root relative; model downloads (~250 MB Whisper + optional ~353 MB Kokoro) land in `~/.cache/vox` on first use with no first-run UX. Fine for dev, wrong for a shipped app.
5. **[Low-Med] No `LICENSE` file** (blocker for an OSS release) + **stale README** (claims "M0 … no actions yet" and a clean `{wakeword,stt,io,core}` layout that no longer matches reality) + docs sprawl.

**Corrections to the audit brief:** two premises were wrong on inspection —
(a) `dashboard/dist/` is **NOT committed** (ignored by `dashboard/.gitignore: dist/`; `git ls-files dashboard/dist` → 0);
(b) the pyproject entry points are **NOT broken** — `src/vox/core/loop.py` defines `main()` (line 708) and `src/vox/diagnose.py` defines `main()` (line 45); `src/vox/__main__.py` imports from `vox.core.loop`. `vox/core/` exists.

---

## Findings by area

### 1. Repo hygiene & layout — **Low (actually a strength)**

Top-level (`ls -la`): `.DS_Store`, `.env`, `.env.example`, `.gitignore`, `.python-version`, `.playwright-mcp/`, `.venv/`, `CLAUDE.md`, `README.md`, `dashboard/`, `data/`, `docs/`, `mcp/`, `pyproject.toml`, `scripts/`, `src/`, `uv.lock`, `vox-capture.wav`, `vox.log`. **172 tracked files.**

- **The "scary" root artifacts are all ignored & untracked** (verified): `vox.log`, `vox-capture.wav`, `.env`, `.DS_Store`, `data/`, `.venv/`, `.playwright-mcp/`, `dashboard/dist/`, `dashboard/node_modules/`, `*.tsbuildinfo`, all `__pycache__/`. `git status --ignored` confirms.
- **`data/` is untracked** (`git ls-files data/` → empty) but on disk holds real personal data: `commands.db`, `memory/core.md`, `memory.jsonl`, `usage.jsonl` (60 KB), `personalities.json`, `reminders.json`, `settings.json`, `vox.pid`. Correctly ignored; no commit risk.
- **`CLAUDE.md` is gitignored** (`.gitignore:12`) and **not tracked** — deliberate ("local working instructions, kept out of the public repo"). Consequence: OSS contributors won't receive the behavioral guidelines. Conscious tradeoff; fine, just flagging.
- **Minor untidiness:** `log_file = "vox.log"` (config.py:85) is a *relative* path, so the 1.8 MB log is written into the repo root (CWD) at runtime; `vox-capture.wav` likewise. They're ignored, but they clutter the working tree.

**Fix:** none required for safety. Optional tidy: default `log_file` and capture scratch into `data/` or `logs/` (both already ignored) so the repo root stays clean.

### 2. `dashboard/` (Vite + React frontend) — **Low org / Med dist-coupling**

- Stack: Vite 6 · React 18 · TypeScript 5.7 · Tailwind 3 · Radix UI (shadcn-style) · TanStack Query · react-router · recharts · motion. `package-lock.json` committed (reproducible builds — good).
- Layout is clean: `src/{components (37), pages (12), hooks (5), lib (2)}` + `App.tsx` / `main.tsx`. `lib/api.ts` is a single typed fetch client that mirrors `docs/dashboard/CONTRACT.md`.
- **`dist/` is NOT committed** (contrary to the brief) — ignored by `dashboard/.gitignore`. It exists on disk (`index.html` + `assets/`) as a local build artifact. Correct.
- **Backend boundary (clean):** FastAPI bridge at `src/vox/web/server.py`, `127.0.0.1:8765` (config `dashboard_port`). Serves REST under `/api`, WS at `/api/usage/stream` + `/api/conversation/stream`, and the built `dashboard/dist` as a static SPA at `/`. Dev: Vite `:5173` proxies `/api` → `127.0.0.1:8765` (`vite.config.ts`); `api.ts` uses `VITE_API_BASE` (empty in prod → same-origin). The bridge is heavily guarded ("the voice daemon must never break because of the dashboard") — good.
- **Concern (dist coupling):** `server.py` resolves `_DIST_DIR = parents[3]/dashboard/dist` — repo-relative. It works from a source checkout but breaks once `vox` is pip/uv-installed (see area 5). No `npm run build` is wired into any Python build step.

**Fix:** add a build step that runs `npm ci && npm run build` and copies `dist/` into the Python package (e.g. `src/vox/web/static/`), and resolve it via `importlib.resources` rather than `parents[3]`.

### 3. `mcp/vox_speak_server.py` — **Low (clean)**

- A tiny FastMCP **stdio** server (idea #34) exposing two tools: `speak(text, voice, rate)` and `announce_done(summary, voice)` — lets an IDE assistant (Cursor / Claude Code) talk out loud.
- **Reuses the core, does not duplicate it:** imports `vox.tts.speak_with` and `vox.web.settings_store`, with a graceful bare-`say` fallback if the `vox` package isn't importable, and a no-op off macOS. Voice/engine are read live from the dashboard settings store, kept deliberately distinct from the system voice.
- `mcp/README.md` documents Cursor/Claude-Code wiring well. `mcp/__pycache__/` present but ignored.

**Fix:** none. Only coupling is the `from vox …` imports, which work when launched from repo root via `uv run` (as documented).

### 4. `scripts/` and `data/` — **Low / Low-Med**

- `scripts/aec_probe.py` (does macOS Voice Processing clean the mic?) and `scripts/smart_turn_probe.py` (verifies `vox.turn_detector`). Both are clearly-labeled one-shot **dev verification prototypes** tied to the VOICE_UPGRADE loops. `aec_probe` is standalone; `smart_turn_probe` imports `vox.turn_detector`. Reasonable to keep. `scripts/__pycache__/` ignored.
- `data/` is the runtime store (SQLite + JSON + memory markdown). Correctly gitignored; not tracked. For a *shipped* app it should live in a per-user dir (`~/Library/Application Support/vox` or `~/.local/share/vox`), not the repo root.

**Fix:** keep `scripts/` (optionally move under `dev/` or note "dev-only" in a scripts README). For distribution, route `data/` through a platform data-dir helper.

### 5. Packaging & distribution — **Med-High**

- `pyproject.toml`: name `vox`, v0.0.1, `requires-python >=3.12,<3.13`, hatchling build, wheel packages `src/vox`. `uv.lock` (96 KB) committed, `.python-version = 3.12`, `[tool.uv] environments = ["sys_platform == 'darwin'"]`.
- **Entry points resolve (correction):** `vox = "vox.core.loop:main"` ✓ (loop.py:708) and `vox-diagnose = "vox.diagnose:main"` ✓ (diagnose.py:45). Package is a **hybrid**: ~20 flat modules (`actions.py`, `assistant.py`, `executor.py`, `audio.py`, `memory.py`, `scheduler.py`, …) **plus** subpackages `core/`, `io/`, `stt/`, `wakeword/`, `web/`.
- **Distribution gaps for end users:**
  1. **No app bundle / signing / notarization.** It's `uv sync && uv run vox` from source. Gatekeeper + TCC permissions can't be pre-granted to a raw terminal run.
  2. **macOS permissions:** mic (AVFoundation), **Accessibility** (AX click/keystroke — `ax.py`), **Screen Recording** (vision). All are TCC prompts; a `uv run` grants them to the *terminal*, not to "Vox". No `Info.plist`/entitlements.
  3. **Model downloads on first use:** Whisper `small.en` (~250 MB), openWakeWord, optional Kokoro (~353 MB), smart-turn (~8 MB) → `~/.cache/vox`. No first-run progress/offline story.
  4. **Frontend not shipped** (see area 2): wheel excludes `dashboard/dist`; `server.py` path is repo-relative.
  5. **Runtime data path** `data/` is CWD-relative (won't exist for an installed app).
  6. **No `LICENSE` file** (verified: none tracked) — a blocker for an open-source release. **No CI/release workflow**, still v0.0.1.

**Fix (ship path):** add `LICENSE`; bundle the built frontend into the package; resolve model/data/log dirs via platform paths; wrap into a signed+notarized `.app` (e.g. `py2app`/`briefcase`) with an `Info.plist` declaring the mic/AX/screen usage strings; add a first-run permissions + model-download flow; add a release workflow.

### 6. Docs organization — **Low-Med**

- 51 tracked docs + 1 untracked (`docs/plan/meetings.md`). Two big trees: `docs/plan/` (29 files incl. `research/` and `research/voice-agents/`) and `docs/dashboard/` (22 files incl. `research/`).
- **Coherent where it counts:** all 9 README-linked `docs/plan/*` files exist; `docs/dashboard/CONTRACT.md` is a live API contract that `api.ts` mirrors.
- **But heavy & log-like:** several huge files — `ideas.md` 54 KB, `dashboard/BUILD_LOG.md` 56 KB, `dashboard/backend.md` 54 KB, `dashboard/frontend.md` 50 KB — plus `session-2026-06-19*.md`, `buildlog`. This reads as an internal design/build journal more than user docs.
- **Stale README:** `README.md` still says *"M0 scope … No actions yet — opening apps arrives in M1"* and *"copy env when you reach M4"*, and shows only `src/vox/{wakeword,stt,io,core}` + `audio.py` + `config.py` — while the real app already has actions, assistant, executor, TTS, scheduler, command DB, vision, dashboard, and MCP. (Layout mismatch is also being flagged by the core agent — kept brief here.)

**Fix:** refresh README (status, actual layout, real getting-started). Consider splitting `docs/` into `docs/design` (journals/research) vs `docs/user` (install & usage) before publishing.

### 7. Config & secrets — **Low (a strength)**

- `config.py` is a `@dataclass(frozen=True)` of **plain, non-secret** values. Secrets are referenced **by env-var name only** (`llm_api_key_env="DEEPSEEK_API_KEY"`, `anthropic_key_env`, `local_ai_key_env="LOCAL_AI1"`, `local_ai_base_url_env="LOCAL_AI1_URL"`) and read from `.env` at runtime. **No secret values in tracked code.** Good pattern for a public repo.
- `.env` (ignored, verified) key names: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `DEEPSEEK_API_KEY`, `LOCAL_AI1`, `LOCAL_AI1_URL`. `dashboard/.env` (ignored) holds only `VITE_API_BASE` (not secret).
- **`.env.example` is slightly out of sync:** it lists `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `ELEVENLABS_API_KEY` but **omits `LOCAL_AI1` and `LOCAL_AI1_URL`**, which `config.py` actually reads. Contributors enabling `local_ai` won't know which vars to set.
- **Personal defaults committed** (not secrets, just personal): `tts_voice="Daniel"`, `browser="Arc"`, MCP voices. Harmless; could default to `""`/system for neutrality.

**Fix:** add `LOCAL_AI1` / `LOCAL_AI1_URL` (+ any `dashboard/.env` var) to `.env.example`; optionally neutralize personal defaults.

---

## Distribution readiness checklist (open-source download)

- [ ] Add a `LICENSE` file (currently none).
- [ ] Refresh `README.md` (status, real layout, real install/usage).
- [ ] Bundle the built dashboard into the Python package; resolve via `importlib.resources`, not `parents[3]`.
- [ ] Add a frontend build step to the release pipeline (`npm ci && npm run build`).
- [ ] Route `data/`, logs, and model caches through per-user platform dirs (not CWD/repo).
- [ ] First-run UX: request mic / Accessibility / Screen Recording; download models with progress.
- [ ] Wrap into a signed + notarized macOS `.app` (py2app / briefcase) with `Info.plist` usage strings + entitlements.
- [ ] Add CI (lint/build/typecheck) + a tagged release workflow; bump from v0.0.1.
- [ ] Sync `.env.example` with all env vars the code reads.

## Quick wins

- Add `LICENSE`.
- Sync `.env.example` (add `LOCAL_AI1`, `LOCAL_AI1_URL`).
- Refresh the README status + project-layout block.
- Point `log_file` / capture scratch at `data/` or `logs/` so the repo root stays clean.
- Add a one-line "dev-only" note (or move to `dev/`) for `scripts/`.

## Larger efforts

- Package + serve the frontend from the installed wheel.
- Per-user data/model/log paths + first-run permission & model-download flow.
- Signed/notarized `.app` bundle with entitlements.
- Split `docs/` into design-journal vs user-facing docs.
- CI + release automation.
