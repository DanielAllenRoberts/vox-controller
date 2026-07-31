"""Phase 1 gate (docs/plan/command-learning/06-rollout.md) — shadow mode.

  1. migration is idempotent and leaves existing data intact
  2. observe() records a candidate + evidence
  3. VARIANT COLLAPSE: different phrasings of the same action → ONE candidate, N phrases
  4. the never-learn gate rejects free-text / non-allowlisted intents
  5. the promotion bar needs spread: 3 hits in one day ≠ ready; across 2 days = ready
  6. a negative signal walks the candidate back
  7. SHADOW MODE: not one command row was created
Runs entirely against a temp DB.
"""
import os
import tempfile
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "data" / "commands.db")
TMP = str(pathlib.Path(tempfile.gettempdir()) / "vox_learn.db")
if os.path.exists(TMP):
    os.remove(TMP)
shutil.copyfile(SRC, TMP)

from vox import command_learn, command_store as cs

command_learn.mode = lambda: "suggest"   # this gate covers OBSERVATION; promotion is gate 2

_real_connect = cs.connect
cs.connect = lambda path=TMP: _real_connect(TMP)   # every writer lands in the temp DB

fails = []


def check(label, cond, detail=""):
    print(f"{'  ✓' if cond else '  ✗'} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        fails.append(label)


conn = cs.connect()
before_cmds = conn.execute("SELECT COUNT(*) FROM command").fetchone()[0]
before_phrases = conn.execute("SELECT COUNT(*) FROM phrase").fetchone()[0]

# --- 1. migration ---------------------------------------------------------------------------------
print("\n1. schema migration")
cs.init_schema(conn)
cs.init_schema(conn)  # twice — must be idempotent
tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
check("candidate tables created", {"command_candidate", "command_candidate_phrase"} <= tables)
cols = {r[1] for r in conn.execute("PRAGMA table_info(command)")}
check("command gained learning columns", {"hit_count", "last_used_at", "fail_count"} <= cols)
check("existing commands intact",
      conn.execute("SELECT COUNT(*) FROM command").fetchone()[0] == before_cmds,
      f"{before_cmds} commands")
check("existing phrases intact",
      conn.execute("SELECT COUNT(*) FROM phrase").fetchone()[0] == before_phrases,
      f"{before_phrases} phrases")

# --- 2/3. observe + variant collapse ---------------------------------------------------------------
print("\n2/3. observe + variant collapse (the 'Alex' case)")
log_lines = []
for phrase in ("open Alex's chat", "send Alex a message", "hey vox could you open alexs chat please"):
    command_learn.observe(phrase, "click", "Alex Fairbairn", app="Slack",
                          success=True, log=log_lines.append)
    command_learn._pending = None      # don't let the next phrase read as a "re-say" negative
cands = cs.candidates(conn)
alex = [c for c in cands if (c["arg"] or "") == "Alex Fairbairn"]
check("one candidate for the action", len(alex) == 1,
      f"{len(alex)} candidate(s), hit_count={alex[0]['hit_count'] if alex else '-'}")
phrases = {p["text"]: p["hit_count"] for p in alex[0]["phrases"]} if alex else {}
# 3 utterances → 2 distinct phrases: "open Alex's chat" and the filler-wrapped "open alexs chat"
# are the SAME words once cleaned, so they merge (and the merged one carries 2 hits).
check("distinct phrasings kept, duplicates merged", len(phrases) == 2, str(phrases))
check("possessive + filler variants merged onto one phrase",
      phrases.get("open alexs chat") == 2, f"hit_count={phrases.get('open alexs chat')}")
check("the genuinely different phrasing is kept too", "send alex a message" in phrases)

# --- 4. never-learn gate ---------------------------------------------------------------------------
print("\n4. never-learn gate")
for intent, arg, why in [
        ("compose", "an email to Alex about the Q3 numbers", "free-text intent"),
        ("quit", "", "control plane"),
        ("navigate", "a really long sentence that is clearly not an identifier at all", "arg shape"),
        ("click", "what did you think of the meeting?", "sentence punctuation")]:
    ok, reason = command_learn.is_learnable(intent, arg)
    check(f"rejects {why}", not ok, reason)
ok, _ = command_learn.is_learnable("navigate", "slack")
check("accepts a normal action", ok)

# --- 5. the promotion bar: N clean hits in a ROLLING window -----------------------------------------
print("\n5. promotion bar (rolling window, no calendar-day requirement)")
same_day = {"window_hits": 3, "negative_count": 0, "blocked": 0}
thin = {"window_hits": 2, "negative_count": 0, "blocked": 0}
r1, why1 = command_learn.clears_bar(same_day)
r2, why2 = command_learn.clears_bar(thin)
check("3 hits on ONE day IS ready (no waiting for tomorrow)", r1, why1)
check("2 hits is not yet ready", not r2, why2)
r3, why3 = command_learn.clears_bar({**same_day, "negative_count": 3})
check("negatives block promotion", not r3, why3)
r4, why4 = command_learn.clears_bar({**same_day, "blocked": 1})
check("an explicitly forgotten action stays blocked", not r4, why4)

# --- 5b. when does it ask instead of just saving? ---------------------------------------------------
print("\n5b. confirm-vs-save")
ask, why = command_learn.should_confirm({"window_hits": 3}, phrase="open alexs chat",
                                        label="Alex Fairbairn")
check("shared wording on good evidence → saves silently", not ask, why or "no confirm needed")
ask2, why2b = command_learn.should_confirm({"window_hits": 3}, phrase="open the thing",
                                           label="Quarterly Revenue Dashboard")
check("a leap on minimal evidence → asks first", ask2, why2b)
ask3, _ = command_learn.should_confirm({"window_hits": 25}, phrase="open the thing",
                                       label="Quarterly Revenue Dashboard")
check("same leap, lots of evidence → stops asking", not ask3, "25 hits")

# --- 6. negative signal ------------------------------------------------------------------------------
print("\n6. negative signal")
command_learn.observe("open the deploy channel", "click", "deploy", app="Slack",
                      success=True, log=log_lines.append)
before = conn.execute("SELECT hit_count, negative_count FROM command_candidate "
                      "WHERE arg='deploy'").fetchone()
command_learn.check_negative("no", log=log_lines.append)
after = conn.execute("SELECT hit_count, negative_count FROM command_candidate "
                     "WHERE arg='deploy'").fetchone()
check("'no' decrements the candidate",
      after["negative_count"] > before["negative_count"] and after["hit_count"] < before["hit_count"],
      f"hits {before['hit_count']}→{after['hit_count']}, negatives "
      f"{before['negative_count']}→{after['negative_count']}")

# --- 7. suggest mode writes no commands (promotion is gate 2) ------------------------------------------------
print("\n7. suggest mode writes nothing")
after_cmds = conn.execute("SELECT COUNT(*) FROM command").fetchone()[0]
after_phrases = conn.execute("SELECT COUNT(*) FROM phrase").fetchone()[0]
check("no commands created", after_cmds == before_cmds, f"{after_cmds} (was {before_cmds})")
check("no phrases created", after_phrases == before_phrases, f"{after_phrases} (was {before_phrases})")
check("evidence WAS recorded",
      conn.execute("SELECT COUNT(*) FROM command_log").fetchone()[0] > 0,
      f"{conn.execute('SELECT COUNT(*) FROM command_log').fetchone()[0]} log rows")

print("\n--- what the observer logged ---")
for line in log_lines:
    print(line)

print()
print("✅ Phase 1 gate PASSED" if not fails else f"❌ {len(fails)} failure(s): {fails}")
conn.close()
