"""Auto dictation (command vs dictation): exact-only lookup, risk tiers, routing, chunk history.

Runs under pytest, or standalone without it:  .venv/bin/python tests/test_auto_dictation.py
Nothing here touches the mic, the screen or the keyboard — AppleScript and AX are faked.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vox import actions, auto_dictation as ad, command_cache, command_store  # noqa: E402


# --- fixtures (plain functions so the standalone runner needs nothing) ---------------------------

def _cmd(cid, intent, phrases, *, arg=None, source="builtin", hit_count=0, match_type="contains"):
    return {"id": cid, "intent": intent, "arg": arg, "param": None, "label": intent, "source": source,
            "hit_count": hit_count, "_ctx_kind": "global", "_ctx_value": None,
            "phrases": [{"id": cid * 10 + i, "text": p, "match_type": match_type}
                        for i, p in enumerate(phrases)]}


def _install_cache():
    """A small in-memory command set shaped like the real seed (everything `contains`)."""
    command_store._learn_setting = lambda key, fallback: fallback   # ignore data/settings.json
    command_cache._ACTION_INTENTS = {"close_tab", "tab_arrow", "navigate", "click", "reload"}
    command_cache._APP_CACHE = {}
    command_cache._BASE = [
        _cmd(1, "close_tab", ["close tab", "close this tab"]),
        _cmd(2, "tab_arrow", ["next tab"], arg="down:1"),
        _cmd(3, "navigate", ["open slack"], arg="slack"),
        _cmd(4, "click", ["click on the team folder"], arg="team", source="learned", hit_count=0),
        _cmd(5, "navigate", ["open my notes"], arg="notes", source="learned", hit_count=0),
        _cmd(6, "navigate", ["open the wiki"], arg="wiki", source="learned", hit_count=5),
        _cmd(7, "navigate", ["open the big quarterly planning spreadsheet please"], arg="sheet"),
        _cmd(8, "tab_arrow", [r"^go (up|down) a tab$"], arg="up:1", match_type="regex"),
        _cmd(9, "click", ["send it"], arg="send", source="learned", hit_count=9),
        _cmd(10, "sleep", ["stand down"]),  # mode/system intent — never an action
    ]


class _Out:
    def __init__(self):
        self.lines = []

    def emit(self, msg):
        self.lines.append(msg)


class _Keys:
    """Fake AppleScript/paste so dictate() and scratch run without a keyboard."""
    def __init__(self):
        self.osa, self.pasted = [], []
        actions._osa = lambda script, timeout=20: (self.osa.append(script), (True, ""))[1]
        actions._paste = lambda text: self.pasted.append(text)


FIELD = {"editable": True, "secure": False, "role": "AXTextArea", "subrole": "", "pid": 42,
         "element": "el-1", "before": None, "ms": 1.0}


def _field(**kw):
    return {**FIELD, **kw}


def _fresh():
    _install_cache()
    ad.reset()
    actions.reset_dictation()
    sys.modules["vox.overlay"] = types.SimpleNamespace(is_active=lambda: False)


# --- step 2: exact-only lookup ---------------------------------------------------------------------

def test_text_context_is_whole_utterance_only():
    _fresh()
    # The loose resolver fires on a sentence that merely contains the phrase…
    assert command_cache.resolve("please close tab now", actions_only=True)["intent"] == "close_tab"
    # …the text-context one doesn't.
    assert command_cache.resolve("please close tab now", actions_only=True, text_context=True) is None
    hit = command_cache.resolve("Close tab.", actions_only=True, text_context=True)
    assert hit and hit["intent"] == "close_tab" and hit["match_type"] == "exact"
    assert command_cache.resolve("next tab", actions_only=True, text_context=True)["arg"] == "down:1"


def test_text_context_excludes_probation_long_regex_and_mode():
    _fresh()
    tc = dict(actions_only=True, text_context=True)
    assert command_cache.resolve("open my notes", **tc) is None             # learned, on probation
    assert command_cache.resolve("open the wiki", **tc)["arg"] == "wiki"    # learned, proven
    assert command_cache.resolve("open the big quarterly planning spreadsheet please", **tc) is None
    assert command_cache.resolve("go up a tab", **tc) is None               # regex phrase
    assert command_cache.resolve("stand down", **tc) is None                # not an action intent
    # The loose path still sees the long phrase (unchanged behaviour outside text fields).
    assert command_cache.resolve("open the big quarterly planning spreadsheet please",
                                 actions_only=True) is not None


def test_risk_tiers():
    assert ad.risk_tier("tab_arrow") == ad.SAFE
    assert ad.risk_tier("navigate") == ad.SAFE
    assert ad.risk_tier("close_tab") == ad.DESTRUCTIVE
    assert ad.risk_tier("reload") == ad.DESTRUCTIVE
    assert ad.risk_tier("some_new_intent") == ad.DESTRUCTIVE   # unknown → fail-safe
    assert ad.risk_tier(None) == ad.DESTRUCTIVE
    assert ad.edit_tier("send", "Slack") == ad.DESTRUCTIVE     # Return sends in a chat app
    assert ad.edit_tier("send", "Notes") == ad.EDIT
    assert ad.edit_tier("new line", "Slack") == ad.EDIT


def test_exact_command_sources():
    _fresh()
    extras = ["scroll down", "reload", "show clickable", "open cursor"]
    assert ad.exact_command("next tab")["via"] == "db"
    hit = ad.exact_command("Scroll down.", extra_phrases=extras)
    assert hit["via"] == "grammar" and hit["intent"] == "scroll"
    assert ad.exact_command("show clickable", extra_phrases=extras)["intent"] == "vox_control"
    # The parser alone would read this as `back`; only enumerated phrases count in a text field.
    assert actions.parse("I'll go back to that later") is not None
    assert ad.exact_command("I'll go back to that later", extra_phrases=extras) is None
    # A learned command can never be destructive from a text field.
    assert ad.exact_command("send it") is None


# --- step 4: routing ---------------------------------------------------------------------------------

def test_decide_outside_text_fields_is_plain_control():
    _fresh()
    assert ad.decide("close tab", None).kind == "command"
    assert ad.decide("close tab", _field(editable=False)).kind == "command"
    r = ad.decide("my password is hunter2", _field(editable=False, secure=True))
    assert r.kind == "command" and r.reason == "secure field"


def test_decide_in_text_field():
    _fresh()
    f = _field()
    assert ad.decide("next tab", f).kind == "command"
    assert ad.decide("please close tab now", f).kind == "text"
    assert ad.decide("I'll go back to that later", f).kind == "text"
    assert ad.decide("Fox news reported it", f).kind == "text"        # no box/fox prefix in fields
    assert ad.decide("literally next tab", f).kind == "text"
    assert ad.decide("um", f).kind == "ignore"
    r = ad.decide("send", f, app="Slack")
    assert r.kind == "text" and r.tier == ad.DESTRUCTIVE
    assert ad.decide("new line", f).kind == "text"
    assert ad.decide("next tab", f, pending=True).kind == "command"
    assert ad.decide("fourteen", f, overlay_active=True).kind == "command"
    assert ad.decide("scratch that", f).kind == "scratch"
    assert ad.decide("That was a command.", f).kind == "recall"


def test_destructive_needs_prefix_or_yes():
    _fresh()
    f = _field()
    r = ad.decide("close tab", f)
    assert r.kind == "confirm" and r.tier == ad.DESTRUCTIVE
    ad.ask_confirm(r.text, r.tier)
    yes = ad.decide("yes", f)
    assert yes.kind == "command" and yes.text == "close tab"
    assert ad.decide("yes", f).kind == "text"            # the question was consumed

    ad.ask_confirm("close tab", ad.DESTRUCTIVE)
    assert ad.decide("no", f).kind == "ignore"
    ad.ask_confirm("close tab", ad.DESTRUCTIVE)
    assert ad.decide("anyway I was saying", f).kind == "text"   # lapses, routed on its own

    p = ad.decide("Vox, close tab.", f)
    assert p.kind == "command" and p.text == "close tab" and p.tier == ad.DESTRUCTIVE
    assert ad.decide("Vox close the tab please", f).kind == "confirm"   # prefix but not exact
    assert ad.decide("vox what's on my screen", f).kind == "command"     # brain allowed via prefix


def test_whole_utterance_floor():
    from vox.config import CONFIG
    from vox.core import loop
    assert not ad.whole_utterance("I'll see you later then", CONFIG.sleep_phrases)
    assert ad.whole_utterance("Stand down.", CONFIG.sleep_phrases)
    assert ad.whole_utterance("standdown", CONFIG.sleep_phrases)
    s = "tell them never mind about the meeting"
    assert loop._floor(s, CONFIG, loop._is_sleep, CONFIG.sleep_phrases, in_field=False)   # today
    assert not loop._floor(s, CONFIG, loop._is_sleep, CONFIG.sleep_phrases, in_field=True)
    assert CONFIG.auto_dictation is False   # off by default


# --- step 3: chunk history -------------------------------------------------------------------------

def test_scratch_plan():
    ch = ad.Chunk("hello world", " Hello world", 42, "el-1")
    assert ad.scratch_plan(ch, _field(before="Hi there. Hello world")) == "delete"
    assert ad.scratch_plan(ch, _field(before="Hi there. Hello world!!")) == "undo"   # typed since
    assert ad.scratch_plan(ch, _field(pid=7, before=" Hello world")) == "refuse"     # other app
    assert ad.scratch_plan(ch, None) == "refuse"
    assert ad.scratch_plan(ch, _field()) == "delete"                                  # same element
    assert ad.scratch_plan(ch, _field(element="el-2")) == "undo"
    big = ad.Chunk("x", " " + "x" * 300, 42, "el-1")
    assert ad.scratch_plan(big, _field(before="x" * 200)) == "undo"


def test_scratch_walks_back_one_chunk_at_a_time():
    _fresh()
    ad.record("one", " One", _field())
    ad.record("two", " two", _field())
    deleted, undone = [], []
    probe = lambda: _field(before="One two")  # noqa: E731
    assert ad.scratch_that(probe, deleted.append, lambda: undone.append(1))[0] == "delete"
    assert deleted == [4] and ad.last_chunk().spoken == "one"
    probe = lambda: _field(before="One")  # noqa: E731 - " One" isn't there verbatim (start of field)
    assert ad.scratch_that(probe, deleted.append, lambda: undone.append(1))[0] == "undo"
    assert ad.scratch_that(probe, deleted.append, lambda: undone.append(1))[0] == "empty"
    ad.record("three", " three", _field())
    m, ch = ad.scratch_that(lambda: _field(pid=99), deleted.append, lambda: undone.append(1))
    assert m == "refuse" and ad.last_chunk() is ch      # refused → kept


def test_edit_words_mirror_dictate():
    keys = _Keys()
    for w in sorted(ad._EDIT_EXACT) + ["delete three words", "scratch word", "enter, enter"]:
        actions.reset_dictation()
        assert ad.edit_word(w) is not None, w
        assert actions.dictate(w) is None, w
    assert keys.pasted == [], keys.pasted
    assert ad.edit_word("delete the file") is None


def test_dictate_returns_what_it_pasted_and_prime():
    keys = _Keys()
    actions.reset_dictation()
    assert actions.dictate("hello there.") == "Hello there."
    assert actions.dictate("how are you") == " How are you"
    assert keys.pasted == ["Hello there.", " How are you"]
    assert actions.dictate("literally next tab") == " next tab"
    for before, active, cap in (("", False, True), ("Hi.", True, True), ("Hi", True, False),
                                ("Hi\n", False, True), ("Hi ", False, False)):
        actions.prime_dictation(before)
        assert (actions._dictation_active, actions._dictation_new_sentence) == (active, cap), before


def test_route_end_to_end_with_fakes():
    _fresh()
    keys, out, said = _Keys(), _Out(), []
    f = _field(before="")
    assert ad.route("hello world", f, out=out, speak=said.append) is None
    assert keys.pasted == ["Hello world"]
    assert any(line.startswith("  [auto] typed 'hello world'") for line in out.lines), out.lines
    assert any(line.startswith("  [auto] focus ") for line in out.lines)

    # scratch that → exactly len("Hello world") backspaces, verified against the field's text
    from vox import ax
    real = ax.focused_text_target
    ax.focused_text_target = lambda max_age=0.25: _field(before="Hello world")
    try:
        assert ad.route("scratch that", f, out=out, speak=said.append) is None
    finally:
        ax.focused_text_target = real
    assert "repeat 11 times" in keys.osa[-1]
    assert ad.last_chunk() is None

    assert ad.route("next tab", f, out=out, speak=said.append) == "next tab"
    assert ad.route("close tab", f, out=out, speak=said.append) is None and said[-1] == "Close tab?"
    assert ad.route("yes", f, out=out, speak=said.append) == "close tab"
    assert any("[auto] confirm 'close tab' tier=destructive" in line for line in out.lines)
    assert ad.route("new line", f, out=out, speak=said.append) is None
    assert any(line.startswith("  [auto] edit 'new line'") for line in out.lines)

    # A secure field never types and never logs the words.
    out2 = _Out()
    assert ad.route("hunter2", _field(editable=False, secure=True), out=out2, speak=said.append) == "hunter2"
    assert not any("hunter2" in line for line in out2.lines)


def test_that_was_a_command():
    _fresh()
    keys, out, said = _Keys(), _Out(), []
    f = _field(before="")
    ad.route("next tab please", f, out=out, speak=said.append)     # not exact → typed
    assert keys.pasted == ["Next tab please"]
    from vox import ax
    real = ax.focused_text_target
    ax.focused_text_target = lambda max_age=0.25: _field(before="Next tab please")
    try:
        assert ad.route("that was a command", f, out=out, speak=said.append) == "next tab please"
    finally:
        ax.focused_text_target = real
    assert "repeat 15 times" in keys.osa[-1]


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok    {name}")
        except Exception as exc:  # report every failure, not just the first
            failed += 1
            import traceback
            print(f"FAIL  {name}: {exc!r}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
