"""Command-DB bridge for the dashboard — read + light edits over the SQLite command store.

Backs the dashboard's **Commands** page: the per-app/site voice command database (idea #36,
``docs/plan/command-db.md``). The read returns the whole DB grouped (contexts → commands → phrases)
plus the intent catalog and a row-count summary. Edits are intentionally small for this first cut —
toggle a command or context on/off, and add / remove a phrase — and the running daemon's in-memory
cache (``vox.command_cache``) is refreshed after every write so changes take effect without a restart.

Self-contained + guarded like the other bridge modules (``rules``/``personalities``): a missing or
empty DB degrades to empty lists, never a 500. All shapes are camelCase to mirror ``lib/api.ts``.
"""

from __future__ import annotations

from vox import command_store

_VALID_MATCH = ("exact", "contains", "regex")


def _conn():
    return command_store.connect()  # data/commands.db (creates the dir; FK enforcement on)


def _refresh_cache() -> None:
    """Tell the running daemon to reload its in-memory command cache after an edit. Guarded and
    optional — when the daemon isn't running (dashboard opened standalone) there's nothing to refresh."""
    try:
        from vox import command_cache
        command_cache.refresh()
    except Exception:
        pass


# --- camelCase serialisers (mirror the dashboard's api.ts shapes) --------------------------------

def _phrase(p: dict) -> dict:
    return {"id": p["id"], "text": p["text"],
            "isPrimary": bool(p["is_primary"]), "matchType": p["match_type"]}


def _command(c: dict) -> dict:
    return {
        "id": c["id"], "intent": c["intent"], "arg": c["arg"], "param": c["param"],
        "label": c["label"], "source": c["source"], "enabled": bool(c["enabled"]),
        "priority": c["priority"],
        "phrases": [_phrase(p) for p in c.get("phrases", [])],
    }


def _intent(i: dict) -> dict:
    return {"name": i["name"], "category": i["category"],
            "takesArg": bool(i["takes_arg"]), "argHelp": i["arg_help"],
            "description": i["description"]}


def _context_sort_key(ctx: dict):
    # Show "Everywhere" (global) first as the base set, then apps/sites by priority then name.
    return (ctx["kind"] != "global", -ctx["priority"], ctx["displayName"].lower())


# --- read ----------------------------------------------------------------------------------------

def list_all() -> dict:
    """The whole command DB for the dashboard: contexts (each with its commands + phrases, disabled
    included), the intent catalog, and a row-count summary."""
    conn = _conn()
    try:
        command_store.init_schema(conn)  # safe if the dashboard opens before the daemon seeds
        contexts = []
        for ctx in command_store.list_contexts(conn):
            cmds = command_store.commands_with_phrases(conn, ctx["id"], include_disabled=True)
            contexts.append({
                "id": ctx["id"], "kind": ctx["kind"], "matchValue": ctx["match_value"],
                "displayName": ctx["display_name"], "priority": ctx["priority"],
                "enabled": bool(ctx["enabled"]),
                "commands": [_command(c) for c in cmds],
            })
        contexts.sort(key=_context_sort_key)
        return {
            "contexts": contexts,
            "intents": [_intent(i) for i in command_store.list_intents(conn)],
            "summary": command_store.summary(conn),
        }
    finally:
        conn.close()


def _one_command(conn, cid: int) -> dict | None:
    """Fetch a single command (with its phrases) as a camelCase dict, or None if it's gone."""
    row = conn.execute("SELECT * FROM command WHERE id=?", (cid,)).fetchone()
    if row is None:
        return None
    c = dict(row)
    ph = conn.execute("SELECT id, text, is_primary, match_type FROM phrase WHERE command_id=? "
                      "ORDER BY is_primary DESC, id", (cid,)).fetchall()
    c["phrases"] = [dict(p) for p in ph]
    return _command(c)


# --- edits (each refreshes the daemon cache so the change is live) --------------------------------

