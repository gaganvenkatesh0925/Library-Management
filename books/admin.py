import logging

from django.contrib import admin
from django.db import transaction

from .activity import activity
from .models import Book, Borrower

logger = logging.getLogger(__name__)


class LoggedModelAdmin(admin.ModelAdmin):
    """Logs admin create/update/delete. Admin views run inside a transaction, so the
    log line is emitted on commit - a change that is rolled back is never logged."""

    def _log(self, action, obj_name, pk, message):
        book_id = pk if obj_name == "book" else None
        transaction.on_commit(lambda: logger.info("%s", message, extra=activity(action, book_id)))

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        name = obj._meta.model_name
        verb, action = ("updated", "UPDATE") if change else ("added", "CREATE")
        self._log(action, name, obj.pk, f"{name.title()} {str(obj)!r} {verb} via admin (user: {request.user})")

    def delete_model(self, request, obj):
        name, pk, label = obj._meta.model_name, obj.pk, str(obj)
        super().delete_model(request, obj)
        self._log("DELETE", name, pk, f"{name.title()} {label!r} deleted via admin (user: {request.user})")

    def delete_queryset(self, request, queryset):
        name = queryset.model._meta.model_name
        deleted = [(obj.pk, str(obj)) for obj in queryset]
        super().delete_queryset(request, queryset)
        for pk, label in deleted:
            self._log("DELETE", name, pk, f"{name.title()} {label!r} deleted via admin (user: {request.user})")


@admin.register(Borrower)
class BorrowerAdmin(LoggedModelAdmin):
    list_display = ("borrower_id", "name")
    search_fields = ("borrower_id", "name")


@admin.register(Book)
class BookAdmin(LoggedModelAdmin):
    list_display = (
        "title", "author", "status", "number_of_copies",
        "borrower", "date_of_borrow", "return_due_date",
    )
    list_filter = ("status",)
    search_fields = ("title", "author", "borrower__name", "borrower__borrower_id")
    autocomplete_fields = ("borrower",)
