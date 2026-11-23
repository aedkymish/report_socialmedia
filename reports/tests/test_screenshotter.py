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


ERROR_GRID = """
<html><body>
<h1 data-e2e="user-title">tk_test</h1>
<div id="grid"><p>حدث خطأ ما</p><button id="r">تحديث</button></div>
<script>
  let clicks = 0;
  document.getElementById('r').onclick = () => {
    clicks++;
    if (clicks >= {works_after}) setTimeout(() => {
      document.getElementById('grid').innerHTML = '<div data-e2e="user-post-item">video</div>';
    }, 300);
  };
</script>
</body></html>
"""


class LiveRetryTests(SimpleTestCase):
    def _run(self, works_after):
        with BrowserLauncher().context({"width": 800, "height": 600}) as ctx:
            page = ctx.new_page()
            page.set_content(ERROR_GRID.replace("{works_after}", str(works_after)))
            notes = TikTokCleaner()._retry_failed_content(page)
            return notes, page.locator('[data-e2e="user-post-item"]').count()

    def test_refresh_button_recovers_grid(self):
        notes, items = self._run(works_after=2)
        self.assertEqual(items, 1)
        self.assertTrue(any("نجح بعد إعادة المحاولة (2)" in n for n in notes), notes)

    def test_grid_never_loads_is_reported(self):
        notes, items = self._run(works_after=99)
        self.assertEqual(items, 0)
        self.assertTrue(any("قائمة الفيديوهات" in n for n in notes), notes)

    def test_no_error_state_no_notes(self):
        with BrowserLauncher().context({"width": 800, "height": 600}) as ctx:
            page = ctx.new_page()
            page.set_content('<div data-e2e="user-post-item">ok</div>')
            self.assertEqual(TikTokCleaner()._retry_failed_content(page), [])


class SessionCookieTests(SimpleTestCase):
    def _file(self, text):
        fh = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        fh.write(text)
        fh.close()
        self.addCleanup(Path(fh.name).unlink)
        return fh.name

    def test_logged_out_export_is_detected(self):
        from reports.services.screenshotter import ProfileScreenshotter
        f = self._file(".tiktok.com\tTRUE\t/\tTRUE\t1999999999\ttt_csrf_token\tx\n"
                       ".tiktok.com\tTRUE\t/\tTRUE\t1999999999\tttwid\ty\n")
        notes = ProfileScreenshotter(cookies_file=f)._cookie_notes("https://www.tiktok.com/@a")
        self.assertTrue(notes and "sessionid" in notes[0], notes)

    def test_logged_in_export_passes(self):
        from reports.services.screenshotter import ProfileScreenshotter
        f = self._file(".tiktok.com\tTRUE\t/\tTRUE\t1999999999\tsessionid\tabc\n")
        self.assertEqual(ProfileScreenshotter(cookies_file=f)._cookie_notes("https://www.tiktok.com/@a"), [])

    def test_check_cookies_command(self):
        import io
        from django.core.management import call_command
        f = self._file(".tiktok.com\tTRUE\t/\tTRUE\t1999999999\tttwid\tSECRETVALUE\n"
                       ".instagram.com\tTRUE\t/\tTRUE\t1999999999\tsessionid\tSECRET2\n")
        out = io.StringIO()
        call_command("check_cookies", file=f, stdout=out)
        text = out.getvalue()
        self.assertIn("✗ tiktok.com", text)
        self.assertIn("✓ instagram.com", text)
        self.assertNotIn("SECRET", text)  # values are never printed


class CookieFormatTests(SimpleTestCase):
    def _file(self, text):
        fh = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
        fh.write(text)
        fh.close()
        self.addCleanup(Path(fh.name).unlink)
        return fh.name

    def test_cookie_editor_json(self):
        import json
        from reports.services.cookies import CookieFile
        f = self._file(json.dumps([
            {"domain": ".tiktok.com", "name": "sessionid", "value": "abc", "path": "/",
             "secure": True, "httpOnly": True, "expirationDate": 1999999999.5},
            {"domain": ".tiktok.com", "name": "ttwid", "value": "x", "session": True},
        ]))
        cf = CookieFile(f)
        report = cf.read()
        self.assertEqual(report.format, "json")
        self.assertEqual([c["name"] for c in report.cookies], ["sessionid", "ttwid"])
        converted = Path(cf.as_netscape_path())
        self.addCleanup(converted.unlink)
        text = converted.read_text()
        self.assertIn("#HttpOnly_.tiktok.com\tTRUE\t/\tTRUE\t1999999999\tsessionid\tabc", text)
        self.assertEqual(CookieFile(str(converted)).read().format, "netscape")

    def test_space_separated_crlf_bom(self):
        from reports.services.cookies import CookieFile
        f = self._file("﻿# Netscape\r\n.tiktok.com TRUE / TRUE 1999999999 sessionid abc\r\n")
        cookies = CookieFile(f).load()
        self.assertEqual(cookies[0]["name"], "sessionid")
        self.assertEqual(cookies[0]["value"], "abc")

    def test_html_and_garbage_explained(self):
        from reports.services.cookies import CookieFile
        self.assertIn("HTML", CookieFile(self._file("<!doctype html><html>")).read().problem)
        problem = CookieFile(self._file("hello world\n")).read().problem
        self.assertIn("أول سطر", problem)
        self.assertNotIn("hello", problem)

    def test_command_reports_problem_without_values(self):
        import io
        from django.core.management import call_command
        f = self._file("sessionid=SECRET; ttwid=SECRET2\n")
        out = io.StringIO()
        call_command("check_cookies", file=f, stdout=out)
        self.assertIn("أدوات المطوّر", out.getvalue())
        self.assertNotIn("SECRET", out.getvalue())
