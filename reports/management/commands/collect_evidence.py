from django.core.management.base import BaseCommand

from reports.models import RequestLink
from reports.services import EvidenceCollector


class Command(BaseCommand):
    help = "تحميل الفيديوهات وتصوير الصفحات الشخصية للروابط غير المعالجة (أو الفاشلة مع --retry)."

    def add_arguments(self, parser):
        parser.add_argument("--retry", action="store_true", help="إعادة معالجة الروابط الفاشلة/الجزئية أيضاً")
        parser.add_argument("--request", type=int, help="معالجة روابط طلب محدد فقط")

    def handle(self, *args, **opts):
        statuses = [RequestLink.EvidenceStatus.PENDING]
        if opts["retry"]:
            statuses += [RequestLink.EvidenceStatus.FAILED, RequestLink.EvidenceStatus.PARTIAL]
        qs = RequestLink.objects.filter(evidence_status__in=statuses)
        if opts["request"]:
            qs = qs.filter(request_id=opts["request"])
        collector = EvidenceCollector()
        for link in qs:
            link = collector.collect(link)
            self.stdout.write(f"[{link.get_evidence_status_display()}] {link.url}")
