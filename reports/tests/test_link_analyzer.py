from django.test import SimpleTestCase

from reports.services import LinkAnalyzer


class LinkAnalyzerTests(SimpleTestCase):
    def setUp(self):
        self.a = LinkAnalyzer()

    def check(self, url, platform, is_post, profile):
        r = self.a.analyze(url)
        self.assertEqual((r.platform, r.is_post, r.profile_url), (platform, is_post, profile), url)

    def test_tiktok(self):
        self.check("https://www.tiktok.com/@user1/video/7312", "tiktok", True, "https://www.tiktok.com/@user1")
        self.check("https://www.tiktok.com/@user1", "tiktok", False, "https://www.tiktok.com/@user1")
        self.check("https://vm.tiktok.com/ZMabc/", "tiktok", True, "")

    def test_instagram(self):
        self.check("https://www.instagram.com/reel/Cx1/", "instagram", True, "")
        self.check("https://www.instagram.com/someone/", "instagram", False, "https://www.instagram.com/someone/")

    def test_facebook(self):
        self.check("https://www.facebook.com/page1/videos/123/", "facebook", True, "https://www.facebook.com/page1")
        self.check("https://www.facebook.com/page1", "facebook", False, "https://www.facebook.com/page1")
        self.check("https://fb.watch/abc/", "facebook", True, "")

    def test_x(self):
        self.check("https://x.com/acc/status/1", "x", True, "https://x.com/acc")
        self.check("https://twitter.com/acc", "x", False, "https://x.com/acc")

    def test_telegram(self):
        self.check("https://t.me/chan/55", "telegram", True, "https://t.me/s/chan")
        self.check("https://t.me/chan", "telegram", False, "https://t.me/s/chan")
