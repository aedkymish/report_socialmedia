"""Diagnose why a profile page does not render fully for the automated browser.

    python manage.py debug_profile https://www.tiktok.com/@user

Reports facts only (cookie NAMES, HTTP statuses, element counts) — never cookie
values or response bodies. Saves a screenshot under MEDIA_ROOT/debug/.
"""
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand

from reports.services.browser import SESSION_COOKIES, BrowserLauncher, cookie_domain_matches
from reports.services.cookies import CookieFile
from reports.services.profile_videos import ProfileVideoLister
from reports.services.screenshotter import cleaner_for

API_HINTS = ("/api/", "item_list", "user/detail", "graphql")


class Command(BaseCommand):
    help = "تشخيص تحميل صفحة شخصية (تسجيل الدخول، طلبات المنصة، شبكة الفيديوهات)."

    def add_arguments(self, parser):
        parser.add_argument("url")
        parser.add_argument("--wait", type=int, default=25, help="ثواني الانتظار بعد فتح الصفحة")
        parser.add_argument("--skip-ytdlp", action="store_true")

    def ok(self, msg):
        self.stdout.write(self.style.SUCCESS("✓ " + msg))

    def bad(self, msg):
        self.stdout.write(self.style.ERROR("✗ " + msg))

    def info(self, msg):
        self.stdout.write("  " + msg)

    def handle(self, *args, **opts):
        url = opts["url"]
        cfg = settings.EVIDENCE
        host = (urlparse(url).hostname or "").lower()
        site = next((d for d in SESSION_COOKIES if host == d or host.endswith("." + d)), None)

        # 1) cookie file
        self.stdout.write(self.style.MIGRATE_HEADING("1) ملف cookies"))
        report = CookieFile(cfg["COOKIES_FILE"]).read()
        if not report.cookies:
            self.bad(f"{cfg['COOKIES_FILE'] or '(غير مضبوط)'}: {report.problem}")
        else:
            self.ok(f"{len(report.cookies)} cookie بصيغة {report.format}")
            if site:
                names = {c["name"] for c in report.cookies if cookie_domain_matches(c["domain"], site)}
                (self.ok if SESSION_COOKIES[site] in names else self.bad)(
                    f"{site}: {len(names)} cookie، جلسة الدخول ({SESSION_COOKIES[site]}) "
                    + ("موجودة" if SESSION_COOKIES[site] in names else "مفقودة"))

        # 2) browser
        self.stdout.write(self.style.MIGRATE_HEADING("2) المتصفح"))
        api_log, console_errors = [], []
        launcher = BrowserLauncher(cfg["CHROMIUM_EXECUTABLE"], cfg["COOKIES_FILE"])
        with launcher.context({"width": 1366, "height": 1600}) as ctx:
            if site:
                in_ctx = {c["name"] for c in ctx.cookies() if cookie_domain_matches(c["domain"], site)}
                (self.ok if SESSION_COOKIES[site] in in_ctx else self.bad)(
                    f"cookies داخل المتصفح لـ {site}: {len(in_ctx)} — جلسة الدخول "
                    + ("مُطبّقة" if SESSION_COOKIES[site] in in_ctx else "غير مُطبّقة"))
            page = ctx.new_page()
            page.on("console", lambda m: m.type == "error" and console_errors.append(m.text[:120]))
            page.on("response", lambda r: any(h in r.url for h in API_HINTS) and api_log.append(r))
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=cfg["SCREENSHOT_TIMEOUT_MS"])
                self.info(f"الصفحة: HTTP {resp.status if resp else '?'} → {page.url}")
            except Exception as exc:
                self.bad(f"تعذر فتح الصفحة: {exc}")
                return
            cleaner = cleaner_for(page.url)
            page.wait_for_timeout(opts["wait"] * 1000)

            (self.bad if cleaner.looks_logged_out(page) else self.ok)(
                "زر تسجيل الدخول ظاهر → المنصة تعتبرك غير مسجّل" if cleaner.looks_logged_out(page)
                else "لا يظهر زر تسجيل الدخول (مسجّل الدخول)")
            captcha = cleaner._visible(page, cleaner.CAPTCHA_SELECTORS)
            (self.bad if captcha else self.ok)("CAPTCHA ظاهر" if captcha else "لا يوجد CAPTCHA")
            counts = page.evaluate("""() => {
                const imgs = [...document.querySelectorAll('[data-e2e="user-post-item"] img')];
                return {items: document.querySelectorAll('[data-e2e="user-post-item"]').length,
                        loaded: imgs.filter(i => i.complete && i.naturalWidth > 0).length,
                        error: /حدث خطأ ما|Something went wrong/.test(document.body.innerText)};
            }""")
            (self.ok if counts["loaded"] else self.bad)(
                f"شبكة الفيديوهات: {counts['items']} عنصر، {counts['loaded']} صورة محمّلة"
                + (" — رسالة خطأ ظاهرة" if counts["error"] else ""))

            self.stdout.write(self.style.MIGRATE_HEADING("3) طلبات المنصة (API)"))
            for r in api_log[:20]:
                self.info(self._describe(r))
            if not api_log:
                self.bad("لم تُرسل الصفحة أي طلب لقائمة الفيديوهات (الصفحة لم تكتمل أو حُجبت).")
            if console_errors:
                self.info(f"أخطاء Console: {len(console_errors)} (أولها: {console_errors[0]})")

            shot = Path(settings.MEDIA_ROOT) / "debug" / f"debug_{datetime.now():%Y%m%d_%H%M%S}.png"
            shot.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(shot))
            self.info(f"لقطة التشخيص: {shot}")

        # 3) yt-dlp listing
        if not opts["skip_ytdlp"]:
            self.stdout.write(self.style.MIGRATE_HEADING("4) قائمة الفيديوهات عبر yt-dlp"))
            try:
                vids = ProfileVideoLister(cfg["COOKIES_FILE"], limit=6).list(url)
                (self.ok if vids else self.bad)(f"yt-dlp أرجع {len(vids)} فيديو")
            except Exception as exc:
                self.bad(f"yt-dlp: {str(exc)[:200]}")

    @staticmethod
    def _describe(r) -> str:
        path = urlparse(r.url).path
        line = f"HTTP {r.status} {path}"
        try:
            body = r.body()
            line += f" ({len(body)} bytes)"
            data = json.loads(body) if body[:1] in (b"{", b"[") else None
            if isinstance(data, dict):
                code = data.get("statusCode", data.get("status_code"))
                items = data.get("itemList") or data.get("items")
                if code is not None:
                    line += f" statusCode={code}"
                if isinstance(items, list):
                    line += f" items={len(items)}"
                if body and not data:
                    line += " (رد فارغ)"
            elif len(body) == 0:
                line += " ← رد فارغ (رفض صامت من المنصة)"
        except Exception:
            pass
        return line
