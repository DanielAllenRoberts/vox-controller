"""Phase 2 gate (docs/plan/command-learning/06-rollout.md) — promotion is live.

  1. 3 uses in one day → auto-saved as a learned command (rolling window, no waiting for tomorrow)
  2. the learned command then RESOLVES from the DB — no LLM round-trip
  3. a variant phrasing attaches as an ALIAS, never a second command
  4. "remember that" saves immediately, bar bypassed
  5. "forget that" deletes it AND blocks re-learning
  6. one "no" retires a learned command that did the wrong thing
  7. re-mapping repoints a learned command but refuses builtin ones
  8. probation deletes a command that never got used; a proven one survives
  9. caps evict the lowest-scoring learned command
Runs entirely against a temp DB.
"""
import os
import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "data" / "commands.db")
TMP = str(pathlib.Path(tempfile.gettempdir()) / "vox_gate2.db")
if os.path.exists(TMP):
    os.remove(TMP)
shutil.copyfile(SRC, TMP)

from vox import command_learn, command_store as cs

_real = cs.connect
cs.connect = lambda path=TMP: _real(TMP)
command_learn._refresh_cache = lambda: None      # no daemon running to refresh
conn = cs.connect()
cs.init_schema(conn)

fails = []


def check(label, cond, detail=""):
    print(f"{'  ✓' if cond else '  ✗'} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        fails.append(label)


def say(phrase, intent="click", arg="standup-notes", app="Slack"):
    command_learn._pending = None                 # each call is its own turn
    return command_learn.observe(phrase, intent, arg, app=app, success=True)


base_cmds = conn.execute("SELECT COUNT(*) FROM command").fetchone()[0]

# --- 1. saved on first use, usable immediately -------------------------------------------------------
# Design as of 2026-08-03: the LLM works something out ONCE, it's saved and usable straight away, and
# every use after that skips the LLM. `learning_min_hits` is the bar for SAVING; permanence is earned
# separately through probation (step 8). Paying for the same resolution three times before it becomes
# usable was the exact cost this feature exists to remove.
print("\n1. saved on the first use, usable immediately")
r1 = say("open my standup notes")
cmd_id = r1.get("promoted")
check("1st use → SAVED", bool(cmd_id), f"command #{cmd_id}")
row = conn.execute("SELECT * FROM command WHERE id=?", (cmd_id,)).fetchone() if cmd_id else None
check("saved as source='learned'", row is not None and row["source"] == "learned")
check("counts the creating use as 1", row is not None and row["hit_count"] == 1,
      f"hit_count={row['hit_count'] if row is not None else '?'}")
# further phrasings attach as aliases to the SAME command (step 3 proves it in detail)
r2, r3 = say("pull up standup notes"), say("show standup notes")
check("later phrasings don't create rival commands",
      not r2.get("promoted") and not r3.get("promoted"),
      f"alias_of={r2.get('alias_of')}/{r3.get('alias_of')}")
check("a focus-dependent intent (click) is APP-scoped",
      row is not None and conn.execute("SELECT match_value FROM context WHERE id=?",
                                       (row["context_id"],)).fetchone()["match_value"] == "Slack")
# ...while opening an app/URL does the same thing anywhere, so it learns once, globally — otherwise
# "open logic" needs three hits in every app you happen to say it from (seen in real shadow data).
for _ in range(3):
    say("open logic", intent="navigate", arg="logic pro", app="Slack")
glob = conn.execute("SELECT c.id, ctx.kind FROM command c JOIN context ctx ON ctx.id=c.context_id "
                    "WHERE c.source='learned' AND c.arg='logic pro'").fetchone()
check("a focus-independent intent (navigate) is GLOBAL", glob is not None and glob["kind"] == "global",
      glob["kind"] if glob else "not learned")
check("and it resolves from any app",
      (cs.resolve(conn, "open logic", app="Cursor") or {}).get("command_id") == (glob["id"] if glob else None))
check("carries its phrases",
      conn.execute("SELECT COUNT(*) FROM phrase WHERE command_id=?", (cmd_id,)).fetchone()[0] >= 2)

# --- 2. it now resolves from the DB (the whole point) ------------------------------------------------
print("\n2. resolves from the DB, no LLM")
hit = cs.resolve(conn, "open my standup notes", app="Slack")
check("'open my standup notes' resolves", hit is not None and hit["command_id"] == cmd_id,
      f"{hit and hit['intent']}/{hit and hit['arg']}")
check("a phrase it never heard does NOT resolve",
      cs.resolve(conn, "open my retro notes", app="Slack") is None)

# --- 3. a new phrasing becomes an alias, not a new command -------------------------------------------
print("\n3. variant collapse after promotion")
before = conn.execute("SELECT COUNT(*) FROM command WHERE source='learned'").fetchone()[0]
r4 = say("bring up the standup notes")
after = conn.execute("SELECT COUNT(*) FROM command WHERE source='learned'").fetchone()[0]
check("no second command created", before == after, f"{before} → {after}")
check("attached as an alias to the same command", r4.get("alias_of") == cmd_id)
check("the new phrase resolves too",
      (cs.resolve(conn, "bring up the standup notes", app="Slack") or {}).get("command_id") == cmd_id)

# --- 4. "remember that" ------------------------------------------------------------------------------
# Now mostly redundant by design: saving happens on the first use, so by the time you could say
# "remember that" it is usually already saved and this just confirms so. It still matters as the
# manual override for anything the auto-path declined (suggest mode, or `learning_confirm` on).
print("\n4. 'remember that'")
say("open the pricing sheet", intent="navigate", arg="pricing-sheet")   # already saves on this use
msg = command_learn.remember_that()
explicit = conn.execute("SELECT * FROM command WHERE source='learned' AND arg='pricing-sheet'").fetchone()
check("the command exists after asking", explicit is not None, msg or "")
check("asking again is harmless (no duplicate)",
      conn.execute("SELECT COUNT(*) FROM command WHERE source='learned' AND arg='pricing-sheet'")
      .fetchone()[0] == 1)

# --- 5. "forget that" --------------------------------------------------------------------------------
print("\n5. 'forget that'")
msg = command_learn.forget_that()
gone = conn.execute("SELECT * FROM command WHERE source='learned' AND arg='pricing-sheet'").fetchone()
check("deleted", gone is None, msg or "")
blocked = conn.execute("SELECT blocked FROM command_candidate WHERE arg='pricing-sheet'").fetchone()
check("blocked from being re-learned", blocked is not None and blocked["blocked"] == 1)
for _ in range(4):
    say("open the pricing sheet", intent="navigate", arg="pricing-sheet")
check("stays gone even after 4 more uses",
      conn.execute("SELECT COUNT(*) FROM command WHERE source='learned' AND arg='pricing-sheet'"
                   ).fetchone()[0] == 0)

# --- 5b. "remember that" as the override when the auto-path declined ---------------------------------
# Kept AFTER "forget that": both act on the last observed action, so testing them against the same
# command in sequence would have them fight over `_last`.
print("\n5b. 'remember that' overrides a withheld save")
_mode = command_learn.mode
command_learn.mode = lambda: "suggest"
say("open the burndown chart", intent="navigate", arg="burndown")
held = conn.execute("SELECT * FROM command WHERE source='learned' AND arg='burndown'").fetchone()
check("suggest mode withholds the save", held is None)
command_learn.mode = _mode
msg2 = command_learn.remember_that()
taken = conn.execute("SELECT * FROM command WHERE source='learned' AND arg='burndown'").fetchone()
check("'remember that' takes it anyway", taken is not None, msg2 or "")
check("recorded as an explicit save",
      taken is not None and taken["learned_reason"] == "explicit")

# --- 6. one "no" retires a learned command that misfired ---------------------------------------------
print("\n6. correction retires a learned command")
command_learn.note_db_hit(cmd_id, "open my standup notes", intent="click",
                          arg="standup-notes", app="Slack")
command_learn.check_negative("no")
row = conn.execute("SELECT enabled FROM command WHERE id=?", (cmd_id,)).fetchone()
check("one 'no' disables it", row is not None and row["enabled"] == 0)
check("the learned command stops resolving",
      (cs.resolve(conn, "open my standup notes", app="Slack") or {}).get("command_id") != cmd_id)

# --- 7. re-mapping ------------------------------------------------------------------------------------
print("\n7. 'when I say that, I actually mean...'")
conn.execute("UPDATE command SET enabled=1 WHERE id=?", (cmd_id,)); conn.commit()
command_learn._last = {"candidate_id": None, "command_id": cmd_id,
                       "phrase": "open my standup notes", "intent": "click",
                       "arg": "standup-notes", "app": "Slack", "context_id": None}
msg = command_learn.remap_last("click", "team-standup")
row = conn.execute("SELECT intent, arg, learned_reason FROM command WHERE id=?", (cmd_id,)).fetchone()
check("learned command re-pointed", row["arg"] == "team-standup", msg or "")
check("marked as a remap (probation resets)", row["learned_reason"] == "remap")
check("its phrases survived",
      conn.execute("SELECT COUNT(*) FROM phrase WHERE command_id=?", (cmd_id,)).fetchone()[0] >= 2)
builtin_id = conn.execute("SELECT id FROM command WHERE source='builtin' LIMIT 1").fetchone()[0]
check("refuses to re-map a BUILTIN command", cs.remap(conn, builtin_id, "navigate", "hijack") is None)

# --- 8. probation --------------------------------------------------------------------------------------
print("\n8. probation")
conn.execute("UPDATE command SET learned_at = datetime('now','-20 days'), hit_count = 0 "
             "WHERE id=?", (cmd_id,))
conn.execute("INSERT INTO command (context_id, intent, arg, label, source, learned_at, hit_count, "
             "last_used_at) VALUES ((SELECT id FROM context WHERE kind='global'), 'navigate', "
             "'proven', 'Proven', 'learned', datetime('now','-20 days'), 5, datetime('now'))")
proven_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
conn.commit()
res = cs.decay(conn)
check("unused command deleted after probation",
      conn.execute("SELECT COUNT(*) FROM command WHERE id=?", (cmd_id,)).fetchone()[0] == 0,
      f"{res['probation_deleted']} deleted")
check("a proven command survives",
      conn.execute("SELECT COUNT(*) FROM command WHERE id=?", (proven_id,)).fetchone()[0] == 1)
check("builtin commands untouched by decay",
      conn.execute("SELECT COUNT(*) FROM command WHERE source='builtin'").fetchone()[0] == base_cmds)

# --- 9. caps evict the weakest ---------------------------------------------------------------------------
print("\n9. caps")
ctx = conn.execute("SELECT id FROM context WHERE kind='global'").fetchone()[0]
for i in range(45):
    conn.execute("INSERT INTO command (context_id, intent, arg, label, source, hit_count, "
                 "last_used_at, learned_at) VALUES (?,?,?,?, 'learned', ?, datetime('now'), "
                 "datetime('now'))", (ctx, "navigate", f"app{i}", f"App {i}", i))
conn.commit()
cs._enforce_caps(conn, ctx)
kept = conn.execute("SELECT COUNT(*) FROM command WHERE source='learned' AND context_id=?",
                    (ctx,)).fetchone()[0]
check("per-context cap enforced", kept <= 40, f"{kept} kept (cap 40)")
survivor = conn.execute("SELECT MIN(hit_count) FROM command WHERE source='learned' AND context_id=? "
                        "AND arg LIKE 'app%'", (ctx,)).fetchone()[0]
check("the least-used were the ones evicted", survivor is not None and survivor > 0,
      f"lowest surviving hit_count={survivor}")

print()
print("✅ Phase 2 gate PASSED" if not fails else f"❌ {len(fails)} failure(s): {fails}")
conn.close()
