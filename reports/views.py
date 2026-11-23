"""Controllers (the C in MVC; Django calls them views)."""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import CreateView, DetailView, ListView

from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.views.generic import TemplateView

from .forms import ActionRequestForm, DecisionForm
from .services.pdf import PdfRenderer, embedded_font_css, report_logo_data_uri
from .reporting import FORM_PLATFORMS, ReportBuilder, ReportCsvExporter, ReportFilter
from .models import ActionRequest, ActionType, RequestLink
from .services import EvidenceDispatcher, LinkAnalyzer


class RequestListView(LoginRequiredMixin, ListView):
    model = ActionRequest
    template_name = "reports/request_list.html"
    paginate_by = 25

    def get_queryset(self):
        qs = (
            ActionRequest.objects.select_related("monitor", "created_by")
            .annotate(
                link_count=Count("links"),
                video_count=Count("links", filter=Q(links__is_video=True)),
            )
            .order_by("-created_at")
        )
        status = self.request.GET.get("status")
        if status in ActionRequest.Status.values:
            qs = qs.filter(status=status)
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(description__icontains=q) | Q(links__url__icontains=q)
                | Q(monitor__username=q) | Q(uploader__username=q) | Q(platform_contact__username=q)
            ).distinct()
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["statuses"] = ActionRequest.Status.choices
        return ctx


class RequestCreateView(LoginRequiredMixin, CreateView):
    model = ActionRequest
    form_class = ActionRequestForm
    template_name = "reports/request_form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["users"] = get_user_model().objects.filter(is_active=True).order_by("username")
        return ctx

    def form_valid(self, form):
        analyzer = LinkAnalyzer()
        with transaction.atomic():
            form.instance.created_by = self.request.user
            self.object = form.save()
            RequestLink.objects.bulk_create(
                RequestLink(request=self.object, url=url, platform=analyzer.analyze(url).platform)
                for url in form.cleaned_data["links"]
            )
            obj = self.object
            transaction.on_commit(lambda: EvidenceDispatcher().dispatch(obj))
        messages.success(self.request, "تم إرسال الطلب. جارٍ تحميل الفيديوهات وتصوير الصفحات الشخصية.")
        return redirect(self.object)


class RequestDetailView(LoginRequiredMixin, DetailView):
    model = ActionRequest
    template_name = "reports/request_detail.html"

    def get_queryset(self):
        return ActionRequest.objects.select_related(
            "monitor", "uploader", "platform_contact", "approved_by", "created_by",
        ).prefetch_related("links")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        links = list(self.object.links.all())
        ctx["links"] = links
        ctx["processing"] = any(
            l.evidence_status in (RequestLink.EvidenceStatus.PENDING, RequestLink.EvidenceStatus.PROCESSING)
            for l in links
        )
        ctx["decision_form"] = DecisionForm()
        ctx["can_decide"] = (
            self.request.user.is_approver and self.object.status == ActionRequest.Status.SUBMITTED
        )
        return ctx


class RequestDecisionView(LoginRequiredMixin, UserPassesTestMixin, View):
    """سادساً: التوقيع والاعتماد الرسمي."""

    def test_func(self):
        return self.request.user.is_approver

    def post(self, request, pk):
        obj = get_object_or_404(ActionRequest, pk=pk)
        form = DecisionForm(request.POST)
        if not form.is_valid():
            messages.error(request, "قرار غير صالح.")
            return redirect(obj)
        try:
            if form.cleaned_data["decision"] == "approve":
                obj.approve(request.user, form.cleaned_data["note"])
                messages.success(request, "تم اعتماد الطلب.")
            else:
                obj.reject(request.user, form.cleaned_data["note"])
                messages.warning(request, "تم رفض الطلب.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect(obj)


class RetryEvidenceView(LoginRequiredMixin, View):
    """Re-run evidence collection for links that failed or were partial."""

    def post(self, request, pk):
        obj = get_object_or_404(ActionRequest, pk=pk)
        link_id = request.POST.get("link")
        links = obj.links.all()
        if link_id:
            links = links.filter(pk=link_id)
        else:
            links = links.exclude(evidence_status=RequestLink.EvidenceStatus.DONE)
        links = list(links)
        if links:
            RequestLink.objects.filter(pk__in=[l.pk for l in links]).update(
                evidence_status=RequestLink.EvidenceStatus.PENDING,
            )
            EvidenceDispatcher().dispatch(obj, links)
            messages.info(request, f"أُعيدت المعالجة لعدد {len(links)} رابط.")
        return redirect(obj)


class ReportView(LoginRequiredMixin, TemplateView):
    """التقارير: حسب الفترة والمنصة ونوع الإجراء، مع تصدير CSV وطباعة."""

    template_name = "reports/report.html"

    def get(self, request, *args, **kwargs):
        result = ReportBuilder().build(ReportFilter.from_query(request.GET))
        export = request.GET.get("export")
        if export == "csv":
            return self._file(ReportCsvExporter().export(result), "text/csv; charset=utf-8", result, "csv")
        if export == "pdf":
            return self._file(self._pdf(result), "application/pdf", result, "pdf")
        return self.render_to_response(self.get_context_data(result=result))

    def _pdf(self, result) -> bytes:
        html = render_to_string("reports/report_pdf.html",
                                {"result": result, "pdf": True, "font_css": embedded_font_css(),
                                 "logo": report_logo_data_uri(),
                                 "logo_height": settings.REPORT["LOGO_HEIGHT"]},
                                request=self.request)
        f = result.filter
        label = f"Report {f.date_from} - {f.date_to} | {self.request.user.username}"
        return PdfRenderer(settings.EVIDENCE["CHROMIUM_EXECUTABLE"]).render(html, footer_label=label)

    @staticmethod
    def _file(content: bytes, content_type: str, result, ext: str) -> HttpResponse:
        f = result.filter
        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="report_{f.date_from}_{f.date_to}.{ext}"'
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        query = self.request.GET.copy()
        query.pop("export", None)
        ctx.update(
            platforms=FORM_PLATFORMS,
            actions=ActionType.choices,
            statuses=ActionRequest.Status.choices,
            query=query.urlencode(),
        )
        return ctx
