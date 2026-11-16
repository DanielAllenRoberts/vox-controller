#!/usr/bin/env python3
"""Pre-commit guard: refuse a commit that would publish a key (this repo is public).

Blocks, among the STAGED changes:
* key files: .env / .env.* (except .env.example), anything under data/, *.db, secrets files;
* any of YOUR saved keys, word for word (read from Vox's key store and an old .env, never printed);
* text shaped like a common API key (Anthropic, OpenAI, Composio, GitHub, Slack, AWS, Google).

Enable once per clone:  git config core.hooksPath scripts/git-hooks
Bypass in a real emergency only:  git commit --no-verify
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_BAD_PATH = re.compile(r"(^|/)(\.env(\..+)?|secrets?\.(db|json|env)|.*\.db|.*\.sqlite3?)$|^data/")
_KEY_SHAPES = [
    ("Anthropic key", r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("OpenAI key", r"sk-(?!ant-)(?:proj-)?[A-Za-z0-9_\-]{32,}"),
    ("Composio key", r"\b(?:ak|ck)_[A-Za-z0-9_\-]{16,}"),
    ("GitHub token", r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    ("Slack token", r"\bxox[abposr]-[A-Za-z0-9\-]{10,}"),
    ("AWS key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("Google key", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
]


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout


def _my_keys() -> list[str]:
    """The user's real key values (to catch them exactly). Read locally; never printed."""
    vals: set[str] = set()
    data = Path(os.environ.get("VOX_DATA_DIR") or ROOT / "data").expanduser()
    try:
        con = sqlite3.connect(f"file:{data / 'secrets.db'}?mode=ro", uri=True)
        vals |= {r[0] for r in con.execute("SELECT value FROM secret")}
        con.close()
    except Exception:
        pass
    for env in (ROOT / ".env", data / ".env"):
        try:
            for line in env.read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    vals.add(line.split("=", 1)[1].strip().strip("'\""))
        except OSError:
            pass
    return [v for v in vals if len(v) >= 12]


def main() -> int:
    problems: list[str] = []
    for path in _git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines():
        if path != ".env.example" and _BAD_PATH.search(path):
            problems.append(f"{path}: this kind of file holds keys or private data and must not be committed")
    added = [ln[1:] for ln in _git("diff", "--cached", "-U0", "--no-color").splitlines()
             if ln.startswith("+") and not ln.startswith("+++")]
    blob = "\n".join(added)
    if any(k in blob for k in _my_keys()):
        problems.append("one of YOUR saved API keys appears in the staged changes")
    for label, pat in _KEY_SHAPES:
        if re.search(pat, blob):
            problems.append(f"something that looks like a key ({label}) appears in the staged changes")
    if problems:
        print("✋ Commit blocked: it would publish a secret (this repo is public).", file=sys.stderr)
        for p in problems:
            print(f"   • {p}", file=sys.stderr)
        print("   Unstage it (git restore --staged <file>) or remove the key, then commit again.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
