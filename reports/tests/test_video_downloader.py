import functools
import http.server
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from django.test import SimpleTestCase

from reports.services import BrowserVideoCapture, NoVideoError, VideoDownloader, VideoResult


class _Fail:
    name = "first"

    def download(self, url, dest):
        raise RuntimeError("ERROR: [TikTok] 1: Unexpected response from webpage request; please report this issue on ...")


class _Ok:
    name = "second"

    def download(self, url, dest):
        dest.mkdir(parents=True, exist_ok=True)
        f = dest / "v.mp4"
        f.write_bytes(b"x")
        return VideoResult(is_video=True, file_path=f, method=self.name)


class _NoVideo:
    name = "novideo"

    def download(self, url, dest):
        raise NoVideoError()


class StrategyChainTests(SimpleTestCase):
    def test_falls_back_to_next_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = VideoDownloader(strategies=[_Fail(), _Ok()]).download("u", Path(tmp))
            self.assertTrue(r.is_video)
            self.assertEqual(r.method, "second")

    def test_no_video_stops_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = VideoDownloader(strategies=[_NoVideo(), _Ok()]).download("u", Path(tmp))
            self.assertFalse(r.is_video)

    def test_all_fail_reports_short_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as cm:
                VideoDownloader(strategies=[_Fail()]).download("u", Path(tmp))
            self.assertIn("Unexpected response", str(cm.exception))
            self.assertNotIn("please report", str(cm.exception))

    def test_parse_tiktok_rehydration(self):
        data = {"__DEFAULT_SCOPE__": {"webapp.video-detail": {"itemInfo": {"itemStruct": {
            "desc": "hello", "author": {"uniqueId": "someone"},
            "video": {"playAddr": "https://v16.tiktokcdn.com/a.mp4", "downloadAddr": ""},
        }}}}}
        meta = BrowserVideoCapture._parse_tiktok(data)
        self.assertEqual(meta["video_urls"], ["https://v16.tiktokcdn.com/a.mp4"])
        self.assertEqual(meta["uploader_url"], "https://www.tiktok.com/@someone")
        self.assertEqual(meta["title"], "hello")


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg needed to make a test clip")
class BrowserCaptureLiveTests(SimpleTestCase):
    """Real headless Chromium against a local HTTP server."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.site = Path(tempfile.mkdtemp())
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
             "testsrc=duration=3:size=320x240:rate=10", "-pix_fmt", "yuv420p", str(cls.site / "clip.mp4")],
            check=True,
        )
        (cls.site / "plain.html").write_text(
            '<html><body><video src="/clip.mp4" muted></video></body></html>')
        tiktok = {"__DEFAULT_SCOPE__": {"webapp.video-detail": {"itemInfo": {"itemStruct": {
            "desc": "clip desc", "author": {"uniqueId": "tester"},
            "video": {"playAddr": "PLACEHOLDER/clip.mp4"}}}}}}
        cls.tiktok_template = json.dumps(tiktok)
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(cls.site))
        handler.log_message = lambda *a: None
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"
        (cls.site / "tiktok.html").write_text(
            '<html><body><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'
            + cls.tiktok_template.replace("PLACEHOLDER", cls.base) + "</script></body></html>")
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        shutil.rmtree(cls.site, ignore_errors=True)
        super().tearDownClass()

    def test_video_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = BrowserVideoCapture(timeout_ms=15000).download(f"{self.base}/plain.html", Path(tmp))
            self.assertTrue(r.is_video)
            self.assertEqual(r.file_path.read_bytes(), (self.site / "clip.mp4").read_bytes())

    def test_tiktok_embedded_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = BrowserVideoCapture(timeout_ms=15000).download(f"{self.base}/tiktok.html", Path(tmp))
            self.assertTrue(r.is_video)
            self.assertEqual(r.uploader_url, "https://www.tiktok.com/@tester")
            self.assertEqual(r.title, "clip desc")
