"""Django settings for the social-media action request system."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "auditlog",
    "accounts",
    "reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "auditlog.middleware.AuditlogMiddleware",  # records the acting user on every change
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "reports.context_processors.branding",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DJANGO_DB_PATH", BASE_DIR / "data" / "db.sqlite3"),
        "OPTIONS": {
            "timeout": 20,  # background evidence threads write concurrently
            # Classic rollback journal (not WAL): every committed change lands in
            # db.sqlite3 itself, so the file stays consistent across the Docker
            # Desktop bind mount (WAL's shared-memory file does not cross the VM).
            "init_command": "PRAGMA journal_mode=DELETE;",
        },
    }
}

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "reports:list"
LOGOUT_REDIRECT_URL = "login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "ar"
def _resolve_time_zone(value: str) -> str:
    """Accept any letter case (e.g. "africa/tripoli" -> "Africa/Tripoli")."""
    from zoneinfo import available_timezones

    value = value.strip()
    zones = {z.lower(): z for z in available_timezones()}
    if value.lower() not in zones:
        raise ValueError(f"DJANGO_TIME_ZONE غير صحيح: {value!r} (مثال صحيح: Africa/Tripoli)")
    return zones[value.lower()]


TIME_ZONE = _resolve_time_zone(os.environ.get("DJANGO_TIME_ZONE", "Africa/Tripoli"))
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = os.environ.get("DJANGO_MEDIA_ROOT", BASE_DIR / "data" / "media")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Evidence collection (video download + profile screenshot) ---
EVIDENCE = {
    # Run collection in a background thread right after submission.
    # Set to "0" to rely only on `python manage.py collect_evidence`.
    "ASYNC": os.environ.get("EVIDENCE_ASYNC", "1") == "1",
    # Optional path to a Chromium binary for Playwright screenshots.
    "CHROMIUM_EXECUTABLE": os.environ.get("CHROMIUM_EXECUTABLE", ""),
    # Optional Netscape cookies file for yt-dlp (needed for some private/login-walled content).
    "COOKIES_FILE": os.environ.get("YTDLP_COOKIES_FILE", ""),
    # Fallback: newest *.txt/*.json dropped into this folder is used automatically.
    "COOKIES_DIR": os.environ.get("EVIDENCE_COOKIES_DIR", str(BASE_DIR / "cookies")),
    "MAX_VIDEO_MB": int(os.environ.get("EVIDENCE_MAX_VIDEO_MB", "500")),
    "SCREENSHOT_TIMEOUT_MS": int(os.environ.get("EVIDENCE_SCREENSHOT_TIMEOUT_MS", "45000")),
    # Max seconds to wait for a profile's content (e.g. TikTok video thumbnails) before the shot.
    "CONTENT_WAIT_SECONDS": int(os.environ.get("EVIDENCE_CONTENT_WAIT_SECONDS", "30")),
    # "قائمة فيديوهات الحساب" sheet: auto = only when the grid did not load in the
    # screenshot; always = for every profile screenshot; never = disabled.
    "VIDEOS_SHEET": os.environ.get("EVIDENCE_VIDEOS_SHEET", "auto").lower(),
}

# django-auditlog: keep the remote IP of the actor with each entry.
AUDITLOG_INCLUDE_ALL_MODELS = False

# Fixed code of the external platform contact point (section 5, item 3 of the form).
PLATFORM_CONTACT_CODE = os.environ.get("PLATFORM_CONTACT_CODE", "003").strip() or "003"

# --- Report branding (PDF header) ---
REPORT = {
    # Logo file shown in the PDF report header (PNG/JPG/SVG/WEBP). Relative paths
    # are resolved against the project directory, e.g. "branding/logo.png".
    "LOGO_PATH": os.environ.get("REPORT_LOGO_PATH", ""),
    # Logo height in the PDF, in pixels (width keeps the aspect ratio).
    "LOGO_HEIGHT": int(os.environ.get("REPORT_LOGO_HEIGHT", "70")),
}
