"""Replay real small-brain router calls from vox.log against the live model, in two configurations.

Why: prompt and model changes on the command path have been judged on a handful of made-up lines.
This replays what Vox actually sent (the exact user message, Mac state and board blocks from
``[prompt->small]`` dumps), using the CURRENT executor system prompt, so two settings can be
compared side by side on real traffic.

    uv run python scripts/replay_router.py --last 40 --out /tmp/replay.md
    uv run python scripts/replay_router.py --last 40 --a thinking=on --b thinking=off

Output is a Markdown table (utterance · what Vox answered then · A · B) plus latency/token summary.
It contains whatever was in your log (board cards, app names), so keep it out of the repo.
"""

from __future__ import annotations

import argparse
import os
import re
import statistics as st
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from openai import OpenAI

from vox import executor
from vox.config import CONFIG

def extract(log_path: str, last: int) -> list[dict]:
    """Pull (user message, logged raw response) pairs for executor calls out of the debug dumps."""
    text = open(log_path, encoding="utf-8", errors="replace").read()
    calls = []
    for m in re.finditer(r"\[debug\]\[prompt->small\] provider=\S+ model=\S+ kind=chat system\n(.*?)"
                         r"\[debug\]\[prompt->small\] provider=\S+ model=\S+ kind=chat system/end\n"
                         r"\[debug\]\[prompt->small\] messages(?: @ [\d:]+)?\n(.*?)"
                         r"\[debug\]\[prompt->small\] messages/end\n"
                         r"(?:\[debug\]\[raw-response\](?: @ [\d:]+)?\n(.*?)\[debug\]\[raw-response\]/end)?",
                         text, re.S):
        system, messages, raw = m.group(1), m.group(2), (m.group(3) or "").strip()
        if "CLICK:" not in system or "CHAT:" not in system:
            continue  # a different prompt (chat/vision/rewrite), not the command router
        # Only single-turn calls: history replay would need the assistant turns reconstructed.
        if messages.count("\n[assistant]") or not messages.startswith("[user] "):
            continue
        user = messages[len("[user] "):].rstrip("\n")
        calls.append({"user": user, "logged": raw, "utterance": user.split("\n", 1)[0]})
    return calls[-last:]


def run(client: OpenAI, model: str, user: str, cfg: dict) -> dict:
    if cfg.get("provider") == "anthropic":
        import anthropic
        m = cfg.get("model", "claude-haiku-4-5-20251001")
        t = time.monotonic()
        r = anthropic.Anthropic().messages.create(model=m, max_tokens=int(cfg.get("max_tokens", 800)),
                                                  system=executor._SYSTEM,
                                                  messages=[{"role": "user", "content": user}])
        text = "".join(b.text for b in r.content if b.type == "text").strip()
        return {"text": text, "s": time.monotonic() - t, "out": r.usage.output_tokens,
                "finish": "length" if r.stop_reason == "max_tokens" else r.stop_reason}
    model = cfg.get("model", model)
    extra = {"thinking": {"type": "disabled"}} if cfg.get("thinking") == "off" else None
    t = time.monotonic()
    r = client.chat.completions.create(model=model, max_tokens=int(cfg.get("max_tokens", 800)),
                                       extra_body=extra,
                                       messages=[{"role": "system", "content": executor._SYSTEM},
                                                 {"role": "user", "content": user}])
    return {"text": (r.choices[0].message.content or "").strip(), "s": time.monotonic() - t,
            "out": r.usage.completion_tokens, "finish": r.choices[0].finish_reason}


def _cfg(spec: str) -> dict:
    return dict(kv.split("=", 1) for kv in spec.split(",") if kv)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="vox.log")
    ap.add_argument("--last", type=int, default=30)
    ap.add_argument("--a", default="thinking=on")
    ap.add_argument("--b", default="thinking=off")
    ap.add_argument("--model", default=CONFIG.small_brain_model)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    load_dotenv(".env")
    client = OpenAI(base_url=CONFIG.llm_base_url, api_key=os.environ.get(CONFIG.llm_api_key_env, ""))
    calls = extract(args.log, args.last)
    if not calls:
        sys.exit("no router calls found (is debug logging on?)")
    a, b = _cfg(args.a), _cfg(args.b)
    with ThreadPoolExecutor(4) as pool:
        ra = list(pool.map(lambda c: run(client, args.model, c["user"], a), calls))
        rb = list(pool.map(lambda c: run(client, args.model, c["user"], b), calls))

    def cell(s: str) -> str:
        return s.replace("|", "/").replace("\n", " ⏎ ")[:90]

    lines = [f"# Router replay: A = `{args.a}` · B = `{args.b}` · model `{args.model}` · n={len(calls)}\n",
             "| # | utterance | logged | A | B |", "|---|---|---|---|---|"]
    for i, (c, x, y) in enumerate(zip(calls, ra, rb), 1):
        flag = "" if x["text"].split(":")[0] == y["text"].split(":")[0] else " ⚠"
        lines.append(f"| {i}{flag} | {cell(c['utterance'])} | {cell(c['logged'])} | "
                     f"{cell(x['text'])} *({x['s']:.1f}s/{x['out']}t{'/LEN' if x['finish'] == 'length' else ''})* | "
                     f"{cell(y['text'])} *({y['s']:.1f}s/{y['out']}t{'/LEN' if y['finish'] == 'length' else ''})* |")
    for name, rs in (("A", ra), ("B", rb)):
        s = sorted(r["s"] for r in rs)
        lines.append(f"\n**{name}**: median {st.median(s):.2f}s · p90 {s[int(len(s) * .9)]:.2f}s · "
                     f"max {s[-1]:.2f}s · output median {st.median(r['out'] for r in rs)} tok · "
                     f"truncated {sum(r['finish'] == 'length' for r in rs)} · empty {sum(not r['text'] for r in rs)}")
    report = "\n".join(lines)
    if args.out:
        open(args.out, "w").write(report)
    print(report)


if __name__ == "__main__":
    main()
