"""Domain model (the M in MVC) for the action-request form."""
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Platform(models.TextChoices):
    TIKTOK = "tiktok", "تيك توك (TikTok)"
    FACEBOOK = "facebook", "فيسبوك (Facebook)"
    TELEGRAM = "telegram", "تلغرام (Telegram)"
    INSTAGRAM = "instagram", "إنستغرام (Instagram)"
    X = "x", "إكس (X)"
    OTHER = "other", "أخرى"


class ActionType(models.TextChoices):
    BLOCK = "block", "حجب"
    LOCK = "lock", "قفل"
    BAN = "ban", "حظر"
    DOCUMENT = "document", "توثيق"


def default_platform_contact_code() -> str:
    return settings.PLATFORM_CONTACT_CODE


class ActionRequest(models.Model):
    """نموذج طلب إجراء (حجب - قفل - حظر - توثيق) للصفحات والقنوات الرسمية."""

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "مُرسل - بانتظار الاعتماد"
        APPROVED = "approved", "معتمد"
        REJECTED = "rejected", "مرفوض"

    # أولاً + ثانياً
    platforms = models.JSONField("المنصات المستهدفة", default=list)
    actions = models.JSONField("نوع الإجراء المطلوب", default=list)
    # رابعاً
    description = models.TextField("شرح مبسط عن الحالة / سبب الطلب")
    # خامساً: المخولون بالعمليات (الكود = اسم المستخدم)
    monitor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="monitored_requests",
        verbose_name="مسؤول الرصد",
    )
    uploader = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="uploaded_requests",
        verbose_name="المسؤول عن التحميل في القناة",
    )
    # Fixed code of the external contact point (not a system user). Stored per
    # request so old requests keep the code that was in force when submitted.
    platform_contact_code = models.CharField(
        "مسؤول المنصة (نقطة الاتصال) - الكود", max_length=32,
        default=default_platform_contact_code, editable=False,
    )
    # سادساً: التوقيع والاعتماد
    declaration_accepted = models.BooleanField("إقرار بصحة البيانات", default=False)
    consent_accepted = models.BooleanField("موافقة على اتخاذ الإجراءات", default=False)
    approver_name = models.CharField("اسم المسؤول المعتمد", max_length=150, default="مكتب الأدلة الرقمية")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="approved_requests", verbose_name="التوقيع الرسمي",
    )
    approved_at = models.DateTimeField("التاريخ", null=True, blank=True)
    review_note = models.TextField("ملاحظات الاعتماد", blank=True)

    status = models.CharField("الحالة", max_length=16, choices=Status.choices, default=Status.SUBMITTED)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_requests",
        verbose_name="أنشئ بواسطة",
    )
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "طلب إجراء"
        verbose_name_plural = "طلبات الإجراء"

    def __str__(self) -> str:
        return f"طلب رقم {self.pk}"

    def get_absolute_url(self) -> str:
        return reverse("reports:detail", args=[self.pk])

    # --- presentation helpers ---
    def platform_labels(self) -> list[str]:
        return [Platform(p).label for p in self.platforms if p in Platform.values]

    def action_labels(self) -> list[str]:
        return [ActionType(a).label for a in self.actions if a in ActionType.values]

    # --- workflow transitions ---
    def approve(self, user, note: str = "") -> None:
        self._decide(self.Status.APPROVED, user, note)

    def reject(self, user, note: str = "") -> None:
        self._decide(self.Status.REJECTED, user, note)

    def _decide(self, status: str, user, note: str) -> None:
        if self.status != self.Status.SUBMITTED:
            raise ValueError("تم اتخاذ قرار في هذا الطلب مسبقاً")
        self.status = status
        self.approved_by = user
        self.approved_at = timezone.now()
        self.review_note = note
        self.save(update_fields=["status", "approved_by", "approved_at", "review_note"])


def evidence_path(instance: "RequestLink", filename: str) -> str:
    return f"evidence/request_{instance.request_id}/link_{instance.pk}/{filename}"


class RequestLink(models.Model):
    """ثالثاً: رابط الصفحة أو القناة + الأدلة الرقمية المجمعة له."""

    class EvidenceStatus(models.TextChoices):
        PENDING = "pending", "بانتظار المعالجة"
        PROCESSING = "processing", "جارٍ التحميل"
        DONE = "done", "اكتمل"
        PARTIAL = "partial", "اكتمل جزئياً"
        FAILED = "failed", "فشل"

    request = models.ForeignKey(ActionRequest, on_delete=models.CASCADE, related_name="links")
    url = models.URLField("الرابط", max_length=1000)
    platform = models.CharField("المنصة", max_length=16, choices=Platform.choices, default=Platform.OTHER)

    is_video = models.BooleanField("فيديو؟", default=False)
    video_file = models.FileField("ملف الفيديو", upload_to=evidence_path, blank=True, max_length=500)
    video_title = models.CharField("عنوان الفيديو", max_length=500, blank=True)
    video_sha256 = models.CharField("بصمة الفيديو SHA-256", max_length=64, blank=True)
    profile_url = models.URLField("رابط الصفحة الشخصية", max_length=1000, blank=True)
    profile_screenshot = models.ImageField("صورة الصفحة الشخصية", upload_to=evidence_path, blank=True, max_length=500)
    screenshot_sha256 = models.CharField("بصمة الصورة SHA-256", max_length=64, blank=True)
    profile_videos_image = models.ImageField(
        "قائمة فيديوهات الحساب (مستخرجة)", upload_to=evidence_path, blank=True, max_length=500,
        help_text="تُنشأ عندما لا تعرض المنصة شبكة الفيديوهات في لقطة الشاشة.",
    )
    profile_videos_sha256 = models.CharField("بصمة قائمة الفيديوهات SHA-256", max_length=64, blank=True)

    evidence_status = models.CharField(
        "حالة الأدلة", max_length=16, choices=EvidenceStatus.choices, default=EvidenceStatus.PENDING,
    )
    evidence_log = models.TextField("سجل المعالجة", blank=True)
    processed_at = models.DateTimeField("تاريخ المعالجة", null=True, blank=True)

    class Meta:
        ordering = ["pk"]
        verbose_name = "رابط"
        verbose_name_plural = "الروابط"

    def __str__(self) -> str:
        return self.url


from auditlog.registry import auditlog  # noqa: E402

auditlog.register(ActionRequest)
auditlog.register(RequestLink, exclude_fields=["evidence_log"])
