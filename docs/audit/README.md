# Vox — Audit & Meetings Recon Index (2026-07-02)

Three documents produced in one pass. Start here.

| Doc | What |
|---|---|
| [`architecture-2026-07-02.md`](architecture-2026-07-02.md) | Python core (`src/vox/`) architecture audit — module boundaries, control flow, debt, quick wins. |
| [`structure-2026-07-02.md`](structure-2026-07-02.md) | Repo structure, secrets/leak posture, packaging & open-source **distribution readiness**. |
| [`../plan/research/meetily-recon.md`](../plan/research/meetily-recon.md) | Recon on **Meetily** (MIT) for the [meetings feature](../plan/meetings.md) — esp. macOS system-audio capture. |

## Overall verdict

**Healthy solo research codebase with bounded, well-understood debt.** The daemon is well-engineered (state-machine `core/loop.py`, "fail-soft/lazy-guarded" optional subsystems, no real circular imports). **Security/leak posture is clean** — every sensitive artifact (`.env`, `data/`, `vox.log`, `*.wav`) is untracked and gitignored, and git history has never contained a key or personal path. The gaps are concentrated in **(a) shippability** (the stated open-source direction) and **(b) test/observability**, not correctness-of-the-moment.

> Note: the audit briefs contained several wrong premises (that the package was flat, that entry points were broken, that `dist/` was committed, that `command_store`/`command_cache` overlapped). Both agents verified against the real code and corrected them — see each doc's "Correction" section.

## Consolidated top issues (ranked)

1. **No tests + ~131 silent `except Exception` swallows** → regressions are invisible. *(High — architecture §)*
2. **9× hardcoded `parents[2|3]/"data"` path walk** → breaks on wheel/app install; blocks distribution. *(High — both §)*
3. **No distribution story** — no `LICENSE` file (OSS blocker), no macOS `.app`/signing/notarization/entitlements (mic + Accessibility + Screen Recording), frontend `dist` found via repo-relative path. *(High — structure §)*
4. **Two god-modules**: `web/server.py` (1333) and `actions.py` (1174, ~200 lines cold-path duplicated AppleScript). *(Med-High — architecture §)*
5. **Duplicated cross-cutting glue**: `_setting()` ×6, `normalize()` ×2 ("must stay identical"), `resolve()` ×2, path-walk ×9, WS pub/sub ×2, perm-boilerplate ×8. *(Med — architecture §)*
6. **Latent hot-loop hazards**: no-timeout `subprocess.run` (screencapture/sips/open) on the sync voice thread; unlocked `command_cache` globals reassigned by the web thread mid-`resolve()`. *(Med — architecture §)*
7. **Stale README** ("M0 … no actions yet" vs a far more complete app) and sprawling docs (51 files). *(Low — structure §)*

## Cheapest high-value fixes (do these first)

- Add `timeout=` to the three bare `subprocess.run` calls in `actions.py` (320/323/609/615).
- Introduce a single `vox/paths.py` (env-var overridable data dir) and replace the 9 path walks.
- Add a `LICENSE` file (repo is already public and open-source-intended).
- Log the swallowed exceptions (even at debug) so failures stop being invisible.
- Update the README's stale M0 framing.

Larger, deliberate efforts: split the two god-modules; extract the duplicated glue into shared helpers; add a first pytest smoke suite; build the macOS packaging/entitlements story for distribution.
