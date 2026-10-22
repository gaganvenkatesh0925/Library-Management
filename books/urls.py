from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("books", views.BookViewSet, basename="book")
router.register("borrowers", views.BorrowerViewSet, basename="borrower")

urlpatterns = [
    path("", views.index, name="index"),
    path("api/", include(router.urls)),
    path("logs/", views.view_logs, name="view_logs"),
    path("logs/data/", views.logs_data, name="logs_data"),
    path("healthz/", views.healthz, name="healthz"),
    path("readyz/", views.readyz, name="readyz"),
]
