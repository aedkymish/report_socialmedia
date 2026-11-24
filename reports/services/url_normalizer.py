"""Canonical form of a social-media URL, used to detect the same link
submitted twice in different spellings."""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit

HOST_ALIASES = {
    "twitter.com": "x.com",
    "mobile.twitter.com": "x.com",
    "telegram.me": "t.me",
    "fb.com": "facebook.com",
    "web.facebook.com": "facebook.com",
}
STRIP_HOST_PREFIXES = ("www.", "m.", "mobile.", "web.")
# Query parameters that identify the content itself (everything else is tracking noise).
KEEP_QUERY = {"id", "v", "story_fbid", "fbid", "set", "p"}


def normalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower().rstrip(".")
    for prefix in STRIP_HOST_PREFIXES:
        if host.startswith(prefix) and host.count(".") >= 2:
            host = host[len(prefix):]
            break
    host = HOST_ALIASES.get(host, host)

    path = parts.path or "/"
    while "//" in path:
        path = path.replace("//", "/")
    if host == "t.me" and path.startswith("/s/"):
        path = path[2:]  # t.me/s/channel/1 == t.me/channel/1
    path = path.rstrip("/") or "/"
    if host in ("x.com", "instagram.com", "tiktok.com", "t.me"):
        path = path.lower()  # usernames are case-insensitive on these platforms

    query = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False) if k.lower() in KEEP_QUERY)
    port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
    return f"{host}{port}{path}" + (f"?{urlencode(query)}" if query else "")