def set_command_enabled(command_id, enabled: bool) -> dict:
    """Enable/disable a command. Returns the updated Command. Raises ValueError on an unknown id."""
    cid = int(command_id)
    conn = _conn()
    try:
        cur = conn.execute("UPDATE command SET enabled=?, updated_at=datetime('now') WHERE id=?",
                           (1 if enabled else 0, cid))
        conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f"unknown command id: {cid}")
        out = _one_command(conn, cid)
    finally:
        conn.close()
    _refresh_cache()
    return out


def set_context_enabled(context_id, enabled: bool) -> dict:
    """Enable/disable a whole context (all its commands stop/resume resolving). Returns {id, enabled}."""
    cid = int(context_id)
    conn = _conn()
    try:
        cur = conn.execute("UPDATE context SET enabled=?, updated_at=datetime('now') WHERE id=?",
                           (1 if enabled else 0, cid))
        conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f"unknown context id: {cid}")
    finally:
        conn.close()
    _refresh_cache()
    return {"id": cid, "enabled": bool(enabled)}


def add_phrase(command_id, text, match_type: str = "contains") -> dict:
    """Add a spoken trigger to a command. Non-regex phrases are normalised (the resolver matches on
    the normalised form). Returns the new (or pre-existing, on a dup) Phrase."""
    cid = int(command_id)
    if match_type not in _VALID_MATCH:
        match_type = "contains"
    text = (text or "").strip()
    if match_type != "regex":
        text = command_store.normalize(text)
    if not text:
        raise ValueError("phrase 'text' is required")
    conn = _conn()
    try:
        if conn.execute("SELECT 1 FROM command WHERE id=?", (cid,)).fetchone() is None:
            raise ValueError(f"unknown command id: {cid}")
        conn.execute(
            "INSERT OR IGNORE INTO phrase (command_id, text, is_primary, match_type) VALUES (?,?,0,?)",
            (cid, text, match_type))
        conn.commit()
        row = conn.execute("SELECT id, text, is_primary, match_type FROM phrase "
                           "WHERE command_id=? AND text=?", (cid, text)).fetchone()  # handles dup
    finally:
        conn.close()
    _refresh_cache()
    return _phrase(dict(row))


def remove_phrase(phrase_id) -> bool:
    """Delete a phrase. Returns True if one was removed."""
    pid = int(phrase_id)
    conn = _conn()
    try:
        cur = conn.execute("DELETE FROM phrase WHERE id=?", (pid,))
        conn.commit()
        removed = cur.rowcount > 0
    finally:
        conn.close()
    if removed:
        _refresh_cache()
    return removed


# --- learning review (idea #24; docs/plan/command-learning/) --------------------------------------
# The audit surface. An LLM writing into your command database is only acceptable if you can see
# exactly what it wrote, why, and undo it — so this exposes both the learned commands and the
# candidates that haven't earned promotion yet.

def learning() -> dict:
    """Learned commands (with evidence + score) and the pending candidates behind them."""
    conn = _conn()
    try:
        learned = command_store.learned_commands(conn)
        cands = command_store.candidates(conn, limit=100)
        ctx = {c["id"]: c for c in command_store.list_contexts(conn)}
    finally:
        conn.close()

    def where(cid):
        c = ctx.get(cid) or {}
        return c.get("match_value") or ("global" if c.get("kind") == "global" else "?")

    return {
        "mode": _learn_mode(),
        "thresholds": _thresholds(),
        "aliases": _learned_aliases(),
        "learned": [{
            "id": c["id"], "intent": c["intent"], "arg": c["arg"], "label": c["label"],
            "context": where(c["context_id"]), "phrases": c["phrases"],
            "enabled": bool(c["enabled"]), "hits": c["hit_count"], "score": c["score"],
            "learned_at": c["learned_at"], "reason": c["learned_reason"],
            "last_used_at": c["last_used_at"],
            **_probation(c),
        } for c in learned],
        "candidates": [{
            "id": c["id"], "intent": c["intent"], "arg": c["arg"],
            "context": where(c["context_id"]),
            "phrases": [p["text"] for p in c["phrases"]],
            "hits": c["hit_count"], "negatives": c["negative_count"],
            "blocked": bool(c["blocked"]), "promoted_id": c["promoted_id"],
            "first_seen": c["first_seen"], "last_seen": c["last_seen"],
            "bar": _bar_reason(c),
        } for c in cands if not c["promoted_id"]],
    }


