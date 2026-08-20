"""Regenerate docs/prompts.md — every prompt Vox sends to an LLM, straight from the live code.

A hand-written prompt doc is stale the first time someone edits a string, so this READS the actual
constants and context builders and renders them. Run it after touching any prompt:

    uv run python scripts/dump_prompts.py          # writes docs/prompts.md
    uv run python scripts/dump_prompts.py --check  # non-zero exit if the doc is out of date

Context blocks are rendered against the CURRENT machine (real tabs, real board, real log), so the
sizes at the bottom are what Vox is actually sending right now — the point being to see what's
eating the context window.
"""
import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "docs" / "prompts.md"

from vox import actions, assistant, executor  # noqa: E402


def approx_tokens(s: str) -> int:
    """Rough token count — ~4 chars/token is close enough to reason about budget."""
    return round(len(s) / 4)


def block(title: str, body: str, lang: str = "text") -> str:
    return f"### {title}\n\n```{lang}\n{body.rstrip()}\n```\n"


# (heading, when it fires, brain, system prompt, what's appended, expected output)
CALLS = [
    ("Action layer (the executor)",
     "Every utterance the deterministic layer couldn't handle, in any mode. The main one.",
     "small", executor._SYSTEM,
     ["environment_context()", "recent_actions_block()", "board_block()", "clarification history"],
     "ONE command line, or TYPE:/EDIT:/LOOK:/CLICK:/SCHEDULE:/BOARD:/TEACH:/CHAT:/DICTATE/IGNORE"),
    ("Conversation (assistant mode)",
     "Chat turns, and anything the executor declined or returned empty for.",
     "small (may defer to big via [BIG])", assistant._SYSTEM,
     ["active persona", "_rules_block()", "_memory_block()", "recent_actions_block()"],
     "Spoken reply + [OPEN]/[DONE] tag; optional MEMORY[core|daily] directive"),
    ("Rewrite the selection (EDIT)",
     "`EDIT: <instruction>` — rewrites whatever text the user has selected.",
     "small", executor._EDIT_SYSTEM, ["the instruction", "the selected text"],
     "The rewritten text only"),
    ("Read the screen from the AX tree (LOOK, cheap path)",
     "`LOOK:` when the accessibility tree can answer it without a screenshot.",
     "small", executor._LOOK_AXTREE_SYSTEM, ["the question", "the AX tree as text"],
     "A short spoken answer, or [BIG] to escalate to real vision"),
    ("Pick which element to click (labels)",
     "`click X` when the exact label wasn't found — the brain picks from what's on screen.",
     "big", executor._CLICK_PICK_SYSTEM, ["the list of on-screen labels", "the user's target"],
     "A verbatim label, or ASK: <label>, or NONE"),
    ("Pick which element to click (set-of-marks vision)",
     "Last resort when labels fail: a screenshot with a numbered badge on every clickable element.",
     "big (vision)", executor._CLICK_VISION_PROMPT.format(target="<target>", n="<N>"),
     ["the annotated screenshot"], "A bare badge number, or NONE"),
]


def render() -> str:
    parts = [
        "# Prompts — everything Vox sends to an LLM",
        "",
        "> **Generated file — do not edit by hand.** Regenerate with "
        "`uv run python scripts/dump_prompts.py` after changing any prompt. "
        "`--check` fails if it's out of date.",
        "",
        "Vox uses **translate-to-command**, not native function calling: the model's raw text output"
        " *is* the tool call, and the executor parses it. That's why output format is stated so"
        " insistently in each prompt — a missing prefix means the reply gets fed to the command"
        " parser (see the prose guard in `executor.execute`).",
        "",
        "## The calls",
        "",
    ]
    for i, (title, when, brain, _sys, ctx, out) in enumerate(CALLS, 1):
        parts.append(f"{i}. **{title}** — {when}  \n"
                     f"   brain: `{brain}` · context attached: {', '.join(f'`{c}`' for c in ctx)}  \n"
                     f"   expects: {out}")
    parts.append("")

    for title, when, brain, sys_prompt, ctx, out in CALLS:
        parts.append(f"## {title}")
        parts.append("")
        parts.append(f"**Fires:** {when}  ")
        parts.append(f"**Brain:** `{brain}` · **~{approx_tokens(sys_prompt)} tokens**  ")
        parts.append(f"**Expects back:** {out}")
        parts.append("")
        parts.append(block("System prompt", sys_prompt))
        parts.append("")

    # --- the context blocks, rendered live -------------------------------------------------
    parts.append("## Context blocks (attached per call)")
    parts.append("")
    parts.append("Rendered against this machine right now, so the sizes are real.")
    parts.append("")
    live = []
    for name, fn in (("environment_context()", actions.environment_context),
                     ("recent_actions_block()", actions.recent_actions_block),
                     ("board_block()", actions.board_block)):
        try:
            text = fn() or "(empty)"
        except Exception as exc:
            text = f"(unavailable: {exc})"
        live.append((name, text))
        parts.append(block(f"{name} — ~{approx_tokens(text)} tokens", text))
        parts.append("")

    parts.append("## Budget")
    parts.append("")
    parts.append("| Piece | ~tokens | Sent on |")
    parts.append("|---|---:|---|")
    for title, _when, _brain, sys_prompt, _ctx, _out in CALLS:
        parts.append(f"| {title} (system) | {approx_tokens(sys_prompt)} | that call |")
    for name, text in live:
        parts.append(f"| {name} | {approx_tokens(text)} | every action-layer call |")
    per_turn = approx_tokens(executor._SYSTEM) + sum(approx_tokens(t) for _n, t in live)
    parts.append(f"| **Typical action-layer turn** | **{per_turn}** | — |")
    parts.append("")
    parts.append("**The context blocks scale with the MACHINE, not the code** — and they're sent on "
                 "*every* action-layer call, so they're the part worth watching.")
    parts.append("")
    parts.append("Measured worst cases on this machine (2026-08-05):")
    parts.append("")
    parts.append("| Block | Now | Worst seen / capped |")
    parts.append("|---|---:|---|")
    parts.append(f"| `environment_context()` | {approx_tokens(live[0][1])} | **~317** — the open-tabs "
                 "list with 27 Arc tabs, included only while the browser is focused |")
    parts.append(f"| `board_block()` | {approx_tokens(live[2][1])} | **~1340** at the 40-card cap |")
    parts.append(f"| `recent_actions_block()` | {approx_tokens(live[1][1])} | bounded — last 6 "
                 "actions, so it can't run away |")
    parts.append("")
    parts.append("Two things follow. The **open-tabs list is the bigger everyday cost**, not the "
                 "board: it's ~317 tokens whenever the browser is focused, which is most of the "
                 "time you're issuing commands. And the **board's 40-card cap is the real ceiling** "
                 "— at ~34 tokens a card, a genuinely busy board would dominate the prompt. Neither "
                 "is a problem at today's sizes; both want to become need-based (attach the board "
                 "only when the utterance is about the board, the tab list only for tab commands) "
                 "before the board fills up.")
    parts.append("")
    return "\n".join(parts) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if docs/prompts.md is stale")
    a = ap.parse_args()
    text = render()
    if a.check:
        current = OUT.read_text() if OUT.exists() else ""
        if current != text:
            print("docs/prompts.md is out of date — run: uv run python scripts/dump_prompts.py")
            raise SystemExit(1)
        print("docs/prompts.md is current")
    else:
        OUT.write_text(text)
        print(f"wrote {OUT.relative_to(ROOT)} ({len(text)} chars)")
