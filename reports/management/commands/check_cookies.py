"""Diagnose the cookies.txt used for login-walled platforms.
Prints cookie NAMES and expiry only — never values."""
from datetime import datetime, timezone

from django.conf import settings
from django.core.management.base import BaseCommand

from reports.services.browser import SESSION_COOKIES, cookie_domain_matches, session_cookie_names
from reports.services.cookies import CookieFile


class Command(BaseCommand):
    help = "فحص ملف cookies: هل يحتوي جلسة دخول لكل منصة؟"

    def add_arguments(self, parser):
        parser.add_argument("--file", default=settings.EVIDENCE["COOKIES_FILE"])

    def handle(self, *args, **opts):
        path = opts["file"]
        if not path:
            self.stdout.write(self.style.ERROR("YTDLP_COOKIES_FILE غير مضبوط في .env"))
            return
        report = CookieFile(path).read()
        cookies = report.cookies
        if not cookies:
            self.stdout.write(self.style.ERROR(f"{path} ({report.size} bytes): {report.problem}"))
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
                if site == "tiktok.com" and any(c["name"] == "sid_guard" for c in found):
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
