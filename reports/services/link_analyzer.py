"""Classifies a social-media URL: which platform, whether it points at a single
post/video, and what the owner's profile page URL is."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from ..models import Platform


@dataclass(frozen=True)
class LinkAnalysis:
    url: str
    platform: str
    is_post: bool          # points to a single post/video (candidate for download)
    profile_url: str       # best guess of the owner's profile page ("" if unknown)


class LinkAnalyzer:
    """Strategy table: one rule set per platform."""

    HOSTS = {
        Platform.TIKTOK: ("tiktok.com",),
        Platform.FACEBOOK: ("facebook.com", "fb.watch", "fb.com"),
        Platform.TELEGRAM: ("t.me", "telegram.me", "telegram.org"),
        Platform.INSTAGRAM: ("instagram.com",),
        Platform.X: ("x.com", "twitter.com"),
    }

    def analyze(self, url: str) -> LinkAnalysis:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower()
        platform = self.detect_platform(host)
        parts = [p for p in parsed.path.split("/") if p]
        handler = getattr(self, f"_analyze_{platform}", self._analyze_other)
        is_post, profile = handler(host, parts, parsed)
        return LinkAnalysis(url=url, platform=platform, is_post=is_post, profile_url=profile)

    def detect_platform(self, host: str) -> str:
        for platform, domains in self.HOSTS.items():
            if any(host == d or host.endswith("." + d) for d in domains):
                return platform.value
        return Platform.OTHER.value

    # --- per-platform rules -------------------------------------------------
    @staticmethod
    def _analyze_tiktok(host, parts, parsed):
        if host.startswith(("vm.", "vt.")) or (parts and parts[0] == "t"):
            return True, ""  # short link: profile resolved later from video metadata
        if parts and parts[0].startswith("@"):
            profile = f"https://www.tiktok.com/{parts[0]}"
            return (len(parts) >= 3 and parts[1] in ("video", "photo")), profile
        return False, ""

    @staticmethod
    def _analyze_instagram(host, parts, parsed):
        if parts and parts[0] in ("reel", "reels", "p", "tv"):
            return True, ""
        if len(parts) >= 3 and parts[1] in ("reel", "p", "tv"):
            return True, f"https://www.instagram.com/{parts[0]}/"
        if parts and parts[0] not in ("stories", "explore"):
            return False, f"https://www.instagram.com/{parts[0]}/"
        return False, ""

    @staticmethod
    def _analyze_facebook(host, parts, parsed):
        if host == "fb.watch" or (parts and parts[0] in ("watch", "reel", "share")):
            return True, ""
        if len(parts) >= 2 and parts[1] in ("videos", "reels", "posts"):
            return parts[1] != "posts", f"https://www.facebook.com/{parts[0]}"
        if parts and parts[0] == "profile.php":
            return False, parsed.geturl()
        if parts:
            return False, f"https://www.facebook.com/{parts[0]}"
        return False, ""

    @staticmethod
    def _analyze_x(host, parts, parsed):
        if len(parts) >= 3 and parts[1] == "status":
            return True, f"https://x.com/{parts[0]}"
        if parts and parts[0] not in ("i", "home", "search"):
            return False, f"https://x.com/{parts[0]}"
        return False, ""

    @staticmethod
    def _analyze_telegram(host, parts, parsed):
        if parts and parts[0] == "s":
            parts = parts[1:]
        if not parts:
            return False, ""
        channel = parts[0]
        is_post = len(parts) >= 2 and re.fullmatch(r"\d+", parts[1]) is not None
        return is_post, f"https://t.me/s/{channel}"

    @staticmethod
    def _analyze_other(host, parts, parsed):
        return True, ""  # unknown site: let yt-dlp decide whether it is a video
