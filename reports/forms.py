from django import forms
from django.contrib.auth import get_user_model
from django.core.validators import URLValidator

from .models import ActionRequest, ActionType, Platform
from .widgets import LinksWidget

User = get_user_model()


class UserCodeField(forms.ModelChoiceField):
    """Accepts an employee code (= username) and resolves it to a User."""

    default_error_messages = {"invalid_choice": "الكود غير موجود أو الحساب غير مفعّل."}

    def __init__(self, **kwargs):
        super().__init__(
            queryset=User.objects.filter(is_active=True),
            to_field_name="username",
            widget=forms.TextInput(attrs={"list": "user-codes", "autocomplete": "off", "dir": "ltr"}),
            **kwargs,
        )


class ActionRequestForm(forms.ModelForm):
    MAX_LINKS = 50

    platforms = forms.MultipleChoiceField(
        label="أولاً: المنصات المستهدفة",
        choices=[c for c in Platform.choices if c[0] != Platform.OTHER],
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": "اختر منصة واحدة على الأقل."},
    )
    actions = forms.MultipleChoiceField(
        label="ثانياً: نوع الإجراء المطلوب",
        choices=ActionType.choices,
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": "اختر إجراءً واحداً على الأقل."},
    )
    links = forms.CharField(
        label="ثالثاً: رابط الصفحة أو القناة المراد العمل عليها",
        help_text="أضف رابطاً في كل حقل (أو الصق عدة روابط دفعة واحدة فتُقسَّم تلقائياً). "
                  "روابط الفيديو تُحمَّل تلقائياً وتُصوَّر الصفحة الشخصية لصاحبها.",
        widget=LinksWidget(),
        error_messages={"required": "أدخل رابطاً واحداً على الأقل."},
    )
    monitor = UserCodeField(label="1. مسؤول الرصد - الكود")
    uploader = UserCodeField(label="2. المسؤول عن التحميل في القناة - الكود")
    declaration_accepted = forms.BooleanField(
        label="أقر أنا المسؤول المعتمد بصحة البيانات الواردة في هذا النموذج وبعد مراجعة كافة الشروط",
    )
    consent_accepted = forms.BooleanField(label="أوافق على اتخاذ الإجراءات اللازمة عبر المنصة رسمياً")

    class Meta:
        model = ActionRequest
        fields = [
            "platforms", "actions", "description",
            "monitor", "uploader",
            "declaration_accepted", "consent_accepted",
        ]
        labels = {"description": "رابعاً: شرح مبسط عن الحالة / سبب الطلب"}
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}

    def clean_links(self) -> list[str]:
        validator = URLValidator(schemes=["http", "https"])
        urls, seen = [], set()
        raw = self.cleaned_data["links"].replace(",", "\n").replace("،", "\n")
        for line in raw.split():
            url = line.strip()
            if not url or url in seen:
                continue
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            try:
                validator(url)
            except forms.ValidationError:
                raise forms.ValidationError(f"رابط غير صالح: {line.strip()}")
            seen.add(url)
            urls.append(url)
        if not urls:
            raise forms.ValidationError("أدخل رابطاً واحداً على الأقل.")
        if len(urls) > self.MAX_LINKS:
            raise forms.ValidationError(f"الحد الأقصى {self.MAX_LINKS} رابطاً في الطلب الواحد.")
        return urls


class AuthorizedPersonsForm(forms.ModelForm):
    """خامساً: تعديل أكواد المخولين قبل الاعتماد."""

    monitor = UserCodeField(label="1. مسؤول الرصد - الكود")
    uploader = UserCodeField(label="2. المسؤول عن التحميل في القناة - الكود")

    class Meta:
        model = ActionRequest
        fields = ["monitor", "uploader"]


class DecisionForm(forms.Form):
    decision = forms.ChoiceField(choices=[("approve", "اعتماد"), ("reject", "رفض")])
    note = forms.CharField(label="ملاحظات", required=False, widget=forms.Textarea(attrs={"rows": 2}))
