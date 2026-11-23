from django import forms
from django.contrib.auth.forms import SetPasswordForm, UserCreationForm

from .models import User


class UserCreateForm(UserCreationForm):
    class Meta:
        model = User
        fields = ["username", "full_name", "role", "is_active", "is_superuser"]
        labels = {"username": "الكود (اسم المستخدم)", "is_active": "الحساب مفعّل",
                  "is_superuser": "مدير النظام (Superadmin)"}
        help_texts = {"username": "", "is_superuser": "يرى إدارة المستخدمين وسجل التدقيق ولوحة الإدارة."}
        widgets = {"username": forms.TextInput(attrs={"dir": "ltr", "autocomplete": "off"})}

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = user.is_superuser  # Django admin access follows superadmin
        if commit:
            user.save()
        return user


class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["full_name", "role", "is_active", "is_superuser"]
        labels = {"is_active": "الحساب مفعّل", "is_superuser": "مدير النظام (Superadmin)"}

    def __init__(self, *args, acting_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.acting_user = acting_user

    def clean(self):
        data = super().clean()
        if self.acting_user and self.instance.pk == self.acting_user.pk:
            if not data.get("is_active"):
                self.add_error("is_active", "لا يمكنك تعطيل حسابك.")
            if not data.get("is_superuser"):
                self.add_error("is_superuser", "لا يمكنك إزالة صلاحية مدير النظام عن نفسك.")
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = user.is_superuser
        if commit:
            user.save()
        return user


class AdminSetPasswordForm(SetPasswordForm):
    """Superadmin sets a user's password (no old password needed)."""
