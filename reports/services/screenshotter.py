"""Takes a screenshot of a profile page with headless Chromium (Playwright)."""
from __future__ import annotations

from pathlib import Path

from .browser import BrowserLauncher


class ProfileScreenshotter:
    VIEWPORT = {"width": 1366, "height": 1600}

    def __init__(self, executable_path: str = "", timeout_ms: int = 45000):
        self.launcher = BrowserLauncher(executable_path)
        self.timeout_ms = timeout_ms

    def capture(self, url: str, out_file: Path) -> Path:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with self.launcher.context(self.VIEWPORT) as ctx:
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass  # social sites keep long-polling; a loaded DOM is enough
            page.wait_for_timeout(2500)
            page.screenshot(path=str(out_file), full_page=False)
        return out_file
