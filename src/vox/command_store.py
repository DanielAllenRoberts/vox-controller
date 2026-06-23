"""SQLite store for app/site-scoped voice commands.

Phase 1 of the command database (see ``docs/plan/command-db.md``, idea #36): the schema, a seed
from today's commands (``docs/plan/command-inventory.md``), and a small read API.

**Nothing in the runtime reads this yet** — it's deliberately additive and safe: an empty or
missing DB leaves Vox behaving exactly as it does today. The runtime lookup + boot cache come in
phase 2.

Design notes (from command-db.md):
- The DB is the single source of truth for ALL commands, incl. the Tier-0 mode/system ones — but
  the safety-critical control plane (abort/quit/restart/mode) always keeps hardcoded defaults as a
  floor (§8a), so this store never being present can't lock you out.
- ``intent.category`` separates ``action`` (dispatched via ``actions._run``) from ``mode`` (switch
  mode) and ``system`` (consumed by the loop).
- Phase 1 seeds only FIXED-phrase commands; parameterised grammar (search X, open arbitrary,
  tab-by-name, scheduler) stays in the code parser for now (decision #2).
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DEFAULT_DB = _DATA_DIR / "commands.db"


# --- schema (mirrors command-db.md §4; IF NOT EXISTS so build() is re-runnable) ------------------
SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS intent (
    name        TEXT PRIMARY KEY,
    category    TEXT NOT NULL DEFAULT 'action'
                CHECK (category IN ('action','mode','system')),
    description TEXT NOT NULL DEFAULT '',
    takes_arg   INTEGER NOT NULL DEFAULT 1,
    arg_help    TEXT
);

CREATE TABLE IF NOT EXISTS context (
    id           INTEGER PRIMARY KEY,
    kind         TEXT    NOT NULL CHECK (kind IN ('global','app','site')),
    match_value  TEXT,
    display_name TEXT    NOT NULL,
    priority     INTEGER NOT NULL DEFAULT 0,
    enabled      INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (kind, match_value)
);

CREATE TABLE IF NOT EXISTS command (
    id          INTEGER PRIMARY KEY,
    context_id  INTEGER NOT NULL REFERENCES context(id) ON DELETE CASCADE,
    intent      TEXT    NOT NULL REFERENCES intent(name),
    arg         TEXT,
    param       TEXT,
    label       TEXT    NOT NULL,
    source      TEXT    NOT NULL DEFAULT 'builtin'
                        CHECK (source IN ('builtin','user','learned')),
    enabled     INTEGER NOT NULL DEFAULT 1,
    priority    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_command_context ON command(context_id);

CREATE TABLE IF NOT EXISTS phrase (
    id          INTEGER PRIMARY KEY,
    command_id  INTEGER NOT NULL REFERENCES command(id) ON DELETE CASCADE,
    text        TEXT    NOT NULL,
    is_primary  INTEGER NOT NULL DEFAULT 0,
    match_type  TEXT    NOT NULL DEFAULT 'exact'
                        CHECK (match_type IN ('exact','contains','regex')),
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (command_id, text)
);
CREATE INDEX IF NOT EXISTS idx_phrase_text ON phrase(text);

CREATE TABLE IF NOT EXISTS command_log (
    id              INTEGER PRIMARY KEY,
    ts              TEXT    NOT NULL DEFAULT (datetime('now')),
    heard_phrase    TEXT    NOT NULL,
    context_kind    TEXT,
    context_value   TEXT,
    command_id      INTEGER REFERENCES command(id) ON DELETE SET NULL,
    resolved_intent TEXT,
    resolved_arg    TEXT,
    resolved_by     TEXT CHECK (resolved_by IN ('deterministic','db','llm')),
    success         INTEGER
);
"""


