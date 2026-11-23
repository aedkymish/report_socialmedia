"""Video download with a chain of strategies:

1. YtDlpStrategy        – yt-dlp, impersonating a real browser's TLS fingerprint
                           (curl_cffi) when available. Handles most platforms.
2. BrowserVideoCapture  – fallback: opens the post in headless Chromium, reads the
                           real video URL from the page data / network traffic and
                           downloads it with the browser's own cookies. Survives
                           most "Unexpected response from webpage" blocks.
"""
from __future__ import annotations

import json
import logging
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .browser import BrowserLauncher
from .cookies import CookieFile

logger = logging.getLogger(__name__)


@dataclass
class VideoResult:
    is_video: bool
    file_path: Path | None = None
    title: str = ""
    uploader_url: str = ""
    info: dict = field(default_factory=dict)
    method: str = ""


class NoVideoError(Exception):
    """The URL was fetched fine but contains no video (image post, profile, text)."""


class VideoStrategy(ABC):
    name = "base"

    @abstractmethod
    def download(self, url: str, dest_dir: Path) -> VideoResult:
        """Return a VideoResult with a file, raise NoVideoError, or raise on failure."""


# --------------------------------------------------------------------------- yt-dlp
class _SilentLogger:
    """Errors are surfaced through exceptions / the evidence log instead of stderr."""

    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


class YtDlpStrategy(VideoStrategy):
    name = "yt-dlp"

    def __init__(self, cookies_file: str = "", max_mb: int = 500):
        self.cookies_file = cookies_file
        self.max_mb = max_mb

    def _options(self, dest_dir: Path) -> dict:
        has_ffmpeg = shutil.which("ffmpeg") is not None
        opts = {
            "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "max_filesize": self.max_mb * 1024 * 1024,
            "format": "bv*+ba/b" if has_ffmpeg else "b",
            "socket_timeout": 30,
            "retries": 3,
            "logger": _SilentLogger(),
        }
        if has_ffmpeg:
            opts["merge_output_format"] = "mp4"
        cookie_path = CookieFile(self.cookies_file).as_netscape_path() if self.cookies_file else ""
        if cookie_path:
            opts["cookiefile"] = cookie_path  # JSON exports are converted on the fly
        target = self._impersonate_target()
        if target is not None:
            opts["impersonate"] = target
        return opts

    @staticmethod
    def _impersonate_target():
        """Chrome TLS fingerprint via curl_cffi – the usual fix for TikTok blocks."""
        try:
            import curl_cffi  # noqa: F401
            from yt_dlp.networking.impersonate import ImpersonateTarget
        except ImportError:
            return None
        return ImpersonateTarget("chrome")

    def download(self, url: str, dest_dir: Path) -> VideoResult:
        import yt_dlp

        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            with yt_dlp.YoutubeDL(self._options(dest_dir)) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info or info.get("_type") == "playlist" or not self._has_video(info):
                    raise NoVideoError()
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as exc:
            if self._is_no_video_error(str(exc)):
                raise NoVideoError() from exc
            raise

        files = [p for p in dest_dir.iterdir() if p.is_file() and not p.name.endswith(".part")]
        if not files:
            raise RuntimeError("yt-dlp لم يحفظ أي ملف")
        return VideoResult(
            is_video=True,
            file_path=max(files, key=lambda p: p.stat().st_size),
            title=(info.get("title") or "")[:500],
            uploader_url=self._uploader_url(info),
            info=info,
            method=self.name,
        )

    @staticmethod
    def _has_video(info: dict) -> bool:
        """True if any format carries a video stream (audio-only/image posts are not videos)."""
        for f in [info, *(info.get("formats") or [])]:
            vcodec = f.get("vcodec")
            if vcodec not in (None, "none"):
                return True
            if vcodec is None and f.get("video_ext") not in (None, "none"):
                return True  # direct file links: codec unknown, container is a video
        return bool(info.get("duration")) and info.get("vcodec") != "none"

    @staticmethod
    def _is_no_video_error(msg: str) -> bool:
        msg = msg.lower()
        return any(k in msg for k in ("no video", "unsupported url", "there is no video", "no media"))

    @staticmethod
    def _uploader_url(info: dict) -> str:
        for key in ("uploader_url", "channel_url"):
            if info.get(key):
                return info[key]
        extractor = (info.get("extractor_key") or "").lower()
        handle = info.get("uploader_id") or info.get("channel_id") or info.get("uploader")
        if not handle:
            return ""
        if "tiktok" in extractor:
            return f"https://www.tiktok.com/@{handle}"
        if "instagram" in extractor:
            return f"https://www.instagram.com/{handle}/"
        if "twitter" in extractor:
            return f"https://x.com/{handle}"
        return ""


