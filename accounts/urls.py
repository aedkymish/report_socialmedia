from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("users/", views.UserListView.as_view(), name="list"),
    path("users/new/", views.UserCreateView.as_view(), name="create"),
    path("users/<int:pk>/", views.UserUpdateView.as_view(), name="edit"),
    path("users/<int:pk>/password/", views.UserPasswordView.as_view(), name="password"),
    path("audit/", views.AuditLogView.as_view(), name="audit"),
]
