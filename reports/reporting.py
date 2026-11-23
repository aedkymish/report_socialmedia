"""Report builder (service layer) for the Reports page.

A request matches when it was created inside the period AND contains at least
one of the selected platforms AND at least one of the selected action types
(an empty selection means "all"). Platforms/actions are JSON lists, so they are
matched in Python – this stays portable across SQLite/PostgreSQL.
"""
from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.utils import timezone

from .models import ActionRequest, ActionType, Platform, RequestLink

FORM_PLATFORMS = [c for c in Platform.choices if c[0] != Platform.OTHER]


@dataclass
class ReportFilter:
    date_from: date
    date_to: date
    platforms: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)

    @classmethod
    def from_query(cls, q) -> "ReportFilter":
        today = timezone.localdate()

        def parse(value, default):
            try:
                return date.fromisoformat(value) if value else default
            except ValueError:
                return default

        d_from = parse(q.get("from"), today - timedelta(days=29))
        d_to = parse(q.get("to"), today)
        if d_from > d_to:
            d_from, d_to = d_to, d_from
        return cls(
            date_from=d_from,
            date_to=d_to,
            platforms=[p for p in q.getlist("platform") if p in Platform.values],
            actions=[a for a in q.getlist("action") if a in ActionType.values],
            statuses=[s for s in q.getlist("status") if s in ActionRequest.Status.values],
        )

    @property
    def days(self) -> int:
        return (self.date_to - self.date_from).days + 1


@dataclass
class Bar:
    key: str
    label: str
    count: int
    pct: float  # of the largest bar, for the bar width


@dataclass
class ReportResult:
    filter: ReportFilter
    requests: list[ActionRequest]
    total: int
    by_platform: list[Bar]
    by_action: list[Bar]
    by_status: list[Bar]
    links_total: int
    links_by_platform: list[Bar]
    videos: int
    evidence_done: int
    evidence_failed: int
    approval_rate: float | None


class ReportBuilder:
    def build(self, f: ReportFilter) -> ReportResult:
        qs = (
            ActionRequest.objects.filter(created_at__date__gte=f.date_from, created_at__date__lte=f.date_to)
            .select_related("monitor", "uploader", "approved_by")
            .order_by("-created_at")
        )
        if f.statuses:
            qs = qs.filter(status__in=f.statuses)
        requests = [r for r in qs if self._matches(r, f)]
        ids = [r.pk for r in requests]
        links = list(RequestLink.objects.filter(request_id__in=ids)
                     .values("request_id", "platform", "is_video", "evidence_status"))
        links_per_request = Counter(l["request_id"] for l in links)
        for r in requests:
            r.link_count = links_per_request.get(r.pk, 0)

        platform_keys = f.platforms or [p for p, _ in FORM_PLATFORMS]
        action_keys = f.actions or list(ActionType.values)
        decided = [r for r in requests if r.status != ActionRequest.Status.SUBMITTED]
        approved = sum(r.status == ActionRequest.Status.APPROVED for r in decided)

        return ReportResult(
            filter=f,
            requests=requests,
            total=len(requests),
            by_platform=self._bars(Counter(p for r in requests for p in set(r.platforms)),
                                   [(k, Platform(k).label) for k in platform_keys]),
            by_action=self._bars(Counter(a for r in requests for a in set(r.actions)),
                                 [(k, ActionType(k).label) for k in action_keys]),
            by_status=self._bars(Counter(r.status for r in requests), ActionRequest.Status.choices),
            links_total=len(links),
            links_by_platform=self._bars(Counter(l["platform"] for l in links), Platform.choices, drop_zero=True),
            videos=sum(l["is_video"] for l in links),
            evidence_done=sum(l["evidence_status"] == RequestLink.EvidenceStatus.DONE for l in links),
            evidence_failed=sum(l["evidence_status"] == RequestLink.EvidenceStatus.FAILED for l in links),
            approval_rate=round(100 * approved / len(decided)) if decided else None,
        )

    @staticmethod
    def _matches(r: ActionRequest, f: ReportFilter) -> bool:
        if f.platforms and not set(r.platforms) & set(f.platforms):
            return False
        if f.actions and not set(r.actions) & set(f.actions):
            return False
        return True

    @staticmethod
    def _bars(counter: Counter, labels, drop_zero=False) -> list[Bar]:
        top = max(counter.values(), default=0) or 1
        bars = [Bar(k, str(label), counter.get(k, 0), 100 * counter.get(k, 0) / top) for k, label in labels]
        return [b for b in bars if b.count] if drop_zero else bars


class ReportCsvExporter:
    HEADERS = ["رقم الطلب", "التاريخ", "الحالة", "المنصات", "الإجراءات", "عدد الروابط",
               "مسؤول الرصد", "المسؤول عن التحميل", "نقطة الاتصال", "المعتمد", "تاريخ الاعتماد", "السبب"]

    def export(self, result: ReportResult) -> bytes:
        buf = io.StringIO()
        w = csv.writer(buf)
        f = result.filter
        w.writerow([f"تقرير الطلبات من {f.date_from} إلى {f.date_to}"])
        w.writerow(self.HEADERS)
        for r in result.requests:
            w.writerow([
                r.pk, timezone.localtime(r.created_at).strftime("%Y-%m-%d %H:%M"), r.get_status_display(),
                "، ".join(r.platform_labels()), "، ".join(r.action_labels()), r.link_count,
                r.monitor.username, r.uploader.username, r.platform_contact_code,
                r.approved_by.username if r.approved_by else "",
                timezone.localtime(r.approved_at).strftime("%Y-%m-%d") if r.approved_at else "",
                r.description.replace("\n", " "),
            ])
        return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM so Excel shows Arabic correctly
