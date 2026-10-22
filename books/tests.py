"""Automated tests. Run with:  python manage.py test

Django creates a temporary MySQL database (test_library_db), runs the tests
there and drops it afterwards, so real data in library_db is never touched.
"""
import os
import time
from io import StringIO
from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.management import call_command
from django.db import OperationalError
from django.db.models import ProtectedError
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APITestCase

from library_management.settings import required_env

from .models import ActivityLog, Book, Borrower

DEMO_DAY = date(2026, 10, 15)


def clear_demo_data():
    """The test database is built by running migrations, so it starts with the demo
    data (migration 0002). Tests that need exact, small data sets start from empty."""
    Book.objects.all().delete()
    Borrower.objects.all().delete()


class MigrationDataTests(TestCase):
    def test_migrate_loads_demo_data(self):
        self.assertEqual(Borrower.objects.count(), 10)
        self.assertEqual(Book.objects.count(), 15)
        self.assertEqual(Book.objects.filter(status="available").count(), 7)
        self.assertEqual(Book.objects.filter(status="borrowed").count(), 5)
        self.assertEqual(Book.objects.filter(status="overdue").count(), 3)


class BookApiTests(APITestCase):
    def setUp(self):
        clear_demo_data()
        self.gagan = Borrower.objects.create(borrower_id="B001", name="Gagan Venkatesh")
        self.rahul = Borrower.objects.create(borrower_id="B002", name="Rahul Kumar")
        self.book = Book.objects.create(
            title="Two Scoops of Django", author="Feldroy", number_of_copies=3,
            status=Book.Status.BORROWED, borrower=self.gagan,
            date_of_borrow=date(2026, 10, 1), return_due_date=date(2026, 10, 15),
        )
        Book.objects.create(title="Clean Code", author="Robert C. Martin", number_of_copies=2)

    def url(self, book_id=None):
        return f"/api/books/{book_id}/" if book_id else "/api/books/"

    # --- CRUD ---------------------------------------------------------------
    def test_list_and_retrieve(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)

        data = self.client.get(self.url(self.book.id)).json()
        self.assertEqual(data["borrower"], "B001")
        self.assertEqual(data["borrower_name"], "Gagan Venkatesh")
        self.assertEqual(data["status_display"], "Borrowed")

    def test_create(self):
        response = self.client.post(self.url(), {
            "title": "Fluent Python", "author": "Luciano Ramalho",
            "number_of_copies": 1, "status": "available",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Book.objects.filter(title="Fluent Python").exists())

    def test_create_available_ignores_loan_details(self):
        response = self.client.post(self.url(), {
            "title": "T", "author": "A", "status": "available",
            "borrower": "B001", "date_of_borrow": "2026-10-01", "return_due_date": "2026-10-10",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.json()["borrower"])
        self.assertIsNone(response.json()["date_of_borrow"])

    def test_put_changes_borrower(self):
        response = self.client.put(self.url(self.book.id), {
            "title": "Two Scoops of Django", "author": "Feldroy", "number_of_copies": 3,
            "status": "borrowed", "borrower": "B002",
            "date_of_borrow": "2026-10-01", "return_due_date": "2026-10-15",
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.book.refresh_from_db()
        self.assertEqual(self.book.borrower, self.rahul)

    def test_put_requires_all_fields(self):
        response = self.client.put(self.url(self.book.id), {"status": "available"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("title", response.json())
        self.assertIn("author", response.json())

    def test_patch_partial_update(self):
        response = self.client.patch(self.url(self.book.id), {"number_of_copies": 7}, format="json")
        self.assertEqual(response.status_code, 200)
        self.book.refresh_from_db()
        self.assertEqual(self.book.number_of_copies, 7)
        self.assertEqual(self.book.borrower, self.gagan)  # untouched fields kept

    def test_patch_to_available_clears_loan(self):
        response = self.client.patch(self.url(self.book.id), {"status": "available"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["borrower_name"])
        self.book.refresh_from_db()
        self.assertIsNone(self.book.borrower)
        self.assertIsNone(self.book.date_of_borrow)
        self.assertIsNone(self.book.return_due_date)

    def test_patch_validates_against_existing_values(self):
        # Only the due date is sent; it must still be checked against the stored borrow date.
        response = self.client.patch(self.url(self.book.id), {"return_due_date": "2026-09-01"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("return_due_date", response.json())

    def test_delete(self):
        response = self.client.delete(self.url(self.book.id))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Book.objects.filter(id=self.book.id).exists())

    def test_missing_book_returns_404(self):
        self.assertEqual(self.client.get(self.url(99999)).status_code, 404)
        self.assertEqual(self.client.put(self.url(99999), {"title": "T", "author": "A"}, format="json").status_code, 404)
        self.assertEqual(self.client.patch(self.url(99999), {}, format="json").status_code, 404)
        self.assertEqual(self.client.delete(self.url(99999)).status_code, 404)

    # --- Search, filter, stats -----------------------------------------------
    def test_search_and_status_filter(self):
        titles = lambda r: [b["title"] for b in r.json()]
        self.assertEqual(titles(self.client.get(self.url(), {"search": "django"})), ["Two Scoops of Django"])
        self.assertEqual(titles(self.client.get(self.url(), {"search": "DJANGO"})), ["Two Scoops of Django"])
        self.assertEqual(titles(self.client.get(self.url(), {"search": "Feldroy"})), ["Two Scoops of Django"])
        self.assertEqual(titles(self.client.get(self.url(), {"search": "Gagan"})), ["Two Scoops of Django"])
        self.assertEqual(titles(self.client.get(self.url(), {"search": "B001"})), ["Two Scoops of Django"])
        self.assertEqual(titles(self.client.get(self.url(), {"search": "available"})), ["Clean Code"])
        self.assertEqual(titles(self.client.get(self.url(), {"search": "Rahul"})), [])
        self.assertEqual(titles(self.client.get(self.url(), {"status": "available"})), ["Clean Code"])
        self.assertEqual(titles(self.client.get(self.url(), {"status": "BORROWED"})), ["Two Scoops of Django"])
        self.assertEqual(titles(self.client.get(self.url(), {"search": "django", "status": "available"})), [])
        self.assertEqual(len(self.client.get(self.url(), {"status": "nonsense"}).json()), 2)  # ignored

    def test_stats(self):
        response = self.client.get("/api/books/stats/")
        self.assertEqual(response.json(), {"total": 2, "available": 1, "borrowed": 1, "overdue": 0})

    # --- Validation -----------------------------------------------------------
    def test_validation_errors(self):
        cases = [
            ({"title": " ", "author": "A", "status": "available"}, "title"),
            ({"title": "T", "author": "", "status": "available"}, "author"),
            ({"title": "T", "author": "A", "number_of_copies": -1}, "number_of_copies"),
            ({"title": "T", "author": "A", "number_of_copies": "abc"}, "number_of_copies"),
            ({"title": "T", "author": "A", "status": "lost"}, "status"),
            ({"title": "T", "author": "A", "status": "borrowed"}, "borrower"),
            ({"title": "T", "author": "A", "status": "borrowed", "borrower": "B001",
              "return_due_date": "2026-10-10"}, "date_of_borrow"),
            ({"title": "T", "author": "A", "status": "overdue", "borrower": "B001",
              "date_of_borrow": "2026-10-10", "return_due_date": "2026-10-01"}, "return_due_date"),
            ({"title": "T", "author": "A", "status": "borrowed", "borrower": "B999",
              "date_of_borrow": "2026-10-01", "return_due_date": "2026-10-10"}, "borrower"),
            ({"title": "T", "author": "A", "status": "borrowed", "borrower": "B001",
              "date_of_borrow": "not-a-date", "return_due_date": "2026-10-10"}, "date_of_borrow"),
            ({"title": "x" * 201, "author": "A"}, "title"),
        ]
        for payload, field in cases:
            with self.subTest(field=field, payload=payload):
                response = self.client.post(self.url(), payload, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())
        self.assertEqual(Book.objects.count(), 2)  # nothing invalid was saved

    def test_malformed_json(self):
        response = self.client.post(self.url(), "{bad json", content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_borrowers_endpoint_is_read_only(self):
        self.assertEqual(len(self.client.get("/api/borrowers/").json()), 2)
        response = self.client.post("/api/borrowers/", {"borrower_id": "B099", "name": "X"}, format="json")
        self.assertEqual(response.status_code, 405)

    # --- Error handling -------------------------------------------------------
    def test_database_error_returns_safe_503(self):
        with mock.patch("books.views.BookViewSet.get_queryset", side_effect=OperationalError("secret detail")):
            response = self.client.get(self.url())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret detail", response.content.decode())
        self.assertIn("database", response.json()["detail"].lower())


class ModelRuleTests(TestCase):
    def setUp(self):
        clear_demo_data()
        self.borrower = Borrower.objects.create(borrower_id="B001", name="Gagan")

    def test_admin_validation_rules(self):
        book = Book(title="T", author="A", status=Book.Status.BORROWED)
        with self.assertRaises(ValidationError):
            book.clean()

        book = Book(title="T", author="A", status=Book.Status.AVAILABLE, borrower=self.borrower,
                    date_of_borrow=date(2026, 10, 1), return_due_date=date(2026, 10, 5))
        book.clean()
        self.assertIsNone(book.borrower)
        self.assertIsNone(book.date_of_borrow)

    def test_borrower_with_books_cannot_be_deleted(self):
        Book.objects.create(title="T", author="A", status=Book.Status.BORROWED, borrower=self.borrower,
                            date_of_borrow=date(2026, 10, 1), return_due_date=date(2026, 10, 5))
        with self.assertRaises(ProtectedError):
            self.borrower.delete()


class SeedDataTests(TransactionTestCase):
    # TransactionTestCase because "seed_data --reset" runs ALTER TABLE, which MySQL
    # commits immediately (normal TestCase relies on rolling back a transaction).
    def test_seed_counts_and_repeatable(self):
        call_command("seed_data", stdout=StringIO())
        call_command("seed_data", stdout=StringIO())
        self.assertEqual(Borrower.objects.count(), 10)
        self.assertEqual(Book.objects.count(), 15)

    def test_reset_restores_demo_state(self):
        call_command("seed_data", stdout=StringIO())
        Book.objects.filter(title="Clean Code").update(status="available", borrower=None,
                                                       date_of_borrow=None, return_due_date=None)
        Book.objects.create(title="Extra", author="X")
        call_command("seed_data", "--reset", stdout=StringIO())
        self.assertEqual(Book.objects.count(), 15)
        self.assertEqual(Book.objects.get(title="Clean Code").status, "borrowed")

    def test_seed_data_is_correct_on_demo_day(self):
        call_command("seed_data", stdout=StringIO())
        for book in Book.objects.all():
            with self.subTest(book=book.title):
                book.full_clean()  # every seeded record passes the app's own rules
                if book.status == Book.Status.BORROWED:
                    self.assertGreater(book.return_due_date, DEMO_DAY)
                    self.assertLess(book.date_of_borrow, DEMO_DAY)
                elif book.status == Book.Status.OVERDUE:
                    self.assertLess(book.return_due_date, DEMO_DAY)
                else:
                    self.assertIsNone(book.borrower)
        for status in Book.Status.values:
            self.assertTrue(Book.objects.filter(status=status).exists())


class PagesAndConfigTests(TestCase):
    def test_index_and_health(self):
        self.assertContains(self.client.get("/"), "Library Management System")
        self.assertEqual(self.client.get("/healthz/").json(), {"status": "ok"})
        self.assertEqual(self.client.get("/readyz/").json()["database"], "ok")

    def test_readyz_reports_database_down(self):
        with mock.patch("books.views.connection.cursor", side_effect=OperationalError("down")):
            response = self.client.get("/readyz/")
        self.assertEqual(response.status_code, 503)

    def test_admin_pages(self):
        admin = get_user_model().objects.create_superuser("admin", "admin@example.com", "pass12345")
        self.client.force_login(admin)
        for url in ["/admin/books/book/", "/admin/books/borrower/", "/admin/books/book/add/",
                    "/admin/books/book/?q=django", "/admin/books/book/?status__exact=overdue"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_any_host_accepted_for_kubernetes(self):
        # Pod IP (kubelet probes), Service name and Ingress hostname must all work.
        for host in ["10.42.0.15:8000", "library-django:8000", "library.local"]:
            with self.subTest(host=host):
                self.assertEqual(self.client.get("/readyz/", HTTP_HOST=host).status_code, 200)
                self.assertEqual(self.client.get("/api/books/stats/", HTTP_HOST=host).status_code, 200)

    def test_https_detected_behind_traefik(self):
        response = self.client.get("/healthz/", HTTP_X_FORWARDED_PROTO="https")
        self.assertTrue(response.wsgi_request.is_secure())

    def test_required_env_fails_clearly(self):
        with mock.patch.dict(os.environ, {"DB_HOST": ""}):
            with self.assertRaisesMessage(ImproperlyConfigured, "DB_HOST"):
                required_env("DB_HOST")


class ActivityLogTests(APITestCase):
    """CRUD/REFRESH/ERROR activity is stored and shown on the View Logs page."""

    def setUp(self):
        cache.clear()  # repeat-suppression state must not leak between tests
        clear_demo_data()
        ActivityLog.objects.all().delete()
        self.borrower = Borrower.objects.create(borrower_id="B001", name="Gagan Venkatesh")
        self.book = Book.objects.create(title="Clean Code", author="Robert C. Martin")

    def entries(self, action=None):
        rows = ActivityLog.objects.order_by("id")
        return list(rows.filter(action=action) if action else rows)

    def later(self, seconds):
        """Pretend `seconds` have passed for the in-memory cache's expiry checks."""
        return mock.patch("django.core.cache.backends.locmem.time.time", return_value=time.time() + seconds)

    def test_crud_operations_are_logged_after_success(self):
        new_id = self.client.post("/api/books/", {"title": "Fluent Python", "author": "L"}, format="json").json()["id"]
        self.client.get(f"/api/books/{new_id}/")
        self.client.patch(f"/api/books/{new_id}/", {"status": "borrowed", "borrower": "B001",
                          "date_of_borrow": "2026-10-01", "return_due_date": "2026-10-20"}, format="json")
        self.client.patch(f"/api/books/{new_id}/", {"status": "available"}, format="json")
        self.client.delete(f"/api/books/{new_id}/")

        got = [(e.action, e.level, e.book_id) for e in self.entries()]
        self.assertEqual(got, [("CREATE", "INFO", new_id), ("READ", "INFO", new_id), ("UPDATE", "INFO", new_id),
                               ("UPDATE", "INFO", new_id), ("DELETE", "INFO", new_id)])
        messages = [e.message for e in self.entries()]
        self.assertIn("lent to B001 (Available -> Borrowed)", messages[2])
        self.assertIn("returned (Borrowed -> Available)", messages[3])

    def test_repeated_automatic_reads_are_logged_once(self):
        for _ in range(3):
            self.client.get("/api/books/")  # e.g. the table reloading after every save
        self.client.get("/api/books/", {"status": "borrowed"})  # a new filter is a new READ
        self.assertEqual(len(self.entries("READ")), 2)
        with self.later(31):
            self.client.get("/api/books/")
        self.assertEqual(len(self.entries("READ")), 3)

    def test_page_open_then_refresh(self):
        self.client.get("/")
        self.client.get("/api/books/")  # the page's own table load: not a second entry
        self.client.get("/")            # burst reload within 5 s: not logged again
        self.assertEqual([e.action for e in self.entries()], ["READ"])
        with self.later(6):
            self.client.get("/")
        self.assertEqual([(e.action, e.message) for e in self.entries()],
                         [("READ", "Library page opened"), ("REFRESH", "Library page refreshed")])

    def test_failures_are_logged_as_errors(self):
        self.client.post("/api/books/", {"title": "T", "author": "A", "status": "borrowed"}, format="json")
        self.client.delete("/api/books/99999/")
        with mock.patch("books.views.BookViewSet.get_queryset", side_effect=OperationalError("secret detail")):
            self.client.get("/api/books/")

        errors = self.entries("ERROR")
        self.assertEqual([(e.level, e.book_id) for e in errors], [("WARNING", None), ("WARNING", 99999), ("ERROR", None)])
        self.assertIn("CREATE failed: invalid data (borrower, date_of_borrow, return_due_date)", errors[0].message)
        self.assertIn("DELETE failed: book not found", errors[1].message)
        self.assertIn("READ failed: database error (OperationalError)", errors[2].message)
        self.assertNotIn("secret detail", errors[2].message)  # DB error text is never stored
        self.assertFalse(self.entries("CREATE"))               # nothing invalid was logged as success

    def test_admin_changes_are_logged(self):
        admin = get_user_model().objects.create_superuser("admin", "admin@example.com", "pass12345")
        self.client.force_login(admin)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/admin/books/book/{self.book.id}/delete/", {"post": "yes"})
        entry = self.entries("DELETE")[0]
        self.assertEqual(entry.book_id, self.book.id)
        self.assertIn("deleted via admin (user: admin)", entry.message)

    def test_logs_page_requires_staff_login(self):
        self.assertRedirects(self.client.get("/logs/"), "/admin/login/?next=/logs/")
        self.assertEqual(self.client.get("/logs/data/").status_code, 403)
        user = get_user_model().objects.create_user("reader", password="pass12345")  # not staff
        self.client.force_login(user)
        self.assertEqual(self.client.get("/logs/").status_code, 302)
        self.assertEqual(self.client.get("/logs/data/").status_code, 403)

    def test_logs_page_shows_stored_records_with_filter(self):
        staff = get_user_model().objects.create_superuser("admin", "admin@example.com", "pass12345")
        self.client.force_login(staff)
        empty = self.client.get("/logs/data/").json()
        self.assertEqual((empty["entries"], empty["summary"]), ([], {"total": 0, "success": 0, "errors": 0}))

        self.client.post("/api/books/", {"title": "Fluent Python", "author": "L"}, format="json")
        self.client.delete(f"/api/books/{self.book.id}/")
        self.client.delete("/api/books/99999/")

        page = self.client.get("/logs/")
        self.assertContains(page, "Activity Logs")
        self.assertContains(page, "Back to Library")
        data = self.client.get("/logs/data/").json()
        self.assertEqual(data["summary"], {"total": 3, "success": 2, "errors": 1})
        self.assertEqual([e["action"] for e in data["entries"]], ["ERROR", "DELETE", "CREATE"])  # newest first
        self.assertEqual(data["entries"][1]["book_id"], self.book.id)

        only = self.client.get("/logs/data/", {"action": "DELETE"}).json()["entries"]
        self.assertEqual([e["action"] for e in only], ["DELETE"])
        self.assertEqual(len(self.client.get("/logs/data/", {"action": "../etc"}).json()["entries"]), 3)  # ignored

    def test_index_has_view_logs_button(self):
        self.assertContains(self.client.get("/"), 'href="/logs/"')
