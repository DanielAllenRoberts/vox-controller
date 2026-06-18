# Rules store (`src/vox/web/rules.py`)

Dashboard iteration 5. A small persisted CRUD store of the user's **behavior
rules** — short standing instructions the assistant layers on top of its base
system prompt (e.g. "always answer in metric", "never use emoji", "keep replies
under two sentences"). Each rule can be toggled on/off without deleting it.

Owned by the rules backend agent. Self-contained; safe to import lazily and
guarded from `assistant.py`.

## Data shape

A `Rule` (per `CONTRACT.md`) is:

```json
{ "id": "284596f6b912", "text": "Always answer in metric", "enabled": true }
```

- `id` — short uuid hex string (survives as the `{rid}` PATCH/DELETE path param).
- `text` — the instruction, trimmed and non-empty.
- `enabled` — bool, defaults `true` on create.

## Persistence

`data/rules.json` (runtime dir, gitignored). Stored shape:

```json
{ "rules": [ { "id": "...", "text": "...", "enabled": true }, ... ] }
```

Writes are atomic (temp file + `replace`) under an `RLock`. A missing or corrupt
file loads as an empty list, and malformed entries (non-dict, missing/blank id,
non-string text) are dropped on load — the store never raises on read.

## Public API

| Function | Returns | Notes |
|---|---|---|
| `list_rules()` | `Rule[]` | All rules. Backs `GET /api/rules`. |
| `add_rule(text)` | `Rule` | `enabled` defaults `true`. Raises `ValueError` on blank text → `POST /api/rules`. |
| `update_rule(id, text=None, enabled=None, **ignored)` | `Rule` | Updates only provided fields. Raises `ValueError` on unknown id or blank text. Extra kwargs ignored (server passes `**body`). Backs `PATCH /api/rules/{id}`. |
| `remove_rule(id)` | `bool` | `True` if removed. Backs `DELETE /api/rules/{id}`. |
| `enabled_rules_text()` | `str` | Enabled rule texts as a `- bullet` block joined by newlines; `""` when none. Never raises. |

### REST mapping (`src/vox/web/server.py`, already wired)

- `GET    /api/rules`        → `list_rules()`
- `POST   /api/rules`        → `add_rule(body["text"])`
- `PATCH  /api/rules/{rid}`  → `update_rule(rid, **body)` (`text?`, `enabled?`)
- `DELETE /api/rules/{rid}`  → `{"ok": bool(remove_rule(rid))}`

All routes are guarded in the server: if this module fails to import, they return
an empty list / `{"ok": False}` and the daemon keeps running.

## Assistant integration (`src/vox/assistant.py`)

`_rules_block()` already calls `rules.enabled_rules_text()` lazily and guarded,
wrapping the bullet block in a system-prompt preamble. When the store is empty,
missing, or broken, it returns `""` and the prompt is unchanged from today's
behaviour — no rules layered on. This module adds nothing to the voice loop's
hot path beyond a single JSON read of `data/rules.json`.

## How to verify

```bash
python3 -c "
from src.vox.web import rules
r = rules.add_rule('Keep replies short')
print(rules.list_rules())
print(repr(rules.enabled_rules_text()))   # '- Keep replies short'
rules.update_rule(r['id'], enabled=False)
print(repr(rules.enabled_rules_text()))   # '' (none enabled)
rules.remove_rule(r['id'])
print(rules.list_rules())                  # []
"
```

Via the running bridge:

```bash
curl -s localhost:8765/api/rules
curl -s -XPOST localhost:8765/api/rules -d '{"text":"Never use emoji"}'
curl -s -XPATCH localhost:8765/api/rules/<id> -d '{"enabled":false}'
curl -s -XDELETE localhost:8765/api/rules/<id>
```
