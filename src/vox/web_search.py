"""Answers that need the live web: weather, facts, "how do I … in <app>".

Asked "what's the weather like in Cape Town?", Vox said it had no live access (seen live 2026-11-06).
Two routes, cheapest first:
  * Weather goes to Open-Meteo (free, no key): geocode the place, read the current conditions.
    Faster and more reliable than scraping a search page.
  * Everything else: DuckDuckGo's HTML results, the top pages fetched and reduced to text, then the
    small brain answers in a couple of spoken sentences and names where it read it.
No API keys, nothing stored. Every network call has a short timeout so a slow site can't stall Vox.
"""

from __future__ import annotations

import html as _html
import json
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
                     "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"}

_WEATHER_CODES = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "foggy", 48: "foggy",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain",
    65: "heavy rain", 71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers",
    81: "rain showers", 82: "heavy rain showers", 95: "thunderstorms", 96: "thunderstorms with hail",
    99: "thunderstorms with hail",
}

_WEATHER_RE = re.compile(r"\b(?:weather|temperature|forecast|rain(?:ing)?|hot|cold|warm|sunny|windy)\b"
                         r".*?\b(?:in|at|for)\s+([a-z][a-z .'-]{1,40}?)(?:\s+(?:today|tomorrow|now|right now|this week))?[?.!]*$",
                         re.I)


_WEATHER_WORDS = r"(?:weather|temperature|forecast)"
_WHEN = r"(?:\s+(?:today|tonight|tomorrow|now|right now|this week|currently))*"


def _weather_place(q: str) -> str | None:
    """The place in a weather question, however it's phrased: "what's the weather like in Cape
    Town", "cape town weather today", "weather cape town", "is it going to rain in London"."""
    t = q.lower().strip().rstrip("?.! ")
    for pat in (_WEATHER_RE.pattern,
                rf"^(?:what(?:'s| is)\s+the\s+)?(?:current\s+)?{_WEATHER_WORDS}(?:\s+like)?(?:\s+(?:in|for|at))?\s+(.+?){_WHEN}$",
                rf"^([a-z][a-z .'-]+?)\s+{_WEATHER_WORDS}(?:\s+forecast)?{_WHEN}$"):
        m = re.search(pat, t, re.I)
        if m and not re.match(r"(?:the|it|today|like|what|how|is|will|does|do)\b", m.group(1).strip()):
            return m.group(1).strip()
    if re.search(rf"\b{_WEATHER_WORDS}\b|\b(?:rain|sunny|cold|hot) (?:today|outside)\b", t):
        return _home()  # "what's the weather?" → where the user is
    return None


def _home() -> str | None:
    """The user's place: the home_location setting, else the city in the Mac's timezone
    (Africa/Johannesburg → Johannesburg)."""
    try:
        from vox.web import settings_store
        h = (settings_store.get("home_location") or "").strip()
        if h:
            return h
    except Exception:
        pass
    try:
        import os
        tz = os.path.realpath("/etc/localtime").split("zoneinfo/")[-1]
        return tz.split("/")[-1].replace("_", " ") or None
    except Exception:
        return None


def _get(url: str, timeout: float = 5.0) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=timeout).read()


def weather(place: str) -> str | None:
    """'It's 17°C and clear in Cape Town, wind 14 km/h. Today's high is 20.' or None."""
    g = json.loads(_get("https://geocoding-api.open-meteo.com/v1/search?count=1&name=" + urllib.parse.quote(place)))
    if not g.get("results"):
        return None
    r = g["results"][0]
    w = json.loads(_get(
        f"https://api.open-meteo.com/v1/forecast?latitude={r['latitude']}&longitude={r['longitude']}"
        "&current=temperature_2m,weather_code,wind_speed_10m&daily=temperature_2m_max,temperature_2m_min"
        "&timezone=auto&forecast_days=1"))
    c, d = w["current"], w["daily"]
    sky = _WEATHER_CODES.get(int(c.get("weather_code", -1)), "")
    return (f"It's {round(c['temperature_2m'])}°C{' and ' + sky if sky else ''} in {r['name']}, "
            f"wind {round(c['wind_speed_10m'])} km/h. Today's high is {round(d['temperature_2m_max'][0])}, "
            f"low {round(d['temperature_2m_min'][0])}.")


def search(query: str, limit: int = 5) -> list[dict]:
    """[{title, url, snippet}] from DuckDuckGo's HTML endpoint."""
    page = _get("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query), timeout=6).decode("utf-8", "replace")
    links = re.findall(r'class="result__a" href="([^"]+)"[^>]*>(.*?)</a>', page)
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', page, re.S)
    out = []
    for i, (href, title) in enumerate(links[:limit]):
        u = href
        m = re.search(r"uddg=([^&]+)", href)  # DDG wraps results in a redirect
        if m:
            u = urllib.parse.unquote(m.group(1))
        if "duckduckgo.com/y.js" in u:  # ads
            continue
        out.append({"title": _text(title), "url": u, "snippet": _text(snippets[i]) if i < len(snippets) else ""})
    return out


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


def _page_text(url: str, limit: int = 6000) -> str:
    try:
        raw = _get(url, timeout=4).decode("utf-8", "replace")
    except Exception:
        return ""
    raw = re.sub(r"(?is)<(script|style|nav|header|footer|svg|noscript)[^>]*>.*?</\1>", " ", raw)
    return _text(raw)[:limit]


def answer(question: str) -> str:
    """A short spoken answer from the live web."""
    q = (question or "").strip()
    place = _weather_place(q)
    if place:
        try:
            w = weather(place)
            if w:
                return w
        except Exception:
            pass  # fall through to a normal search
    try:
        results = search(q)
    except Exception:
        return "I couldn't reach the web just now."
    if not results:
        return "I couldn't find anything on that."
    with ThreadPoolExecutor(3) as pool:
        pages = list(pool.map(lambda r: _page_text(r["url"]), results[:3]))
    sources = "\n\n".join(
        f"[{i + 1}] {r['title']} ({urllib.parse.urlparse(r['url']).netloc})\n{r['snippet']}\n{p[:3000]}"
        for i, (r, p) in enumerate(zip(results[:3], pages)))
    from vox import assistant
    reply = assistant.complete(
        f"Question: {q}\n\nWeb results:\n{sources}", brain="small", kind="web", prompt="web",
        system=("You answer a spoken question from web results. Reply in 1-3 short sentences that will "
                "be read aloud: no lists, no markdown, no URLs. Use only what the results say; if they "
                "don't answer it, say so. End with 'according to <site name>' for where it came from."))
    return (reply or "").strip() or "I couldn't work out an answer from what I found."
