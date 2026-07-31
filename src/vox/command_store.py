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


# --- learning schema (docs/plan/command-learning/05) ---------------------------------------------
# Additive: new tables + nullable/defaulted columns, so an existing commands.db keeps working. The
# candidate tables are the "holding pen" — an action the LLM resolved that hasn't earned a command
# yet. NOTHING here affects voice behaviour; that's what makes shadow mode (phase 1) possible.

_LEARN_SCHEMA = """
CREATE TABLE IF NOT EXISTS command_candidate (
    id             INTEGER PRIMARY KEY,
    context_id     INTEGER NOT NULL REFERENCES context(id) ON DELETE CASCADE,
    intent         TEXT    NOT NULL,
    arg            TEXT,
    action_key     TEXT    NOT NULL UNIQUE,   -- context|intent|normalize(arg) — identity, see doc 02
    hit_count      INTEGER NOT NULL DEFAULT 0,
    negative_count INTEGER NOT NULL DEFAULT 0,
    distinct_days  INTEGER NOT NULL DEFAULT 0,
    last_day       TEXT,                      -- YYYY-MM-DD of the last counted hit
    first_seen     TEXT    NOT NULL DEFAULT (datetime('now')),
    last_seen      TEXT    NOT NULL DEFAULT (datetime('now')),
    blocked        INTEGER NOT NULL DEFAULT 0,
    blocked_until  TEXT,
    promoted_id    INTEGER REFERENCES command(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_candidate_key ON command_candidate(action_key);

CREATE TABLE IF NOT EXISTS command_candidate_phrase (
    id           INTEGER PRIMARY KEY,
    candidate_id INTEGER NOT NULL REFERENCES command_candidate(id) ON DELETE CASCADE,
    text         TEXT    NOT NULL,
    hit_count    INTEGER NOT NULL DEFAULT 1,
    last_used_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (candidate_id, text)
);
"""

# column → DDL, added only if missing (sqlite has no ADD COLUMN IF NOT EXISTS)
_LEARN_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "command": [("hit_count", "INTEGER NOT NULL DEFAULT 0"), ("last_used_at", "TEXT"),
                ("fail_count", "INTEGER NOT NULL DEFAULT 0"), ("learned_at", "TEXT"),
                ("learned_reason", "TEXT")],
    "phrase": [("hit_count", "INTEGER NOT NULL DEFAULT 0"), ("last_used_at", "TEXT"),
               ("source", "TEXT NOT NULL DEFAULT 'builtin'")],
    "command_log": [("candidate_id", "INTEGER"), ("ambiguous", "INTEGER NOT NULL DEFAULT 0"),
                    ("confidence", "REAL"), ("negated", "INTEGER NOT NULL DEFAULT 0")],
}


def _migrate(conn: sqlite3.Connection) -> None:
    """Add any missing learning columns. Idempotent — safe on every boot, like the seed."""
    for table, cols in _LEARN_COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, ddl in cols:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    conn.commit()


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.executescript(_LEARN_SCHEMA)
    conn.commit()
    _migrate(conn)


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


# --- optional query logging ----------------------------------------------------------------------
# A runtime hook so every DB read is visible in vox.log ("which query it runs"). Off by default
# (no-op) so the CLI/tests stay quiet; the daemon installs ConsoleOutput.emit at boot (command_cache).
_QUERY_LOG = None  # Callable[[str], None] | None


def set_query_logger(fn) -> None:
    """Install a logging callback (e.g. ``ConsoleOutput.emit``); pass ``None`` to disable."""
    global _QUERY_LOG
    _QUERY_LOG = fn


