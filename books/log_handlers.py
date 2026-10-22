"""Logging handler + filter used by settings.LOGGING.

Library activity is logged with the standard `logging` module and tagged with
`extra=activity(...)` (see books/activity.py). Every record still goes to stdout;
tagged records are ALSO stored in MySQL so the View Logs page can show them,
because container stdout and local files do not survive a restart and Django
cannot read `kubectl logs`.

This module is imported while Django configures logging (before apps are ready),
so models are imported lazily inside emit().
"""
import logging
import sys
import threading
from datetime import datetime, timezone

KEEP_ROWS = 5000      # older entries are pruned so the table cannot grow forever
PRUNE_EVERY = 200     # ...checked once every N inserts


class ActivityLogHandler(logging.Handler):
    """Stores records that carry an `action` attribute in the ActivityLog table."""

    _local = threading.local()

    def emit(self, record):
        action = getattr(record, "action", None)
        if action is None or getattr(self._local, "busy", False):
            return
        self._local.busy = True  # never log about storing a log (no recursion)
        try:
            from .models import ActivityLog

            entry = ActivityLog.objects.create(
                timestamp=datetime.fromtimestamp(record.created, tz=timezone.utc),
                action=action,
                level=record.levelname,
                message=record.getMessage()[:500],
                book_id=getattr(record, "book_id", None),
            )
            if entry.pk % PRUNE_EVERY == 0:
                ActivityLog.objects.filter(pk__lte=entry.pk - KEEP_ROWS).delete()
        except Exception as exc:
            # E.g. MySQL is down. The record was already printed to stdout by the
            # console handler; a logging problem must never break the request.
            sys.stderr.write(f"ActivityLogHandler: could not store log record ({type(exc).__name__})\n")
        finally:
            self._local.busy = False


class ActivityTagFilter(logging.Filter):
    """Adds `action_tag` for the console format, e.g. "[UPDATE book=16] "."""

    def filter(self, record):
        action = getattr(record, "action", None)
        book_id = getattr(record, "book_id", None)
        if action is None:
            record.action_tag = ""
        else:
            record.action_tag = f"[{action} book={book_id}] " if book_id else f"[{action}] "
        return True
