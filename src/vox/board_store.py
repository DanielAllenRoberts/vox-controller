"""SQLite store for the workspace board — a Trello-like kanban that doubles as an
agent-accessible knowledge base (see ``docs/plan/ideas.md`` #51).

Deliberately lean and self-contained (mirrors ``command_store.py``): boards → lists → cards,
one SQLite file, no external service. We *referenced* the data model of ``kanbn/kan`` (an
AGPL Next.js+Postgres app) but implement our own so it stays MIT-clean, zero-dep, and
readable/writable **in-process** by the Python daemon — the whole point is that the agent can
`add`/`move`/`read`/`search` cards directly, not over an HTTP hop.

Design notes:
- Three tables: ``board`` (a board), ``board_list`` (a column), ``card`` (a card). ``board_list``
  not ``list`` — avoids any reserved-word ambiguity, matches the "one obvious name" style.
- ``position`` orders lists within a board and cards within a list (float-free: plain ints,
  renumbered on move). A new card/list appends to the end.
- ``tags`` is a comma-separated string (like the memory store) — simple, searchable, no join table.
- ``build()`` seeds ONE default board ("Workspace") with To Do / Doing / Done on an empty DB, so a
  fresh install has somewhere to put cards; it's idempotent (never re-seeds a non-empty DB).
- The read API returns camelCase-friendly dicts via ``board_snapshot`` for the web layer to pass
  through, and plain helpers (``add_card`` etc.) the agent tools call directly.
"""

from __future__ import annotations

from vox.paths import DATA_DIR

import json
import re
import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path

_DATA_DIR = DATA_DIR
DEFAULT_DB = _DATA_DIR / "board.db"

DEFAULT_BOARD = "Workspace"
DEFAULT_LISTS = ("To Do", "Doing", "Done")


