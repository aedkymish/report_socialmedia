"""Controllers (the C in MVC; Django calls them views)."""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView

from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.views.generic import TemplateView

from .forms import ActionRequestForm, AuthorizedPersonsForm, DecisionForm
from .services.pdf import PdfRenderer, app_css, embedded_font_css, report_logo_data_uri, resolve_report_logo
from .navigation import ORDERING as NAV_ORDERING
from .navigation import RequestListFilter, RequestNavigator
from .services.url_normalizer import normalize_url
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
            .order_by(*NAV_ORDERING)
        )
        self.list_filter = RequestListFilter.from_params(self.request.GET)
        return self.list_filter.apply(qs, ordered=True)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["statuses"] = ActionRequest.Status.choices
        ctx["filter_qs"] = self.list_filter.querystring()  # carried into each row's link
        return ctx


class RequestCreateView(LoginRequiredMixin, CreateView):
    model = ActionRequest
    form_class = ActionRequestForm
    template_name = "reports/request_form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["users"] = get_user_model().objects.filter(is_active=True).order_by("username")
        ctx["platform_contact_code"] = settings.PLATFORM_CONTACT_CODE
        return ctx

    def form_valid(self, form):
        analyzer = LinkAnalyzer()
        with transaction.atomic():
            form.instance.created_by = self.request.user
            self.object = form.save()
            RequestLink.objects.bulk_create(  # bulk_create skips save(): set normalized_url here
                RequestLink(request=self.object, url=url, platform=analyzer.analyze(url).platform,
                            normalized_url=normalize_url(url))
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
            "monitor", "uploader", "approved_by", "created_by",
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
        ctx["can_edit_authorized"] = self.object.can_edit_authorized(self.request.user)
        ctx["can_delete"] = self.object.can_delete(self.request.user)
        ctx["nav"] = RequestNavigator(self.object, RequestListFilter.from_params(self.request.GET))
        if ctx["can_edit_authorized"]:
            ctx["authorized_form"] = kwargs.get("authorized_form") or AuthorizedPersonsForm(
                initial={"monitor": self.object.monitor.username, "uploader": self.object.uploader.username})
            ctx["users"] = get_user_model().objects.filter(is_active=True).order_by("username")
            ctx["edit_open"] = "authorized_form" in kwargs
        ctx["can_decide"] = (
            self.request.user.is_approver and self.object.status == ActionRequest.Status.SUBMITTED
        )
        return ctx


class RequestDeleteView(LoginRequiredMixin, DeleteView):
    """حذف الطلب قبل الاعتماد: GET = صفحة تأكيد، POST = حذف (مع ملفات الأدلة)."""

    model = ActionRequest
    template_name = "reports/request_confirm_delete.html"
    success_url = reverse_lazy("reports:list")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            obj = get_object_or_404(ActionRequest, pk=kwargs["pk"])
            if not obj.can_delete(request.user):
                messages.error(request, "لا يمكن حذف الطلب: تم اعتماده/رفضه أو ليست لديك الصلاحية.")
                return redirect(obj)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        links = list(self.object.links.all())
        ctx["links_count"] = len(links)
        ctx["files_count"] = sum(bool(f) for l in links
                                 for f in (l.video_file, l.profile_screenshot, l.profile_videos_image))
        return ctx

    def form_valid(self, form):
        number = self.object.pk
        with transaction.atomic():
            self.object.delete_evidence_files()
            self.object.delete()  # links cascade; django-auditlog records who deleted it
        messages.success(self.request, f"تم حذف الطلب رقم {number} وملفات أدلته.")
        return redirect(self.success_url)


class AuthorizedPersonsUpdateView(LoginRequiredMixin, View):
    """POST: تعديل خامساً (مسؤول الرصد / المسؤول عن التحميل) قبل الاعتماد."""

    def post(self, request, pk):
        obj = get_object_or_404(ActionRequest.objects.select_related("monitor", "uploader"), pk=pk)
        if not obj.can_edit_authorized(request.user):
            messages.error(request, "لا يمكن تعديل المخولين: الطلب معتمد/مرفوض أو ليست لديك الصلاحية.")
            return redirect(obj)
        form = AuthorizedPersonsForm(request.POST, instance=obj)
        if not form.is_valid():
            detail = RequestDetailView()
            detail.setup(request, pk=pk)
            detail.object = detail.get_object()
            return detail.render_to_response(detail.get_context_data(authorized_form=form))
        if form.has_changed():
            form.save()
            messages.success(request, "تم تعديل المخولين بالعمليات (مسجّل في سجل التدقيق).")
        else:
            messages.info(request, "لم يتغير شيء.")
        return redirect(obj)


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
                                 "app_css": app_css(),
                                 "logo": report_logo_data_uri(),
                                 "watermark": settings.REPORT["WATERMARK"],
                                 "watermark_opacity": settings.REPORT["WATERMARK_OPACITY"],
                                 "watermark_text": settings.REPORT["WATERMARK_TEXT"],
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
        if resolve_report_logo():
            from django.urls import reverse
            ctx.update(logo=reverse("reports:logo"), logo_height=settings.REPORT["LOGO_HEIGHT"])
        ctx.update(
            platforms=FORM_PLATFORMS,
            actions=ActionType.choices,
            statuses=ActionRequest.Status.choices,
            query=query.urlencode(),
        )
        return ctx


class BrandingLogoView(LoginRequiredMixin, View):
    """Serves REPORT_LOGO_PATH (from ./branding) to signed-in users."""

    def get(self, request):
        from django.http import FileResponse, Http404

        logo = resolve_report_logo()
        if not logo:
            raise Http404("no logo configured")
        path, mime = logo
        response = FileResponse(open(path, "rb"), content_type=mime)
        response["Cache-Control"] = "private, max-age=300"
        return response


class LinkCheckView(LoginRequiredMixin, View):
    """GET ?url=… → is this link already used in a request? (live warning in the form)"""

    def get(self, request):
        from django.http import JsonResponse

        from .forms import find_existing_links

        url = request.GET.get("url", "").strip()[:1000]
        if not url:
            return JsonResponse({"duplicate": False})
        found = find_existing_links([url])
        if not found:
            return JsonResponse({"duplicate": False})
        link = found[0][1]
        return JsonResponse({
            "duplicate": True,
            "request": link.request_id,
            "status": link.request.get_status_display(),
            "href": link.request.get_absolute_url(),
        })
