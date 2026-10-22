import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.db import connection
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .activity import activity, first_time
from .models import ActivityLog, Book, Borrower
from .serializers import BookSerializer, BorrowerSerializer

logger = logging.getLogger(__name__)

# Identical automatic reads by the same client inside this window are logged once.
REPEAT_READ_SECONDS = 30
PAGE_REPEAT_SECONDS = 5  # a deliberate F5 is a REFRESH; a burst of reloads is logged once
LOGS_PAGE_LIMIT = 100


class BookViewSet(viewsets.ModelViewSet):
    """Full CRUD for books.

    GET    /api/books/                 list (supports ?search= and ?status=)
    POST   /api/books/                 create
    GET    /api/books/<id>/            retrieve
    PUT    /api/books/<id>/            full update
    PATCH  /api/books/<id>/            partial update
    DELETE /api/books/<id>/            delete
    GET    /api/books/stats/           dashboard counts
    """

    serializer_class = BookSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["title", "author", "borrower__name", "borrower__borrower_id", "status"]

    def get_queryset(self):
        queryset = Book.objects.select_related("borrower")
        status = self.request.query_params.get("status", "").strip().lower()
        if status in Book.Status.values:
            queryset = queryset.filter(status=status)
        return queryset

    # Each write is logged only after save()/delete() returns, i.e. after MySQL
    # accepted it. Failures propagate untouched to DRF / api_exception_handler,
    # which logs them as ERROR activity.

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        query = request.query_params.urlencode()
        if first_time(request, f"list:{query}", REPEAT_READ_SECONDS):
            logger.info("Viewed book list (%s): %d result(s)", query or "all books", len(response.data),
                        extra=activity(ActivityLog.Action.READ))
        return response

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        book_id = response.data["id"]
        if first_time(request, f"book:{book_id}", REPEAT_READ_SECONDS):
            logger.info("Viewed book %r", response.data["title"], extra=activity(ActivityLog.Action.READ, book_id))
        return response

    def perform_create(self, serializer):
        book = serializer.save()
        logger.info("Book %r added (status: %s)", book.title, book.get_status_display(),
                    extra=activity(ActivityLog.Action.CREATE, book.pk))

    def perform_update(self, serializer):
        was, old_status = serializer.instance.status, serializer.instance.get_status_display()
        book = serializer.save()
        new_status = book.get_status_display()
        if book.status == was:
            message = f"Book {book.title!r} details updated (status: {new_status})"
        elif book.status == Book.Status.AVAILABLE:
            message = f"Book {book.title!r} returned ({old_status} -> {new_status})"
        elif was == Book.Status.AVAILABLE:
            message = f"Book {book.title!r} lent to {book.borrower.borrower_id} ({old_status} -> {new_status})"
        else:
            message = f"Book {book.title!r} status changed ({old_status} -> {new_status})"
        logger.info("%s", message, extra=activity(ActivityLog.Action.UPDATE, book.pk))

    def perform_destroy(self, instance):
        book_id, title = instance.pk, instance.title
        instance.delete()
        logger.info("Book %r deleted", title, extra=activity(ActivityLog.Action.DELETE, book_id))

    @action(detail=False, methods=["get"])
    def stats(self, request):
        counts = Book.objects.aggregate(
            total=Count("id"),
            available=Count("id", filter=Q(status=Book.Status.AVAILABLE)),
            borrowed=Count("id", filter=Q(status=Book.Status.BORROWED)),
            overdue=Count("id", filter=Q(status=Book.Status.OVERDUE)),
        )
        return Response(counts)


class BorrowerViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only list of pre-populated borrowers (used by the form dropdown)."""

    queryset = Borrower.objects.all()
    serializer_class = BorrowerSerializer
    pagination_class = None


def index(request):
    """The single-page UI. All data is loaded from the REST API by JavaScript."""
    # First visit -> READ, later visits -> REFRESH; rapid repeated reloads are logged once.
    if first_time(request, "page", PAGE_REPEAT_SECONDS):
        if first_time(request, "visited", 60 * 60):
            logger.info("Library page opened", extra=activity(ActivityLog.Action.READ))
        else:
            logger.info("Library page refreshed", extra=activity(ActivityLog.Action.REFRESH))
        first_time(request, "list:", REPEAT_READ_SECONDS)  # the page's own table load is part of this entry
    return render(request, "books/index.html", {"status_choices": Book.Status.choices})


@staff_member_required
def view_logs(request):
    """Activity log page (admin/staff login required). Data comes from logs_data."""
    return render(request, "books/logs.html", {"actions": ActivityLog.Action.values, "limit": LOGS_PAGE_LIMIT})


def logs_data(request):
    """JSON for the View Logs page: summary counts + latest entries, optionally filtered."""
    if not (request.user.is_active and request.user.is_staff):
        return JsonResponse({"detail": "Staff login required."}, status=403)

    summary = ActivityLog.objects.aggregate(
        total=Count("id"),
        success=Count("id", filter=Q(level="INFO") & ~Q(action=ActivityLog.Action.ERROR)),
        errors=Count("id", filter=Q(action=ActivityLog.Action.ERROR)),
    )
    entries = ActivityLog.objects.all()
    selected = request.GET.get("action", "")
    if selected in ActivityLog.Action.values:  # anything else = all entries
        entries = entries.filter(action=selected)

    rows = [
        {
            "timestamp": timezone.localtime(e.timestamp).strftime("%d %b %Y, %H:%M:%S"),
            "action": e.action,
            "level": e.level,
            "message": e.message,
            "book_id": e.book_id,
        }
        for e in entries[:LOGS_PAGE_LIMIT]
    ]
    return JsonResponse({"summary": summary, "entries": rows, "limit": LOGS_PAGE_LIMIT})


def healthz(request):
    """Liveness: the Django process is up (does not touch the database)."""
    return JsonResponse({"status": "ok"})


def readyz(request):
    """Readiness: Django can reach MySQL (later used by Kubernetes probes)."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"status": "ok", "database": "ok"})
    except Exception:
        return JsonResponse({"status": "error", "database": "unavailable"}, status=503)
