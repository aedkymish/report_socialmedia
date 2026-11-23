from django.contrib import admin

from .models import ActionRequest, RequestLink


class RequestLinkInline(admin.TabularInline):
    model = RequestLink
    extra = 0
    fields = ("url", "platform", "is_video", "video_file", "profile_url", "profile_screenshot", "evidence_status")
    readonly_fields = ("platform", "is_video", "evidence_status")


@admin.register(ActionRequest)
class ActionRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "monitor", "uploader", "platform_contact", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("description", "links__url", "monitor__username")
    inlines = [RequestLinkInline]
    raw_id_fields = ("monitor", "uploader", "platform_contact", "approved_by", "created_by")


@admin.register(RequestLink)
class RequestLinkAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "platform", "is_video", "evidence_status", "processed_at")
    list_filter = ("platform", "is_video", "evidence_status")
    search_fields = ("url", "profile_url")
    readonly_fields = ("video_sha256", "screenshot_sha256", "evidence_log", "processed_at")
