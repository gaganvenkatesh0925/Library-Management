"""Small helpers for activity logging.

A log call becomes a library "activity" (stored for the View Logs page) by
tagging it:   logger.info("Book %r added", title, extra=activity("CREATE", book.pk))
"""
import hashlib

from django.core.cache import cache


def activity(action, book_id=None):
    return {"action": action, "book_id": book_id}


def first_time(request, key, seconds):
    """True if this client has not done `key` within the last `seconds`.

    The UI reloads the book list after every save and on every page load; this
    keeps those automatic repeats from flooding the log with identical READ
    entries. Uses Django's default in-memory cache (per process, no setup).
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    client = forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
    digest = hashlib.sha256(f"{client}|{key}".encode()).hexdigest()
    return cache.add(f"activity:{digest}", True, seconds)
