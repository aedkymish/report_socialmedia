"""HTML -> PDF with the headless Chromium already used for screenshots.
Chromium shapes Arabic and lays out RTL correctly; fonts are embedded so the
output does not depend on the fonts installed in the container."""
from __future__ import annotations

import base64
import logging
from functools import lru_cache
from pathlib import Path

from .browser import BrowserLauncher

logger = logging.getLogger(__name__)

FONTS_DIR = Path(__file__).resolve().parent.parent / "static" / "reports" / "fonts"
FONT_FILES = [
    # (file, weight, unicode-range)
    ("noto-sans-arabic-arabic-400-normal.woff2", 400,
     "U+0600-06FF, U+0750-077F, U+0870-089F, U+08A0-08FF, U+200C-200E, U+2010-2011, U+204F, U+2E41, U+FB50-FDFF, U+FE70-FEFC"),
    ("noto-sans-arabic-arabic-700-normal.woff2", 700,
     "U+0600-06FF, U+0750-077F, U+0870-089F, U+08A0-08FF, U+200C-200E, U+2010-2011, U+204F, U+2E41, U+FB50-FDFF, U+FE70-FEFC"),
    ("noto-sans-latin-400-normal.woff2", 400, "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215"),
    ("noto-sans-latin-700-normal.woff2", 700, "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215"),
]


@lru_cache(maxsize=1)
def embedded_font_css(family: str = "ReportSans") -> str:
    rules = []
    for name, weight, urange in FONT_FILES:
        data = base64.b64encode((FONTS_DIR / name).read_bytes()).decode()
        rules.append(
            f"@font-face{{font-family:'{family}';font-style:normal;font-weight:{weight};"
            f"src:url(data:font/woff2;base64,{data}) format('woff2');unicode-range:{urange};}}"
        )
    return "\n".join(rules)


class PdfRenderer:
    FOOTER = (
        '<div style="width:100%;font-size:8px;color:#666;padding:0 12mm;display:flex;'
        'justify-content:space-between;font-family:sans-serif;">'
        '<span>{label}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>'
    )

    def __init__(self, executable_path: str = "", timeout_ms: int = 60000):
        self.launcher = BrowserLauncher(executable_path)
        self.timeout_ms = timeout_ms

    def render(self, html: str, footer_label: str = "") -> bytes:
        with self.launcher.context({"width": 1240, "height": 1754}) as ctx:
            page = ctx.new_page()
            page.set_content(html, wait_until="load", timeout=self.timeout_ms)
            page.evaluate("() => document.fonts.ready.then(() => true)")
            page.emulate_media(media="print")
            return page.pdf(
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
                display_header_footer=True,
                header_template="<div></div>",
                footer_template=self.FOOTER.format(label=footer_label),
                margin={"top": "14mm", "bottom": "16mm", "left": "12mm", "right": "12mm"},
            )


LOGO_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".svg": "image/svg+xml", ".webp": "image/webp", ".gif": "image/gif"}
LOGO_MAX_BYTES = 2 * 1024 * 1024


def resolve_report_logo() -> tuple[Path, str] | None:
    """(path, mime) of REPORT_LOGO_PATH if it is usable, else None (with a warning).
    Read on every call so replacing the file needs no restart."""
    from django.conf import settings

    configured = settings.REPORT.get("LOGO_PATH", "").strip()
    if not configured:
        return None
    path = Path(configured)
    if not path.is_absolute():
        path = Path(settings.BASE_DIR) / path
    mime = LOGO_TYPES.get(path.suffix.lower())
    if not path.is_file():
        logger.warning("REPORT_LOGO_PATH not found: %s", path)
        return None
    if not mime:
        logger.warning("REPORT_LOGO_PATH has an unsupported type: %s", path.suffix)
        return None
    if path.stat().st_size > LOGO_MAX_BYTES:
        logger.warning("REPORT_LOGO_PATH is larger than 2 MB: %s", path)
        return None
    return path, mime


def report_logo_data_uri() -> str:
    """REPORT_LOGO_PATH as an embeddable data URI (for the PDF), or ""."""
    logo = resolve_report_logo()
    if not logo:
        return ""
    path, mime = logo
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"
