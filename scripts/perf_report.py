#!/usr/bin/env python3
"""Where does Vox's response time actually go?

Reads vox.log and reports the things that decide whether Vox feels instant or sluggish:

  • fast-lane hit rate — the single biggest lever. A Vosk grammar match is ~5ms; a miss costs a
    full Whisper pass (~1-2s) and often an LLM round-trip (~3-15s) on top.
  • per-command latency — from "you: X" to the action line, so slow commands rank themselves.
  • the phrases that keep MISSING the fast lane — these are the candidates to add to the grammar,
    which is the cheapest speed-up available.
  • STT and brain timings, so you can tell a slow model from slow recognition.

Usage:
    uv run python scripts/perf_report.py [path/to/vox.log] [--since HH:MM] [--top N]

Reads only; safe to run against a live log while the daemon is writing to it.
"""

import re
import statistics
import sys
from collections import Counter, defaultdict

TS = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\s+(.*)$")
STT = re.compile(r"stt ([\d.]+)s")
YOU = re.compile(r"^you: (.*)$")
DONE = re.compile(r"^(?:→|🔊|✎|🛑|🖥)")


def _secs(h, m, s):
    return int(h) * 3600 + int(m) * 60 + int(s)


def _fmt(v):
    return f"{v:.2f}s"


def parse(path, since=None):
    fast, whisper, low_conf = 0, 0, 0
    missed, stt_times, events = Counter(), [], []
    for raw in open(path, encoding="utf-8", errors="replace"):
        m = TS.match(raw.rstrip("\n"))
        if not m:
            continue
        t, rest = _secs(*m.groups()[:3]), m.group(4).strip()
        if since is not None and t < since:
            continue
        if "FAST LANE" in rest:
            fast += 1
        elif "no match [unk]" in rest:
            whisper += 1
        elif "low conf" in rest and "Whisper lane" in rest:
            low_conf += 1
            whisper += 1
        if (sm := STT.search(rest)):
            stt_times.append(float(sm.group(1)))
        if (ym := YOU.match(rest)):
            events.append((t, "you", ym.group(1).strip().strip("'\"")))
        elif DONE.match(rest):
            events.append((t, "done", rest[:70]))
        elif rest.startswith("[debug] heard:"):
            # what Whisper produced — i.e. what the grammar failed to catch
            said = rest.split(":", 1)[1].strip().strip("'\"")
            if said and len(said.split()) <= 5:
                missed[said.lower()] += 1
    return fast, whisper, low_conf, missed, stt_times, events


def main():
    args = [a for a in sys.argv[1:]]
    path = next((a for a in args if not a.startswith("--")), "vox.log")
    top = 15
    since = None
    for i, a in enumerate(args):
        if a == "--top" and i + 1 < len(args):
            top = int(args[i + 1])
        if a == "--since" and i + 1 < len(args):
            hh, _, mm = args[i + 1].partition(":")
            since = _secs(hh, mm or 0, 0)

    fast, whisper, low_conf, missed, stt, events = parse(path, since)
    total_utt = fast + whisper

    print(f"\n=== Vox performance · {path} ===\n")
    if total_utt:
        rate = fast / total_utt * 100
        print(f"Fast lane (Vosk grammar, ~5ms)   {fast:5d}  {rate:5.1f}%")
        print(f"Whisper lane (~1-2s + maybe LLM) {whisper:5d}  {100 - rate:5.1f}%"
              f"{f'  ({low_conf} were low-confidence grammar hits)' if low_conf else ''}")
        if rate < 60:
            print("  ⚠ Under 60% — most utterances are paying the slow path. The misses listed")
            print("    below are the cheapest thing to fix: every phrase added to the grammar")
            print("    moves that command from seconds to milliseconds.")
    if stt:
        srt = sorted(stt)
        print(f"\nWhisper STT   n={len(stt)}  median {_fmt(statistics.median(stt))}"
              f"  p90 {_fmt(srt[int(len(srt) * 0.9)])}  max {_fmt(max(stt))}")

    # latency: each "you:" to the next action line
    lat = defaultdict(list)
    for i, (t, kind, val) in enumerate(events):
        if kind != "you":
            continue
        for t2, k2, _ in events[i + 1:i + 6]:
            if k2 == "done":
                if 0 <= t2 - t < 120:      # ignore spans across an idle gap
                    lat[val.lower()].append(t2 - t)
                break

    if lat:
        print(f"\nSlowest commands (spoken → done):\n")
        print(f"  {'phrase':40s} {'n':>3s} {'median':>8s} {'worst':>7s}")
        ranked = sorted(lat.items(), key=lambda kv: -statistics.median(kv[1]))
        for phrase, ds in ranked[:top]:
            print(f"  {phrase[:38]:40s} {len(ds):3d} {statistics.median(ds):7.1f}s {max(ds):6d}s")

        alld = [d for ds in lat.values() for d in ds]
        print(f"\n  overall: n={len(alld)} median {statistics.median(alld):.1f}s "
              f"p90 {sorted(alld)[int(len(alld) * 0.9)]:.1f}s")

    if missed:
        print(f"\nShort phrases that went through Whisper (grammar candidates):\n")
        for phrase, n in missed.most_common(top):
            print(f"  {n:4d}x  {phrase!r}")
        print("\n  Adding these to the command DB (or _fast_lane_extra_phrases in core/loop.py)")
        print("  puts them on the fast lane.")
    print()


if __name__ == "__main__":
    main()
