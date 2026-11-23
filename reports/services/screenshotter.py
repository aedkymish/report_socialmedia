"""Takes a screenshot of a profile page with headless Chromium (Playwright)."""
from __future__ import annotations

from pathlib import Path


class ProfileScreenshotter:
    VIEWPORT = {"width": 1366, "height": 1600}
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    )

    def __init__(self, executable_path: str = "", timeout_ms: int = 45000):
        self.executable_path = executable_path
        self.timeout_ms = timeout_ms

    def capture(self, url: str, out_file: Path) -> Path:
        from playwright.sync_api import sync_playwright

        out_file.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as pw:
            browser = self._launch(pw)
            try:
                context = browser.new_context(
                    viewport=self.VIEWPORT, user_agent=self.USER_AGENT, locale="ar",
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass  # social sites keep long-polling; a loaded DOM is enough
                page.wait_for_timeout(2500)
                page.screenshot(path=str(out_file), full_page=False)
            finally:
                browser.close()
        return out_file

    def _launch(self, pw):
        if self.executable_path:
            return pw.chromium.launch(executable_path=self.executable_path)
        try:
            return pw.chromium.launch()
        except Exception:
            fallback = Path("/opt/pw-browsers/chromium")
            if fallback.exists():
                return pw.chromium.launch(executable_path=str(fallback))
            raise