# --- the handler vocabulary: (name, category, takes_arg, arg_help, description) -------------------
# `action` = dispatched via actions._run; `mode` = switch mode; `system` = consumed by the loop.
_INTENTS: list[tuple[str, str, int, str | None, str]] = [
    ("navigate",      "action", 1, "app name or site URL",   "Open an app or known website"),
    ("navigate_new",  "action", 1, "target",                 "Open in a new tab (force fresh)"),
    ("search",        "action", 1, "query",                  "Web search"),
    ("back",          "action", 0, None,                     "Go back (browser/app)"),
    ("tab",           "action", 1, "tab name",               "Switch to a tab by name"),
    ("tab_arrow",     "action", 1, "up:N | down:N",          "Move between tabs (relative)"),
    ("tab_index",     "action", 1, "N | first | last",       "Switch to a tab by position"),
    ("window",        "action", 1, "window name",            "Switch to a window by name"),
    ("window_move",   "action", 1, "next | previous",        "Cycle windows"),
    ("window_index",  "action", 1, "N",                      "Switch to a window by number"),
    ("desktop_move",  "action", 1, "next | previous",        "Switch Space / desktop"),
    ("desktop_index", "action", 1, "N",                      "Switch to a desktop by number"),
    ("profile",       "action", 1, "N",                      "Switch to an Arc profile by number"),
    ("profile_move",  "action", 1, "next | previous",        "Cycle Arc profiles"),
    ("app_cycle",     "action", 1, "app name",               "Switch to / cycle an app's windows"),
    ("sidebar",       "action", 1, "show | hide | toggle",   "Show/hide the tab sidebar (Arc)"),
    ("close_tab",     "action", 0, None,                     "Close the current tab"),
    ("click",         "action", 1, "control label",          "Click an on-screen control (AX tree)"),
    # mode switches (consumed by the loop, not actions._run)
    ("enter_control",   "mode", 0, None, "Enter control mode"),
    ("enter_assistant", "mode", 0, None, "Enter assistant mode"),
    ("enter_dictation", "mode", 0, None, "Start dictation (speak-to-type)"),
    # system / control plane (loop) — these keep hardcoded defaults as a safety floor (§8a)
    ("sleep",           "system", 0, None, "Exit the current mode → idle"),
    ("abort",           "system", 0, None, "Emergency stop → idle"),
    ("quit",            "system", 0, None, "Quit the program"),
    ("restart",         "system", 0, None, "Restart the process"),
    ("dashboard_open",  "system", 0, None, "Open the dashboard"),
    ("dashboard_close", "system", 0, None, "Close the dashboard"),
]


# --- connection / build --------------------------------------------------------------------------

