"""Orchestrates evidence collection for each link of a request:
   1. analyse the link (platform / post or profile / profile URL)
   2. if it is a video -> download & store it
   3. screenshot the owner's profile page and store it
"""
from __future__ import annotations

import hashlib
import logging
import tempfile
import threading
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.db import close_old_connections
from django.utils import timezone

from ..models import ActionRequest, RequestLink
from .link_analyzer import LinkAnalyzer
from .screenshotter import ProfileScreenshotter
from .video_downloader import VideoDownloader

logger = logging.getLogger(__name__)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class EvidenceCollector:
    def __init__(self, analyzer=None, downloader=None, screenshotter=None):
        cfg = settings.EVIDENCE
        self.analyzer = analyzer or LinkAnalyzer()
        self.downloader = downloader or VideoDownloader(
            cfg["COOKIES_FILE"], cfg["MAX_VIDEO_MB"],
            chromium_executable=cfg["CHROMIUM_EXECUTABLE"], timeout_ms=cfg["SCREENSHOT_TIMEOUT_MS"],
        )
        self.screenshotter = screenshotter or ProfileScreenshotter(
            cfg["CHROMIUM_EXECUTABLE"], cfg["SCREENSHOT_TIMEOUT_MS"],
        )

    def collect_request(self, action_request: ActionRequest) -> None:
        for link in action_request.links.all():
            self.collect(link)

    def collect(self, link: RequestLink) -> RequestLink:
        log: list[str] = []
        link.evidence_status = RequestLink.EvidenceStatus.PROCESSING
        link.save(update_fields=["evidence_status"])

        analysis = self.analyzer.analyze(link.url)
        link.platform = analysis.platform
        link.profile_url = analysis.profile_url or ""
        video_ok: bool | None = None  # None = no video applicable for this link

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)

            # 1) video
            if analysis.is_post:
                video_ok = self._collect_video(link, tmp_dir / "video", log)
            else:
                log.append("الرابط صفحة شخصية/قناة وليس منشوراً - لا يوجد فيديو للتحميل.")

            # 2) profile screenshot (fall back to the link itself)
            target = link.profile_url or link.url
            if not link.profile_url:
                log.append("تعذر تحديد رابط الصفحة الشخصية؛ سيتم تصوير الرابط نفسه.")
            screenshot_ok = self._collect_screenshot(link, target, tmp_dir / "profile.png", log)

        expected = [screenshot_ok] if video_ok is None else [screenshot_ok, video_ok]
        if all(expected):
            link.evidence_status = RequestLink.EvidenceStatus.DONE
        elif any(expected):
            link.evidence_status = RequestLink.EvidenceStatus.PARTIAL
        else:
            link.evidence_status = RequestLink.EvidenceStatus.FAILED
        link.evidence_log = "\n".join(log)
        link.processed_at = timezone.now()
        link.save()
        return link

    # --- steps -----------------------------------------------------------------
    def _collect_video(self, link: RequestLink, dest: Path, log: list[str]) -> bool | None:
        try:
            result = self.downloader.download(link.url, dest)
        except Exception as exc:  # network / extractor / login-wall errors
            logger.exception("video download failed for %s", link.url)
            log.append(f"فشل تحميل الفيديو: {exc}")
            return False
        if not result.is_video:
            link.is_video = False
            log.append("لا يحتوي الرابط على فيديو.")
            return None
        link.is_video = True
        link.video_title = result.title
        if result.uploader_url and not link.profile_url:
            link.profile_url = result.uploader_url
        if not result.file_path:
            log.append("تم التعرف على الفيديو لكن لم يُحفظ أي ملف.")
            return False
        link.video_sha256 = sha256_of(result.file_path)
        with open(result.file_path, "rb") as fh:
            link.video_file.save(result.file_path.name, File(fh), save=False)
        via = "المتصفح" if result.method == "browser" else result.method
        log.append(f"تم تحميل الفيديو عبر {via} ({result.file_path.stat().st_size // 1024} KB) SHA-256={link.video_sha256}")
        return True

    def _collect_screenshot(self, link: RequestLink, url: str, out: Path, log: list[str]) -> bool:
        try:
            self.screenshotter.capture(url, out)
        except Exception as exc:
            logger.exception("screenshot failed for %s", url)
            log.append(f"فشل تصوير الصفحة الشخصية ({url}): {exc}")
            return False
        link.screenshot_sha256 = sha256_of(out)
        stamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        with open(out, "rb") as fh:
            link.profile_screenshot.save(f"profile_{stamp}.png", File(fh), save=False)
        log.append(f"تم تصوير الصفحة الشخصية: {url} SHA-256={link.screenshot_sha256}")
        return True


class EvidenceDispatcher:
    """Runs collection in a background thread (or inline when ASYNC is off)."""

    def __init__(self, collector_factory=EvidenceCollector):
        self.collector_factory = collector_factory

    def dispatch(self, action_request: ActionRequest, links=None) -> None:
        link_ids = [l.pk for l in (links if links is not None else action_request.links.all())]
        if settings.EVIDENCE["ASYNC"]:
            threading.Thread(target=self._run, args=(link_ids,), daemon=True).start()
        else:
            self._run(link_ids, close_connections=False)

    def _run(self, link_ids: list[int], close_connections: bool = True) -> None:
        if close_connections:
            close_old_connections()
        try:
            collector = self.collector_factory()
            for link in RequestLink.objects.filter(pk__in=link_ids):
                try:
                    collector.collect(link)
                except Exception:
                    logger.exception("evidence collection crashed for link %s", link.pk)
                    RequestLink.objects.filter(pk=link.pk).update(
                        evidence_status=RequestLink.EvidenceStatus.FAILED,
                    )
        finally:
            if close_connections:
                close_old_connections()
