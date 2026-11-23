"""Superadmin-only controllers: user management and the audit log."""
from auditlog.models import LogEntry
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, FormView, ListView, UpdateView

from .forms import AdminSetPasswordForm, UserCreateForm, UserUpdateForm
from .models import User


class SuperuserRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Logged-out users go to login; logged-in non-superusers get 403."""

    raise_exception = False

    def test_func(self):
        return self.request.user.is_superuser

    def handle_no_permission(self):
        self.raise_exception = self.request.user.is_authenticated
        return super().handle_no_permission()


class UserListView(SuperuserRequiredMixin, ListView):
    model = User
    template_name = "accounts/user_list.html"
    paginate_by = 50

    def get_queryset(self):
        qs = User.objects.order_by("username")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(Q(username__icontains=q) | Q(full_name__icontains=q))
        role = self.request.GET.get("role")
        if role in User.Role.values:
            qs = qs.filter(role=role)
        active = self.request.GET.get("active")
        if active in ("1", "0"):
            qs = qs.filter(is_active=active == "1")
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["roles"] = User.Role.choices
        query = self.request.GET.copy()
        query.pop("page", None)
        ctx["query"] = query.urlencode()
        return ctx


class UserCreateView(SuperuserRequiredMixin, CreateView):
    model = User
    form_class = UserCreateForm
    template_name = "accounts/user_form.html"
    success_url = reverse_lazy("accounts:list")

    def form_valid(self, form):
        messages.success(self.request, f"تم إنشاء المستخدم {form.cleaned_data['username']}.")
        return super().form_valid(form)


class UserUpdateView(SuperuserRequiredMixin, UpdateView):
    model = User
    form_class = UserUpdateForm
    template_name = "accounts/user_form.html"
    success_url = reverse_lazy("accounts:list")

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "acting_user": self.request.user}

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["history"] = LogEntry.objects.get_for_object(self.object).select_related("actor")[:30]
        return ctx

    def form_valid(self, form):
        messages.success(self.request, f"تم حفظ بيانات {self.object.username}.")
        return super().form_valid(form)


class UserPasswordView(SuperuserRequiredMixin, FormView):
    form_class = AdminSetPasswordForm
    template_name = "accounts/user_password.html"

    def dispatch(self, request, *args, **kwargs):
        self.target = get_object_or_404(User, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.target}

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "target": self.target}

    def form_valid(self, form):
        form.save()
        messages.success(self.request, f"تم تغيير كلمة مرور {self.target.username}.")
        return redirect("accounts:list")


class AuditLogView(SuperuserRequiredMixin, ListView):
    """سجل التدقيق: كل إنشاء/تعديل/حذف مع المنفّذ والوقت والتغييرات."""

    template_name = "accounts/audit_log.html"
    paginate_by = 50
    MODELS = [("accounts", "user"), ("reports", "actionrequest"), ("reports", "requestlink")]

    def content_types(self):
        return ContentType.objects.filter(
            Q(app_label="accounts", model="user")
            | Q(app_label="reports", model__in=["actionrequest", "requestlink"])
        )

    def get_queryset(self):
        qs = LogEntry.objects.select_related("actor", "content_type").order_by("-timestamp")
        g = self.request.GET
        if g.get("model", "").isdigit():
            qs = qs.filter(content_type_id=int(g["model"]))
        if g.get("action", "").isdigit():
            qs = qs.filter(action=int(g["action"]))
        if g.get("actor"):
            qs = qs.filter(actor__username=g["actor"].strip())
        if g.get("from"):
            qs = qs.filter(timestamp__date__gte=g["from"])
        if g.get("to"):
            qs = qs.filter(timestamp__date__lte=g["to"])
        if g.get("object"):
            qs = qs.filter(object_repr__icontains=g["object"].strip())
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["content_types"] = [(ct.pk, ct.model_class()._meta.verbose_name) for ct in self.content_types()]
        from .templatetags.audit_tags import ACTION_LABELS
        ctx["actions"] = [(v, ACTION_LABELS.get(v, l)) for v, l in LogEntry.Action.choices]
        query = self.request.GET.copy()
        query.pop("page", None)
        ctx["query"] = query.urlencode()
        return ctx
