"""Phase 0 gate (docs/plan/command-learning/06-rollout.md):
  1. every seeded phrase still resolves to its own command  (behaviour unchanged)
  2. the built-in coverage battery still passes
  3. a synthetic collision resolves identically 100x         (deterministic, not row-order luck)
  4. a synthetic true ambiguity falls through instead of guessing
  5. command_cache.resolve (runtime) agrees with command_store.resolve (dev)
Runs against a COPY of the DB. Read-only w.r.t. the real one.
"""
import pathlib
import shutil
import tempfile
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from vox import command_cache as cc
from vox import command_store as cs

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "data" / "commands.db")
TMP = str(pathlib.Path(tempfile.gettempdir()) / "vox_verify.db")
shutil.copyfile(SRC, TMP)
conn = sqlite3.connect(TMP)
conn.row_factory = sqlite3.Row

fails = []

# --- 1. every seeded phrase resolves to the command that owns it ---------------------------------
rows = conn.execute("""
    SELECT p.text, p.match_type, c.id cid, c.intent, ctx.kind, ctx.match_value
    FROM phrase p JOIN command c ON c.id = p.command_id
    JOIN context ctx ON ctx.id = c.context_id
    WHERE c.enabled = 1 AND p.match_type != 'regex'
""").fetchall()
for r in rows:
    app = r["match_value"] if r["kind"] == "app" else None
    got = cs.resolve(conn, r["text"], app=app)
    if got is None:
        fails.append(f"phrase {r['text']!r} (app={app}) → NO MATCH (owner cmd {r['cid']})")
    elif got["intent"] != r["intent"]:
        fails.append(f"phrase {r['text']!r} (app={app}) → {got['intent']}, owner is {r['intent']}")
print(f"1. seeded phrases: {len(rows) - len([f for f in fails])}/{len(rows)} resolve to their own command")

# --- 2. the shipped coverage battery --------------------------------------------------------------
battery_pass = 0
for text, app, domain, expect in cs._BATTERY:
    r = cs.resolve(conn, text, app=app, domain=domain)
    got = r["intent"] if r else None
    if got == expect:
        battery_pass += 1
    else:
        fails.append(f"battery {text!r} (app={app}) → {got}, expected {expect}")
print(f"2. coverage battery: {battery_pass}/{len(cs._BATTERY)} as expected")

# --- 3. collision determinism: two commands, same phrase, one is 'learned' ------------------------
ctx_id = conn.execute("SELECT id FROM context WHERE kind='global'").fetchone()[0]
# Take a REAL seeded global phrase and have a learned command claim the exact same words.
victim = conn.execute("""
    SELECT p.text, c.id cid, c.intent FROM phrase p JOIN command c ON c.id = p.command_id
    WHERE c.context_id = ? AND c.source = 'builtin' ORDER BY LENGTH(p.text) DESC LIMIT 1
""", (ctx_id,)).fetchone()
conn.execute("INSERT INTO command (context_id, intent, arg, label, source) "
             "VALUES (?,?,?,?, 'learned')", (ctx_id, "navigate", "hijacked", "Learned dupe"))
learned_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
conn.execute("INSERT INTO phrase (command_id, text, match_type) VALUES (?,?, 'contains')",
             (learned_id, victim["text"]))
conn.commit()
picks = {(cs.resolve(conn, victim["text"]) or {}).get("command_id") for _ in range(100)}
builtin_wins = picks == {victim["cid"]}
print(f"3. collision on {victim['text']!r} (builtin cmd {victim['cid']} vs learned {learned_id}): "
      f"{len(picks)} distinct winner(s) over 100 runs → "
      f"{'builtin wins, deterministic' if builtin_wins else 'FAIL'}")
if not builtin_wins:
    fails.append(f"collision non-deterministic or learned won: picks={picks} "
                 f"builtin={victim['cid']} learned={learned_id}")

# --- 4. true ambiguity → fall through (two learned rows, different actions, identical rank) -------
for arg, label in (("alpha", "Ambi A"), ("beta", "Ambi B")):
    conn.execute("INSERT INTO command (context_id, intent, arg, label, source) "
                 "VALUES (?,?,?,?, 'learned')", (ctx_id, "navigate", arg, label))
    cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("INSERT INTO phrase (command_id, text, match_type) "
                 "VALUES (?, 'do the ambiguous thing', 'exact')", (cid,))
conn.commit()
amb = cs.resolve(conn, "do the ambiguous thing")
print(f"4. true ambiguity: resolve → {amb!r} ({'falls through' if amb is None else 'FAIL — guessed'})")
if amb is not None:
    fails.append(f"ambiguity guessed instead of falling through: {amb}")

# --- 5. runtime cache resolver agrees with the dev resolver ---------------------------------------
cc._BASE = cc._commands_for(conn, "global", None)
cc._APP_CACHE = {"Arc": cc._commands_for(conn, "app", "Arc")}
cc._ACTION_INTENTS = {i["name"] for i in cs.list_intents(conn) if i["category"] == "action"}
disagree = 0
checked = 0
for r in rows:
    if r["kind"] == "app" and r["match_value"] != "Arc":
        continue
    app = "Arc" if r["kind"] == "app" else None
    checked += 1
    a = cs.resolve(conn, r["text"], app=app)
    b = cc.resolve(r["text"], app=app)
    if (a or {}).get("intent") != (b or {}).get("intent"):
        disagree += 1
        fails.append(f"cache/store disagree on {r['text']!r}: {(a or {}).get('intent')} vs {(b or {}).get('intent')}")
print(f"5. cache vs store: {checked - disagree}/{checked} agree")

print()
if fails:
    print(f"❌ {len(fails)} failure(s):")
    for f in fails[:15]:
        print("   -", f)
else:
    print("✅ Phase 0 gate PASSED")
conn.close()
