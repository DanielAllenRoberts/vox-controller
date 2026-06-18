"""Tiered, human-editable Markdown memory store for Vox.

Realises ``docs/dashboard/MEMORY_DESIGN.md`` (v1). Two tiers, both plaintext
Markdown under ``data/memory/`` (gitignored), so the user can read, trust, and
hand-edit exactly what's kept — the same "if it's not on disk it doesn't exist"
philosophy as OpenClaw's notes and Hermes' MEMORY.md.

  • **Core** — ``data/memory/core.md``: a small, curated set of durable,
    always-relevant facts. **Always injected** into the prompt.
  • **Daily** — ``data/memory/daily/YYYY-MM-DD.md``: dated logs of what happened /
    was learned that day. Recalled by relevance (today + yesterday always, plus
    keyword-matched older days).

Entry format, one per Markdown bullet, human-editable::

    - [2026-06-18T09:12Z] (#prefs #vox) Prefers concise, spoken-style answers.

timestamp · optional ``#tags`` · text. The entry **id** is a stable line-hash of
its tier + raw line, so the dashboard can target edit/delete even after the user
hand-edits the file. ``core.md`` may use ``##`` section headers for readability;
those are skipped when parsing entries.

**Canonical-store invariant:** Markdown is the source of truth. Any future
SQLite/vector index is a *rebuildable* layer over it, and recall must always fall
back to a plain Markdown scan. This module is self-contained and **never raises on
read** — a missing/corrupt store yields an empty result, never an exception, so
the voice daemon is unaffected.

A one-time, idempotent migration folds any legacy ``data/memory.jsonl`` into
``core.md`` (then the JSONL is ignored).

Research and rationale: ``docs/dashboard/research/memory-tiered.md`` and
``docs/dashboard/memory.md``.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Runtime store lives under data/ (gitignored). Resolved relative to repo root
# (this file is src/vox/memory.py → parents[2] is the repo root).
_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_MEM_DIR = _DATA_DIR / "memory"
_CORE_FILE = _MEM_DIR / "core.md"
_DAILY_DIR = _MEM_DIR / "daily"
_LEGACY_JSONL = _DATA_DIR / "memory.jsonl"
# Marker so the legacy JSONL → core.md migration runs at most once.
_MIGRATED_MARKER = _MEM_DIR / ".migrated-jsonl"

# One process-wide lock so concurrent callers (voice daemon + dashboard API
# thread) never interleave partial writes.
_LOCK = threading.RLock()

# --- Parsing -----------------------------------------------------------------

# A memory bullet: "- [<ts>] (#a #b) text"  — the timestamp and tag group are
# optional so a user can scribble a bare "- something" and we still keep it.
_BULLET = re.compile(
    r"^\s*-\s+"                      # bullet
    r"(?:\[(?P<ts>[^\]]*)\]\s*)?"   # optional [timestamp]
    r"(?:\((?P<tags>[^)]*)\)\s*)?"  # optional (#tag #tag)
    r"(?P<text>.*\S)\s*$"           # the text (must have non-space content)
)
_TAG = re.compile(r"#([\w-]+)")
_WORD = re.compile(r"[a-z0-9]+")

# Common words carry little signal for keyword recall; drop them from scoring.
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have i in is it its of on or that the "
    "this to was were will with you your me my we our do does did not no yes".split()
)


def _tokens(text: str) -> list[str]:
    """Lowercase word tokens with stopwords removed."""
    return [w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS]


def _now_iso() -> str:
    """Current UTC timestamp, ISO-8601 (the on-disk + API ``ts`` format)."""
    return datetime.now(timezone.utc).isoformat()


def _ts_seconds(ts) -> float:
    """Epoch seconds for an entry's ``ts``, for recency scoring + sorting.

    Tolerates ISO-8601 strings (with or without a trailing ``Z``), legacy
    float-epoch, and junk → 0.0. Never raises.
    """
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str) and ts.strip():
        s = ts.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(s).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _entry_id(tier: str, raw_line: str) -> str:
    """Stable line-hash id for an entry: hash of ``tier`` + its raw Markdown line.

    Survives hand-edits to *other* lines and reordering; changes only if this
    entry's own text/tags/ts change (which is the intended "this is a different
    memory now" behaviour).
    """
    h = hashlib.sha1(f"{tier}\x00{raw_line.strip()}".encode("utf-8"))
    return h.hexdigest()[:12]


def _render_line(ts: str, tags: list[str], text: str) -> str:
    """Render one memory bullet in the canonical on-disk format."""
    parts = ["-", f"[{ts}]"]
    if tags:
        parts.append("(" + " ".join(f"#{t.lstrip('#')}" for t in tags) + ")")
    parts.append(text.strip())
    return " ".join(parts)


def _parse_line(tier: str, line: str) -> dict | None:
    """Parse one Markdown line into an entry dict, or None if it isn't a bullet.

    ``##`` headers, blank lines, and prose are ignored (return None). Never raises.
    """
    raw = line.rstrip("\n")
    stripped = raw.strip()
    if not stripped or stripped.startswith("#"):
        return None  # header / blank / comment, not an entry
    m = _BULLET.match(raw)
    if not m:
        return None
    text = (m.group("text") or "").strip()
    if not text:
        return None
    tag_blob = m.group("tags") or ""
    tags = _TAG.findall(tag_blob)
    return {
        "id": _entry_id(tier, raw),
        "ts": (m.group("ts") or "").strip(),
        "text": text,
        "tags": tags,
        "tier": tier,
    }


# --- File helpers (read: never raise) ----------------------------------------

def _read_file_entries(path: Path, tier: str) -> list[dict]:
    """Parse all entries from one Markdown file. Missing/unreadable → []."""
    try:
        if not path.exists():
            return []
        out: list[dict] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                entry = _parse_line(tier, line)
                if entry is not None:
                    out.append(entry)
        return out
    except Exception:
        return []  # canonical-store invariant: read never raises


def _daily_path(d: _date) -> Path:
    return _DAILY_DIR / f"{d.isoformat()}.md"


def _parse_date(value: str | None) -> _date:
    """Coerce a YYYY-MM-DD string (or None) to a date; today on bad input."""
    if not value:
        return datetime.now(timezone.utc).date()
    try:
        return _date.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc).date()


# --- One-time legacy JSONL → core.md migration -------------------------------

def _migrate_legacy_jsonl() -> None:
    """Fold a legacy ``data/memory.jsonl`` into ``core.md`` exactly once.

    Idempotent: guarded by a ``.migrated-jsonl`` marker. Each legacy record
    becomes a core bullet (legacy memories were durable, hand-curated facts).
    Best-effort — any failure is swallowed so it never blocks the daemon.
    """
    try:
        if _MIGRATED_MARKER.exists() or not _LEGACY_JSONL.exists():
            return
        records: list[dict] = []
        with _LEGACY_JSONL.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        _MEM_DIR.mkdir(parents=True, exist_ok=True)
        # Build the set of text already present in core so re-runs (or a partially
        # migrated file) don't duplicate.
        existing = {e["text"].strip().lower() for e in _read_file_entries(_CORE_FILE, "core")}
        new_lines: list[str] = []
        for r in records:
            text = str(r.get("text") or "").strip()
            if not text or text.lower() in existing:
                continue
            ts = r.get("ts")
            ts = ts if isinstance(ts, str) and ts.strip() else _now_iso()
            tags = [str(t) for t in (r.get("tags") or [])]
            new_lines.append(_render_line(ts, tags, text))
            existing.add(text.lower())

        if new_lines:
            header_needed = not _CORE_FILE.exists()
            with _CORE_FILE.open("a", encoding="utf-8") as f:
                if header_needed:
                    f.write("# Core memories\n\n")
                f.write("\n".join(new_lines) + "\n")

        _MIGRATED_MARKER.write_text(_now_iso() + "\n", encoding="utf-8")
    except Exception:
        # Migration is best-effort; a failure must never break a read/write or
        # the daemon. We simply leave the marker absent and retry next time.
        pass


def _ensure_ready() -> None:
    """Create the store dirs and run the one-time migration. Guarded."""
    try:
        _MEM_DIR.mkdir(parents=True, exist_ok=True)
        _DAILY_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    _migrate_legacy_jsonl()


# --- Scoring (pluggable seam) ------------------------------------------------

def _score(query_tokens: list[str], entry: dict) -> float:
    """Transparent keyword relevance score for a daily entry against a query.

    Pluggable seam: swap for an embedding cosine (or 70/30 hybrid) later without
    touching the API or on-disk format. Contract: higher == more relevant, <= 0
    means "no match".

    Signals: token overlap with the entry text (bulk of the score), a boost when
    a query token matches a tag, and a mild recency tiebreak.
    """
    if not query_tokens:
        return 0.0
    text_tokens = _tokens(entry.get("text", ""))
    if not text_tokens:
        return 0.0
    counts: dict[str, int] = {}
    for t in text_tokens:
        counts[t] = counts.get(t, 0) + 1
    tags = {t.lower() for t in entry.get("tags", [])}

    score = 0.0
    for token in set(query_tokens):
        score += counts.get(token, 0)
        if token in tags:
            score += 2.0  # tag hits are a strong, intentional signal
    if score <= 0:
        return 0.0
    age_days = max(0.0, (time.time() - _ts_seconds(entry.get("ts"))) / 86_400)
    score += 0.5 / (1.0 + age_days / 30.0)
    return score


# --- Public API --------------------------------------------------------------

def add(text: str, tier: str = "daily", tags: list[str] | None = None) -> dict:
    """Append a memory bullet and return the stored entry dict.

    ``tier`` is ``"core"`` or ``"daily"`` (anything else → ``"daily"``). Daily
    entries land in today's ``daily/YYYY-MM-DD.md``.

    Back-compat: the legacy signature was ``add(text, tags_list)`` — callers (and
    the dashboard ``POST /api/memory``) still pass a *list* as the second
    positional arg. If ``tier`` is a list, it's treated as ``tags`` and the entry
    goes to ``daily`` (the old default behaviour, where everything was one log).

    Returns ``{id, ts, text, tags, tier}``. Never raises on bad input — a blank
    text returns an unsaved sentinel dict rather than throwing.
    """
    # Legacy positional-tags shim: add(text, ["#a"]) → daily with those tags.
    if isinstance(tier, (list, tuple)):
        tags = list(tier)
        tier = "daily"
    tier = "core" if str(tier).lower() == "core" else "daily"
    tags = [str(t).lstrip("#") for t in (tags or [])]
    text = (text or "").strip()

    ts = _now_iso()
    entry = {"id": "", "ts": ts, "text": text, "tags": tags, "tier": tier}
    if not text:
        return entry  # nothing to store; don't write empty bullets

    line = _render_line(ts, tags, text)
    entry["id"] = _entry_id(tier, line)

    with _LOCK:
        _ensure_ready()
        try:
            if tier == "core":
                path = _CORE_FILE
                header = "# Core memories\n\n"
            else:
                path = _daily_path(datetime.now(timezone.utc).date())
                header = f"# {path.stem}\n\n"
            path.parent.mkdir(parents=True, exist_ok=True)
            need_header = not path.exists()
            with path.open("a", encoding="utf-8") as f:
                if need_header:
                    f.write(header)
                f.write(line + "\n")
        except Exception:
            pass  # write failures must not crash the caller
    return entry


def core() -> list[dict]:
    """All core memories, file order (newest appended last). For the dashboard."""
    with _LOCK:
        _ensure_ready()
        return _read_file_entries(_CORE_FILE, "core")


def daily(date: str | None = None) -> list[dict]:
    """Daily memories for ``date`` (YYYY-MM-DD, default today), file order.

    Unknown/blank date → today. Missing file → []. For the dashboard.
    """
    with _LOCK:
        _ensure_ready()
        return _read_file_entries(_daily_path(_parse_date(date)), "daily")


def dates() -> list[str]:
    """All dates that have a daily log, newest first (YYYY-MM-DD). For browsing."""
    with _LOCK:
        _ensure_ready()
        try:
            out = []
            for p in _DAILY_DIR.glob("*.md"):
                stem = p.stem
                try:
                    _date.fromisoformat(stem)
                except ValueError:
                    continue  # ignore non-date filenames
                out.append(stem)
            return sorted(out, reverse=True)
        except Exception:
            return []


def recall(query: str, k: int = 5) -> list[dict]:
    """Memories for prompt injection: **all core** + the most relevant **daily**.

    Daily selection always includes **today + yesterday** (continuity across a day
    boundary), then keyword-matched older days, up to ``k`` daily entries total.
    An empty query → core + the ``k`` most recent daily entries.

    Each returned entry carries a ``score`` (0.0 for core / always-included days).
    Ordering: all core first (file order), then daily best-first. Never raises.
    """
    try:
        k = int(k)
    except (TypeError, ValueError):
        k = 5
    if k < 0:
        k = 0

    with _LOCK:
        _ensure_ready()
        core_entries = _read_file_entries(_CORE_FILE, "core")
        today = datetime.now(timezone.utc).date()
        always_dates = {today, today - timedelta(days=1)}
        # Gather all daily entries, tracking which came from the always-load window.
        recent_entries: list[dict] = []   # today + yesterday (unconditional)
        older_entries: list[dict] = []    # everything else (keyword-matched)
        for d_str in dates():
            d = _parse_date(d_str)
            entries = _read_file_entries(_daily_path(d), "daily")
            if d in always_dates:
                recent_entries.extend(entries)
            else:
                older_entries.extend(entries)

    core_out = [{**e, "score": 0.0} for e in core_entries]

    # Always-included recent days, newest entry first, each score 0.0.
    recent_out = sorted(
        recent_entries, key=lambda e: _ts_seconds(e.get("ts")), reverse=True
    )

    q = (query or "").strip()
    if not q:
        daily_out = [{**e, "score": 0.0} for e in recent_out][:k]
        return core_out + daily_out

    qtokens = _tokens(q)
    # Score recent entries too so the best-matching recent ones surface first,
    # but recent entries are never dropped for lack of a match (continuity).
    scored_recent = [
        {**e, "score": round(_score(qtokens, e), 4)} for e in recent_out
    ]
    scored_older = sorted(
        ({**e, "score": round(_score(qtokens, e), 4)} for e in older_entries),
        key=lambda e: (e["score"], _ts_seconds(e.get("ts"))),
        reverse=True,
    )
    matched_older = [e for e in scored_older if e["score"] > 0]

    # Recent (always) first, then keyword-matched older, capped at k daily total.
    daily_out = (scored_recent + matched_older)[:k]
    return core_out + daily_out


def remove(id: str) -> bool:  # noqa: A002 - matches the contract's API name
    """Delete the entry whose line-hash is ``id``. True if something was removed.

    Scans core then every daily file, rewriting the one that contained the match.
    Non-entry lines (headers, blanks) are preserved verbatim. Never raises.
    """
    if not id:
        return False
    with _LOCK:
        _ensure_ready()
        files = [(_CORE_FILE, "core")]
        try:
            files += [(p, "daily") for p in sorted(_DAILY_DIR.glob("*.md"))]
        except Exception:
            pass
        for path, tier in files:
            try:
                if not path.exists():
                    continue
                lines = path.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            kept: list[str] = []
            removed = False
            for line in lines:
                entry = _parse_line(tier, line)
                if entry is not None and entry["id"] == id:
                    removed = True
                    continue  # drop this bullet
                kept.append(line)
            if removed:
                try:
                    body = "\n".join(kept)
                    if body and not body.endswith("\n"):
                        body += "\n"
                    path.write_text(body, encoding="utf-8")
                except Exception:
                    return False
                return True
    return False


def update(id: str, text: str | None = None, tags: list[str] | None = None) -> dict | None:  # noqa: A002
    """Edit the entry whose line-hash is ``id`` in place; return the new entry dict.

    Rewrites the one bullet that matches, preserving its original timestamp and the
    file (tier) it lives in. ``text``/``tags`` left as ``None`` are kept as-is. The
    returned entry carries a *new* ``id`` (the line-hash changes with its content).
    ``None`` if no entry matched. Never raises; on a write failure returns ``None``.
    """
    if not id:
        return None
    with _LOCK:
        _ensure_ready()
        files = [(_CORE_FILE, "core")]
        try:
            files += [(p, "daily") for p in sorted(_DAILY_DIR.glob("*.md"))]
        except Exception:
            pass
        for path, tier in files:
            try:
                if not path.exists():
                    continue
                lines = path.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            new_entry: dict | None = None
            out: list[str] = []
            for line in lines:
                entry = _parse_line(tier, line)
                if new_entry is None and entry is not None and entry["id"] == id:
                    ts = entry.get("ts") or _now_iso()
                    new_text = entry["text"] if text is None else (text or "").strip()
                    if not new_text:
                        # Refusing to blank an entry — that's a delete, not an edit.
                        return None
                    new_tags = (
                        entry.get("tags", [])
                        if tags is None
                        else [str(t).lstrip("#") for t in tags]
                    )
                    new_line = _render_line(ts, new_tags, new_text)
                    out.append(new_line)
                    new_entry = {
                        "id": _entry_id(tier, new_line),
                        "ts": ts,
                        "text": new_text,
                        "tags": new_tags,
                        "tier": tier,
                    }
                else:
                    out.append(line)
            if new_entry is not None:
                try:
                    body = "\n".join(out)
                    if body and not body.endswith("\n"):
                        body += "\n"
                    path.write_text(body, encoding="utf-8")
                except Exception:
                    return None
                return new_entry
    return None


def path_for(tier: str, date: str | None = None) -> str:
    """On-disk path for a tier (for the dashboard "open file location" button).

    ``tier="core"`` → ``core.md``; ``tier="daily"`` → that date's log (default
    today). Returns an absolute path string; the file need not exist yet.
    """
    if str(tier).lower() == "core":
        return str(_CORE_FILE)
    return str(_daily_path(_parse_date(date)))


# --- Back-compat: the old flat-log API ---------------------------------------

def all() -> list[dict]:  # noqa: A001 - matches the legacy contract's API name
    """Every memory (core + all daily), newest first. Back-compat for the old
    flat-log callers and the dashboard's ``GET /api/memory`` list view.

    Entries carry ``tier`` so newer callers can distinguish; legacy callers that
    only read ``{id, ts, text, tags}`` keep working. Never raises.
    """
    with _LOCK:
        _ensure_ready()
        entries = _read_file_entries(_CORE_FILE, "core")
        try:
            for p in _DAILY_DIR.glob("*.md"):
                entries.extend(_read_file_entries(p, "daily"))
        except Exception:
            pass
    return sorted(entries, key=lambda e: _ts_seconds(e.get("ts")), reverse=True)