def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    """Open (creating the parent dir if needed) with FK enforcement + Row access."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def build(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    """Create the schema (idempotent) and seed it once (only into an empty DB). Returns the conn."""
    conn = connect(path)
    init_schema(conn)
    seed(conn)
    return conn


# --- seeding -------------------------------------------------------------------------------------

def _ensure_context(conn: sqlite3.Connection, kind: str, match_value: str | None,
                    display_name: str, priority: int) -> int:
    """Get-or-create a context id. (NULL match_value can't use INSERT OR IGNORE — UNIQUE treats
    NULLs as distinct — so we SELECT-first.)"""
    row = conn.execute(
        "SELECT id FROM context WHERE kind=? AND "
        "((match_value IS NULL AND ? IS NULL) OR match_value=?)",
        (kind, match_value, match_value)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO context (kind, match_value, display_name, priority) VALUES (?,?,?,?)",
        (kind, match_value, display_name, priority))
    return cur.lastrowid


def _add_command(conn: sqlite3.Connection, context_id: int, intent: str, label: str,
                 phrases: list[str], *, arg: str | None = None, param: str | None = None,
                 match_type: str = "contains") -> int:
    """Insert one command + its phrases (first phrase is primary)."""
    cur = conn.execute(
        "INSERT INTO command (context_id, intent, arg, param, label) VALUES (?,?,?,?,?)",
        (context_id, intent, arg, param, label))
    cid = cur.lastrowid
    for i, text in enumerate(phrases):
        conn.execute(
            "INSERT OR IGNORE INTO phrase (command_id, text, is_primary, match_type) VALUES (?,?,?,?)",
            (cid, text, 1 if i == 0 else 0, match_type))
    return cid


def seed(conn: sqlite3.Connection) -> bool:
    """Seed today's commands (per command-inventory.md). Idempotent: only runs on an empty DB
    (returns False if already seeded). Reads site aliases + Tier-0 phrases FROM code so the seed
    stays in sync — this is the one-time migration of those into the DB."""
    if conn.execute("SELECT COUNT(*) FROM command").fetchone()[0] > 0:
        return False

    conn.executemany(
        "INSERT OR IGNORE INTO intent (name, category, takes_arg, arg_help, description) "
        "VALUES (?,?,?,?,?)",
        [(n, c, t, h, d) for (n, c, t, h, d) in _INTENTS])

    g = _ensure_context(conn, "global", None, "Everywhere", 0)
    arc = _ensure_context(conn, "app", "Arc", "Arc", 10)

    # --- global: site-opens (migrate actions._SITE_ALIASES → navigate commands) ---
    from vox import actions
    for name, url in actions._SITE_ALIASES.items():
        _add_command(conn, g, "navigate", f"Open {name.title()}",
                     [f"open {name}", f"go to {name}"], arg=url)

    # --- global: other fixed commands (parameterised ones stay in the code parser, decision #2) ---
    _add_command(conn, g, "window_move", "Next window", ["next window"], arg="next")
    _add_command(conn, g, "window_move", "Previous window", ["previous window", "prev window"], arg="previous")
    _add_command(conn, g, "desktop_move", "Next desktop", ["swipe right", "next desktop", "next space"], arg="next")
    _add_command(conn, g, "desktop_move", "Previous desktop", ["swipe left", "previous desktop", "previous space"], arg="previous")

    # --- browser (Arc) fixed commands ---
    _add_command(conn, arc, "tab_arrow", "Next tab", ["next tab"], arg="down:1")
    _add_command(conn, arc, "tab_arrow", "Previous tab", ["previous tab", "prev tab"], arg="up:1")
    _add_command(conn, arc, "tab_arrow", "First tab", ["first tab", "top tab"], arg="up:30")
    _add_command(conn, arc, "tab_arrow", "Last tab", ["last tab", "bottom tab"], arg="down:30")
    _add_command(conn, arc, "close_tab", "Close tab", ["close tab", "close this tab"])
    _add_command(conn, arc, "sidebar", "Show tabs", ["show tabs", "show sidebar"], arg="show")
    _add_command(conn, arc, "sidebar", "Hide tabs", ["hide tabs", "hide sidebar"], arg="hide")
    _add_command(conn, arc, "sidebar", "Toggle sidebar", ["toggle sidebar", "toggle tabs"], arg="toggle")
    _add_command(conn, arc, "back", "Go back", ["go back", "navigate back"])
    _add_command(conn, arc, "profile_move", "Next profile", ["next profile"], arg="next")
    _add_command(conn, arc, "profile_move", "Previous profile", ["previous profile", "prev profile"], arg="previous")

    # --- Tier-0 mode/system: seed phrases FROM config (the loop keeps these as a hardcoded floor too) ---
    from vox.config import CONFIG
    _tier0 = [
        ("enter_control",   "Enter control mode",    CONFIG.control_phrases),
        ("enter_assistant", "Enter assistant mode",  CONFIG.assistant_phrases),
        ("enter_dictation", "Start dictation",       CONFIG.dictate_phrases),
        ("sleep",           "Sleep (exit to idle)",  CONFIG.sleep_phrases),
        ("abort",           "Emergency stop",        CONFIG.abort_phrases),
        ("quit",            "Quit Vox",              CONFIG.quit_phrases),
        ("restart",         "Restart Vox",           CONFIG.restart_phrases),
        ("dashboard_open",  "Open dashboard",        CONFIG.open_dashboard_phrases),
        ("dashboard_close", "Close dashboard",       CONFIG.close_dashboard_phrases),
    ]
    for intent, label, phrases in _tier0:
        if phrases:
            _add_command(conn, g, intent, label, list(phrases))

    conn.commit()
    return True


# --- read API (used by phase 2's boot-load + lookup; handy for inspection/tests now) -------------

def _rows(conn, sql, params=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def list_intents(conn) -> list[dict]:
    return _rows(conn, "SELECT * FROM intent ORDER BY category, name")


def list_contexts(conn) -> list[dict]:
    return _rows(conn, "SELECT * FROM context ORDER BY priority DESC, id")


def commands_with_phrases(conn, context_id: int) -> list[dict]:
    """All commands for a context, each with its phrases attached (for resolution / display)."""
    cmds = _rows(conn, "SELECT * FROM command WHERE context_id=? AND enabled=1 "
                       "ORDER BY priority DESC, id", (context_id,))
    for c in cmds:
        c["phrases"] = _rows(conn, "SELECT text, is_primary, match_type FROM phrase "
                                   "WHERE command_id=? ORDER BY is_primary DESC, id", (c["id"],))
    return cmds


def summary(conn) -> dict:
    """Row counts per table — for quick inspection / seed verification."""
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("intent", "context", "command", "phrase", "command_log")}


# --- resolver (the §6 matching the phase-2 runtime will use; standalone here for testing) ---------

def normalize(text: str) -> str:
    """Lowercase + strip punctuation — a local copy of wakeword.backends.normalize so the store
    doesn't pull in the audio stack. MUST stay identical to it (the loop matches the same way)."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


