import io

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import User
from reports.models import ActionRequest, RequestLink
from reports.services.url_normalizer import normalize_url


class NormalizeUrlTests(SimpleTestCase):
    def same(self, *urls):
        keys = {normalize_url(u) for u in urls}
        self.assertEqual(len(keys), 1, keys)

    def differ(self, a, b):
        self.assertNotEqual(normalize_url(a), normalize_url(b))

    def test_spelling_variants_are_the_same_link(self):
        self.same("https://www.tiktok.com/@User/video/123", "http://tiktok.com/@user/video/123/",
                  "tiktok.com/@user/video/123?lang=ar&is_from_webapp=1", "https://m.tiktok.com/@user/video/123#x")
        self.same("https://twitter.com/Acc/status/1", "https://x.com/acc/status/1?s=20", "https://mobile.twitter.com/acc/status/1")
        self.same("https://t.me/s/chan/5", "https://telegram.me/chan/5", "t.me/chan/5/")
        self.same("https://www.instagram.com/reel/Cx1/?igsh=abc", "https://instagram.com/reel/cx1")
        self.same("https://m.facebook.com/profile.php?id=100&ref=x", "https://www.facebook.com/profile.php?id=100")

    def test_identifying_parts_are_kept(self):
        self.differ("https://www.facebook.com/profile.php?id=100", "https://www.facebook.com/profile.php?id=200")
        self.differ("https://www.tiktok.com/@a/video/1", "https://www.tiktok.com/@a/video/2")
        self.differ("https://www.youtube.com/watch?v=AAA", "https://www.youtube.com/watch?v=BBB")
        self.differ("https://www.facebook.com/PageA", "https://www.facebook.com/PageB")


class DuplicateLinkRuleTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("M1", password="x")
        self.old = ActionRequest.objects.create(platforms=["tiktok"], actions=["block"], description="d",
                                                monitor=self.u, uploader=self.u, created_by=self.u)
        RequestLink.objects.create(request=self.old, url="https://www.tiktok.com/@bad/video/1", platform="tiktok")
        self.client.force_login(self.u)

    def post(self, links):
        return self.client.post(reverse("reports:create"), {
            "platforms": ["tiktok"], "actions": ["block"], "links": links, "description": "d",
            "monitor": "M1", "uploader": "M1", "declaration_accepted": "on", "consent_accepted": "on",
        })

    def test_link_already_in_another_request_is_rejected(self):
        resp = self.post(["https://tiktok.com/@BAD/video/1/?lang=ar", "https://x.com/new"])
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f"الرابط مسجّل مسبقاً في الطلب رقم {self.old.pk}")
        self.assertEqual(ActionRequest.objects.count(), 1)

    def test_new_links_accepted_and_normalized_saved(self):
        resp = self.post(["https://x.com/new/status/9", "https://twitter.com/NEW/status/9"])  # same link twice
        req = ActionRequest.objects.latest("pk")
        self.assertRedirects(resp, req.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(list(req.links.values_list("normalized_url", flat=True)), ["x.com/new/status/9"])

    def test_deleted_request_frees_its_links(self):
        self.old.delete()
        resp = self.post(["https://www.tiktok.com/@bad/video/1"])
        self.assertEqual(resp.status_code, 302)

    def test_live_check_endpoint(self):
        url = reverse("reports:link_check")
        dup = self.client.get(url, {"url": "http://m.tiktok.com/@bad/video/1"}).json()
        self.assertEqual((dup["duplicate"], dup["request"]), (True, self.old.pk))
        self.assertEqual(dup["href"], self.old.get_absolute_url())
        self.assertFalse(self.client.get(url, {"url": "https://x.com/other"}).json()["duplicate"])
        self.client.logout()
        self.assertEqual(self.client.get(url, {"url": "x"}).status_code, 302)

    def test_find_duplicates_command(self):
        other = ActionRequest.objects.create(description="d", monitor=self.u, uploader=self.u, created_by=self.u)
        RequestLink.objects.create(request=other, url="https://tiktok.com/@bad/video/1/", platform="tiktok")
        out = io.StringIO()
        call_command("find_duplicate_links", stdout=out)
        self.assertIn("tiktok.com/@bad/video/1", out.getvalue())
        self.assertIn(f"#{self.old.pk}", out.getvalue())
