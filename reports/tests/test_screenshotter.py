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
<div data-e2e="user-post-item"><img src="data:image/gif;base64,R0lGODlhAQABAIAAAP///wAAACwAAAAAAQABAAACAkQBADs=" width=100 height=100></div>
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


SLOW_GRID = """
<html><body>
<h1 data-e2e="user-title">tk_test</h1>
<div id="grid"><div class="skeleton">loading</div></div>
<script>
  setTimeout(() => {
    const gif = "data:image/gif;base64,R0lGODlhAQABAIAAAP///wAAACwAAAAAAQABAAACAkQBADs=";
    document.getElementById('grid').innerHTML =
      [1,2,3].map(i => '<div data-e2e="user-post-item"><img src="' + gif + '"></div>').join('');
  }, {delay});
</script>
</body></html>
"""


class LiveReadinessTests(SimpleTestCase):
    def _clean(self, delay, timeout_ms=25000):
        cleaner = TikTokCleaner()
        cleaner.READY_TIMEOUT_MS = timeout_ms
        with BrowserLauncher().context({"width": 800, "height": 600}) as ctx:
            page = ctx.new_page()
            page.set_content(SLOW_GRID.replace("{delay}", str(delay)))
            notes = cleaner.clean(page)
            return notes, page.locator('[data-e2e="user-post-item"] img').count()

    def test_waits_for_thumbnails_not_just_header(self):
        notes, imgs = self._clean(delay=4000)
        self.assertEqual(imgs, 3)
        self.assertFalse(any("لم تكتمل" in n for n in notes), notes)

    def test_reports_when_grid_never_loads(self):
        notes, imgs = self._clean(delay=999999, timeout_ms=3000)
        self.assertEqual(imgs, 0)
        self.assertTrue(any("لم تكتمل" in n for n in notes), notes)


class SessionAliasTests(SimpleTestCase):
    def test_tiktok_alias_cookies_count_as_session(self):
        from reports.services.browser import has_session_cookie
        mk = lambda n: {"name": n, "value": "v", "domain": ".tiktok.com"}
        self.assertTrue(has_session_cookie([mk("sid_tt")], "tiktok.com"))
        self.assertTrue(has_session_cookie([mk("sessionid_ss")], "tiktok.com"))
        self.assertFalse(has_session_cookie([mk("sid_guard"), mk("ttwid")], "tiktok.com"))

    def test_sid_guard_hint(self):
        import io
        from django.core.management import call_command
        fh = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        fh.write(".tiktok.com\tTRUE\t/\tTRUE\t1999999999\tsid_guard\tx\n")
        fh.close()
        self.addCleanup(Path(fh.name).unlink)
        out = io.StringIO()
        call_command("check_cookies", file=fh.name, stdout=out)
        self.assertIn("sid_guard بدون sessionid", out.getvalue())


class SidGuardExpiryTests(SimpleTestCase):
    def test_expired_session_reported_with_date(self):
        import io
        from django.core.management import call_command
        # created 2026-01-26, max-age 180 days -> expired 2026-07-25
        value = "deadbeef%7C1769462457%7C15552000%7CSat%2C+25-Jul-2026+21%3A20%3A57+GMT"
        fh = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        fh.write(f".tiktok.com\tTRUE\t/\tTRUE\t1999999999\tsid_guard\t{value}\n")
        fh.close()
        self.addCleanup(Path(fh.name).unlink)
        out = io.StringIO()
        call_command("check_cookies", file=fh.name, stdout=out)
        self.assertIn("انتهت بتاريخ 2026-07-25", out.getvalue())
        self.assertNotIn("deadbeef", out.getvalue())


class LiveItemListTests(SimpleTestCase):
    """Real Chromium + local HTTP server imitating TikTok's item_list API."""

    @classmethod
    def setUpClass(cls):
        import functools, http.server, threading
        super().setUpClass()
        cls.site = Path(tempfile.mkdtemp())
        gif = "data:image/gif;base64,R0lGODlhAQABAIAAAP///wAAACwAAAAAAQABAAACAkQBADs="
        page = """<html><body><h1 data-e2e="user-title">tk</h1><div id="grid"></div><script>
          fetch('api/post/item_list/').then(r => r.text()).then(t => {
            if (!t) return;  // TikTok's silent refusal: grid stays as skeleton
            setTimeout(() => { document.getElementById('grid').innerHTML =
              '<div data-e2e="user-post-item"><img src="GIF"></div>'; }, 6000);
          });</script></body></html>""".replace("GIF", gif)
        for name, body in (("refused", ""), ("ok", '{"statusCode":0,"itemList":[1]}')):
            d = cls.site / name / "api" / "post" / "item_list"
            d.mkdir(parents=True)
            (d / "index.html").write_text(body)
            (cls.site / name / "page.html").write_text(page)
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(cls.site))
        handler.log_message = lambda *a: None
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        import shutil
        cls.httpd.shutdown()
        shutil.rmtree(cls.site, ignore_errors=True)
        super().tearDownClass()

    def _run(self, name):
        import time
        cleaner = TikTokCleaner()
        cleaner.READY_TIMEOUT_MS = 30000
        with BrowserLauncher().context({"width": 800, "height": 600}) as ctx:
            page = ctx.new_page()
            cleaner.observe(page)
            page.goto(f"{self.base}/{name}/page.html")
            start = time.monotonic()
            notes = cleaner.clean(page)
            return notes, cleaner.content_ready, time.monotonic() - start, \
                page.locator('[data-e2e="user-post-item"] img').count()

    def test_waits_for_late_grid_when_list_arrives(self):
        notes, ready, _, imgs = self._run("ok")
        self.assertTrue(ready, notes)
        self.assertEqual(imgs, 1)

    def test_empty_item_list_stops_early_with_reason(self):
        notes, ready, elapsed, imgs = self._run("refused")
        self.assertFalse(ready)
        self.assertEqual(imgs, 0)
        self.assertLess(elapsed, 20)  # did not burn the full 30s timeout
        self.assertTrue(any("رد فارغ على طلب item_list" in n for n in notes), notes)
