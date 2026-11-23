import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from reports.services.browser import BrowserLauncher, load_netscape_cookies
from reports.services.screenshotter import (
    PageCleaner, TikTokCleaner, XCleaner, cleaner_for,
)

PROFILE = """
<html><body style="background:#000;color:#fff">
<h1 data-e2e="user-title">tk_test</h1>
<div data-e2e="user-post-item"><img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" width=100 height=100></div>
<div id="captcha-verify-container-main-page" style="position:fixed;inset:0;background:rgba(0,0,0,.7)">
  <div>Drag the slider to fit the puzzle</div>
  {close}
</div>
</body></html>
"""
CLOSABLE = PROFILE.format(close='<button id="captcha_close_button" onclick="this.parentNode.remove()">x</button>')
NOT_CLOSABLE = PROFILE.format(close="")


class CleanerSelectionTests(SimpleTestCase):
    def test_platform_cleaners(self):
        self.assertIsInstance(cleaner_for("https://www.tiktok.com/@a"), TikTokCleaner)
        self.assertIsInstance(cleaner_for("https://twitter.com/a"), XCleaner)
        self.assertIs(type(cleaner_for("https://example.com")), PageCleaner)


class CookieParsingTests(SimpleTestCase):
    def test_netscape_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write("# Netscape HTTP Cookie File\n"
                     ".tiktok.com\tTRUE\t/\tTRUE\t1999999999\tsessionid\tabc\n"
                     "#HttpOnly_.tiktok.com\tTRUE\t/\tTRUE\t0\ttt_chain\txyz\n"
                     "broken line\n")
        cookies = load_netscape_cookies(fh.name)
        Path(fh.name).unlink()
        self.assertEqual([c["name"] for c in cookies], ["sessionid", "tt_chain"])
        self.assertEqual(cookies[0]["expires"], 1999999999)
        self.assertTrue(cookies[1]["httpOnly"])
        self.assertNotIn("expires", cookies[1])

    def test_missing_file(self):
        self.assertEqual(load_netscape_cookies("/nope/cookies.txt"), [])
        self.assertEqual(load_netscape_cookies(""), [])


class LiveCleanerTests(SimpleTestCase):
    """Real headless Chromium."""

    def _run(self, html, cookies_file=""):
        with BrowserLauncher(cookies_file=cookies_file).context({"width": 800, "height": 600}) as ctx:
            page = ctx.new_page()
            page.set_content(html)
            notes = TikTokCleaner().clean(page)
            overlay = page.locator("#captcha-verify-container-main-page").count()
            return notes, overlay, ctx.cookies()

    def test_closable_captcha_is_dismissed(self):
        notes, overlay, _ = self._run(CLOSABLE)
        self.assertEqual(overlay, 0)
        self.assertTrue(any("تم إغلاقه" in n for n in notes), notes)

    def test_unclosable_captcha_is_reported(self):
        notes, overlay, _ = self._run(NOT_CLOSABLE)
        self.assertEqual(overlay, 1)
        self.assertTrue(any("CAPTCHA" in n and "YTDLP_COOKIES_FILE" in n for n in notes), notes)

    def test_cookies_are_loaded_into_browser(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write(".tiktok.com\tTRUE\t/\tTRUE\t1999999999\tsessionid\tabc\n")
        _, _, cookies = self._run("<p>x</p>", cookies_file=fh.name)
        Path(fh.name).unlink()
        self.assertIn("sessionid", [c["name"] for c in cookies])
