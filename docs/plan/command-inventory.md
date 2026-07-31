# Command inventory — every command today, split by scope

> Companion to [`command-db.md`](command-db.md). This is the **complete catalogue** of what Vox can
> do by voice right now, separated into **always-on** (mode/system), **global** (work no matter what
> app you're on), and **app-specific** (today: **browser only**). It's the **seed data** for the
> command DB — each row below becomes `context` + `command` + `phrase` rows.
>
> **`intent`/`arg`** map to the existing handlers in `actions.py` (`parse()` → `_run()` dispatch).
> **var?** = does the argument come from speech (a variable/slot) or is it fixed.

---

## Tier 0 — Always-on (mode & system control)

They switch modes or control the process, and are **always available regardless of context**. Per
your requirement, **dictation is in this tier — always visible, always there.** Consumed by the
loop/wake backend (not `actions.parse`), so in the DB they carry `intent.category = 'mode'` or
`'system'`.

> **These live in the DB too** (resolved decision #1 — everything together, editable from the
> dashboard, e.g. your own sleep word). **But the control plane keeps a hardcoded safety floor:**
> `abort`/`quit`/`restart`/mode-switch defaults are always active and the DB only *adds* to them, so
> an empty or broken DB can never lock you out. See `command-db.md` §8a.

| What | Say | Result |
|---|---|---|
| Enter **control** mode | "take control", "control mode", "start control" | Dragon-style command mode |
| Enter **assistant** mode | "hey vox" (+ "hey fox/box/vaux" mishears) | LLM chat |
| **Dictation** (speak-to-type) | "start typing", "start dictation", "begin typing", "dictate" · from idle: "vox start typing" | types at the cursor — **always on** |
| Dictation editing (in dictation) | "backspace", "new line", "delete", "stop typing" | edit/stop while typing |
| **Sleep** → idle | "stand down", "go to sleep", farewells ("bye vox", "goodbye", "see you later"…) | exit current mode |
| **Abort** (emergency) | "terminate task", "emergency stop", "abort abort", "stop stop stop" | drop to idle from anywhere |
| **Quit** program | "quit vox" (+ "close/exit/terminate vox", fox/box mishears) | stop the daemon |
| **Restart** process | "restart vox" (+ "reboot vox", "restart yourself") | re-exec (picks up code changes) |
| **One-shot** from idle | "Vox, &lt;any command&gt;" | run one command without entering a mode |
| Open/close **dashboard** | "open dashboard", "close dashboard" | the web UI |

---

## Tier 1 — Global commands (work no matter what app you're on)

The "overall" set. In the DB these are the **`global`** context (priority 0).

| Label | Say (examples) | intent | arg | var? |
|---|---|---|---|---|
| **Click a control** | "click &lt;x&gt;", "press &lt;x&gt;", "tap &lt;x&gt;", "select &lt;x&gt;" | `click` | the target label (matched via AX tree) | ✅ var |
| **Open app or site** | "open &lt;x&gt;", "go to &lt;x&gt;" | `navigate` | app name, or a known site's URL | ✅ var |
| **Open in a new tab** | "open a new &lt;x&gt;", "go to a new &lt;x&gt;" | `navigate_new` | target | ✅ var |
| **Web search** | "search &lt;q&gt;", "search for &lt;q&gt;" | `search` | query | ✅ var |
| **Switch to / cycle an app** | "switch to &lt;app&gt;", "&lt;app&gt; window", "next &lt;app&gt; window", "&lt;app&gt; space", "cycle &lt;app&gt;" | `app_cycle` | app name | ✅ var |
| **Next / previous window** | "next window", "previous window" | `window_move` | `next` / `previous` | fixed |
| **Window by number** | "window 2", "go to window three" | `window_index` | N | ✅ var |
| **Window by name** | "go to my &lt;name&gt; window" | `window` | name | ✅ var |
| **Switch desktop / Space** | "swipe left/right", "next/previous desktop \| space \| screen" | `desktop_move` | `next` / `previous` | fixed |
| **Desktop by number** | "desktop 2", "go to space three" | `desktop_index` | N | ✅ var |
| **Timer / alarm / reminder** | "set a timer for 5 minutes", "set an alarm for 7am", "remind me to call Sam in 10 minutes", "every day at 9 to stretch" | *(scheduler)* | time + text | ✅ var |
| **List / cancel schedules** | "what timers do I have", "cancel my alarm" | *(scheduler)* | — | ✅ var |
| **What app is this** | "what app is this", "which app am I on" | *(query)* | — | fixed |

### Known sites for "open &lt;site&gt;" (the `_SITE_ALIASES` table → global `navigate` commands)
`github · gmail · google · youtube · twitter/x · reddit · hacker news · chatgpt · claude · gemini ·
netflix · spotify · amazon · maps · calendar · drive · docs · notion · linear · slack · figma ·
stack overflow · wikipedia · twitch`

> Each becomes a fixed global `navigate` command (e.g. "open youtube" → `navigate https://youtube.com`).
> They're **global** (opening a site works regardless of focus) but show up prominently in a browser
> context — so the "Arc command set" you picture = **browser-specific ∪ global**. *(This is decision
> #3 in `command-db.md` — flagging it again because your example grouped these under Arc.)*

---

## Tier 2 — App-specific commands

> **Today there is exactly one app-specific set: the browser (Arc / Chromium-family / Safari).**
> No other app (Slack, Cursor, Notion, …) has its own commands yet — that's the gap the AX-tree
> capture flow fills later (see `command-db.md` → Future capabilities).

### Browser (Arc / Google Chrome / Brave / Edge / Safari)
DB: an **`app`** context per browser (priority 10). Several are Arc-specific (sidebar, profiles).

| Label | Say (examples) | intent | arg | var? |
|---|---|---|---|---|
| **Next / previous tab** | "next tab", "previous tab" | `tab_arrow` | `down:1` / `up:1` | fixed |
| **Move N tabs** | "up 3 tabs", "down two tabs", "tab up", "tab down" | `tab_arrow` | `up:N` / `down:N` | ✅ var |
| **First / top tab** | "first tab", "top tab", "to the top" | `tab_arrow` | `up:30` | fixed |
| **Last / bottom tab** | "last tab", "bottom tab", "to the bottom" | `tab_arrow` | `down:30` | fixed |
| **Tab by number** | "tab 3", "the tenth tab" | `tab_index` | N (or first/last) | ✅ var |
| **Tab by name** | "go to my &lt;name&gt; tab", "switch to &lt;name&gt; tab" | `tab` | name | ✅ var |
| **Close tab** | "close tab", "close this tab" | `close_tab` | — | fixed |
| **Show / hide tab sidebar** (Arc) | "show tabs", "hide tabs", "toggle sidebar" | `sidebar` | `show` / `hide` / `toggle` | fixed |
| **Go back** | "go back", "navigate back" | `back` | — | fixed |
| **Next / previous profile** (Arc) | "next profile", "previous profile" | `profile_move` | `next` / `previous` | fixed |
| **Profile by number** (Arc) | "profile 2", "go to profile three" | `profile` | N | ✅ var |

### Every other app
**None yet.** Slack, Cursor, Notion, Finder, etc. currently only get Tier-0 + Tier-1 commands. Adding
per-app commands for them is the next frontier (AX-tree capture, then multi-action — documented in
`command-db.md`).

---

## Notes for seeding the DB

- **Always-on (Tier 0)** → seeded into the DB with `intent.category` of `mode`/`system`, but the
  loop/wake layer reads them as *hardcoded defaults ∪ DB phrases* (the §8a safety floor). The loop
  still consumes them (they change mode/process state, they don't dispatch through `actions._run`).
- **Global (Tier 1)** → the `global` context.
- **Browser (Tier 2)** → an `app` context per browser; the Arc-only ones (sidebar, profiles) can be
  tagged to Arc specifically or kept in a shared "Chromium" context — a seeding detail to decide.
- **Fixed** commands (no var) are the clean phase-1 candidates: exact phrase → fixed `intent`+`arg`.
  **Variable** commands (✅ var) either stay in the code parser for now or use the `param` column —
  see `command-db.md` decision #2.
