"""Is Vox running? Asked from outside the engine: by each agent's vox-speak MCP server (and hooks),
which live in their own processes and would otherwise keep talking after you quit Vox.

Running means Vox's own API answered: ``/api/status`` on the dashboard port said ``running``. A
listening port alone isn't enough, because another program can hold the same port number.
"""

from __future__ import annotations

import json
import urllib.request


def _port() -> int:
    try:
        from vox.config import CONFIG
        return int(getattr(CONFIG, "dashboard_port", 8765))
    except Exception:
        return 8765


def vox_running(port: int | None = None, timeout: float = 0.5) -> bool:
    """True if the Vox engine answers on this Mac. Fast and never raises: anything else is False."""
    url = f"http://127.0.0.1:{port or _port()}/api/status"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read(65536)).get("running") is True
    except Exception:
        return False