def _one_line(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


# --- read API (used by phase 2's boot-load + lookup; handy for inspection/tests now) -------------

def _rows(conn, sql, params=()) -> list[dict]:
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    if _QUERY_LOG is not None:
        try:
            _QUERY_LOG(f"  [cmddb] query: {_one_line(sql)}  params={tuple(params)} → {len(rows)} row(s)")
        except Exception:
            pass  # logging must never break a query
    return rows


def list_intents(conn) -> list[dict]:
    return _rows(conn, "SELECT * FROM intent ORDER BY category, name")


def list_contexts(conn) -> list[dict]:
    return _rows(conn, "SELECT * FROM context ORDER BY priority DESC, id")


def commands_with_phrases(conn, context_id: int, include_disabled: bool = False) -> list[dict]:
    """All commands for a context, each with its phrases attached (for resolution / display).
    Loads phrases in ONE query (not N+1) so a focus load is a couple of clean log lines.
    ``include_disabled`` keeps disabled commands too — the dashboard shows them so you can re-enable."""
    where = "context_id=?" if include_disabled else "context_id=? AND enabled=1"
    cmds = _rows(conn, f"SELECT * FROM command WHERE {where} ORDER BY priority DESC, id", (context_id,))
    if not cmds:
        return cmds
    ids = [c["id"] for c in cmds]
    rows = _rows(conn, "SELECT id, command_id, text, is_primary, match_type FROM phrase "
                       f"WHERE command_id IN ({','.join('?' * len(ids))}) "
                       "ORDER BY command_id, is_primary DESC, id", tuple(ids))
    by_cmd: dict[int, list[dict]] = {}
    for r in rows:
        by_cmd.setdefault(r["command_id"], []).append(
            {"id": r["id"], "text": r["text"], "is_primary": r["is_primary"], "match_type": r["match_type"]})
    for c in cmds:
        c["phrases"] = by_cmd.get(c["id"], [])
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


# --- ranking: which match wins when several do (docs/plan/command-learning/04) -------------------
# The old resolver returned the FIRST phrase that matched, scanning rows in whatever order SQLite
# handed back. With 49 curated commands collisions were designed out by hand; the moment LEARNED rows
# exist two commands will eventually both match and the winner becomes a coin-flip — a silent wrong
# action that's near-impossible to reproduce. So every match is collected and ranked explicitly.

_CTX_RANK = {"site": 2, "app": 1, "global": 0}     # most specific context wins
_SOURCE_RANK = {"user": 2, "builtin": 1, "learned": 0}  # a human's command always beats an inferred one
_MATCH_RANK = {"exact": 2, "contains": 1, "regex": 0}   # precision over generality


def match_sort_key(m: dict) -> tuple:
    """Ranking key for one candidate match — higher sorts first. Total and deterministic: the final
    element is the command id, so even a dead tie resolves the same way every single time."""
    return (
        _CTX_RANK.get(m.get("_ctx_kind"), 0),
        _SOURCE_RANK.get(m.get("_source") or "builtin", 1),
        _MATCH_RANK.get(m.get("match_type"), 0),
        len(normalize(m.get("phrase") or "")),   # a longer phrase is more specific
        -int(m.get("command_id") or 0),          # negated: lowest id wins the final tiebreak
    )


def rank_matches(matches: list[dict], *, ambiguity_ok: bool = False) -> dict | None:
    """Pick the winner from all matches, or None when the top two are genuinely ambiguous.

    Ambiguous = the top two point at DIFFERENT actions (intent+arg) and rank identically on every
    criterion. Guessing there is how you get a confident wrong action, so we return None and let the
    caller fall through to the LLM — slower, but it can't silently do the wrong thing.
    ``ambiguity_ok`` forces a pick (used by the CLI/self-test, which wants to see what would win)."""
    if not matches:
        return None
    ranked = sorted(matches, key=match_sort_key, reverse=True)
    best = ranked[0]
    if not ambiguity_ok and len(ranked) > 1:
        second = ranked[1]
        same_action = ((best.get("intent"), best.get("arg")) == (second.get("intent"), second.get("arg")))
        if not same_action and match_sort_key(best)[:4] == match_sort_key(second)[:4]:
            best = dict(best)
            best["ambiguous_with"] = second.get("command_id")
            return None if not ambiguity_ok else best
    return best


def collect_matches(cmds: list[dict], t: str, ctx_kind: str, ctx_value: str | None) -> list[dict]:
    """Every (command, phrase) in ``cmds`` whose phrase matches normalized utterance ``t``."""
    out = []
    for c in cmds:
        for p in c.get("phrases", []):
            mt = p.get("match_type", "exact")
            if _phrase_hit(p["text"], mt, t):
                out.append({**{k: c.get(k) for k in ("intent", "arg", "param", "label")},
                            "command_id": c["id"], "phrase_id": p.get("id"),
                            "context": f'{ctx_kind}:{ctx_value or "*"}',
                            "phrase": p["text"], "match_type": mt,
                            "_ctx_kind": ctx_kind, "_source": c.get("source")})
    return out


def resolve(conn, text: str, *, app: str | None = None, domain: str | None = None) -> dict | None:
    """Resolve `text` to a command the way the phase-2 runtime does: collect every match across the
    candidate contexts, then rank them (context → source → match type → phrase specificity → id).
    Returns a result dict (intent/arg/param/label/context/phrase/match_type), or None when nothing
    matched or the top two are ambiguous (→ falls through to the parser / LLM)."""
    t = normalize(text)
    if not t:
        return None
    matches: list[dict] = []
    for ctx in candidate_contexts(conn, app=app, domain=domain):
        matches += collect_matches(commands_with_phrases(conn, ctx["id"]), t,
                                   ctx["kind"], ctx["match_value"])
    return rank_matches(matches)


# --- learning: the write path (docs/plan/command-learning/05) -------------------------------------
# Phase 1 is SHADOW MODE: everything below records evidence. Nothing here creates a command or
# changes what Vox does — promotion is deliberately not implemented yet.

def action_key(context_id: int, intent: str, arg: str | None) -> str:
    """Identity of an action — the thing that makes variant phrasings collapse onto ONE command
    (doc 02). Keyed by what it DOES, never by the words that triggered it."""
    return f"{context_id}|{intent}|{normalize(arg or '')}"


def log_resolution(conn, *, heard: str, context_kind=None, context_value=None, command_id=None,
                   intent=None, arg=None, resolved_by="llm", success=None,
                   confidence=None, ambiguous=False, candidate_id=None) -> int:
    """Append one row to command_log — the evidence trail. Called for EVERY resolution
    (deterministic / db / llm alike). Returns the row id so a later negative signal can flag it."""
    cur = conn.execute(
        "INSERT INTO command_log (heard_phrase, context_kind, context_value, command_id, "
        "resolved_intent, resolved_arg, resolved_by, success, confidence, ambiguous, candidate_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (heard, context_kind, context_value, command_id, intent, arg, resolved_by,
         None if success is None else int(success), confidence, int(bool(ambiguous)), candidate_id))
    conn.commit()
    return cur.lastrowid


