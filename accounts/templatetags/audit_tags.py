from django import template

register = template.Library()


@register.filter
def audit_changes(entry):
    """[(field, old, new)] using auditlog's human-readable diff when available."""
    try:
        changes = entry.changes_display_dict
    except Exception:
        changes = entry.changes_dict or {}
    rows = []
    for field, value in (changes or {}).items():
        if isinstance(value, (list, tuple)) and len(value) == 2:
            old, new = value
        else:
            old, new = "", value
        rows.append((field, "" if old in (None, "None") else old, "" if new in (None, "None") else new))
    return rows


@register.filter
def model_label(entry):
    model = entry.content_type.model_class() if entry.content_type_id else None
    return model._meta.verbose_name if model else ""


ACTION_LABELS = {0: "إنشاء", 1: "تعديل", 2: "حذف", 3: "اطلاع"}


@register.filter
def action_label(entry):
    return ACTION_LABELS.get(entry.action, entry.get_action_display())
