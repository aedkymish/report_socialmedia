"""The organisation logo in the form/report header must never overlap the text."""
import base64
import io
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from accounts.models import User
from reports.models import ActionRequest
from reports.services.browser import BrowserLauncher

OVERLAP_JS = """() => {
  const img = document.querySelector('.form-head .head-logo img').getBoundingClientRect();
  const text = document.querySelector('.form-head .head-text').getBoundingClientRect();
  const sep = !(img.right <= text.left || text.right <= img.left || img.bottom <= text.top || text.bottom <= img.top);
  return {overlap: sep, imgW: img.width, imgH: img.height};
}"""


def png(w, h) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "navy").save(buf, format="PNG")
    return buf.getvalue()


class LogoLayoutTests(TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))
        self.u = User.objects.create_user("M1", password="x")
        self.req = ActionRequest.objects.create(platforms=["tiktok"], actions=["block"], description="d",
                                                monitor=self.u, uploader=self.u, created_by=self.u)
        self.client.force_login(self.u)

    def _settings(self, logo: Path):
        return self.settings(REPORT={**settings.REPORT, "LOGO_PATH": str(logo), "LOGO_HEIGHT": 70})

    def test_logo_served_and_shown_on_form(self):
        logo = self.dir / "logo.png"
        logo.write_bytes(png(50, 50))
        with self._settings(logo):
            page = self.client.get(self.req.get_absolute_url())
            self.assertContains(page, reverse("reports:logo"))
            resp = self.client.get(reverse("reports:logo"))
            self.assertEqual(resp["Content-Type"], "image/png")
        self.client.logout()
        with self._settings(logo):
            self.assertEqual(self.client.get(reverse("reports:logo")).status_code, 302)  # login required

    def test_no_logo_configured(self):
        with self.settings(REPORT={**settings.REPORT, "LOGO_PATH": ""}):
            self.assertNotContains(self.client.get(self.req.get_absolute_url()), 'class="head-logo"')
            self.assertEqual(self.client.get(reverse("reports:logo")).status_code, 404)

    def test_logo_never_overlaps_text(self):
        logo = self.dir / "logo.png"
        pages = {}
        for w, h in ((900, 150), (150, 600), (300, 300)):  # very wide, very tall, square
            logo.write_bytes(png(w, h))
            data_uri = "data:image/png;base64," + base64.b64encode(png(w, h)).decode()
            with self._settings(logo):
                html = self.client.get(self.req.get_absolute_url()).content.decode()
            pages[(w, h)] = html.replace(reverse("reports:logo"), data_uri)

        with BrowserLauncher().context({"width": 794, "height": 1123}) as ctx:  # A4 @96dpi
            page = ctx.new_page()
            for (w, h), html in pages.items():
                for width, media in ((794, "print"), (1000, "screen"), (380, "screen")):
                    page.set_viewport_size({"width": width, "height": 1123})
                    page.emulate_media(media=media)
                    page.set_content(html, wait_until="load")
                    res = page.evaluate(OVERLAP_JS)
                    self.assertFalse(res["overlap"], f"logo {w}x{h} overlaps text at {width}px {media}: {res}")
                    self.assertLessEqual(res["imgH"], 70.5)
                    self.assertGreater(res["imgW"], 0)