def mark_negated(conn, log_id: int) -> None:
    """A negative signal ("no" / undo / an immediate re-say) followed this action — flag the log row
    and walk back the candidate it fed, so a correction can never count toward promotion (doc 01)."""
    row = conn.execute("SELECT candidate_id, negated FROM command_log WHERE id=?", (log_id,)).fetchone()
    if row is None or row["negated"]:
        return
    conn.execute("UPDATE command_log SET negated=1 WHERE id=?", (log_id,))
    if row["candidate_id"]:
        conn.execute("UPDATE command_candidate SET negative_count = negative_count + 1, "
                     "hit_count = MAX(0, hit_count - 1) WHERE id=?", (row["candidate_id"],))
    conn.commit()


def find_by_action(conn, context_id: int, intent: str, arg: str | None) -> dict | None:
    """THE lookup that stops variants multiplying: does a command for this ACTION already exist?
    If it does, a new phrasing becomes an alias on it — never a second command (doc 02)."""
    want = normalize(arg or "")
    rows = _rows(conn, "SELECT * FROM command WHERE context_id=? AND intent=?", (context_id, intent))
    for r in rows:
        if normalize(r["arg"] or "") == want:
            return r
    return None


def note_candidate(conn, *, context_id: int, intent: str, arg: str | None, phrase: str,
                   today: str | None = None) -> dict:
    """Upsert the candidate for this action key, count the hit (and the DAY, which is what separates
    a habit from saying the same thing three times because it didn't work), and cluster the phrase."""
    from datetime import date
    day = today or date.today().isoformat()
    key = action_key(context_id, intent, arg)
    row = conn.execute("SELECT * FROM command_candidate WHERE action_key=?", (key,)).fetchone()
    if row is None:
        conn.execute("INSERT INTO command_candidate (context_id, intent, arg, action_key, "
                     "hit_count, distinct_days, last_day) VALUES (?,?,?,?,1,1,?)",
                     (context_id, intent, arg, key, day))
        cand_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    else:
        cand_id = row["id"]
        new_day = row["last_day"] != day
        conn.execute("UPDATE command_candidate SET hit_count = hit_count + 1, "
                     "distinct_days = distinct_days + ?, last_day = ?, "
                     "last_seen = datetime('now') WHERE id=?",
                     (1 if new_day else 0, day, cand_id))
    p = normalize(phrase)
    if p:
        conn.execute("INSERT INTO command_candidate_phrase (candidate_id, text) VALUES (?,?) "
                     "ON CONFLICT(candidate_id, text) DO UPDATE SET "
                     "hit_count = hit_count + 1, last_used_at = datetime('now')", (cand_id, p))
    conn.commit()
    return dict(conn.execute("SELECT * FROM command_candidate WHERE id=?", (cand_id,)).fetchone())


