"""Diagnose the cookies.txt used for login-walled platforms.
Prints cookie NAMES and expiry only — never values."""
from datetime import datetime, timezone
from urllib.parse import unquote

from django.conf import settings
from django.core.management.base import BaseCommand

from reports.services.browser import SESSION_COOKIES, cookie_domain_matches, session_cookie_names
from reports.services.cookies import CookieFile, resolve_cookies_file


def tiktok_session_expiry(sid_guard_value: str) -> float | None:
    """sid_guard = <sid>|<created_unix>|<max_age_seconds>|<date>; return created+max_age."""
    parts = unquote(sid_guard_value).split("|")
    try:
        return int(parts[1]) + int(parts[2])
    except (IndexError, ValueError):
        return None


class Command(BaseCommand):
    help = "فحص ملف cookies: هل يحتوي جلسة دخول لكل منصة؟"

    def add_arguments(self, parser):
        parser.add_argument("--file", default=None, help="افتراضياً: YTDLP_COOKIES_FILE أو أحدث ملف في مجلد cookies/")

    def handle(self, *args, **opts):
        path = opts["file"] or resolve_cookies_file()
        if not path:
            self.stdout.write(self.style.ERROR(
                "لا يوجد ملف cookies. ضع الملف (.txt أو .json) داخل مجلد cookies/ في المشروع "
                f"(داخل الحاوية: {settings.EVIDENCE['COOKIES_DIR']})."))
            return
        report = CookieFile(path).read()
        cookies = report.cookies
        if not cookies:
            size = f" ({report.size} bytes)" if report.exists else ""
            extra = ""
            if not report.exists:
                extra = (f" — ضع الملف داخل مجلد cookies/ في المشروع (يُربط تلقائياً بـ "
                         f"{settings.EVIDENCE['COOKIES_DIR']}) أو احذف YTDLP_COOKIES_FILE من .env.")
            self.stdout.write(self.style.ERROR(f"{path}{size}: {report.problem}{extra}"))
            return
        fmt = {"netscape": "Netscape cookies.txt", "json": "JSON (يُحوَّل تلقائياً)"}[report.format]
        self.stdout.write(f"{path}: {len(cookies)} cookie — الصيغة: {fmt}")
        now = datetime.now(timezone.utc).timestamp()
        for site, session_name in dict.fromkeys(SESSION_COOKIES.items()):
            found = [c for c in cookies if cookie_domain_matches(c["domain"], site)]
            if not found:
                continue
            valid = session_cookie_names(site)
            session = next((c for c in found if c["name"] in valid and c["value"]), None)
            names = ", ".join(sorted({c["name"] for c in found}))
            if not session:
                hint = ""
                guard = next((c for c in found if c["name"] == "sid_guard"), None)
                if site == "tiktok.com" and guard:
                    expired_at = tiktok_session_expiry(guard["value"])
                    if expired_at and expired_at < now:
                        hint = (f" — جلسة الدخول المسجلة في sid_guard انتهت بتاريخ "
                                f"{datetime.fromtimestamp(expired_at, timezone.utc):%Y-%m-%d}. "
                                "سجّل الدخول في تيك توك من جديد ثم صدّر الملف.")
                    else:
                        hint = (" — يوجد sid_guard بدون sessionid: غالباً تم التصدير بعد تسجيل الخروج أو "
                                "من ملف تعريف (Profile) آخر في المتصفح.")
                self.stdout.write(self.style.ERROR(
                    f"✗ {site}: لا توجد جلسة دخول ({session_name} مفقود). الموجود: {names}{hint}"))
            elif session.get("expires") and session["expires"] < now:
                self.stdout.write(self.style.ERROR(f"✗ {site}: جلسة الدخول منتهية الصلاحية — صدّر الملف من جديد"))
            else:
                self.stdout.write(self.style.SUCCESS(f"✓ {site}: جلسة دخول موجودة ({len(found)} cookie)"))
        others = {c["domain"].lstrip(".") for c in cookies
                  if not any(cookie_domain_matches(c["domain"], s) for s in SESSION_COOKIES)}
        if others:
            self.stdout.write(f"نطاقات أخرى في الملف: {', '.join(sorted(others))}")