# --------------------------------------------------------------- headless browser
class BrowserVideoCapture(VideoStrategy):
    name = "browser"
    VIEWPORT = {"width": 1280, "height": 900}

    def __init__(self, executable_path: str = "", max_mb: int = 500, timeout_ms: int = 45000,
                 cookies_file: str = ""):
        self.launcher = BrowserLauncher(executable_path, cookies_file)
        self.max_bytes = max_mb * 1024 * 1024
        self.timeout_ms = timeout_ms

    def download(self, url: str, dest_dir: Path) -> VideoResult:
        dest_dir.mkdir(parents=True, exist_ok=True)
        with self.launcher.context(self.VIEWPORT) as ctx:
            page = ctx.new_page()
            seen: list[str] = []
            page.on("response", lambda r: self._is_video_response(r) and seen.append(r.url))

            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            meta = self._page_metadata(page)
            self._nudge_playback(page)

            candidates = [*meta.pop("video_urls", []), *self._dom_video_srcs(page), *seen]
            candidates = list(dict.fromkeys(c for c in candidates if c.startswith("http")))
            if not candidates:
                raise RuntimeError("لم يُعثر على رابط فيديو في الصفحة (قد تتطلب تسجيل دخول)")

            last_error = None
            for video_url in candidates:
                try:
                    path = self._fetch(ctx, video_url, page.url, dest_dir)
                    return VideoResult(
                        is_video=True, file_path=path, method=self.name,
                        title=meta.get("title", "")[:500], uploader_url=meta.get("uploader_url", ""),
                    )
                except Exception as exc:  # try the next candidate
                    last_error = exc
            raise RuntimeError(f"تعذر تنزيل الفيديو من المتصفح: {last_error}")

    # -- helpers --------------------------------------------------------------
    @staticmethod
    def _is_video_response(response) -> bool:
        ctype = (response.headers.get("content-type") or "").lower()
        return ctype.startswith("video/") or "mime_type=video_mp4" in response.url

    def _nudge_playback(self, page) -> None:
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        try:
            page.evaluate("() => document.querySelectorAll('video').forEach(v => { v.muted = true; v.play().catch(()=>{}); })")
        except Exception:
            pass
        page.wait_for_timeout(3000)

    @staticmethod
    def _dom_video_srcs(page) -> list[str]:
        try:
            return page.evaluate(
                "() => [...document.querySelectorAll('video, video source')]"
                ".map(v => v.currentSrc || v.src).filter(Boolean)"
            )
        except Exception:
            return []

    def _page_metadata(self, page) -> dict:
        """Platform-specific embedded JSON (TikTok) + OpenGraph tags."""
        meta: dict = {"video_urls": []}
        try:
            raw = page.evaluate(
                "() => document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__')?.textContent || ''"
            )
            if raw:
                meta.update(self._parse_tiktok(json.loads(raw)))
        except Exception:
            logger.debug("no tiktok rehydration data", exc_info=True)
        try:
            og = page.evaluate(
                "() => Object.fromEntries([...document.querySelectorAll('meta[property^=\"og:\"]')]"
                ".map(m => [m.getAttribute('property'), m.content]))"
            )
            for key in ("og:video:secure_url", "og:video:url", "og:video"):
                if og.get(key):
                    meta["video_urls"].append(og[key])
            meta.setdefault("title", og.get("og:title", ""))
        except Exception:
            pass
        return meta

    @staticmethod
    def _parse_tiktok(data: dict) -> dict:
        item = (
            data.get("__DEFAULT_SCOPE__", {})
            .get("webapp.video-detail", {})
            .get("itemInfo", {})
            .get("itemStruct", {})
        )
        if not item:
            return {}
        video = item.get("video") or {}
        urls = [video.get("playAddr"), video.get("downloadAddr")]
        for br in video.get("bitrateInfo") or []:
            urls.extend((br.get("PlayAddr") or {}).get("UrlList") or [])
        unique_id = (item.get("author") or {}).get("uniqueId")
        return {
            "video_urls": [u for u in urls if u],
            "title": item.get("desc", ""),
            "uploader_url": f"https://www.tiktok.com/@{unique_id}" if unique_id else "",
        }

    def _fetch(self, ctx, video_url: str, referer: str, dest_dir: Path) -> Path:
        resp = ctx.request.get(
            video_url, headers={"Referer": referer, "Range": "bytes=0-"}, timeout=self.timeout_ms * 3,
        )
        if resp.status not in (200, 206):
            raise RuntimeError(f"HTTP {resp.status}")
        ctype = (resp.headers.get("content-type") or "").lower()
        if ctype and not (ctype.startswith("video/") or "octet-stream" in ctype):
            raise RuntimeError(f"ليس ملف فيديو ({ctype})")
        body = resp.body()
        if len(body) > self.max_bytes:
            raise RuntimeError("حجم الفيديو أكبر من الحد المسموح")
        if len(body) < 10 * 1024:
            raise RuntimeError("الملف صغير جداً ليكون فيديو")
        ext = Path(urlparse(video_url).path).suffix.lower()
        path = dest_dir / f"video{ext if ext in ('.mp4', '.webm', '.mov', '.m4v') else '.mp4'}"
        path.write_bytes(body)
        return path


# ------------------------------------------------------------------- the façade
class VideoDownloader:
    """Tries each strategy in order; the first one that yields a file wins."""

    def __init__(self, cookies_file: str = "", max_mb: int = 500, strategies=None,
                 chromium_executable: str = "", timeout_ms: int = 45000, browser_cookies_file: str = ""):
        self.strategies: list[VideoStrategy] = strategies or [
            YtDlpStrategy(cookies_file, max_mb),
            BrowserVideoCapture(chromium_executable, max_mb, timeout_ms, browser_cookies_file or cookies_file),
        ]

    def download(self, url: str, dest_dir: Path) -> VideoResult:
        errors: list[str] = []
        for strategy in self.strategies:
            work_dir = dest_dir / strategy.name
            try:
                return strategy.download(url, work_dir)
            except NoVideoError:
                return VideoResult(is_video=False, method=strategy.name)
            except Exception as exc:
                logger.warning("%s failed for %s: %s", strategy.name, url, exc)
                errors.append(f"[{strategy.name}] {self._short(exc)}")
                shutil.rmtree(work_dir, ignore_errors=True)
        raise RuntimeError(" | ".join(errors))

    @staticmethod
    def _short(exc: Exception) -> str:
        msg = str(exc).split("; please report this issue")[0]
        return msg.replace("ERROR: ", "").strip()[:300]
