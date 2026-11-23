"""Shared headless-Chromium launcher (Playwright) used by the screenshotter and
the browser-based video capture."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


class BrowserLauncher:
    FALLBACK_EXECUTABLE = Path("/opt/pw-browsers/chromium")

    def __init__(self, executable_path: str = ""):
        self.executable_path = executable_path

    @contextmanager
    def context(self, viewport: dict, **kwargs):
        """Yield a fresh BrowserContext; everything is closed on exit."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = self._launch(pw)
            try:
                ctx = browser.new_context(
                    viewport=viewport, user_agent=USER_AGENT, locale="ar", **kwargs,
                )
                yield ctx
            finally:
                browser.close()

    def _launch(self, pw):
        args = ["--autoplay-policy=no-user-gesture-required", "--mute-audio"]
        if self.executable_path:
            return pw.chromium.launch(executable_path=self.executable_path, args=args)
        try:
            return pw.chromium.launch(args=args)
        except Exception:
            if self.FALLBACK_EXECUTABLE.exists():
                return pw.chromium.launch(executable_path=str(self.FALLBACK_EXECUTABLE), args=args)
            raise
