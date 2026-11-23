from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.RequestListView.as_view(), name="list"),
    path("new/", views.RequestCreateView.as_view(), name="create"),
    path("<int:pk>/", views.RequestDetailView.as_view(), name="detail"),
    path("<int:pk>/decision/", views.RequestDecisionView.as_view(), name="decision"),
    path("<int:pk>/retry/", views.RetryEvidenceView.as_view(), name="retry"),
]
