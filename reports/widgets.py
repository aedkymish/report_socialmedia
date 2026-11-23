from django import forms


class LinksWidget(forms.Widget):
    """One input per URL with add/remove buttons; pasting several URLs splits them
    into rows. Submits as repeated `name` values, exposed to the form as one
    newline-joined string (so validation stays in ActionRequestForm.clean_links)."""

    template_name = "reports/widgets/links.html"

    def value_from_datadict(self, data, files, name):
        values = data.getlist(name) if hasattr(data, "getlist") else [data.get(name, "")]
        return "\n".join(v for v in values if v is not None)

    def value_omitted_from_data(self, data, files, name):
        return name not in data

    def get_context(self, name, value, attrs):
        ctx = super().get_context(name, value, attrs)
        rows = [v.strip() for v in (value or "").splitlines() if v.strip()]
        ctx["widget"]["rows"] = rows or [""]
        return ctx