def _learned_aliases() -> list[dict]:
    """Phrases the learner attached to an EXISTING command (the variant collapse, doc 02).

    These were invisible until now: the page counts learned *commands*, and when the learner sees a
    new way of saying something Vox already does it attaches the phrase to that command instead of
    creating a duplicate — the better outcome, and the one that left the dashboard reporting
    "0 learned" while it had in fact been learning. Read live: `phrase.source='learned'` on a command
    that isn't itself learned."""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT p.id, p.text, p.hit_count, c.id AS command_id, c.label, c.intent, c.arg "
            "FROM phrase p JOIN command c ON c.id = p.command_id "
            "WHERE p.source='learned' AND c.source <> 'learned' ORDER BY p.id DESC").fetchall()
        return [{"id": r["id"], "text": r["text"], "hits": r["hit_count"],
                 "command_id": r["command_id"], "label": r["label"],
                 "intent": r["intent"], "arg": r["arg"]} for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def _thresholds() -> dict:
    """The live tuning knobs, so the UI can explain *why* something hasn't been saved yet rather
    than leaving the user to guess (or read the code)."""
    from vox import command_store as cs
    return {
        "min_hits": int(cs._learn_setting("learning_min_hits", 3)),
        "window_days": float(cs._learn_setting("learning_window_days", 2)),
        "probation_days": int(cs._learn_setting("learning_probation_days", 14)),
        "probation_uses": int(cs._learn_setting("learning_probation_uses", 2)),
        "max_negatives": int(cs._learn_setting("learning_max_negatives", 3)),
    }


def _probation(c) -> dict:
    """Is this learned command still unproven? `decay()` deletes a learned row that's older than
    `learning_probation_days` and still under `learning_probation_uses` hits — so "on probation"
    means exactly: inside that window, and not yet at the use count that makes it permanent."""
    from datetime import datetime, timedelta
    t = _thresholds()
    uses_left = max(0, t["probation_uses"] - int(c["hit_count"] or 0))
    if not c["learned_at"] or uses_left == 0:
        return {"probation": False, "probation_days_left": None, "probation_uses_left": 0}
    try:
        learned_at = datetime.fromisoformat(str(c["learned_at"]))
        days_left = (learned_at + timedelta(days=t["probation_days"]) - datetime.utcnow()).days
    except Exception:
        days_left = None
    return {"probation": True, "probation_days_left": days_left, "probation_uses_left": uses_left}


def _bar_reason(c) -> str:
    """The human reason this candidate has or hasn't earned promotion — reuses the SAME predicate
    the learner uses, so the UI can never disagree with the actual decision."""
    try:
        from vox import command_learn
        ok, why = command_learn.clears_bar(dict(c))
        return ("ready — " if ok else "") + why
    except Exception:
        return ""


def reject_candidate(candidate_id) -> bool:
    """Reject a candidate from the UI: block it so it stops accumulating AND can't come back on its
    own. Without this the only ways to say "no, never" were a voice correction or raw SQL."""
    conn = _conn()
    try:
        cur = conn.execute("UPDATE command_candidate SET blocked=1 WHERE id=?", (int(candidate_id),))
        conn.commit()
        return bool(cur.rowcount)
    finally:
        conn.close()


def _learn_mode() -> str:
    try:
        from vox import command_learn
        return command_learn.mode()
    except Exception:
        return "unknown"


def promote_candidate(candidate_id) -> dict | None:
    """Approve a candidate by hand (the 'suggest' path, and a manual override in any mode)."""
    conn = _conn()
    try:
        cid = command_store.promote(conn, int(candidate_id), reason="approved")
        row = _one_command(conn, cid) if cid else None
    finally:
        conn.close()
    _refresh_cache()
    return row


def forget_learned(command_id, *, block_days: int = 30) -> bool:
    """Delete a learned command and stop it coming straight back. Refuses builtin/user rows."""
    conn = _conn()
    try:
        ok = command_store.retire(conn, int(command_id), delete=True, block_days=block_days)
    finally:
        conn.close()
    if ok:
        _refresh_cache()
    return ok
