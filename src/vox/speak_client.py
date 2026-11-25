"""Ask the running Vox to speak a line, from another process (an agent's vox-speak MCP server, a hook).

Speaking in-process loads a Kokoro model and ONNX Runtime into that process and keeps them: about
1 GB for every agent session that has spoken, duplicating the copy Vox already holds. Handing the
line to Vox's /api/speak means one model does all the speaking.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request

# Long enough to wait our turn in the speech queue and then speak; the call returns when the line
# has been said, as an in-process speak_with does.
_TIMEOUT = 600.0


def _port() -> int:
    try:
        from vox.config import CONFIG
        return int(getattr(CONFIG, "dashboard_port", 8765))
    except Exception:
        return 8765


def speak_via_vox(text: str, *, engine: str = "", say_voice=None, kokoro_voice=None, rate=None,
                  label: str = "", cue: str = "", drop_if_paused: bool = False,
                  port: int | None = None) -> bool | None:
    """Have Vox speak `text`. True if spoken, False if Vox dropped it (speech paused), None if Vox
    didn't take it (not running, or not Vox on the port): the caller can then speak it itself."""
    body = json.dumps({"text": text, "engine": engine or "", "sayVoice": say_voice,
                       "kokoroVoice": kokoro_voice, "rate": rate, "label": label, "cue": cue or "",
                       "dropIfPaused": bool(drop_if_paused)}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port or _port()}/api/speak", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            reply = json.loads(resp.read(65536))
    except (TimeoutError, socket.timeout):
        return True  # Vox took the line and is still on it; speaking it here too would repeat it
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return True
        return None
    except Exception:
        return None
    if not isinstance(reply, dict) or reply.get("ok") is not True or "spoken" not in reply:
        return None
    return bool(reply["spoken"])
