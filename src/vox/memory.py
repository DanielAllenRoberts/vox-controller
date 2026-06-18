"""Local-first memory store for Vox (OpenClaw/Hermes-inspired, minimal).

A single flat episodic log persisted as JSON Lines under ``data/memory.jsonl``.
Each line is one ``Memory`` record::

    {"id": "...", "ts": "2026-06-18T05:21:24+00:00", "text": "...", "tags": ["..."]}

Recall ranks records against a query with a transparent keyword score (TF-style
overlap + tag/recency boosts). The scorer is pluggable: swap ``_score`` for an
embedding-backed ranker later without touching the add/recall/all/remove API or
the on-disk format. Keeping the store as plain JSONL keeps it inspectable,
git-diffable, and dependency-free — the same philosophy behind OpenClaw's
Markdown logs and Hermes' file-backed MEMORY.md.

Design notes and the research behind it live in
``docs/dashboard/research/memory.md``.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Runtime store lives under data/ (gitignored). Resolved relative to repo root
# (this file is src/vox/memory.py → parents[2] is the repo root).
_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_STORE = _DATA_DIR / "memory.jsonl"

# One process-wide lock so concurrent callers (voice daemon + dashboard API
# thread) never interleave partial writes to the JSONL file.
_LOCK = threading.RLock()

_WORD = re.compile(r"[a-z0-9]+")

# Common words carry little signal for keyword recall; drop them from scoring.
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have i in is it its of on or that the "
    "this to was were will with you your me my we our do does did not no yes".split()
)


def _tokens(text: str) -> list[str]:
    """Lowercase word tokens with stopwords removed."""
    return [w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS]


def _ts_seconds(ts) -> float:
    """Epoch seconds for a record's ``ts``, used for recency scoring + sorting.

    ``ts`` is stored as an ISO-8601 string (matching usage.py and the dashboard
    contract). Tolerates the legacy float-epoch format and junk → 0.0.
    """
    if isinstance(ts, (int, float)):
        return float(ts)  # legacy records written before the ISO switch
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _read_all() -> list[dict]:
    """Load every record from the JSONL store (oldest first). Tolerates blanks."""
    if not _STORE.exists():
        return []
    out: list[dict] = []
    with _STORE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # Skip a corrupt line rather than crashing the daemon.
                continue
    return out


def _write_all(records: list[dict]) -> None:
    """Atomically rewrite the whole store (used by remove())."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _STORE.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(_STORE)


def _score(query: str, record: dict) -> float:
    """Transparent keyword relevance score for a record against a query.

    Pluggable seam: replace this with an embedding cosine (or hybrid) ranker
    later. Contract: higher == more relevant; <= 0 means "no match".

    Signals (deliberately simple):
      • token overlap between query and the record's text (the bulk of the score)
      • a boost when a query token matches one of the record's tags
      • a mild recency tiebreak so fresher memories edge out stale ones
    """
    q = _tokens(query)
    if not q:
        return 0.0
    text_tokens = _tokens(record.get("text", ""))
    if not text_tokens:
        return 0.0
    text_counts: dict[str, int] = {}
    for t in text_tokens:
        text_counts[t] = text_counts.get(t, 0) + 1

    tags = {t.lower() for t in record.get("tags", [])}

    score = 0.0
    for token in set(q):
        score += text_counts.get(token, 0)
        if token in tags:
            score += 2.0  # tag hits are a strong, intentional signal
    if score <= 0:
        return 0.0

    # Recency tiebreak: newest record gets +~0.5, decaying over ~30 days.
    age_days = max(0.0, (time.time() - _ts_seconds(record.get("ts"))) / 86_400)
    score += 0.5 / (1.0 + age_days / 30.0)
    return score


def add(text: str, tags: list[str] | None = None) -> dict:
    """Append a memory and return the stored record.

    Returns the ``Memory`` dict ``{id, ts, text, tags}`` (no ``score`` — that's
    only attached by recall()).
    """
    record = {
        "id": uuid.uuid4().hex[:12],
        "ts": datetime.now(timezone.utc).isoformat(),
        "text": text.strip(),
        "tags": list(tags or []),
    }
    with _LOCK:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        with _STORE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def recall(query: str, k: int = 5) -> list[dict]:
    """Return up to ``k`` memories most relevant to ``query``, best first.

    Each returned record carries a ``score`` float. An empty/whitespace query
    returns the ``k`` most recent memories (score 0.0) so callers always get a
    sane "what do you remember" answer.
    """
    with _LOCK:
        records = _read_all()

    if not query or not query.strip():
        recent = sorted(records, key=lambda r: _ts_seconds(r.get("ts")), reverse=True)[:k]
        return [{**r, "score": 0.0} for r in recent]

    scored = ((_score(query, r), r) for r in records)
    ranked = sorted(
        (sr for sr in scored if sr[0] > 0),
        key=lambda sr: (sr[0], _ts_seconds(sr[1].get("ts"))),
        reverse=True,
    )
    return [{**r, "score": round(s, 4)} for s, r in ranked[:k]]


def all() -> list[dict]:  # noqa: A001 - matches the contract's API name
    """Return every memory, newest first."""
    with _LOCK:
        records = _read_all()
    return sorted(records, key=lambda r: _ts_seconds(r.get("ts")), reverse=True)


def remove(id: str) -> bool:  # noqa: A002 - matches the contract's API name
    """Delete the memory with ``id``. Returns True if a record was removed."""
    with _LOCK:
        records = _read_all()
        kept = [r for r in records if r.get("id") != id]
        if len(kept) == len(records):
            return False
        _write_all(kept)
    return True
