"""Composio: Vox's link to the user's apps (Google Calendar first; Gmail, Slack, Notion… later).

The user's apps are connected in their own Composio account (composio.dev). Vox needs only the
project API key (``COMPOSIO_API_KEY``, Settings → Brains → API keys); it finds the ACTIVE connected
account for a toolkit itself and runs tools through Composio's REST API. Read-only uses for now.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

_BASE = "https://backend.composio.dev/api/v3.1"
_accounts: dict[str, tuple[float, list[str]]] = {}


def api_key() -> str:
    try:
        from dotenv import load_dotenv
        from vox.paths import ENV_FILE
        load_dotenv(ENV_FILE)
        load_dotenv()
    except Exception:
        pass
    return os.environ.get("COMPOSIO_API_KEY", "").strip()


def configured() -> bool:
    return bool(api_key())


def _request(method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
    url = _BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"x-api-key": api_key(), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read() or b"{}")


def accounts(toolkit: str) -> list[str]:
    """IDs of the ACTIVE connected accounts for ``toolkit`` (e.g. "googlecalendar"). Cached 10 min."""
    hit = _accounts.get(toolkit)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    res = _request("GET", "/connected_accounts", {"toolkit_slugs": [toolkit], "statuses": ["ACTIVE"],
                                                    "account_type": "ALL", "limit": 20})
    ids = [i["id"] for i in res.get("items") or [] if i.get("status") == "ACTIVE"]
    _accounts[toolkit] = (time.time(), ids)
    return ids


def execute(tool_slug: str, arguments: dict, toolkit: str) -> dict:
    """Run one tool with the toolkit's first active account. Returns the tool's ``data``.
    Raises RuntimeError with a speakable reason."""
    if not configured():
        raise RuntimeError("Composio isn't set up (no API key).")
    ids = accounts(toolkit)
    if not ids:
        raise RuntimeError(f"There's no active {toolkit} connection in your Composio project.")
    res = _request("POST", f"/tools/execute/{tool_slug}",
                   body={"connected_account_id": ids[0], "arguments": arguments})
    if not res.get("successful", False):
        raise RuntimeError(str(res.get("error") or "Composio couldn't run that."))
    return res.get("data") or {}


def calendar_events(start, end) -> list[dict]:
    """Google Calendar events overlapping [start, end) (local datetimes), in the shape
    ``vox.calendars.events`` uses."""
    from datetime import datetime
    off = start.astimezone().strftime("%z")
    off = off[:3] + ":" + off[3:]
    data = execute("GOOGLECALENDAR_EVENTS_LIST", {
        "calendarId": "primary", "singleEvents": True, "orderBy": "startTime", "maxResults": 50,
        "timeMin": start.strftime("%Y-%m-%dT%H:%M:%S") + off,
        "timeMax": end.strftime("%Y-%m-%dT%H:%M:%S") + off,
        "fields": "items(summary,start,end,location,status)"}, "googlecalendar")
    items = data.get("items") or (data.get("response_data") or {}).get("items") or []
    out = []
    for e in items:
        if e.get("status") == "cancelled":
            continue
        s, f = e.get("start") or {}, e.get("end") or {}
        all_day = "date" in s and "dateTime" not in s
        try:
            if all_day:
                sd = datetime.fromisoformat(s["date"])
                fd = datetime.fromisoformat(f.get("date") or s["date"])
            else:
                sd = datetime.fromisoformat(s["dateTime"]).astimezone().replace(tzinfo=None)
                fd = datetime.fromisoformat(f.get("dateTime") or s["dateTime"]).astimezone().replace(tzinfo=None)
        except Exception:
            continue
        out.append({"title": e.get("summary") or "(no title)", "start": sd, "end": fd, "all_day": all_day,
                    "location": e.get("location") or "", "calendar": "Google"})
    return out
