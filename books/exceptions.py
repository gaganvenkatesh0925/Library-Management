import logging

from django.db import DatabaseError
from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from .activity import activity

logger = logging.getLogger(__name__)

OPERATIONS = {
    "list": "READ", "retrieve": "READ", "create": "CREATE",
    "update": "UPDATE", "partial_update": "UPDATE", "destroy": "DELETE",
}


def api_exception_handler(exc, context):
    """DRF's normal error handling, plus a safe response for database failures.

    Validation errors (400), not found (404) etc. are handled by DRF as usual.
    Database errors would otherwise become a 500 page that may leak internals,
    so we log the real error and return a generic message instead.

    Every failure is also logged as an ERROR activity for the View Logs page.
    Only field names and exception class names go into those messages - never
    submitted values or database error text (which can contain host/user names).
    """
    response = exception_handler(exc, context)
    request, view = context.get("request"), context.get("view")
    operation = OPERATIONS.get(getattr(view, "action", None), "Request")
    where = f"{getattr(request, 'method', '?')} {getattr(request, 'path', '?')}"
    book_id = context.get("kwargs", {}).get("pk")
    tag = activity("ERROR", book_id)

    if response is None and isinstance(exc, DatabaseError):
        # Full traceback goes to stdout only; the stored message stays generic.
        logger.exception("%s failed: database error (%s) during %s", operation, type(exc).__name__, where, extra=tag)
        return Response(
            {"detail": "The database is currently unavailable. Please try again shortly."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if response is None:
        # Django itself logs the traceback for this 500 (django.request).
        logger.error("%s failed: unexpected error (%s) during %s", operation, type(exc).__name__, where, extra=tag)
    elif isinstance(exc, drf_exceptions.ValidationError):
        fields = ", ".join(exc.detail) if isinstance(exc.detail, dict) else "request body"
        logger.warning("%s failed: invalid data (%s) during %s", operation, fields, where, extra=tag)
    elif isinstance(exc, (Http404, drf_exceptions.NotFound)):
        logger.warning("%s failed: book not found during %s", operation, where, extra=tag)
    else:
        logger.warning("%s failed: %s (HTTP %s) during %s", operation, type(exc).__name__,
                       response.status_code, where, extra=tag)
    return response
