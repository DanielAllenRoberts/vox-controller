"""Routing check: does the brain turn everyday requests into the right kind of action?

    uv run python scripts/router_eval.py            # every case, with a pass/fail table
    uv run python scripts/router_eval.py -k agent   # only cases whose phrase contains "agent"

Each case is a phrase and what the router's FIRST line must look like (a regex). Only the routing
call is made: nothing runs (no clicks, no board changes, no agents). The Mac state given to the
brain is a fixed sample, so results don't depend on what's open. Use it after any prompt change.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vox import assistant, executor  # noqa: E402

SAMPLE_STATE = (
    "Focused app: Safari\n"
    "Running apps: Finder, Safari, Notes, Music, Spotify, Slack, Calendar, Notion, Vox\n"
    "Active tab: Inbox — https://mail.example.com/\n"
    "Connections (use APPS:): composio\n"
    "Displays, left to right: left screen (Studio Display, main); right screen (DELL U2720Q)\n"
    "Now: Monday 2026-01-05 09:12 (GMT)"
)

# (phrase, first-line regex)
CASES = [
    ("open notion calendar", r"^open "),   # the parser catches this one before the brain anyway
    ("can you bring up my slack", r"^open slack|^switch to slack|^slack window"),
    ("close notion", r"^quit notion"),
    ("go to github", r"^(open|go to) github"),
    ("search for best pizza in town", r"^search .*pizza"),
    ("next tab please", r"^next tab"),
    ("save this", r"^press (cmd|command)\+s"),
    ("reopen the tab i just closed", r"^press (cmd|command)\+shift\+t"),
    ("pose my music", r"^pause music"),
    ("what song is this", r"^what'?s playing"),
    ("play my film score playlist", r"^play my film score playlist"),
    ("add this song to my chill playlist", r"^add this song to my chill playlist"),
    ("move slack to the other screen", r"^move slack to the (other|right|left) screen"),
    ("make notion fill the whole screen", r"^maximi[sz]e notion"),
    ("click the send button", r"^CLICK:"),
    ("point at the export button", r"^POINT:"),
    ("what does this error on my screen mean", r"^LOOK:"),
    ("write a short note to sam saying i'll be late", r"^TYPE:|^APPS:"),   # with a mail/Slack connection, sending is fair
    ("make this more formal", r"^EDIT:"),
    ("start typing", r"^DICTATE"),
    ("remind me in 10 minutes to call the bank", r"^SCHEDULE: reminder"),
    ("set an alarm for 7am tomorrow", r"^SCHEDULE: alarm"),
    ("every weekday at 7 tell me my calendar and the weather", r"^SCHEDULE: routine"),
    ("add buy milk to my to do list", r"^BOARD: add_card"),
    ("move the invoice card to doing", r"^BOARD: move_card"),
    ("put everything back on the board", r"^BOARD: restore|^CHAT:|^I "),   # nothing was deleted in this sample, so saying so is right
    ("whenever i say refresh press command r", r"^TEACH:"),
    ("log an issue the click went to the wrong button", r"^ISSUE:"),
    ("any new emails from sam", r"^APPS:"),
    ("reply to sam's email saying thanks", r"^APPS:"),
    ("start an agent in the getprice folder to fix the login bug", r"^AGENTS:"),
    ("what's the update on the getprice agent", r"^AGENTS:"),
    ("ask the docs agent if it's done", r"^AGENTS:"),
    ("open slack and send sam a message saying testing", r"^AGENT:|^APPS:"),
    ("what's the weather like in durban", r"^WEB:"),
    ("who won the last f1 race", r"^WEB:"),
    ("what time is it", r"^CHAT:"),
    ("tell me a joke", r"^CHAT:"),
    ("turn the voice replies off for now", r"^SET:"),   # "reply silently" itself is caught by the parser first
    ("the tv is so loud in the other room", r"^IGNORE|^CHAT:"),
]


def route(phrase: str) -> str:
    prompt = f"{phrase}\n\n[Current Mac state — use this to pick the right app/tab]\n{SAMPLE_STATE}"
    return assistant.complete(prompt, None, system=executor._router_system(), brain="small", prompt="router").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", default="", help="only phrases containing this")
    args = ap.parse_args()
    assistant._dbg = lambda *a, **k: None
    cases = [c for c in CASES if args.k.lower() in c[0]]
    passed, slow = 0, []
    t_all = time.time()
    for phrase, want in cases:
        t = time.time()
        try:
            out = route(phrase)
        except Exception as exc:
            out = f"(error: {exc})"
        dt = time.time() - t
        first = (out.splitlines() or [""])[0]
        ok = bool(re.search(want, first, re.I))
        passed += ok
        if dt > 4:
            slow.append((phrase, dt))
        print(f"{'PASS' if ok else 'FAIL'}  {dt:4.1f}s  {phrase!r:58} → {first[:90]}")
        if not ok:
            print(f"{'':12}wanted /{want}/")
    print(f"\n{passed}/{len(cases)} passed in {time.time() - t_all:.0f}s"
          + (f"; slow (>4 s): {len(slow)}" if slow else ""))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
