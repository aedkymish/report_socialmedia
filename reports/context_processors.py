from django.conf import settings

from .services.pdf import resolve_report_logo


def branding(request):
    """Lets templates show the organisation logo (form header, print)."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    return {
        "branding_logo": resolve_report_logo() is not None,
        "branding_logo_height": settings.REPORT["LOGO_HEIGHT"],
    }
