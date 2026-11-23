"""Fallback evidence when a platform shows the profile header but refuses to
render the video grid to an automated browser:

1. ProfileVideoLister  – asks yt-dlp for the profile's latest videos (metadata only).
2. VideosSheetRenderer – renders a clearly-labelled sheet: the real header (cropped
   from the authentic screenshot) + the list of videos with thumbnails and links.

The authentic screenshot is never modified; the sheet is stored separately.
"""
from __future__ import annotations

import base64
import html
import io
from datetime import datetime, timezone as dt_tz
from pathlib import Path

from .browser import BrowserLauncher
from .cookies import CookieFile
from .video_downloader import YtDlpStrategy, _SilentLogger


class ProfileVideoLister:
    def __init__(self, cookies_file: str = "", limit: int = 12):
        self.cookies_file = cookies_file
        self.limit = limit

    def list(self, profile_url: str) -> list[dict]:
        import yt_dlp

        opts = {
            "quiet": True, "no_warnings": True, "logger": _SilentLogger(),
            "extract_flat": "in_playlist", "playlistend": self.limit,
            "skip_download": True, "socket_timeout": 30,
        }
        target = YtDlpStrategy._impersonate_target()
        if target is not None:
            opts["impersonate"] = target
        cookie_path = CookieFile(self.cookies_file).as_netscape_path() if self.cookies_file else ""
        if cookie_path:
            opts["cookiefile"] = cookie_path
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(profile_url, download=False) or {}
        entries = [e for e in (info.get("entries") or []) if e][: self.limit]
        return [self._normalize(e) for e in entries]

    @staticmethod
    def _normalize(e: dict) -> dict:
        thumb = e.get("thumbnail") or ""
        if not thumb and e.get("thumbnails"):
            thumb = (e["thumbnails"][-1] or {}).get("url", "")
        ts = e.get("timestamp")
        return {
            "id": str(e.get("id") or ""),
            "url": e.get("url") or e.get("webpage_url") or "",
            "title": (e.get("title") or e.get("description") or "")[:140],
            "thumbnail": thumb,
            "date": datetime.fromtimestamp(ts, dt_tz.utc).strftime("%Y-%m-%d") if ts else "",
            "views": e.get("view_count"),
        }


class VideosSheetRenderer:
    HEADER_HEIGHT = 330

    def __init__(self, executable_path: str = "", cookies_file: str = ""):
        self.launcher = BrowserLauncher(executable_path, cookies_file)

    def render(self, header_screenshot: Path, profile_url: str, videos: list[dict], out: Path) -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        with self.launcher.context({"width": 1366, "height": 900}) as ctx:
            page = ctx.new_page()
            page.set_content(self._html(header_screenshot, profile_url, videos), wait_until="load")
            page.wait_for_timeout(1500)
            page.screenshot(path=str(out), full_page=True)
        return out

    def _header_data_uri(self, path: Path) -> str:
        from PIL import Image

        with Image.open(path) as img:
            crop = img.crop((0, 0, img.width, min(self.HEADER_HEIGHT, img.height)))
            buf = io.BytesIO()
            crop.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    def _html(self, header: Path, profile_url: str, videos: list[dict]) -> str:
        e = html.escape
        now = datetime.now(dt_tz.utc).strftime("%Y-%m-%d %H:%M UTC")
        cards = "".join(
            f'<div class="card">'
            f'{f"<img src={chr(34)}{e(v["thumbnail"])}{chr(34)} referrerpolicy=no-referrer>" if v["thumbnail"] else "<div class=noimg>—</div>"}'
            f'<div class="meta"><div class="t">{e(v["title"]) or "&nbsp;"}</div>'
            f'<div class="u">{e(v["url"])}</div>'
            f'<div class="d">{e(v["date"])}{f" · {v["views"]:,} مشاهدة" if v.get("views") else ""}</div></div></div>'
            for v in videos
        ) or '<p class="empty">لم تُرجع المنصة أي فيديو.</p>'
        return f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><style>
 body{{margin:0;background:#fff;color:#111;font-family:"Segoe UI",Tahoma,Arial,sans-serif}}
 .banner{{background:#0f4c5c;color:#fff;padding:12px 20px;font-size:15px}}
 .banner b{{font-size:17px}} .ltr{{direction:ltr;unicode-bidi:embed}}
 .header img{{width:100%;display:block;border-bottom:3px solid #0f4c5c}}
 .grid{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;padding:16px}}
 .card{{border:1px solid #ddd;border-radius:6px;overflow:hidden;font-size:12px}}
 .card img,.noimg{{width:100%;aspect-ratio:3/4;object-fit:cover;background:#eee;display:block}}
 .noimg{{display:flex;align-items:center;justify-content:center;color:#999}}
 .meta{{padding:6px}} .t{{font-weight:600;max-height:3.2em;overflow:hidden}}
 .u{{direction:ltr;color:#0f4c5c;word-break:break-all;font-size:10px;margin-top:4px}}
 .d{{color:#666;margin-top:2px}} .empty{{padding:20px}}
</style></head><body>
<div class="banner"><b>قائمة فيديوهات الحساب — مستخرجة آلياً</b><br>
 لم تعرض المنصة شبكة الفيديوهات في لقطة الشاشة، فاستُخرجت القائمة من بيانات المنصة عبر yt-dlp.
 هذه الصورة مُولَّدة وليست لقطة شاشة مباشرة. الجزء العلوي مقتطع من لقطة الشاشة الأصلية.<br>
 <span class="ltr">{e(profile_url)}</span> · {now} · عدد الفيديوهات: {len(videos)}</div>
<div class="header"><img src="{self._header_data_uri(header)}"></div>
<div class="grid">{cards}</div></body></html>"""
