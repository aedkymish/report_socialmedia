import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from reports.models import ActionRequest, RequestLink
from reports.services import EvidenceCollector, VideoResult

TMP_MEDIA = tempfile.mkdtemp()
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class FakeDownloader:
    def download(self, url, dest: Path):
        if "/video/" not in url and "/status/" not in url:
            return VideoResult(is_video=False)
        dest.mkdir(parents=True, exist_ok=True)
        f = dest / "123.mp4"
        f.write_bytes(b"fake-video")
        return VideoResult(is_video=True, file_path=f, title="clip", uploader_url="")


class FakeScreenshotter:
    def __init__(self):
        self.urls = []

    def capture(self, url, out: Path):
        self.urls.append(url)
        out.write_bytes(PNG)
        return out


@override_settings(MEDIA_ROOT=TMP_MEDIA, EVIDENCE={**settings.EVIDENCE, "ASYNC": False})
class WorkflowTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.mon = User.objects.create_user("M100", password="x", role=User.Role.MONITOR)
        self.up = User.objects.create_user("U200", password="x", role=User.Role.UPLOADER)
        self.pc = User.objects.create_user("P300", password="x", role=User.Role.PLATFORM_CONTACT)
        self.boss = User.objects.create_user("A900", password="x", role=User.Role.APPROVER, full_name="مدير")
        self.shots = FakeScreenshotter()
        factory = lambda: EvidenceCollector(downloader=FakeDownloader(), screenshotter=self.shots)
        from reports import views
        self._orig = views.EvidenceDispatcher
        views.EvidenceDispatcher = lambda: self._orig(collector_factory=factory)

    def tearDown(self):
        from reports import views
        views.EvidenceDispatcher = self._orig

    def payload(self, **kw):
        data = {
            "platforms": ["tiktok", "x"], "actions": ["block", "document"],
            "links": "https://www.tiktok.com/@bad/video/99\nx.com/acc\n",
            "description": "محتوى مخالف", "monitor": "M100", "uploader": "U200",
            "platform_contact": "P300", "declaration_accepted": "on", "consent_accepted": "on",
        }
        data.update(kw)
        return data

    def test_requires_login(self):
        self.assertEqual(self.client.get(reverse("reports:create")).status_code, 302)

    def test_unknown_code_rejected(self):
        self.client.force_login(self.mon)
        resp = self.client.post(reverse("reports:create"), self.payload(uploader="NOPE"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "الكود غير موجود")

    def test_submit_collects_evidence_and_approve(self):
        self.client.force_login(self.mon)
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(reverse("reports:create"), self.payload())
        req = ActionRequest.objects.get()
        self.assertRedirects(resp, req.get_absolute_url())
        self.assertEqual(req.monitor, self.mon)

        video, profile = req.links.order_by("pk")
        self.assertTrue(video.is_video)
        self.assertTrue(video.video_file.name.endswith(".mp4"))
        self.assertEqual(len(video.video_sha256), 64)
        self.assertTrue(video.profile_screenshot)
        self.assertEqual(video.evidence_status, RequestLink.EvidenceStatus.DONE)
        self.assertEqual(profile.url, "https://x.com/acc")
        self.assertFalse(profile.is_video)
        self.assertEqual(profile.evidence_status, RequestLink.EvidenceStatus.DONE)
        self.assertIn("https://www.tiktok.com/@bad", self.shots.urls)

        # non-approver cannot approve
        self.client.post(reverse("reports:decision", args=[req.pk]), {"decision": "approve"})
        req.refresh_from_db()
        self.assertEqual(req.status, ActionRequest.Status.SUBMITTED)

        self.client.force_login(self.boss)
        self.client.post(reverse("reports:decision", args=[req.pk]), {"decision": "approve", "note": "ok"})
        req.refresh_from_db()
        self.assertEqual(req.status, ActionRequest.Status.APPROVED)
        self.assertEqual(req.approved_by, self.boss)
        self.assertIsNotNone(req.approved_at)
        self.assertContains(self.client.get(req.get_absolute_url()), "مدير")