# --- schema (IF NOT EXISTS so build() is re-runnable) --------------------------------------------
SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS board (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL UNIQUE,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS board_list (
    id          INTEGER PRIMARY KEY,
    board_id    INTEGER NOT NULL REFERENCES board(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (board_id, name)
);
CREATE INDEX IF NOT EXISTS idx_list_board ON board_list(board_id);

CREATE TABLE IF NOT EXISTS card (
    id          INTEGER PRIMARY KEY,
    list_id     INTEGER NOT NULL REFERENCES board_list(id) ON DELETE CASCADE,
    title       TEXT    NOT NULL,
    body        TEXT    NOT NULL DEFAULT '',
    tags        TEXT    NOT NULL DEFAULT '',
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_card_list ON card(list_id);
-- Recently deleted cards, so a delete can be undone ("put them back"). The whole card as JSON plus
-- where it was. Pruned to the newest TRASH_KEEP.
CREATE TABLE IF NOT EXISTS card_trash (
    id          INTEGER PRIMARY KEY,
    card_json   TEXT    NOT NULL,
    list_id     INTEGER,
    list_name   TEXT    NOT NULL DEFAULT '',
    deleted_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


# --- connection / build --------------------------------------------------------------------------

def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    """Open (creating the parent dir if needed) with FK enforcement + Row access."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Columns added after v1. ALTER TABLE ADD COLUMN keeps existing boards intact.
_CARD_COLUMNS = (
    ("due", "TEXT"),                                   # "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM", local time
    ("checklist", "TEXT NOT NULL DEFAULT '[]'"),       # JSON [{"text": str, "done": bool}]
    ("archived", "INTEGER NOT NULL DEFAULT 0"),
    ("reminder_id", "TEXT"),                           # the scheduler job that announces the due date
)


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    have = {r["name"] for r in conn.execute("PRAGMA table_info(card)")}
    for col, decl in _CARD_COLUMNS:
        if col not in have:
            conn.execute(f"ALTER TABLE card ADD COLUMN {col} {decl}")
    conn.commit()


def build(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    """Create the schema (idempotent) and seed the default board once. Returns the conn."""
    conn = connect(path)
    init_schema(conn)
    seed(conn)
    return conn


def seed(conn: sqlite3.Connection) -> bool:
    """Seed one default board with To Do / Doing / Done — only on an empty DB. Returns False if a
    board already exists (so we never clobber the user's board)."""
    if conn.execute("SELECT COUNT(*) FROM board").fetchone()[0] > 0:
        return False
    bid = conn.execute("INSERT INTO board (name) VALUES (?)", (DEFAULT_BOARD,)).lastrowid
    for i, name in enumerate(DEFAULT_LISTS):
        conn.execute("INSERT INTO board_list (board_id, name, position) VALUES (?,?,?)",
                     (bid, name, i))
    conn.commit()
    return True


# --- helpers -------------------------------------------------------------------------------------

def _touch_board(conn: sqlite3.Connection, board_id: int) -> None:
    conn.execute("UPDATE board SET updated_at = datetime('now') WHERE id = ?", (board_id,))


def _board_id_of_list(conn: sqlite3.Connection, list_id: int) -> int | None:
    row = conn.execute("SELECT board_id FROM board_list WHERE id = ?", (list_id,)).fetchone()
    return row["board_id"] if row else None


def _next_position(conn: sqlite3.Connection, table: str, parent_col: str, parent_id: int) -> int:
    """The next append position (max+1) among rows sharing a parent — table/columns are internal
    constants (never user input), so the f-string interpolation is safe."""
    row = conn.execute(
        f"SELECT COALESCE(MAX(position), -1) + 1 AS p FROM {table} WHERE {parent_col} = ?",
        (parent_id,)).fetchone()
    return int(row["p"])


def resolve_board(conn: sqlite3.Connection, board: str | int | None = None) -> int | None:
    """Resolve a board by id, name (case-insensitive), or None → the first board. For the agent
    saying "the board" when only the default exists."""
    if isinstance(board, int):
        row = conn.execute("SELECT id FROM board WHERE id = ?", (board,)).fetchone()
        return row["id"] if row else None
    if isinstance(board, str) and board.strip():
        row = conn.execute("SELECT id FROM board WHERE name = ? COLLATE NOCASE",
                           (board.strip(),)).fetchone()
        return row["id"] if row else None
    row = conn.execute("SELECT id FROM board ORDER BY id LIMIT 1").fetchone()
    return row["id"] if row else None


def resolve_list(conn: sqlite3.Connection, name: str, board_id: int | None = None) -> int | None:
    """Resolve a list (column) by name within a board — so the agent can say "add to Doing"."""
    if board_id is None:
        board_id = resolve_board(conn)
    if board_id is None or not (isinstance(name, str) and name.strip()):
        return None
    row = conn.execute(
        "SELECT id FROM board_list WHERE board_id = ? AND name = ? COLLATE NOCASE",
        (board_id, name.strip())).fetchone()
    return row["id"] if row else None


def find_card(conn: sqlite3.Connection, needle: str | int,
              board: str | int | None = None) -> dict | None:
    """Resolve a card the way a PERSON refers to it: an id, an exact title, or a partial/fuzzy one.

    Voice never yields a card id — you say "move the AC Direct card to doing". Exact title first,
    then a substring, then the closest fuzzy match (mis-hears are the norm here, same reason the
    click matcher is fuzzy). Ambiguity resolves to the shortest matching title, which is the most
    specific one. Returns the card dict, or None."""
    if isinstance(needle, str) and needle.strip().startswith("#") and needle.strip()[1:].isdigit():
        needle = needle.strip()[1:]   # "#14", the way the board block and short-term memory name cards
    if isinstance(needle, int) or (isinstance(needle, str) and needle.strip().isdigit()):
        return _card_row(conn, int(needle))
    text = _strip_noise(needle)
    if not text:
        return None
    board_id = resolve_board(conn, board)
    rows = _rows_for_board(conn, board_id)
    low = text.lower()
    exact = [r for r in rows if r["title"].strip().lower() == low]
    if exact:
        return _card_dict(exact[0])
    part = [r for r in rows if low in r["title"].lower() or r["title"].lower() in low]
    if part:
        return _card_dict(min(part, key=lambda r: len(r["title"])))
    import difflib
    best, score = None, 0.0
    for r in rows:
        s = difflib.SequenceMatcher(None, low, r["title"].lower()).ratio()
        if s > score:
            best, score = r, s
    return _card_dict(best) if best is not None and score >= 0.6 else None


def _strip_noise(text) -> str:
    """Drop the words people wrap a card's name in when speaking — "the AC Direct **card**".
    Without this the wrapper word breaks both the substring test and the fuzzy ratio, and a card
    the user named perfectly clearly comes back as not-found."""
    import re
    t = (text or "").strip()
    t = re.sub(r"^\s*(?:the|my|that|this)\s+", "", t, flags=re.I)
    t = re.sub(r"\s+(?:card|task|ticket|item|one)\s*$", "", t, flags=re.I)
    return t.strip()


def _rows_for_board(conn: sqlite3.Connection, board_id: int | None):
    return conn.execute(
        "SELECT c.* FROM card c JOIN board_list l ON l.id = c.list_id WHERE l.board_id = ?",
        (board_id,)).fetchall() if board_id is not None else []


# --- write API (used by the web layer + agent tools) ---------------------------------------------

def create_board(conn: sqlite3.Connection, name: str, lists: list[str] | None = None) -> dict:
    """Create a board. Until now the ONLY board that could exist was the one `seed()` made, so
    "make me a board for X" was impossible even though the schema was always multi-board (every
    list carries a board_id and `resolve_board` already took a name).

    Seeds the same To Do / Doing / Done columns as the default board unless `lists` says otherwise —
    an empty board can't hold a card, so creating one without columns just fails on the next step."""
    if not (isinstance(name, str) and name.strip()):
        raise ValueError("board name is required")
    try:
        cur = conn.execute("INSERT INTO board (name) VALUES (?)", (name.strip(),))
    except sqlite3.IntegrityError:
        raise ValueError(f"a board named {name.strip()!r} already exists")
    board_id = cur.lastrowid
    for i, ln in enumerate(lists if lists is not None else ["To Do", "Doing", "Done"]):
        if ln and ln.strip():
            conn.execute("INSERT INTO board_list (board_id, name, position) VALUES (?,?,?)",
                         (board_id, ln.strip(), i))
    conn.commit()
    row = conn.execute("SELECT * FROM board WHERE id = ?", (board_id,)).fetchone()
    return dict(row)


def rename_list(conn: sqlite3.Connection, list_id: int, name: str) -> dict | None:
    """Rename a column. Returns the updated list, or None if it doesn't exist."""
    if not (isinstance(name, str) and name.strip()):
        raise ValueError("list name is required")
    row = _list_row(conn, int(list_id))
    if row is None:
        return None
    try:
        conn.execute("UPDATE board_list SET name = ? WHERE id = ?", (name.strip(), int(list_id)))
    except sqlite3.IntegrityError:
        raise ValueError(f"a list named {name.strip()!r} already exists on this board")
    _touch_board(conn, row.get("board_id"))
    conn.commit()
    return _list_row(conn, int(list_id))


def delete_list(conn: sqlite3.Connection, list_id: int) -> bool:
    """Delete a column AND its cards (the FK cascades). Returns False if it didn't exist."""
    row = _list_row(conn, int(list_id))
    if row is None:
        return False
    conn.execute("DELETE FROM board_list WHERE id = ?", (int(list_id),))
    _touch_board(conn, row.get("board_id"))
    conn.commit()
    return True


def add_list(conn: sqlite3.Connection, name: str, board: str | int | None = None) -> dict:
    """Create a column at the end of a board. Raises ValueError on a blank/duplicate name."""
    if not (isinstance(name, str) and name.strip()):
        raise ValueError("list name is required")
    board_id = resolve_board(conn, board)
    if board_id is None:
        raise ValueError("no such board")
    pos = _next_position(conn, "board_list", "board_id", board_id)
    try:
        cur = conn.execute("INSERT INTO board_list (board_id, name, position) VALUES (?,?,?)",
                           (board_id, name.strip(), pos))
    except sqlite3.IntegrityError:
        raise ValueError(f"a list named {name.strip()!r} already exists on this board")
    conn.commit()
    return _list_row(conn, cur.lastrowid)


def add_card(conn: sqlite3.Connection, list_name: str, title: str, body: str = "",
             tags: str = "", board: str | int | None = None, due: str | None = None) -> dict:
    """Add a card to the end of a column (resolved by name). The primary agent write.
    Raises ValueError if the title is blank or the list can't be resolved."""
    if not (isinstance(title, str) and title.strip()):
        raise ValueError("card title is required")
    list_id = resolve_list(conn, list_name, resolve_board(conn, board))
    if list_id is None:
        raise ValueError(f"no list named {list_name!r} on this board")
    pos = _next_position(conn, "card", "list_id", list_id)
    cur = conn.execute(
        "INSERT INTO card (list_id, title, body, tags, position) VALUES (?,?,?,?,?)",
        (list_id, title.strip(), (body or "").strip(), _norm_tags(tags), pos))
    _touch_board(conn, _board_id_of_list(conn, list_id))
    conn.commit()
    if due:
        return update_card(conn, cur.lastrowid, due=due)
    return _card_row(conn, cur.lastrowid)


def update_card(conn: sqlite3.Connection, card_id: int, *, title: str | None = None,
                body: str | None = None, tags: str | None = None, due: str | None = None,
                checklist: list | None = None, archived: bool | None = None) -> dict | None:
    """Edit a card in place. ``due=""`` clears the deadline. Returns the updated card, or None if
    not found. Changing the title, deadline or archive state re-syncs the card's reminder."""
    sets, params = [], []
    if due is not None:
        sets.append("due = ?"); params.append(normalize_due(due))
    if checklist is not None:
        sets.append("checklist = ?"); params.append(json.dumps(_norm_checklist(checklist)))
    if archived is not None:
        sets.append("archived = ?"); params.append(1 if archived else 0)
    if title is not None:
        if not title.strip():
            raise ValueError("title cannot be blank")
        sets.append("title = ?"); params.append(title.strip())
    if body is not None:
        sets.append("body = ?"); params.append(body.strip())
    if tags is not None:
        sets.append("tags = ?"); params.append(_norm_tags(tags))
    if not sets:
        return _card_row(conn, card_id)  # nothing to change
    sets.append("updated_at = datetime('now')")
    params.append(card_id)
    cur = conn.execute(f"UPDATE card SET {', '.join(sets)} WHERE id = ?", params)
    if cur.rowcount == 0:
        return None
    conn.commit()
    if title is not None or due is not None or archived is not None:
        _sync_reminder(conn, card_id)
    return _card_row(conn, card_id)


def move_card(conn: sqlite3.Connection, card_id: int, to_list: str | int,
              position: int | None = None, board: str | int | None = None) -> dict | None:
    """Move a card to another column (by name or id), appending to the end unless ``position`` is
    given. Returns the moved card, or None if the card or target list can't be resolved."""
    row = conn.execute("SELECT id FROM card WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        return None
    if isinstance(to_list, int):
        lst = conn.execute("SELECT id FROM board_list WHERE id = ?", (to_list,)).fetchone()
        list_id = lst["id"] if lst else None
    else:
        list_id = resolve_list(conn, str(to_list), resolve_board(conn, board))
    if list_id is None:
        return None
    if position is None:
        position = _next_position(conn, "card", "list_id", list_id)
    conn.execute(
        "UPDATE card SET list_id = ?, position = ?, updated_at = datetime('now') WHERE id = ?",
        (list_id, int(position), card_id))
    _touch_board(conn, _board_id_of_list(conn, list_id))
    conn.commit()
    return _card_row(conn, card_id)


TRASH_KEEP = 200


def delete_card(conn: sqlite3.Connection, card_id: int) -> bool:
    """Delete a card. It goes to ``card_trash`` first, so ``restore_card`` can bring it back."""
    row = conn.execute("SELECT * FROM card WHERE id = ?", (card_id,)).fetchone()
    if row is not None:
        _cancel_reminder(row["reminder_id"] if "reminder_id" in row.keys() else None)
        lst = _list_row(conn, row["list_id"]) or {}
        conn.execute("INSERT INTO card_trash (card_json, list_id, list_name) VALUES (?,?,?)",
                     (json.dumps(_card_dict(row)), row["list_id"], lst.get("name", "")))
        conn.execute("DELETE FROM card_trash WHERE id NOT IN "
                     "(SELECT id FROM card_trash ORDER BY id DESC LIMIT ?)", (TRASH_KEEP,))
    cur = conn.execute("DELETE FROM card WHERE id = ?", (card_id,))
    conn.commit()
    return cur.rowcount > 0


def trash(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """Recently deleted cards, newest first: {"trashId", "title", "list", "deletedAt", "card"}."""
    out = []
    for r in conn.execute("SELECT * FROM card_trash ORDER BY id DESC LIMIT ?", (int(limit),)):
        card = json.loads(r["card_json"])
        out.append({"trashId": r["id"], "title": card.get("title", ""), "list": r["list_name"],
                    "deletedAt": r["deleted_at"], "card": card})
    return out


def restore_card(conn: sqlite3.Connection, needle: str | int) -> dict | None:
    """Bring back a deleted card: the most recently deleted one whose title matches ``needle``
    (exact, then contains), or by trash id. Back into its old column (or the board's first column
    if that's gone) with its notes, tags, deadline and checklist. None if nothing matches."""
    rows = trash(conn, TRASH_KEEP)
    want = str(needle).strip().lower().lstrip("#")
    hit = None
    if isinstance(needle, int) or want.isdigit():
        hit = next((r for r in rows if r["trashId"] == int(want)), None)
    hit = hit or next((r for r in rows if r["title"].strip().lower() == want), None)
    hit = hit or next((r for r in rows if want and want in r["title"].lower()), None)
    if hit is None:
        return None
    card = hit["card"]
    list_id = hit["card"].get("listId")
    if conn.execute("SELECT 1 FROM board_list WHERE id = ?", (list_id,)).fetchone() is None:
        first = conn.execute("SELECT id FROM board_list ORDER BY board_id, position LIMIT 1").fetchone()
        if first is None:
            return None
        list_id = first["id"]
    pos = _next_position(conn, "card", "list_id", list_id)
    cur = conn.execute(
        "INSERT INTO card (list_id, title, body, tags, position, checklist) VALUES (?,?,?,?,?,?)",
        (list_id, card.get("title", ""), card.get("body", ""), _norm_tags(card.get("tags")), pos,
         json.dumps(card.get("checklist") or [])))
    conn.execute("DELETE FROM card_trash WHERE id = ?", (hit["trashId"],))
    _touch_board(conn, _board_id_of_list(conn, list_id))
    conn.commit()
    if card.get("due"):
        return update_card(conn, cur.lastrowid, due=card["due"])   # also re-arms its reminder
    return _card_row(conn, cur.lastrowid)


# --- read API ------------------------------------------------------------------------------------

def _norm_tags(tags: str | list | None) -> str:
    """Normalize tags to a comma-separated string (accepts a list or a string)."""
    if tags is None:
        return ""
    if isinstance(tags, (list, tuple)):
        parts = [str(t).strip() for t in tags]
    else:
        parts = [t.strip() for t in str(tags).split(",")]
    return ", ".join(p for p in parts if p)


def _card_row(conn: sqlite3.Connection, card_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM card WHERE id = ?", (card_id,)).fetchone()
    return _card_dict(r) if r else None


def _list_row(conn: sqlite3.Connection, list_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM board_list WHERE id = ?", (list_id,)).fetchone()
    return dict(r) if r else None


def _card_dict(r: sqlite3.Row) -> dict:
    keys = r.keys()
    try:
        checklist = json.loads(r["checklist"]) if "checklist" in keys else []
    except (TypeError, ValueError):
        checklist = []
    return {
        "id": r["id"], "listId": r["list_id"], "title": r["title"], "body": r["body"],
        "tags": [t.strip() for t in r["tags"].split(",") if t.strip()],
        "position": r["position"], "createdAt": r["created_at"], "updatedAt": r["updated_at"],
        "due": r["due"] if "due" in keys else None,
        "checklist": checklist,
        "archived": bool(r["archived"]) if "archived" in keys else False,
    }


# --- deadlines, checklists, reminders ------------------------------------------------------------

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
REMINDER_HOUR = 9  # a date-only deadline is announced at 9:00 that morning


def normalize_due(value: str | None, today: date | None = None) -> str | None:
    """A deadline as "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM", or None to clear it. Accepts ISO, plus the
    words people say: today, tomorrow, a weekday ("friday" = the next one), "next week", "in 3 days".
    Raises ValueError for anything else."""
    v = (value or "").strip().lower().rstrip(".")
    if not v or v in ("none", "no", "clear", "remove"):
        return None
    today = today or date.today()
    v = re.sub(r"^(?:on|by|due|for)\s+", "", v)
    if v == "today":
        return today.isoformat()
    if v == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    if v in ("next week", "in a week"):
        return (today + timedelta(days=7)).isoformat()
    m = re.fullmatch(r"in (\d+) (day|week)s?", v)
    if m:
        n = int(m.group(1)) * (7 if m.group(2) == "week" else 1)
        return (today + timedelta(days=n)).isoformat()
    m = re.fullmatch(r"(?:this |next )?(" + "|".join(_WEEKDAYS) + r")", v)
    if m:
        ahead = (_WEEKDAYS.index(m.group(1)) - today.weekday()) % 7 or 7  # the next one, never today
        return (today + timedelta(days=ahead)).isoformat()
    try:
        if "t" in v or " " in v:
            return datetime.fromisoformat(v.replace(" ", "T")).strftime("%Y-%m-%dT%H:%M")
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise ValueError(f"I couldn't read {value!r} as a date") from None


def due_datetime(due: str | None) -> datetime | None:
    """When a deadline's reminder goes off: its time, or 9:00 on a date-only deadline."""
    if not due:
        return None
    try:
        if "T" in due:
            return datetime.fromisoformat(due)
        return datetime.combine(date.fromisoformat(due), time(REMINDER_HOUR))
    except ValueError:
        return None


def _norm_checklist(items) -> list[dict]:
    out = []
    for it in items or []:
        if isinstance(it, str):
            text, done = it, False
        elif isinstance(it, dict):
            text, done = str(it.get("text", "")), bool(it.get("done", False))
        else:
            continue
        if text.strip():
            out.append({"text": text.strip(), "done": done})
    return out


def _cancel_reminder(job_id) -> None:
    if not job_id:
        return
    try:
        from vox import scheduler
        scheduler.cancel_job(job_id)
    except Exception:
        pass


def _sync_reminder(conn: sqlite3.Connection, card_id: int) -> None:
    """Keep one reminder per card with a future deadline: replace it when the deadline or title
    changes, drop it when the deadline is cleared, already past, or the card is archived."""
    r = conn.execute("SELECT title, due, archived, reminder_id FROM card WHERE id = ?", (card_id,)).fetchone()
    if r is None:
        return
    _cancel_reminder(r["reminder_id"])
    new_id = None
    when = due_datetime(r["due"])
    if when is not None and when > datetime.now() and not r["archived"]:
        try:
            from vox import scheduler
            what = "now" if "T" in (r["due"] or "") else "today"
            new_id = scheduler.create_job("reminder", f"{r['title']}, which is due {what}", fire_at=when)["id"]
        except Exception:
            new_id = None
    conn.execute("UPDATE card SET reminder_id = ? WHERE id = ?", (new_id, card_id))
    conn.commit()


def due_cards(conn: sqlite3.Connection, days: int = 7, today: date | None = None) -> list[dict]:
    """Open cards due within ``days`` (overdue ones included), soonest first, with their list."""
    limit = ((today or date.today()) + timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT card.*, board_list.name AS list_name FROM card "
        "JOIN board_list ON card.list_id = board_list.id "
        "WHERE card.archived = 0 AND card.due IS NOT NULL AND substr(card.due, 1, 10) <= ? "
        "ORDER BY card.due", (limit,)).fetchall()
    out = []
    for r in rows:
        d = _card_dict(r)
        d["list"] = r["list_name"]
        out.append(d)
    return out


def bulk(conn: sqlite3.Connection, ops: list[dict]) -> list[dict]:
    """Several changes in one call, in order: [{"op": "add"|"move"|"delete"|"archive"|"update", …}].
    Each result is {"ok": True, "card": …} or {"ok": False, "error": …}; one failure doesn't stop
    the rest."""
    results = []
    for op in ops or []:
        kind = str(op.get("op", "")).lower()
        try:
            if kind == "add":
                card = add_card(conn, str(op.get("list", "")), str(op.get("title", "")),
                                str(op.get("body", "") or ""), op.get("tags") or "", op.get("board"), op.get("due"))
            elif kind == "move":
                card = move_card(conn, int(op["card"]), op.get("toList"), op.get("position"), op.get("board"))
            elif kind == "delete":
                card = {"id": int(op["card"])} if delete_card(conn, int(op["card"])) else None
            elif kind == "archive":
                card = update_card(conn, int(op["card"]), archived=bool(op.get("archived", True)))
            elif kind == "update":
                fields = {k: op[k] for k in ("title", "body", "tags", "due", "checklist", "archived") if k in op}
                card = update_card(conn, int(op["card"]), **fields)
            else:
                raise ValueError(f"unknown op {kind!r}")
            results.append({"ok": True, "card": card} if card is not None else {"ok": False, "error": "card or list not found"})
        except (ValueError, KeyError, TypeError) as exc:
            results.append({"ok": False, "error": str(exc)})
    return results


def board_snapshot(conn: sqlite3.Connection, board: str | int | None = None,
                   archived: bool = False) -> dict:
    """A whole board as nested lists→cards (camelCase), for the dashboard AND agent read. Loads all
    cards in one query (no N+1)."""
    board_id = resolve_board(conn, board)
    if board_id is None:
        return {"id": None, "name": None, "lists": []}
    b = conn.execute("SELECT * FROM board WHERE id = ?", (board_id,)).fetchone()
    lists = conn.execute(
        "SELECT * FROM board_list WHERE board_id = ? ORDER BY position, id", (board_id,)).fetchall()
    list_ids = [l["id"] for l in lists]
    cards_by_list: dict[int, list] = {lid: [] for lid in list_ids}
    if list_ids:
        rows = conn.execute(
            f"SELECT * FROM card WHERE list_id IN ({','.join('?' * len(list_ids))}) AND archived = ? "
            "ORDER BY position, id", (*list_ids, 1 if archived else 0)).fetchall()
        for r in rows:
            cards_by_list.setdefault(r["list_id"], []).append(_card_dict(r))
    return {
        "id": b["id"], "name": b["name"],
        "lists": [{"id": l["id"], "name": l["name"], "position": l["position"],
                   "cards": cards_by_list.get(l["id"], [])} for l in lists],
    }


def list_boards(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM board ORDER BY id").fetchall()]


def search(conn: sqlite3.Connection, query: str, limit: int = 50) -> list[dict]:
    """Case-insensitive substring search across card title, body and tags — the agent's knowledge
    lookup. Each hit carries its list + board name so results are self-locating."""
    q = (query or "").strip()
    if not q:
        return []
    like = f"%{q}%"
    rows = conn.execute(
        "SELECT card.*, board_list.name AS list_name, board.name AS board_name "
        "FROM card JOIN board_list ON card.list_id = board_list.id "
        "JOIN board ON board_list.board_id = board.id "
        "WHERE card.title LIKE ? COLLATE NOCASE OR card.body LIKE ? COLLATE NOCASE "
        "OR card.tags LIKE ? COLLATE NOCASE "
        "ORDER BY card.updated_at DESC LIMIT ?",
        (like, like, like, int(limit))).fetchall()
    out = []
    for r in rows:
        d = _card_dict(r)
        d["list"] = r["list_name"]
        d["board"] = r["board_name"]
        out.append(d)
    return out


def summary(conn: sqlite3.Connection) -> dict:
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("board", "board_list", "card")}


# --- CLI: build / inspect / smoke-test -----------------------------------------------------------

def _print_board(conn) -> None:
    snap = board_snapshot(conn)
    print(f"Board: {snap['name']}  (id={snap['id']})")
    for lst in snap["lists"]:
        print(f"\n  ▸ {lst['name']}  ({len(lst['cards'])} cards)")
        for c in lst["cards"]:
            tags = f"  #{' #'.join(c['tags'])}" if c["tags"] else ""
            print(f"      [{c['id']}] {c['title']}{tags}")


def _selftest(conn) -> None:
    """A tiny end-to-end battery against a throwaway card so behavior is verified, not assumed."""
    print("Smoke test:\n")
    c = add_card(conn, "To Do", "TEST — wire the board", "body notes here", "test, demo")
    print(f"  add_card → [{c['id']}] in list {c['listId']} tags={c['tags']}")
    moved = move_card(conn, c["id"], "Doing")
    print(f"  move_card → now in list {moved['listId']}")
    up = update_card(conn, c["id"], title="TEST — wired ✓", tags="test")
    print(f"  update_card → title={up['title']!r} tags={up['tags']}")
    hits = search(conn, "wired")
    print(f"  search('wired') → {len(hits)} hit(s): {[h['title'] for h in hits]}")
    ok = delete_card(conn, c["id"])
    print(f"  delete_card → {ok}")
    gone = search(conn, "wired")
    print(f"  search('wired') after delete → {len(gone)} hit(s)")
    print(f"\n  {'PASS' if (moved and up and hits and ok and not gone) else 'FAIL'}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Vox workspace board — build / inspect / test")
    ap.add_argument("--show", action="store_true", help="print the board")
    ap.add_argument("--selftest", action="store_true", help="run a CRUD+search smoke test")
    ap.add_argument("--search", dest="q", help="search cards and exit")
    _args = ap.parse_args()

    _conn = build()  # ensure the DB exists + is seeded
    if _args.q:
        for _h in search(_conn, _args.q):
            print(f"  [{_h['id']}] {_h['title']}  ({_h['board']} / {_h['list']})")
    elif _args.selftest:
        _selftest(_conn)
    else:
        for _t, _n in summary(_conn).items():
            print(f"  {_t:12} {_n}")
        print()
        _print_board(_conn)
        print('\nTry:  python -m vox.board_store --selftest')
        print('      python -m vox.board_store --search wired')
