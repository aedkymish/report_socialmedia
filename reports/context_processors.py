from django.conf import settings

from .services.pdf import resolve_report_logo


def branding(request):
    """Lets templates show the organisation logo (form header, print)."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    has_logo = resolve_report_logo() is not None
    return {
        "branding_logo": has_logo,
        "branding_logo_height": settings.REPORT["LOGO_HEIGHT"],
        "branding_watermark": has_logo and settings.REPORT["WATERMARK"],
        "branding_watermark_opacity": settings.REPORT["WATERMARK_OPACITY"],
        "branding_watermark_text": settings.REPORT["WATERMARK_TEXT"],
    }
