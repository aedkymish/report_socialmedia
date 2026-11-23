"""Shared headless-Chromium launcher (Playwright) used by the screenshotter and
the browser-based video capture."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path

from .cookies import CookieFile

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


def load_netscape_cookies(path: str) -> list[dict]:
    """Backward-compatible name: loads Netscape *or* JSON cookie exports."""
    return CookieFile(path).load()


# Cookie that proves a logged-in session, per platform (first name is shown in messages).
SESSION_COOKIES = {
    "tiktok.com": "sessionid",
    "instagram.com": "sessionid",
    "facebook.com": "c_user",
    "x.com": "auth_token",
    "twitter.com": "auth_token",
}


def cookie_domain_matches(cookie_domain: str, site: str) -> bool:
    d = cookie_domain.lstrip(".").lower()
    return d == site or d.endswith("." + site)


# Equivalent session cookies some platforms set instead of / alongside the main one.
SESSION_ALIASES = {
    "tiktok.com": {"sessionid", "sessionid_ss", "sid_tt"},
}


def session_cookie_names(site: str) -> set[str]:
    return SESSION_ALIASES.get(site, {SESSION_COOKIES[site]} if site in SESSION_COOKIES else set())


def has_session_cookie(cookies: list[dict], site: str) -> bool | None:
    """True/False for known platforms, None when we don't know which cookie to expect."""
    names = session_cookie_names(site)
    if not names:
        return None
    return any(c["name"] in names and c["value"] and cookie_domain_matches(c["domain"], site) for c in cookies)


class BrowserLauncher:
    FALLBACK_EXECUTABLE = Path("/opt/pw-browsers/chromium")

    def __init__(self, executable_path: str = "", cookies_file: str = ""):
        self.executable_path = executable_path
        self.cookies_file = cookies_file

    @contextmanager
    def context(self, viewport: dict, **kwargs):
        """Yield a fresh BrowserContext (with the configured cookies); closed on exit."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = self._launch(pw)
            try:
                ctx = browser.new_context(
                    viewport=viewport, user_agent=USER_AGENT, locale="ar", **kwargs,
                )
                self._add_cookies(ctx)
                yield ctx
            finally:
                browser.close()

    def _add_cookies(self, ctx) -> None:
        cookies = load_netscape_cookies(self.cookies_file)
        if not cookies:
            return
        try:
            ctx.add_cookies(cookies)
        except Exception:  # one malformed cookie must not break the capture
            for c in cookies:
                try:
                    ctx.add_cookies([c])
                except Exception:
                    logger.debug("skipped cookie %s", c.get("name"))

    def _launch(self, pw):
        """Prefer full Chromium in new-headless mode (renders sites like a normal
        browser); fall back to the lighter headless shell, then a known path."""
        args = ["--autoplay-policy=no-user-gesture-required", "--mute-audio"]
        if self.executable_path:
            return pw.chromium.launch(executable_path=self.executable_path, args=args)
        attempts = [
            lambda: pw.chromium.launch(channel="chromium", args=args),
            lambda: pw.chromium.launch(args=args),
        ]
        if self.FALLBACK_EXECUTABLE.exists():
            attempts.append(lambda: pw.chromium.launch(executable_path=str(self.FALLBACK_EXECUTABLE), args=args))
        last_error = None
        for attempt in attempts:
            try:
                return attempt()
            except Exception as exc:
                last_error = exc
        raise last_error
