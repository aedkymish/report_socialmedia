"""Downloads a video with yt-dlp and reports its metadata."""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class VideoResult:
    is_video: bool
    file_path: Path | None = None
    title: str = ""
    uploader_url: str = ""
    info: dict = field(default_factory=dict)


class _SilentLogger:
    """Errors are surfaced through exceptions / the evidence log instead of stderr."""

    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


class VideoDownloader:
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
            "logger": _SilentLogger(),
            "retries": 3,
        }
        if has_ffmpeg:
            opts["merge_output_format"] = "mp4"
        if self.cookies_file:
            opts["cookiefile"] = self.cookies_file
        return opts

    def download(self, url: str, dest_dir: Path) -> VideoResult:
        """Return VideoResult(is_video=False) when the URL holds no video.
        Raises on network/extractor errors that are not "no video here"."""
        import yt_dlp  # imported lazily so the web app starts without it

        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            with yt_dlp.YoutubeDL(self._options(dest_dir)) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info or info.get("_type") == "playlist" or not self._has_video(info):
                    return VideoResult(is_video=False, info=info or {})
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as exc:
            if self._is_no_video_error(str(exc)):
                return VideoResult(is_video=False)
            raise

        files = sorted(p for p in dest_dir.iterdir() if p.is_file() and not p.name.endswith(".part"))
        return VideoResult(
            is_video=True,
            file_path=max(files, key=lambda p: p.stat().st_size) if files else None,
            title=(info.get("title") or "")[:500],
            uploader_url=self._uploader_url(info),
            info=info,
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
