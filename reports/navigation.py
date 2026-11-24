"""Shared list filtering + previous/next navigation between requests.

The list and the request page use the same RequestListFilter and the same
ordering, so the arrows walk exactly through what the list showed."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from django.db.models import Case, IntegerField, Q, When

from .models import ActionRequest

ORDERING = ("-created_at", "-pk")  # newest first; pk breaks ties deterministically


@dataclass(frozen=True)
class RequestListFilter:
    q: str = ""
    status: str = ""

    @classmethod
    def from_params(cls, params) -> "RequestListFilter":
        status = params.get("status", "")
        return cls(q=params.get("q", "").strip(),
                   status=status if status in ActionRequest.Status.values else "")

    def apply(self, qs, ordered: bool = False):
        if self.status:
            qs = qs.filter(status=self.status)
        if self.q:
            match = (Q(description__icontains=self.q) | Q(links__url__icontains=self.q)
                     | Q(monitor__username=self.q) | Q(uploader__username=self.q)
                     | Q(platform_contact_code=self.q))
            number = self.request_number
            if number is not None:
                match |= Q(pk=number)  # "12" or "#12" finds request 12 (plus any text matches)
            qs = qs.filter(match).distinct()
            if number is not None and ordered:
                # the request with that number comes first, then the other matches by date
                qs = qs.annotate(_number_hit=Case(When(pk=number, then=0), default=1, output_field=IntegerField())
                                 ).order_by("_number_hit", *ORDERING)
        return qs

    @property
    def request_number(self) -> int | None:
        """The search text as a request number ('12', '#12', '٢١'), else None."""
        text = self.q.lstrip("#").strip().translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
        return int(text) if text.isdigit() and len(text) <= 9 else None

    @property
    def active(self) -> bool:
        return bool(self.q or self.status)

    def querystring(self) -> str:
        """'?q=…&status=…' to carry the filter between list and detail ('' if none)."""
        params = {k: v for k, v in (("q", self.q), ("status", self.status)) if v}
        return "?" + urlencode(params) if params else ""


class RequestNavigator:
    """Previous (newer) / next (older) request within the filtered list."""

    def __init__(self, current: ActionRequest, list_filter: RequestListFilter):
        self.current = current
        base = list_filter.apply(ActionRequest.objects.all())
        # Opened with a filter the request no longer matches (e.g. just approved): walk the full list.
        if list_filter.active and not base.filter(pk=current.pk).exists():
            list_filter = RequestListFilter()
            base = ActionRequest.objects.all()
        self.filter = list_filter
        self._base = base
        c, pk = current.created_at, current.pk
        self._newer = Q(created_at__gt=c) | Q(created_at=c, pk__gt=pk)
        self._older = Q(created_at__lt=c) | Q(created_at=c, pk__lt=pk)

    def _url(self, obj) -> str | None:
        return obj.get_absolute_url() + self.filter.querystring() if obj else None

    @property
    def previous_url(self) -> str | None:  # the row above in the list
        return self._url(self._base.filter(self._newer).order_by("created_at", "pk").only("pk").first())

    @property
    def next_url(self) -> str | None:  # the row below in the list
        return self._url(self._base.filter(self._older).order_by(*ORDERING).only("pk").first())

    @property
    def position(self) -> int:
        return self._base.filter(self._newer).count() + 1

    @property
    def total(self) -> int:
        return self._base.count()

    @property
    def list_url(self) -> str:
        from django.urls import reverse
        return reverse("reports:list") + self.filter.querystring()
