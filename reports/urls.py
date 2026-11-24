from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.RequestListView.as_view(), name="list"),
    path("new/", views.RequestCreateView.as_view(), name="create"),
    path("<int:pk>/", views.RequestDetailView.as_view(), name="detail"),
    path("<int:pk>/decision/", views.RequestDecisionView.as_view(), name="decision"),
    path("<int:pk>/authorized/", views.AuthorizedPersonsUpdateView.as_view(), name="authorized"),
    path("<int:pk>/delete/", views.RequestDeleteView.as_view(), name="delete"),
    path("links/check/", views.LinkCheckView.as_view(), name="link_check"),
    path("<int:pk>/retry/", views.RetryEvidenceView.as_view(), name="retry"),
    path("reports/", views.ReportView.as_view(), name="report"),
    path("branding/logo/", views.BrandingLogoView.as_view(), name="logo"),
]