def window_hits(conn, candidate_id: int, days: float) -> int:
    """Clean hits for this candidate inside a ROLLING window of ``days``.

    The promotion bar counts recency, not calendar days: three uses this afternoon is a habit worth
    learning, while three uses spread over six months is not the same signal at all. Reads
    command_log (which already timestamps every resolution) and ignores rows a correction negated."""
    row = conn.execute(
        "SELECT COUNT(*) FROM command_log WHERE candidate_id=? AND negated=0 "
        "AND ts >= datetime('now', ?)", (candidate_id, f"-{float(days)} days")).fetchone()
    return int(row[0]) if row else 0


def note_usage(conn, command_id: int, phrase_id: int | None = None, *, success: bool = True) -> None:
    """Bump usage on a command (and the phrase that matched) — the data decay and eviction run on.
    On failure bump fail_count instead; a success resets it (doc 04, F3)."""
    if success:
        conn.execute("UPDATE command SET hit_count = hit_count + 1, last_used_at = datetime('now'), "
                     "fail_count = 0 WHERE id=?", (command_id,))
    else:
        conn.execute("UPDATE command SET fail_count = fail_count + 1 WHERE id=?", (command_id,))
    if phrase_id:
        conn.execute("UPDATE phrase SET hit_count = hit_count + 1, last_used_at = datetime('now') "
                     "WHERE id=?", (phrase_id,))
    conn.commit()


# --- promotion & upkeep (phase 2) -----------------------------------------------------------------

_MAX_PHRASES_PER_COMMAND = 6
_PHRASE_SIMILARITY = 0.85


def score(hit_count, last_used_at) -> float:
    """hits × recency, half-life 30 days — one explainable number for eviction, decay and phrase
    pruning. Ten hits three months ago scores 1.25; three hits this week ~2.9. Recent-and-modest
    beats old-and-heavy, which is what you want from something tracking how you work *now*."""
    from datetime import datetime, timezone
    hits = float(hit_count or 0)
    if not last_used_at:
        return hits * 0.5  # never used since promotion → treat as half a hit's worth of evidence
    try:
        seen = datetime.fromisoformat(str(last_used_at).replace(" ", "T"))
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        days = max(0.0, (datetime.now(timezone.utc) - seen).total_seconds() / 86400.0)
    except Exception:
        return hits
    return hits * (0.5 ** (days / 30.0))


def _token_similar(a: str, b: str) -> float:
    """Token-set similarity — order-insensitive, so 'open alex chat' ≈ 'chat alex open'."""
    import difflib
    return difflib.SequenceMatcher(None, " ".join(sorted(a.split())),
                                   " ".join(sorted(b.split()))).ratio()


def attach_phrase(conn, command_id: int, phrase: str, *, source: str = "learned") -> bool:
    """Add an alias to an EXISTING command — the other half of variant collapse (doc 02).

    Applies, in order: exact-duplicate → near-duplicate → subsumption → cap+evict. Returns True only
    if a new phrase row was written (False means it merged into one already there, which is a success
    too — it's the whole point)."""
    p = normalize(phrase)
    if not p:
        return False
    rows = _rows(conn, "SELECT * FROM phrase WHERE command_id=?", (command_id,))
    for r in rows:
        existing = normalize(r["text"])
        if existing == p or _token_similar(existing, p) >= _PHRASE_SIMILARITY:
            conn.execute("UPDATE phrase SET hit_count = hit_count + 1, "
                         "last_used_at = datetime('now') WHERE id=?", (r["id"],))
            conn.commit()
            return False
        # Subsumption: keep the SHORTER, more general phrase of a containing pair.
        pt, et = set(p.split()), set(existing.split())
        if et and et < pt:      # existing is contained in the new one → existing already covers it
            conn.execute("UPDATE phrase SET hit_count = hit_count + 1 WHERE id=?", (r["id"],))
            conn.commit()
            return False
        if pt and pt < et:      # the new one is more general → replace the longer existing phrase
            conn.execute("UPDATE phrase SET text=?, hit_count = hit_count + 1, "
                         "last_used_at = datetime('now') WHERE id=?", (p, r["id"]))
            conn.commit()
            return False
    conn.execute("INSERT INTO phrase (command_id, text, match_type, source, hit_count, last_used_at) "
                 "VALUES (?,?, 'exact', ?, 1, datetime('now'))", (command_id, p, source))
    # Cap: a command needing more than N ways to say it is usually a template (doc 02, phase 4).
    rows = _rows(conn, "SELECT * FROM phrase WHERE command_id=?", (command_id,))
    if len(rows) > _MAX_PHRASES_PER_COMMAND:
        worst = min(rows, key=lambda r: score(r["hit_count"], r["last_used_at"]))
        conn.execute("DELETE FROM phrase WHERE id=?", (worst["id"],))
    conn.commit()
    return True


