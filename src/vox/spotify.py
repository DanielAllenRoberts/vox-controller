"""Spotify by voice: what's playing, play a playlist by name, add this song to a playlist, play a song.

Two halves:
* **The Spotify app** (AppleScript): what's playing, and PLAYING anything by URI. No account link
  needed, and it works on free accounts (the Web API's playback endpoints need Premium).
* **The Web API** (your account): your playlists, search, adding a track to a playlist. Linked once
  from Vox → Settings → General → Spotify with a free developer app's Client ID (PKCE: no secret).
  Tokens live in ``<data>/spotify.json`` on this Mac.

Redirect URI to register in the Spotify app: http://127.0.0.1:8765/api/spotify/callback
"""

from __future__ import annotations

import base64
import difflib
import hashlib
import json
import re
import secrets
import subprocess
import threading
import time
import urllib.parse
import urllib.request

from vox.paths import DATA_DIR

_STORE = DATA_DIR / "spotify.json"
_LOCK = threading.Lock()
REDIRECT_URI = "http://127.0.0.1:8765/api/spotify/callback"
_SCOPES = ("playlist-read-private playlist-read-collaborative playlist-modify-private "
           "playlist-modify-public user-read-currently-playing user-library-modify")
_pending: dict = {}           # state → code_verifier, for the login in flight
_playlists_cache: tuple[float, list] | None = None


def _setting(key: str, fallback=None):
    try:
        from vox.web import settings_store
        val = settings_store.get(key)
        return fallback if val is None else val
    except Exception:
        return fallback


def client_id() -> str:
    return str(_setting("spotify_client_id", "") or "").strip()


def _load() -> dict:
    try:
        return json.loads(_STORE.read_text())
    except Exception:
        return {}


def _save(d: dict) -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d))
    tmp.chmod(0o600)
    tmp.replace(_STORE)


def connected() -> bool:
    return bool(_load().get("refresh_token"))


def status() -> dict:
    d = _load()
    return {"clientId": bool(client_id()), "connected": bool(d.get("refresh_token")),
            "user": d.get("user", ""), "redirectUri": REDIRECT_URI}


# --- login (PKCE) --------------------------------------------------------------------------------

def auth_url() -> str:
    """The Spotify login page to open in the browser. Raises ValueError without a Client ID."""
    cid = client_id()
    if not cid:
        raise ValueError("Add your Spotify Client ID first.")
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(16)
    _pending.clear()
    _pending[state] = verifier
    return "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": cid, "response_type": "code", "redirect_uri": REDIRECT_URI, "scope": _SCOPES,
        "code_challenge_method": "S256", "code_challenge": challenge, "state": state})


def _token_request(fields: dict) -> dict:
    req = urllib.request.Request("https://accounts.spotify.com/api/token",
                                 data=urllib.parse.urlencode(fields).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def finish_login(code: str, state: str) -> str:
    """Exchange the callback's code for tokens. Returns the Spotify display name."""
    verifier = _pending.pop(state, None)
    if not verifier:
        raise ValueError("That login link has expired. Press Connect again.")
    tok = _token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI,
                          "client_id": client_id(), "code_verifier": verifier})
    d = {"access_token": tok["access_token"], "refresh_token": tok.get("refresh_token", ""),
         "expires_at": time.time() + int(tok.get("expires_in", 3600)) - 60}
    with _LOCK:
        _save(d)
    me = api("GET", "/me") or {}
    d["user"] = me.get("display_name") or me.get("id") or ""
    with _LOCK:
        _save(d)
    return d["user"]


def disconnect() -> None:
    global _playlists_cache
    _playlists_cache = None
    with _LOCK:
        try:
            _STORE.unlink()
        except FileNotFoundError:
            pass


