"""Where Vox keeps its runtime files.

Running from a checkout, everything lives in ``<repo>/data`` and the log is ``./vox.log``, exactly as
before. The installed app sets ``VOX_DATA_DIR`` (``~/Library/Application Support/Vox/data``) because
an app can't write into its own bundle. In that case the log moves in beside the data unless
``VOX_LOG_FILE`` says otherwise.
"""

from __future__ import annotations

import os
from pathlib import Path

# src/vox/paths.py → parents[2] is the repo root (or the unpacked engine dir when installed).
REPO_ROOT = Path(__file__).resolve().parents[2]

_env_data = os.environ.get("VOX_DATA_DIR", "").strip()
# The installed app's layout is <support>/engine (this source) beside <support>/venv and
# <support>/data. Recognise it even without VOX_DATA_DIR: processes the app doesn't launch, such as
# the MCP servers that Claude Code starts, must use the same data folder as the engine (agent
# names, settings), not a stray <support>/engine/data.
_installed_data = (REPO_ROOT.parent / "data"
                   if REPO_ROOT.name == "engine" and (REPO_ROOT.parent / "venv").is_dir() else None)

if _env_data:
    DATA_DIR = Path(_env_data).expanduser()
elif _installed_data is not None:
    DATA_DIR = _installed_data
else:
    DATA_DIR = REPO_ROOT / "data"
_outside_repo = bool(_env_data) or _installed_data is not None

# Where API keys entered in the app are saved. A checkout keeps using its repo-root .env.
ENV_FILE = DATA_DIR / ".env" if _outside_repo else REPO_ROOT / ".env"

LOG_FILE = (
    os.environ.get("VOX_LOG_FILE", "").strip()
    or (str(DATA_DIR / "vox.log") if _outside_repo else "vox.log")
)
