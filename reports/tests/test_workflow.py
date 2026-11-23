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
            "declaration_accepted": "on", "consent_accepted": "on",
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
        self.assertEqual(req.platform_contact_code, "003")

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


class SheetFallbackTests(TestCase):
    """When the grid never renders, a separate, labelled videos sheet is produced."""

    def test_sheet_created_when_grid_missing(self):
        from reports.services.screenshotter import ScreenshotResult

        class GridlessShots:
            def capture(self, url, out):
                from PIL import Image
                Image.new("RGB", (1366, 900), "black").save(out)
                return ScreenshotResult(out, ["grid missing"], content_ready=False)

        class Lister:
            def list(self, url):
                return [{"id": "1", "url": "https://www.tiktok.com/@a/video/1", "title": "t",
                         "thumbnail": "", "date": "2026-11-01", "views": 5}]

        from reports.services.profile_videos import VideosSheetRenderer
        user = User.objects.create_user("Z1", password="x")
        req = ActionRequest.objects.create(description="d", monitor=user, uploader=user,
                                           created_by=user)
        link = RequestLink.objects.create(request=req, url="https://www.tiktok.com/@a")
        with self.settings(MEDIA_ROOT=TMP_MEDIA):
            collector = EvidenceCollector(downloader=FakeDownloader(), screenshotter=GridlessShots(),
                                          video_lister=Lister(), sheet_renderer=VideosSheetRenderer())
            link = collector.collect(link)
        self.assertTrue(link.profile_screenshot)
        self.assertTrue(link.profile_videos_image)
        self.assertEqual(len(link.profile_videos_sha256), 64)
        self.assertIn("قائمة فيديوهات الحساب (1 فيديو)", link.evidence_log)


class MultipleLinksFormTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("M1", password="x")

    def _form(self, links):
        from django.http import QueryDict
        from reports.forms import ActionRequestForm
        q = QueryDict(mutable=True)
        q.setlist("platforms", ["tiktok"]); q.setlist("actions", ["block"])
        q.update({"description": "d", "monitor": "M1", "uploader": "M1",
                  "declaration_accepted": "on", "consent_accepted": "on"})
        q.setlist("links", links)
        return ActionRequestForm(q)

    def test_separate_fields_are_all_kept_in_order(self):
        f = self._form(["https://www.tiktok.com/@a/video/1", "", "t.me/chan/5",
                        "https://x.com/acc", "https://www.tiktok.com/@a/video/1"])
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.cleaned_data["links"], [
            "https://www.tiktok.com/@a/video/1", "https://t.me/chan/5", "https://x.com/acc"])

    def test_comma_or_space_separated_paste_in_one_field(self):
        f = self._form(["https://x.com/a, https://x.com/b،https://x.com/c https://x.com/d"])
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(len(f.cleaned_data["links"]), 4)

    def test_all_empty_rejected_and_bad_url_named(self):
        self.assertIn("رابطاً واحداً", str(self._form(["", " "]).errors))
        self.assertIn("رابط غير صالح", str(self._form(["https://x.com/a", "https://exa mple"]).errors))

    def test_rows_rerendered_after_validation_error(self):
        f = self._form(["https://x.com/a", "https://x.com/b"])
        f.data = f.data.copy(); f.data["description"] = ""
        self.assertFalse(f.is_valid())
        html = str(f["links"])
        self.assertEqual(html.count('type="url" name="links"'), 2)


class VideosSheetModeTests(TestCase):
    def _collect(self, mode, grid_ready):
        from reports.services.screenshotter import ScreenshotResult

        class Shots:
            def capture(self, url, out):
                from PIL import Image
                Image.new("RGB", (800, 400), "black").save(out)
                return ScreenshotResult(out, [], content_ready=grid_ready)

        class Lister:
            calls = 0

            def list(self, url):
                Lister.calls += 1
                return [{"id": "1", "url": "u", "title": "t", "thumbnail": "", "date": "", "views": None}]

        class Renderer:
            def render(self, header, profile_url, videos, out):
                out.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
                return out

        user = User.objects.create_user(f"Z{mode}{grid_ready}", password="x")
        req = ActionRequest.objects.create(description="d", monitor=user, uploader=user,
                                           created_by=user)
        link = RequestLink.objects.create(request=req, url="https://www.tiktok.com/@a")
        evidence = {**settings.EVIDENCE, "VIDEOS_SHEET": mode}
        with self.settings(MEDIA_ROOT=TMP_MEDIA, EVIDENCE=evidence):
            link = EvidenceCollector(downloader=FakeDownloader(), screenshotter=Shots(),
                                     video_lister=Lister(), sheet_renderer=Renderer()).collect(link)
        return link, Lister.calls

    def test_auto_creates_only_when_grid_missing(self):
        link, calls = self._collect("auto", grid_ready=False)
        self.assertTrue(link.profile_videos_image)
        self.assertIn("لم تظهر في لقطة الشاشة", link.evidence_log)
        link, calls = self._collect("auto", grid_ready=True)
        self.assertFalse(link.profile_videos_image)
        self.assertEqual(calls, 0)
        self.assertIn("EVIDENCE_VIDEOS_SHEET=always", link.evidence_log)

    def test_always_and_never(self):
        self.assertTrue(self._collect("always", grid_ready=True)[0].profile_videos_image)
        self.assertFalse(self._collect("never", grid_ready=False)[0].profile_videos_image)


