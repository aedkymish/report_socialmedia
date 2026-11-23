from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """System user. The `username` field IS the employee code (الكود)."""

    class Role(models.TextChoices):
        MONITOR = "monitor", "مسؤول الرصد"
        UPLOADER = "uploader", "المسؤول عن التحميل في القناة"
        PLATFORM_CONTACT = "platform_contact", "مسؤول المنصة (نقطة الاتصال)"
        APPROVER = "approver", "المسؤول المعتمد (مكتب الأدلة الرقمية)"

    full_name = models.CharField("الاسم الكامل", max_length=150, blank=True)
    role = models.CharField("الصفة", max_length=32, choices=Role.choices, default=Role.MONITOR)

    class Meta:
        verbose_name = "مستخدم"
        verbose_name_plural = "المستخدمون"

    @property
    def code(self) -> str:
        return self.username

    @property
    def is_approver(self) -> bool:
        return self.role == self.Role.APPROVER or self.is_superuser

    def __str__(self) -> str:
        return f"{self.username} - {self.full_name}" if self.full_name else self.username


from auditlog.registry import auditlog  # noqa: E402

auditlog.register(User, exclude_fields=["password", "last_login"])