def _access_token() -> str | None:
    with _LOCK:
        d = _load()
        if not d.get("refresh_token"):
            return None
        if time.time() < d.get("expires_at", 0) and d.get("access_token"):
            return d["access_token"]
        tok = _token_request({"grant_type": "refresh_token", "refresh_token": d["refresh_token"],
                              "client_id": client_id()})
        d["access_token"] = tok["access_token"]
        d["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
        if tok.get("refresh_token"):
            d["refresh_token"] = tok["refresh_token"]
        _save(d)
        return d["access_token"]


def api(method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict | None:
    """One Web API call. None when not connected."""
    token = _access_token()
    if not token:
        return None
    url = "https://api.spotify.com/v1" + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


# --- the Spotify app -----------------------------------------------------------------------------

def _osa(script: str) -> tuple[bool, str]:
    try:
        p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=8)
        return p.returncode == 0, (p.stdout or p.stderr).strip()
    except Exception as exc:
        return False, str(exc)


def now_playing() -> dict | None:
    """{"name", "artist", "album", "uri", "state", "app"} from Spotify, else Apple Music; None if
    neither has a track."""
    for app, uri in (("Spotify", "id of current track"), ("Music", '""')):
        ok, out = _osa(f'if application "{app}" is running then tell application "{app}" to return '
                       f'(name of current track) & "\\t" & (artist of current track) & "\\t" & '
                       f'(album of current track) & "\\t" & ({uri}) & "\\t" & (player state as text)')
        if ok and out.count("\t") >= 4:
            name, artist, album, track_uri, state = out.split("\t")[:5]
            if name:
                return {"name": name, "artist": artist, "album": album, "uri": track_uri,
                        "state": state, "app": app}
    return None


def _play_uri(uri: str, shuffle: bool | None = None) -> bool:
    pre = f"set shuffling to {'true' if shuffle else 'false'}\n" if shuffle is not None else ""
    ok, _ = _osa(f'tell application "Spotify"\n{pre}play track "{uri}"\nend tell')
    return ok


# --- what Vox calls ------------------------------------------------------------------------------

_NOT_LINKED = ("I need your Spotify account for that. Link it in Vox → Settings → General → Spotify.")


def say_now_playing() -> str:
    np = now_playing()
    if np is None:
        return "Nothing's playing."
    who = f" by {np['artist']}" if np["artist"] else ""
    paused = " (paused)" if np["state"] == "paused" else ""
    return f"{np['name']}{who}{paused}."


def playlists(fresh: bool = False) -> list[dict]:
    """The user's playlists: [{"name", "id", "uri", "owner_me"}]. Cached 10 minutes."""
    global _playlists_cache
    if not fresh and _playlists_cache and time.time() - _playlists_cache[0] < 600:
        return _playlists_cache[1]
    out, url = [], "/me/playlists"
    params = {"limit": 50, "offset": 0}
    me = (_load().get("user") or "")
    for _ in range(10):   # up to 500 playlists
        page = api("GET", url, params)
        if not page:
            break
        for p in page.get("items") or []:
            if p:
                out.append({"name": p.get("name", ""), "id": p.get("id"), "uri": p.get("uri"),
                            "owner_me": (p.get("owner") or {}).get("display_name") == me})
        if not page.get("next"):
            break
        params["offset"] += 50
    _playlists_cache = (time.time(), out)
    return out


def _clean_name(name: str) -> str:
    n = re.sub(r"^(?:my|the|our)\s+", "", (name or "").strip().lower())
    return re.sub(r"\s+(?:playlist|play list|list)$", "", n).strip()


def find_playlist(name: str) -> dict | None:
    """The user's playlist best matching a spoken name (exact, contains, then sounds-like)."""
    want = _clean_name(name)
    pls = playlists()
    if not want or not pls:
        return None
    by = {p["name"].lower(): p for p in pls}
    if want in by:
        return by[want]
    hits = [p for p in pls if want in p["name"].lower() or p["name"].lower() in want]
    if hits:
        return min(hits, key=lambda p: len(p["name"]))
    close = difflib.get_close_matches(want, list(by), n=1, cutoff=0.6)
    return by[close[0]] if close else None


def play_playlist(name: str, shuffle: bool = False) -> str:
    if not connected():
        return _NOT_LINKED
    pl = find_playlist(name)
    if pl is None:
        return f"I couldn't find a playlist called {_clean_name(name)!r}."
    if not _play_uri(pl["uri"], shuffle=shuffle):
        return "Spotify didn't respond. Is it installed?"
    return f"Playing {pl['name']}{', shuffled' if shuffle else ''}."


def add_current_to(name: str) -> str:
    if not connected():
        return _NOT_LINKED
    np = now_playing()
    if np is None or np.get("app") != "Spotify" or not np.get("uri", "").startswith("spotify:track:"):
        return "Nothing's playing in Spotify to add."
    pl = find_playlist(name)
    if pl is None:
        return f"I couldn't find a playlist called {_clean_name(name)!r}."
    try:
        api("POST", f"/playlists/{pl['id']}/tracks", body={"uris": [np["uri"]]})
    except Exception as exc:
        code = getattr(exc, "code", "")
        return ("Spotify won't let me change that playlist (it isn't yours)." if code == 403
                else f"Spotify said no ({code or exc}).")
    return f"Added {np['name']} to {pl['name']}."


def play_search(query: str) -> str:
    """'play cataclysm by tom dabrowski' → the top track for that search."""
    if not connected():
        return _NOT_LINKED
    q = (query or "").strip()
    m = re.match(r"(.+?)\s+by\s+(.+)$", q)
    search = f'track:{m.group(1)} artist:{m.group(2)}' if m else q
    res = api("GET", "/search", {"q": search, "type": "track", "limit": 1}) or {}
    items = ((res.get("tracks") or {}).get("items")) or []
    if not items and m:
        res = api("GET", "/search", {"q": q, "type": "track", "limit": 1}) or {}
        items = ((res.get("tracks") or {}).get("items")) or []
    if not items:
        return f"I couldn't find {q!r} on Spotify."
    t = items[0]
    if not _play_uri(t["uri"]):
        return "Spotify didn't respond. Is it installed?"
    artists = ", ".join(a["name"] for a in t.get("artists") or [])
    return f"Playing {t['name']}{' by ' + artists if artists else ''}."


def run(arg: str) -> str:
    """actions intent 'spotify': 'now', 'playlist|<name>', 'shuffle|<name>', 'add|<name>', 'play|<query>'."""
    verb, _, rest = (arg or "").partition("|")
    try:
        if verb == "now":
            return say_now_playing()
        if verb == "playlist":
            return play_playlist(rest)
        if verb == "shuffle":
            return play_playlist(rest, shuffle=True)
        if verb == "add":
            return add_current_to(rest)
        if verb == "play":
            return play_search(rest)
    except Exception as exc:
        return f"Spotify didn't work just now ({exc})."
    return "I don't know that Spotify command."