def _enforce_caps(conn, context_id: int) -> int:
    """Evict the lowest-scoring LEARNED commands over the per-context / global caps. builtin and user
    rows are never counted and never evicted. Returns how many were dropped."""
    dropped = 0
    for sql, params, cap in (
            ("SELECT * FROM command WHERE source='learned' AND context_id=?", (context_id,),
             int(_learn_setting("learning_max_per_context", 40))),
            ("SELECT * FROM command WHERE source='learned'", (),
             int(_learn_setting("learning_max_total", 300)))):
        rows = _rows(conn, sql, params)
        while len(rows) > cap:
            worst = min(rows, key=lambda r: score(r["hit_count"], r["last_used_at"]))
            conn.execute("DELETE FROM command WHERE id=?", (worst["id"],))
            rows = [r for r in rows if r["id"] != worst["id"]]
            dropped += 1
    if dropped:
        conn.commit()
    return dropped


def _learn_setting(key, fallback):
    """Live dashboard override for a learning setting, else the fallback (guarded)."""
    try:
        from vox.web import settings_store
        val = settings_store.get(key)
        if val is not None:
            return val
    except Exception:
        pass
    return fallback


def promote(conn, candidate_id: int, *, reason: str = "threshold") -> int | None:
    """Turn a candidate into a real command (``source='learned'``) with its clustered phrases.

    Returns the new command id, or None if it couldn't/shouldn't. Idempotent: an already-promoted or
    blocked candidate is a no-op. If a command for the action appeared meanwhile, the phrases are
    attached to THAT instead of creating a duplicate (doc 02's rule, enforced here too)."""
    row = conn.execute("SELECT * FROM command_candidate WHERE id=?", (candidate_id,)).fetchone()
    if row is None or row["blocked"] or row["promoted_id"]:
        return None
    cand = dict(row)
    phrases = [r["text"] for r in _rows(
        conn, "SELECT text FROM command_candidate_phrase WHERE candidate_id=? "
              "ORDER BY hit_count DESC, id", (candidate_id,))][:_MAX_PHRASES_PER_COMMAND]
    if not phrases:
        return None

    existing = find_by_action(conn, cand["context_id"], cand["intent"], cand["arg"])
    if existing is not None:
        for p in phrases:
            attach_phrase(conn, existing["id"], p)
        conn.execute("UPDATE command_candidate SET promoted_id=? WHERE id=?",
                     (existing["id"], candidate_id))
        conn.commit()
        return existing["id"]

    label = f"{cand['intent']} {cand['arg']}".strip() if cand["arg"] else cand["intent"]
    cur = conn.execute(
        "INSERT INTO command (context_id, intent, arg, label, source, learned_at, learned_reason) "
        "VALUES (?,?,?,?, 'learned', datetime('now'), ?)",
        (cand["context_id"], cand["intent"], cand["arg"], f"Learned: {label}"[:60], reason))
    cmd_id = cur.lastrowid
    for p in phrases:
        attach_phrase(conn, cmd_id, p)
    conn.execute("UPDATE command_candidate SET promoted_id=? WHERE id=?", (cmd_id, candidate_id))
    conn.commit()
    _enforce_caps(conn, cand["context_id"])
    return cmd_id


def remap(conn, command_id: int, intent: str, arg: str | None) -> dict | None:
    """Re-point a LEARNED command at a different action, keeping its phrases ("when I say X I
    actually mean Y" — doc 04). Refuses builtin/user rows: those are human-authored and an inferred
    edit must never overwrite them. Returns the previous action (so it can be undone / recorded as
    the anti-mapping), or None if it refused."""
    row = conn.execute("SELECT * FROM command WHERE id=?", (command_id,)).fetchone()
    if row is None or row["source"] != "learned":
        return None
    was = {"intent": row["intent"], "arg": row["arg"]}
    conn.execute("UPDATE command SET intent=?, arg=?, updated_at=datetime('now'), "
                 "learned_at=datetime('now'), learned_reason='remap', "
                 "hit_count=0, fail_count=0, enabled=1 WHERE id=?",   # re-mapped ⇒ probation resets
                 (intent, arg, command_id))
    conn.commit()
    return was


