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

from .browser import SESSION_COOKIES, BrowserLauncher, has_session_cookie
from .cookies import CookieFile


@dataclass
class ScreenshotResult:
    path: Path
    notes: list[str] = field(default_factory=list)
    content_ready: bool = True   # False when the platform never rendered the post grid
    logged_out: bool = False


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
    # JS predicate returning true once the page has *really* rendered (not just
    # its skeleton placeholders). None = only wait for CONTENT_SELECTOR.
    READY_JS: str | None = None
    ERROR_JS: str | None = None
    READY_TIMEOUT_MS = 25000
    NOT_READY_NOTE = "تنبيه: انتهت مهلة انتظار تحميل محتوى الصفحة؛ قد تظهر أجزاء غير مكتملة في الصورة."

    def looks_logged_out(self, page) -> bool:
        return self._visible(page, self.LOGIN_BUTTON_SELECTORS)

    content_ready: bool = True

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
        ready = self._wait_until_ready(page)
        retry_notes = self._retry_failed_content(page)
        notes.extend(retry_notes)
        # Pressing "Refresh" can trigger a new verification dialog: close it again.
        for _ in range(2):
            if not self._click_first(page, self.CLOSE_SELECTORS):
                break
            page.wait_for_timeout(1500)
        if retry_notes:
            ready = self._wait_until_ready(page)
        self.content_ready = ready
        if not ready:
            notes.append(self.refused_reason() or self.NOT_READY_NOTE)

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
                page.wait_for_selector(self.RETRY_SUCCESS_SELECTOR, state="visible", timeout=6000)
                page.wait_for_timeout(1500)  # let thumbnails paint
                return [f"تعذر تحميل المحتوى أولاً، ونجح بعد إعادة المحاولة ({retried})."]
            except Exception:
                page.wait_for_timeout(2000)
        if retried:
            return [self.RETRY_FAILED_NOTE]
        return []

    def observe(self, page) -> None:
        """Called before navigation, to watch the platform's own network traffic."""

    def refused_reason(self) -> str:
        """Non-empty when the platform definitively refused the content (stop waiting)."""
        return ""

    def _is_ready(self, page) -> bool:
        try:
            return bool(page.evaluate(self.READY_JS))
        except Exception:
            return False

    def _shows_error(self, page) -> bool:
        if not self.ERROR_JS:
            return False
        try:
            return bool(page.evaluate(self.ERROR_JS))
        except Exception:
            return False

    def _wait_until_ready(self, page) -> bool:
        if not self.READY_JS:
            return True
        waited, step, refused_for = 0, 500, 0
        while waited < self.READY_TIMEOUT_MS:
            if self._is_ready(page):
                page.wait_for_timeout(1000)  # let the last thumbnails paint
                return True
            if self.refused_reason() or self._shows_error(page):
                refused_for += step
                if refused_for >= 5000:  # grace period: the site may retry by itself
                    return False
            if waited == 3000:
                self._nudge_lazy_loading(page)
            page.wait_for_timeout(step)
            waited += step
        return self._is_ready(page)

    @staticmethod
    def _nudge_lazy_loading(page) -> None:
        """Scroll a little and back so lazily-loaded thumbnails start loading."""
        try:
            page.mouse.wheel(0, 600)
            page.wait_for_timeout(700)
            page.mouse.wheel(0, -600)
        except Exception:
            pass

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
    CONTENT_SELECTOR = '[data-e2e="user-title"]'
    # Ready when the video thumbnails have actually loaded, or the page settled
    # into a definite state (no videos / private / error -> handled by retry).
    READY_JS = r"""() => {
        const imgs = [...document.querySelectorAll('[data-e2e="user-post-item"] img')];
        const loaded = imgs.filter(i => i.complete && i.naturalWidth > 0).length;
        if (imgs.length && loaded >= Math.min(6, imgs.length)) return true;
        const t = document.body ? document.body.innerText : "";
        return /لا يوجد محتوى|لا توجد مقاطع|No content|This account is private|هذا الحساب خاص|حساب خاص/i.test(t);
    }"""
    # In-page failure ("Something went wrong" + Refresh): stop waiting so the
    # retry step runs; it never counts as ready.
    ERROR_JS = r"""() => {
        if (document.querySelector('[data-e2e="user-post-item"] img')) return false;
        const t = document.body ? document.body.innerText : "";
        return /حدث خطأ ما|Something went wrong/i.test(t);
    }"""
    NOT_READY_NOTE = ("تنبيه: لم تكتمل صور الفيديوهات في صفحة تيك توك خلال المهلة؛ "
                      "بيانات الحساب ظاهرة لكن قد تظهر مربعات فارغة مكان الفيديوهات.")
    LOGIN_BUTTON_SELECTORS = ['[data-e2e="nav-login-button"]', '[data-e2e="top-login-button"]',
                              'button:has-text("تسجيل الدخول")', 'button:has-text("Log in")']
    RETRY_BUTTON = re.compile(r"^\s*(تحديث|Refresh|Retry|Try again)\s*$", re.I)
    RETRY_SUCCESS_SELECTOR = '[data-e2e="user-post-item"]'
    RETRY_FAILED_NOTE = (
        "تنبيه: بيانات الحساب ظاهرة في الصورة، لكن تيك توك رفض تحميل قائمة الفيديوهات "
        "(حدث خطأ ما) رغم إعادة المحاولة. الحل: إضافة ملف cookies لحساب رسمي (YTDLP_COOKIES_FILE)."
    )


    ITEM_LIST_PATH = "/api/post/item_list"

    def __init__(self):
        self._item_list_responses = []

    def observe(self, page) -> None:
        # Only store the response objects here; bodies are read later from the
        # polling loop (blocking calls inside event handlers are unsafe).
        page.on("response", lambda r: self.ITEM_LIST_PATH in r.url and self._item_list_responses.append(r))

    def refused_reason(self) -> str:
        if not self._item_list_responses:
            return ""
        for resp in self._item_list_responses:
            try:
                body = resp.body()
            except Exception:
                continue
            if resp.status == 200 and len(body) > 2:
                return ""  # at least one real answer: keep waiting for thumbnails
        return ("تيك توك رفض إرسال قائمة الفيديوهات لهذا المتصفح (رد فارغ على طلب item_list) — "
                "الانتظار لا يغيّر النتيجة. السبب: المتصفح غير مسجّل الدخول (أضف cookies بجلسة دخول صالحة). "
                "تم إنشاء صورة قائمة الفيديوهات بديلاً.")


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

    def __init__(self, executable_path: str = "", timeout_ms: int = 45000, cookies_file: str = "",
                 content_wait_seconds: int = 30):
        self.launcher = BrowserLauncher(executable_path, cookies_file)
        self.cookies_file = cookies_file
        self.timeout_ms = timeout_ms
        self.content_wait_ms = max(5, content_wait_seconds) * 1000

    def _cookie_notes(self, url: str) -> list[str]:
        host = (urlparse(url).hostname or "").lower()
        site = next((d for d in SESSION_COOKIES if host == d or host.endswith("." + d)), None)
        if not site:
            return []
        if not self.cookies_file:
            return [f"لم يُضبط ملف cookies؛ المتصفح يزور {site} كزائر غير مسجّل."]
        report = CookieFile(self.cookies_file).read()
        cookies = report.cookies
        if not cookies:
            return [f"تعذر قراءة ملف cookies ({self.cookies_file}): {report.problem}"]
        if has_session_cookie(cookies, site) is False:
            return [f"ملف cookies لا يحتوي جلسة دخول لـ {site} (الكوكي {SESSION_COOKIES[site]} مفقود). "
                    "صدّره مرة أخرى وأنت مسجّل الدخول وعلى صفحة الموقع نفسه."]
        return []

    def capture(self, url: str, out_file: Path) -> ScreenshotResult:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with self.launcher.context(self.VIEWPORT) as ctx:
            page = ctx.new_page()
            cleaner = cleaner_for(url)
            cleaner.READY_TIMEOUT_MS = self.content_wait_ms
            cleaner.observe(page)
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass  # social sites keep long-polling; a loaded DOM is enough
            page.wait_for_timeout(2000)
            notes = self._cookie_notes(page.url) + cleaner.clean(page)
            logged_out = cleaner.looks_logged_out(page)
            if logged_out:
                notes.append("المتصفح غير مسجّل الدخول في المنصة (زر تسجيل الدخول ظاهر) رغم ملف cookies؛ "
                             "شغّل: python manage.py debug_profile <الرابط> لمعرفة السبب.")
            page.screenshot(path=str(out_file), full_page=False)
        return ScreenshotResult(out_file, notes, cleaner.content_ready, logged_out)
