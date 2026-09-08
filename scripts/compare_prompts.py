"""Measure the v2 action-layer prompt draft against the live v1, and keep v1 embedded in the draft.

  uv run python scripts/compare_prompts.py          # print the comparison + refresh the doc
  uv run python scripts/compare_prompts.py --print  # print the extracted v2 draft only

The draft lives in docs/prompt-v2-draft.md as the FIRST ```text block under "## The draft", so the
prose and the prompt can't drift apart — edit the doc, re-run this, and the numbers follow.
"""
import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
DOC = ROOT / "docs" / "prompt-v2-draft.md"

from vox import executor  # noqa: E402


def approx_tokens(s: str) -> int:
    return round(len(s) / 4)


def extract_draft(text: str) -> str:
    """The first ```text fence after the '## The draft' heading."""
    after = text.split("## The draft", 1)
    if len(after) < 2:
        raise SystemExit("couldn't find '## The draft' in the doc")
    m = re.search(r"```text\n(.*?)```", after[1], re.S)
    if not m:
        raise SystemExit("couldn't find a ```text block under '## The draft'")
    return m.group(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true", dest="show")
    a = ap.parse_args()

    doc = DOC.read_text()
    v2 = extract_draft(doc)
    v1 = executor._SYSTEM

    if a.show:
        print(v2)
        return

    rows = [("v1 (live)", v1), ("v2 (draft)", v2)]
    print(f"{'':14} {'chars':>7} {'~tokens':>8} {'lines':>6}")
    for name, t in rows:
        print(f"{name:14} {len(t):>7} {approx_tokens(t):>8} {t.count(chr(10)) + 1:>6}")
    saved = approx_tokens(v1) - approx_tokens(v2)
    pct = saved / approx_tokens(v1) * 100 if approx_tokens(v1) else 0
    verdict = (f"v2 is {abs(saved)} tokens {'SMALLER' if saved > 0 else 'LARGER'} "
               f"({abs(pct):.0f}%) on every action-layer call")
    print(f"\n{verdict}.")

    # Coverage: every TOOL and every COMMAND in v1 must survive. Listed explicitly rather than
    # scraped — a regex for /[A-Z]+:/ also picks up "IMPORTANT:" (an aside) and "DDTHH:" (part of
    # the ISO format string) and then reports them as missing tools, which is just noise.
    TOOLS = ["CLICK", "TYPE", "EDIT", "DICTATE", "LOOK", "SCHEDULE", "BOARD", "TEACH", "CHAT",
             "IGNORE"]
    COMMANDS = ["open ", "go to ", "search ", "go to my ", "next tab", "previous tab", "go back",
                "close tab", "next window", "previous window", "swipe left", "swipe right",
                "profile ", "window", "show tabs", "hide tabs"]
    missing_tools = [t for t in TOOLS if t not in v2]
    missing_cmds = [c for c in COMMANDS if c in v1 and c not in v2]
    print(f"\ntools:    {len(TOOLS) - len(missing_tools)}/{len(TOOLS)} present"
          f"{' — MISSING ' + ', '.join(missing_tools) if missing_tools else ''}")
    print(f"commands: {len(COMMANDS) - len(missing_cmds)}/{len(COMMANDS)} present"
          f"{' — MISSING ' + ', '.join(repr(c) for c in missing_cmds) if missing_cmds else ''}")
    gaps = missing_tools + missing_cmds

    # Refresh the cost table + embed v1 verbatim so the doc is self-contained for rollback.
    table = (f"| | chars | ~tokens |\n|---|---:|---:|\n"
             f"| v1 (live) | {len(v1)} | {approx_tokens(v1)} |\n"
             f"| v2 (this draft) | {len(v2)} | {approx_tokens(v2)} |\n\n"
             f"**{verdict}.** Coverage: "
             f"{'every tool and command in v1 survives' if not gaps else 'MISSING ' + ', '.join(map(str, gaps))}.")
    doc = re.sub(r"\| \| chars \| ~tokens \|.*?(?=\n## What changed)", table + "\n\n", doc, flags=re.S)
    doc = doc.replace("PLACEHOLDER_V1", v1.rstrip())
    DOC.write_text(doc)
    print(f"\nrefreshed {DOC.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