def retire(conn, command_id: int, *, delete: bool = False, block_days: int = 0) -> bool:
    """Demote (``enabled=0``) or delete a LEARNED command, optionally blocking its action from being
    re-promoted (else "forget that" is undone by the next three uses). builtin/user are untouchable."""
    row = conn.execute("SELECT * FROM command WHERE id=?", (command_id,)).fetchone()
    if row is None or row["source"] != "learned":
        return False
    key = action_key(row["context_id"], row["intent"], row["arg"])
    if block_days:
        conn.execute("UPDATE command_candidate SET blocked=1, "
                     "blocked_until=datetime('now', ?) WHERE action_key=?",
                     (f"+{int(block_days)} days", key))
    if delete:
        conn.execute("DELETE FROM command WHERE id=?", (command_id,))
    else:
        conn.execute("UPDATE command SET enabled=0, updated_at=datetime('now') WHERE id=?",
                     (command_id,))
    conn.commit()
    return True


def learned_commands(conn, *, include_disabled: bool = True) -> list[dict]:
    """Every learned command with its phrases + current score — the dashboard's review surface."""
    where = "source='learned'" if include_disabled else "source='learned' AND enabled=1"
    rows = _rows(conn, f"SELECT * FROM command WHERE {where} ORDER BY learned_at DESC")
    for r in rows:
        r["phrases"] = [p["text"] for p in _rows(
            conn, "SELECT text FROM phrase WHERE command_id=? ORDER BY hit_count DESC", (r["id"],))]
        r["score"] = round(score(r["hit_count"], r["last_used_at"]), 3)
    return rows


def decay(conn) -> dict:
    """Nightly upkeep: probation, retirement, candidate cleanup, log trim (doc 03).

    Probation is what makes automatic learning safe — a command learned during a one-off burst that
    never gets used again deletes itself, so a wrong guess costs days rather than forever."""
    out = {"probation_deleted": 0, "demoted": 0, "deleted": 0, "candidates_dropped": 0, "log_trimmed": 0}
    p_days = int(_learn_setting("learning_probation_days", 14))
    p_uses = int(_learn_setting("learning_probation_uses", 2))

    # 1. Probation — learned, old enough to judge, still unproven → delete (it never earned a place).
    cur = conn.execute(
        "DELETE FROM command WHERE source='learned' AND learned_at IS NOT NULL "
        "AND learned_at < datetime('now', ?) AND hit_count < ?", (f"-{p_days} days", p_uses))
    out["probation_deleted"] = cur.rowcount or 0

    # 2. Retirement — proven once, but long unused. Demote first (reversible), delete much later.
    cur = conn.execute(
        "UPDATE command SET enabled=0 WHERE source='learned' AND enabled=1 "
        "AND COALESCE(last_used_at, learned_at) < datetime('now', '-60 days')")
    out["demoted"] = cur.rowcount or 0
    cur = conn.execute(
        "DELETE FROM command WHERE source='learned' "
        "AND COALESCE(last_used_at, learned_at) < datetime('now', '-180 days')")
    out["deleted"] = cur.rowcount or 0

    # 3. Candidates that never became anything, and the rolling evidence window.
    cur = conn.execute("DELETE FROM command_candidate WHERE promoted_id IS NULL "
                       "AND last_seen < datetime('now', '-30 days')")
    out["candidates_dropped"] = cur.rowcount or 0
    cur = conn.execute("DELETE FROM command_log WHERE ts < datetime('now', '-90 days')")
    out["log_trimmed"] = cur.rowcount or 0
    conn.commit()
    return out


def candidates(conn, *, limit: int = 200) -> list[dict]:
    """Every candidate with its clustered phrases, best-evidenced first — what shadow mode has seen
    and what the dashboard's Candidates queue renders."""
    rows = _rows(conn, "SELECT * FROM command_candidate ORDER BY hit_count DESC, last_seen DESC "
                       "LIMIT ?", (limit,))
    if not rows:
        return rows
    ids = [r["id"] for r in rows]
    ph = _rows(conn, "SELECT candidate_id, text, hit_count FROM command_candidate_phrase "
                     f"WHERE candidate_id IN ({','.join('?' * len(ids))}) "
                     "ORDER BY hit_count DESC", tuple(ids))
    by: dict[int, list[dict]] = {}
    for r in ph:
        by.setdefault(r["candidate_id"], []).append({"text": r["text"], "hit_count": r["hit_count"]})
    for r in rows:
        r["phrases"] = by.get(r["id"], [])
    return rows


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
