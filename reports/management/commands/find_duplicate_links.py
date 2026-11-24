"""List links that appear in more than one request (e.g. data from before the
no-duplicates rule). Read-only: nothing is changed."""
from django.core.management.base import BaseCommand
from django.db.models import Count

from reports.models import RequestLink


class Command(BaseCommand):
    help = "عرض الروابط المكررة في أكثر من طلب (للبيانات القديمة). لا يعدّل شيئاً."

    def handle(self, *args, **opts):
        dups = (RequestLink.objects.values("normalized_url")
                .annotate(n=Count("request", distinct=True)).filter(n__gt=1).order_by("-n"))
        if not dups:
            self.stdout.write(self.style.SUCCESS("لا توجد روابط مكررة."))
            return
        for d in dups:
            links = RequestLink.objects.filter(normalized_url=d["normalized_url"]).select_related("request")
            reqs = ", ".join(f"#{l.request_id} ({l.request.get_status_display()})" for l in links.order_by("request_id"))
            self.stdout.write(f"{d['normalized_url']}\n    → {d['n']} طلبات: {reqs}")
        self.stdout.write(self.style.WARNING(f"المجموع: {len(dups)} رابط مكرر."))
