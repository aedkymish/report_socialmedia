import json

from django import template
from django.utils.safestring import mark_safe

from reports.icons import PLATFORM_ICONS, action_svg, platform_svg, ui_svg

register = template.Library()


@register.simple_tag
def platform_icon(key, size=18):
    return platform_svg(key, int(size))


@register.simple_tag
def action_icon(key, size=18):
    return action_svg(key, int(size))


@register.simple_tag
def icon(name, size=18):
    return ui_svg(name, int(size))


@register.simple_tag
def platform_icons_json():
    """{key: '<svg…>'} for client-side use (links widget)."""
    data = {k: str(platform_svg(k, 16)) for k in PLATFORM_ICONS}
    data["other"] = str(platform_svg("other", 16))
    return mark_safe(json.dumps(data).replace("</", "<\\/"))


@register.inclusion_tag("ui/platform_list.html")
def platforms(keys, size=16):
    from reports.models import Platform
    return {"items": [(k, Platform(k).label) for k in keys if k in Platform.values], "size": size}


@register.inclusion_tag("ui/action_list.html")
def actions(keys, size=16):
    from reports.models import ActionType
    return {"items": [(k, ActionType(k).label) for k in keys if k in ActionType.values], "size": size}