class PlatformContactCodeTests(TestCase):
    def test_fixed_code_shown_readonly_and_not_overridable(self):
        u = User.objects.create_user("M1", password="x")
        self.client.force_login(u)
        page = self.client.get(reverse("reports:create"))
        self.assertContains(page, 'value="003"')
        self.assertContains(page, "readonly")
        with self.settings(PLATFORM_CONTACT_CODE="777"):
            self.client.post(reverse("reports:create"), {
                "platforms": ["tiktok"], "actions": ["block"], "links": "https://x.com/a",
                "description": "d", "monitor": "M1", "uploader": "M1",
                "platform_contact_code": "HACK", "declaration_accepted": "on", "consent_accepted": "on",
            })
        self.assertEqual(ActionRequest.objects.get().platform_contact_code, "777")


class AuthorizedPersonsEditTests(TestCase):
    """خامساً: editable before approval by creator / approver / superadmin, then locked."""

    def setUp(self):
        self.creator = User.objects.create_user("M100", password="x", role=User.Role.MONITOR)
        self.other = User.objects.create_user("M200", password="x", role=User.Role.MONITOR)
        self.up = User.objects.create_user("U200", password="x", role=User.Role.UPLOADER)
        self.boss = User.objects.create_user("A900", password="x", role=User.Role.APPROVER)
        self.req = ActionRequest.objects.create(description="d", monitor=self.creator, uploader=self.up,
                                                created_by=self.creator)
        self.url = reverse("reports:authorized", args=[self.req.pk])

    def test_creator_edits_and_change_is_audited(self):
        from auditlog.models import LogEntry
        self.client.force_login(self.creator)
        self.assertContains(self.client.get(self.req.get_absolute_url()), 'id="edit-authorized"')
        resp = self.client.post(self.url, {"monitor": "M200", "uploader": "U200"})
        self.assertRedirects(resp, self.req.get_absolute_url())
        self.req.refresh_from_db()
        self.assertEqual(self.req.monitor, self.other)
        entry = LogEntry.objects.get_for_object(self.req).filter(action=LogEntry.Action.UPDATE).latest("timestamp")
        self.assertEqual(entry.actor, self.creator)
        self.assertIn("monitor", entry.changes_dict)

    def test_unknown_code_shows_error_and_keeps_form_open(self):
        self.client.force_login(self.creator)
        resp = self.client.post(self.url, {"monitor": "NOPE", "uploader": "U200"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "الكود غير موجود")
        self.assertNotContains(resp, 'id="edit-authorized" class="no-print"\n        style="border:1px solid var(--line);border-radius:8px;padding:12px;margin:10px 0" hidden')
        self.req.refresh_from_db()
        self.assertEqual(self.req.monitor, self.creator)

    def test_other_users_cannot_edit(self):
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(self.req.get_absolute_url()), 'id="edit-authorized"')
        self.client.post(self.url, {"monitor": "M200", "uploader": "U200"})
        self.req.refresh_from_db()
        self.assertEqual(self.req.monitor, self.creator)

    def test_approver_can_edit_then_locked_after_decision(self):
        self.client.force_login(self.boss)
        self.client.post(self.url, {"monitor": "M200", "uploader": "U200"})
        self.req.refresh_from_db()
        self.assertEqual(self.req.monitor, self.other)
        self.req.approve(self.boss)
        page = self.client.get(self.req.get_absolute_url())
        self.assertNotContains(page, 'id="edit-authorized"')
        self.assertContains(page, "لا يمكن تعديل المخولين بعد اعتماد الطلب")
        self.client.post(self.url, {"monitor": "M100", "uploader": "U200"})
        self.req.refresh_from_db()
        self.assertEqual(self.req.monitor, self.other)