def _phrase_hit(phrase_text: str, match_type: str, t: str) -> bool:
    """Does normalized utterance `t` match this phrase? (Mirrors the loop: `contains` is substring,
    which is how `phrase_match` works today; `exact` is equality; `regex` is a raw-text search.)"""
    if match_type == "regex":
        try:
            return re.search(phrase_text, t) is not None
        except re.error:
            return False
    p = normalize(phrase_text)
    if match_type == "exact":
        return p == t
    return p in t  # contains (default)


def candidate_contexts(conn, app: str | None = None, domain: str | None = None) -> list[dict]:
    """Enabled contexts that apply to the current focus, highest priority first (site > app > global)."""
    out = []
    for c in list_contexts(conn):
        if not c["enabled"]:
            continue
        if c["kind"] == "global":
            out.append(c)
        elif c["kind"] == "app" and app and (c["match_value"] or "").lower() == app.lower():
            out.append(c)
        elif c["kind"] == "site" and domain and (c["match_value"] or "").lower() == domain.lower():
            out.append(c)
    out.sort(key=lambda c: c["priority"], reverse=True)
    return out


def resolve(conn, text: str, *, app: str | None = None, domain: str | None = None) -> dict | None:
    """Resolve `text` to a command the way phase-2 runtime will: walk candidate contexts highest
    priority first; within each, try exact → contains → regex; the first hit wins. Returns a result
    dict (intent/arg/param/label/context/phrase/match_type) or None (→ falls through to the parser)."""
    t = normalize(text)
    if not t:
        return None
    for ctx in candidate_contexts(conn, app=app, domain=domain):
        cmds = commands_with_phrases(conn, ctx["id"])
        for mt in ("exact", "contains", "regex"):
            for c in cmds:
                for p in c["phrases"]:
                    if p["match_type"] == mt and _phrase_hit(p["text"], mt, t):
                        return {**{k: c[k] for k in ("intent", "arg", "param", "label")},
                                "command_id": c["id"],
                                "context": f'{ctx["kind"]}:{ctx["match_value"] or "*"}',
                                "phrase": p["text"], "match_type": mt}
    return None


# --- CLI: build / inspect / test resolution ------------------------------------------------------

