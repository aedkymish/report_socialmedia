"""Takes a screenshot of a profile page with headless Chromium (Playwright).

Before the shot, a platform-specific PageCleaner closes pop-ups that cover the
profile (TikTok's verification dialog, login walls, cookie banners) using their
own close buttons, and waits for the profile content to render. CAPTCHAs are
never solved — only dismissed when the site offers a close button; if one is
still showing, it is reported in the evidence log.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .browser import SESSION_COOKIES, BrowserLauncher, has_session_cookie, load_netscape_cookies


@dataclass
class ScreenshotResult:
    path: Path
    notes: list[str] = field(default_factory=list)


class PageCleaner:
    """Generic rules; subclasses add platform-specific selectors."""

    CLOSE_SELECTORS: list[str] = [
        'div[role="dialog"] [aria-label="Close"]',
        'div[role="dialog"] [aria-label="إغلاق"]',
        'button[aria-label="Close"]',
    ]
    CAPTCHA_SELECTORS: list[str] = [
        'iframe[src*="captcha"]', '[id*="captcha" i]', '[class*="captcha" i]',
    ]
    CONTENT_SELECTOR: str | None = None
    LOGIN_BUTTON_SELECTORS: list[str] = []

    def looks_logged_out(self, page) -> bool:
        return self._visible(page, self.LOGIN_BUTTON_SELECTORS)

    def clean(self, page) -> list[str]:
        notes = []
        had_captcha = self._visible(page, self.CAPTCHA_SELECTORS)
        for _ in range(3):  # dialogs can stack (captcha, then login)
            if not self._click_first(page, self.CLOSE_SELECTORS):
                break
            page.wait_for_timeout(1200)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        self._wait_for_content(page)
        notes.extend(self._retry_failed_content(page))
        # Pressing "Refresh" can trigger a new verification dialog: close it again.
        for _ in range(2):
            if not self._click_first(page, self.CLOSE_SELECTORS):
                break
            page.wait_for_timeout(1500)

        if self._visible(page, self.CAPTCHA_SELECTORS):
            notes.append(
                "تنبيه: ظهر تحقق CAPTCHA من المنصة ولم يُغلق؛ قد تكون الصورة غير مكتملة. "
                "الحل: إضافة ملف cookies لحساب رسمي (YTDLP_COOKIES_FILE)."
            )
        elif had_captcha:
            notes.append("ظهر تحقق CAPTCHA من المنصة وتم إغلاقه قبل التصوير.")
        return notes

    # Some sites render the header but fail the content request and show an
    # in-page "Something went wrong / Refresh" state. Press their own button.
    RETRY_BUTTON: re.Pattern | None = None
    RETRY_SUCCESS_SELECTOR: str | None = None
    RETRY_ATTEMPTS = 3
    RETRY_FAILED_NOTE = ""

    def _retry_failed_content(self, page) -> list[str]:
        if not self.RETRY_BUTTON:
            return []
        retried = 0
        for _ in range(self.RETRY_ATTEMPTS):
            button = page.get_by_role("button", name=self.RETRY_BUTTON).first
            try:
                if not (button.count() and button.is_visible()):
                    break
                button.click(timeout=3000)
            except Exception:
                break
            retried += 1
            try:
                page.wait_for_selector(self.RETRY_SUCCESS_SELECTOR, state="visible", timeout=8000)
                page.wait_for_timeout(1500)  # let thumbnails paint
                return [f"تعذر تحميل المحتوى أولاً، ونجح بعد إعادة المحاولة ({retried})."]
            except Exception:
                page.wait_for_timeout(2000)
        if retried:
            return [self.RETRY_FAILED_NOTE]
        return []

    def _wait_for_content(self, page) -> None:
        if self.CONTENT_SELECTOR:
            try:
                page.wait_for_selector(self.CONTENT_SELECTOR, state="visible", timeout=8000)
            except Exception:
                pass
        page.wait_for_timeout(1500)

    @staticmethod
    def _click_first(page, selectors: list[str]) -> bool:
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible():
                    loc.click(timeout=2000)
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _visible(page, selectors: list[str]) -> bool:
        for sel in selectors:
            try:
                loc = page.locator(sel)
                for i in range(min(loc.count(), 5)):
                    if loc.nth(i).is_visible():
                        return True
            except Exception:
                continue
        return False


class TikTokCleaner(PageCleaner):
    CLOSE_SELECTORS = [
        "#captcha_close_button",
        '[id*="captcha" i] [aria-label="Close"]',
        '[class*="captcha" i] [aria-label="Close"]',
        '[class*="captcha" i] [class*="close" i]',
        '[id*="captcha" i] button:has(svg)',
        '[data-e2e="modal-close-inner-button"]',
        '[data-e2e="modal-close-button"]',
        *PageCleaner.CLOSE_SELECTORS,
    ]
    CONTENT_SELECTOR = '[data-e2e="user-post-item"] img, [data-e2e="user-title"]'
    LOGIN_BUTTON_SELECTORS = ['[data-e2e="nav-login-button"]', '[data-e2e="top-login-button"]',
                              'button:has-text("تسجيل الدخول")', 'button:has-text("Log in")']
    RETRY_BUTTON = re.compile(r"^\s*(تحديث|Refresh|Retry|Try again)\s*$", re.I)
    RETRY_SUCCESS_SELECTOR = '[data-e2e="user-post-item"]'
    RETRY_FAILED_NOTE = (
        "تنبيه: بيانات الحساب ظاهرة في الصورة، لكن تيك توك رفض تحميل قائمة الفيديوهات "
        "(حدث خطأ ما) رغم إعادة المحاولة. الحل: إضافة ملف cookies لحساب رسمي (YTDLP_COOKIES_FILE)."
    )


class InstagramCleaner(PageCleaner):
    CLOSE_SELECTORS = [
        'div[role="dialog"] svg[aria-label="Close"]',
        'div[role="dialog"] svg[aria-label="إغلاق"]',
        *PageCleaner.CLOSE_SELECTORS,
    ]
    CONTENT_SELECTOR = "header section"


class FacebookCleaner(PageCleaner):
    CLOSE_SELECTORS = ['div[aria-label="Close"][role="button"]', 'div[aria-label="إغلاق"][role="button"]',
                       *PageCleaner.CLOSE_SELECTORS]


class XCleaner(PageCleaner):
    CLOSE_SELECTORS = ['[data-testid="app-bar-close"]', '[data-testid="xMigrationBottomBar"] button',
                       *PageCleaner.CLOSE_SELECTORS]
    CONTENT_SELECTOR = '[data-testid="UserName"]'


CLEANERS = {
    "tiktok.com": TikTokCleaner,
    "instagram.com": InstagramCleaner,
    "facebook.com": FacebookCleaner,
    "x.com": XCleaner,
    "twitter.com": XCleaner,
}


def cleaner_for(url: str) -> PageCleaner:
    host = (urlparse(url).hostname or "").lower()
    for domain, cls in CLEANERS.items():
        if host == domain or host.endswith("." + domain):
            return cls()
    return PageCleaner()


class ProfileScreenshotter:
    VIEWPORT = {"width": 1366, "height": 1600}

    def __init__(self, executable_path: str = "", timeout_ms: int = 45000, cookies_file: str = ""):
        self.launcher = BrowserLauncher(executable_path, cookies_file)
        self.cookies_file = cookies_file
        self.timeout_ms = timeout_ms

    def _cookie_notes(self, url: str) -> list[str]:
        host = (urlparse(url).hostname or "").lower()
        site = next((d for d in SESSION_COOKIES if host == d or host.endswith("." + d)), None)
        if not site:
            return []
        if not self.cookies_file:
            return [f"لم يُضبط ملف cookies؛ المتصفح يزور {site} كزائر غير مسجّل."]
        cookies = load_netscape_cookies(self.cookies_file)
        if not cookies:
            return [f"ملف cookies ({self.cookies_file}) غير موجود أو فارغ أو بصيغة غير صحيحة."]
        if has_session_cookie(cookies, site) is False:
            return [f"ملف cookies لا يحتوي جلسة دخول لـ {site} (الكوكي {SESSION_COOKIES[site]} مفقود). "
                    "صدّره مرة أخرى وأنت مسجّل الدخول وعلى صفحة الموقع نفسه."]
        return []

    def capture(self, url: str, out_file: Path) -> ScreenshotResult:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with self.launcher.context(self.VIEWPORT) as ctx:
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass  # social sites keep long-polling; a loaded DOM is enough
            page.wait_for_timeout(2000)
            cleaner = cleaner_for(page.url)
            notes = self._cookie_notes(page.url) + cleaner.clean(page)
            if cleaner.looks_logged_out(page):
                notes.append("المتصفح غير مسجّل الدخول في المنصة (زر تسجيل الدخول ظاهر).")
            page.screenshot(path=str(out_file), full_page=False)
        return ScreenshotResult(out_file, notes)
