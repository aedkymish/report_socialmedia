from datetime import timedelta

from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from reports.models import ActionRequest, RequestLink
from reports.reporting import ReportBuilder, ReportFilter


class ReportTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("M1", password="x")
        now = timezone.now()

        def make(platforms, actions, days_ago, status="submitted", links=()):
            r = ActionRequest.objects.create(platforms=platforms, actions=actions, description="d",
                                             monitor=self.u, uploader=self.u,
                                             created_by=self.u, status=status)
            ActionRequest.objects.filter(pk=r.pk).update(created_at=now - timedelta(days=days_ago))
            for p, vid in links:
                RequestLink.objects.create(request=r, url=f"https://{p}.com/x", platform=p, is_video=vid,
                                           evidence_status="done")
            return r

        self.a = make(["tiktok"], ["block"], 1, "approved", [("tiktok", True), ("tiktok", False)])
        self.b = make(["tiktok", "x"], ["document"], 3, "rejected", [("x", False)])
        self.c = make(["facebook"], ["ban", "block"], 5)
        self.old = make(["tiktok"], ["block"], 60)

    def build(self, **params):
        q = QueryDict(mutable=True)
        for k, v in params.items():
            q.setlist(k, v if isinstance(v, list) else [v])
        return ReportBuilder().build(ReportFilter.from_query(q))

    def test_default_period_is_last_30_days(self):
        res = self.build()
        self.assertEqual({r.pk for r in res.requests}, {self.a.pk, self.b.pk, self.c.pk})
        self.assertEqual(res.links_total, 3)
        self.assertEqual(res.videos, 1)
        self.assertEqual(res.approval_rate, 50)  # 1 approved of 2 decided

    def test_filter_platform_and_action(self):
        res = self.build(platform="tiktok", action="block")
        self.assertEqual([r.pk for r in res.requests], [self.a.pk])
        res = self.build(platform=["x", "facebook"])
        self.assertEqual({r.pk for r in res.requests}, {self.b.pk, self.c.pk})
        counts = {b.key: b.count for b in res.by_platform}
        self.assertEqual(counts, {"x": 1, "facebook": 1})

    def test_period_and_counts(self):
        today = timezone.localdate()
        res = self.build(**{"from": str(today - timedelta(days=90)), "to": str(today - timedelta(days=30))})
        self.assertEqual([r.pk for r in res.requests], [self.old.pk])
        res = self.build(**{"from": str(today - timedelta(days=90))})
        self.assertEqual({b.key: b.count for b in res.by_action}["block"], 3)

    def test_page_and_csv(self):
        self.client.force_login(self.u)
        page = self.client.get(reverse("reports:report"), {"platform": "tiktok"})
        self.assertContains(page, "تقرير طلبات الإجراء")
        self.assertEqual(len(page.context["result"].requests), 2)
        csv = self.client.get(reverse("reports:report"), {"platform": "tiktok", "export": "csv"})
        self.assertEqual(csv["Content-Type"], "text/csv; charset=utf-8")
        body = csv.content.decode("utf-8-sig")
        self.assertIn("رقم الطلب", body)
        self.assertEqual(body.count("\n"), 4)  # title + header + 2 rows


class ReportPdfTests(TestCase):
    def test_pdf_export_embeds_arabic_font(self):
        u = User.objects.create_user("M1", password="x")
        ActionRequest.objects.create(platforms=["tiktok"], actions=["block"], description="d",
                                     monitor=u, uploader=u, created_by=u)
        self.client.force_login(u)
        resp = self.client.get(reverse("reports:report"), {"export": "pdf", "platform": "tiktok"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp["Content-Disposition"].endswith('.pdf"'))
        self.assertTrue(resp.content.startswith(b"%PDF"))
        self.assertIn(b"NotoSansArabic", resp.content)  # font embedded, not system fallback


class ReportLogoTests(TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from PIL import Image
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        self.png = self.dir / "logo.png"
        Image.new("RGB", (40, 40), "navy").save(self.png)
        self.u = User.objects.create_user("M1", password="x")
        self.client.force_login(self.u)

    def _pdf(self, logo_path):
        from django.conf import settings
        with self.settings(REPORT={**settings.REPORT, "LOGO_PATH": str(logo_path)}):
            resp = self.client.get(reverse("reports:report"), {"export": "pdf"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.content.startswith(b"%PDF"))
        return resp.content

    def test_logo_embedded_when_configured(self):
        self.assertIn(b"/Subtype /Image", self._pdf(self.png))

    def test_missing_or_unsupported_logo_is_ignored(self):
        from reports.services.pdf import report_logo_data_uri
        bad = self.dir / "logo.bmp"
        bad.write_bytes(b"BM")
        for path in (self.dir / "nope.png", bad):
            with self.assertLogs("reports.services.pdf", "WARNING"):
                self.assertNotIn(b"/Subtype /Image", self._pdf(path))
        self.assertNotIn(b"/Subtype /Image", self._pdf(""))

    def test_relative_path_resolved_against_project(self):
        from django.conf import settings
        from reports.services.pdf import report_logo_data_uri
        rel = self.png.relative_to(self.dir)
        with self.settings(BASE_DIR=self.dir, REPORT={**settings.REPORT, "LOGO_PATH": str(rel)}):
            self.assertTrue(report_logo_data_uri().startswith("data:image/png;base64,"))