def _fmt(text, app, domain, r) -> str:
    ctx = (f" [app={app}]" if app else "") + (f" [domain={domain}]" if domain else "")
    if r:
        a = f" arg={r['arg']!r}" if r["arg"] else ""
        return (f"  ✓ {text!r}{ctx} → {r['intent']}{a}"
                f"   ({r['label']}; via {r['context']} '{r['phrase']}' [{r['match_type']}])")
    return f"  ✗ {text!r}{ctx} → no DB match (would fall through to actions.parse → LLM)"


# (text, app, domain, expected_intent or None) — mixes exact phrases, natural variants, and
# things that SHOULD stay unmatched (parameterised grammar / unknown) so coverage is honest.
_BATTERY = [
    ("next tab", "Arc", None, "tab_arrow"),
    ("go to the next tab", "Arc", None, "tab_arrow"),
    ("previous tab", "Arc", None, "tab_arrow"),
    ("close this tab please", "Arc", None, "close_tab"),
    ("show tabs", "Arc", None, "sidebar"),
    ("next profile", "Arc", None, "profile_move"),
    ("open youtube", None, None, "navigate"),
    ("can you open github", None, None, "navigate"),
    ("next window", None, None, "window_move"),
    ("swipe left", None, None, "desktop_move"),
    ("take control", None, None, "enter_control"),
    ("start typing", None, None, "enter_dictation"),
    ("go to sleep", None, None, "sleep"),
    ("quit vox", None, None, "quit"),
    ("search for cats", None, None, None),     # parameterised → stays in the parser
    ("open my email", None, None, None),       # not a seeded fixed site
    ("what time is it", None, None, None),      # not a command
]


def _selftest(conn) -> None:
    print("Coverage battery (expected vs resolved):\n")
    passed = 0
    for text, app, domain, expect in _BATTERY:
        r = resolve(conn, text, app=app, domain=domain)
        got = r["intent"] if r else None
        good = got == expect
        passed += good
        print(("  ✓" if good else "  ✗") + _fmt(text, app, domain, r)[3:]
              + ("" if good else f"   [expected {expect}]"))
    print(f"\n{passed}/{len(_BATTERY)} as expected.")


def _repl(conn) -> None:
    app = domain = None
    print("Interactive resolver. Type a phrase to test. Commands: ':app Arc', ':domain youtube.com',")
    print("':app' / ':domain' (clear), ':q' to quit.\n")
    while True:
        try:
            line = input(f"[app={app or '-'} domain={domain or '-'}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print(); break
        if not line:
            continue
        if line in (":q", ":quit", ":exit"):
            break
        if line.startswith(":app"):
            app = line[4:].strip() or None; continue
        if line.startswith(":domain"):
            domain = line[7:].strip() or None; continue
        print(_fmt(line, app, domain, resolve(conn, line, app=app, domain=domain)))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Vox command store — build / inspect / test resolution")
    ap.add_argument("--try", dest="text", help="resolve a single phrase and exit")
    ap.add_argument("--app", help="focused-app context (e.g. Arc)")
    ap.add_argument("--domain", help="active-tab domain context (e.g. youtube.com)")
    ap.add_argument("--repl", action="store_true", help="interactive resolver (type phrases)")
    ap.add_argument("--selftest", action="store_true", help="run a coverage battery")
    _args = ap.parse_args()

    _conn = build()  # ensure the DB exists + is seeded
    if _args.text:
        print(_fmt(_args.text, _args.app, _args.domain,
                   resolve(_conn, _args.text, app=_args.app, domain=_args.domain)))
    elif _args.selftest:
        _selftest(_conn)
    elif _args.repl:
        _repl(_conn)
    else:
        print(f"command DB: {DEFAULT_DB}")
        for _t, _n in summary(_conn).items():
            print(f"  {_t:12} {_n}")
        print('\nTry:  python -m vox.command_store --try "next tab" --app Arc')
        print('      python -m vox.command_store --selftest')
        print('      python -m vox.command_store --repl')
