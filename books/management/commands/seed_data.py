from django.core.management.base import BaseCommand
from django.db import connection, transaction

from books.demo_data import load_demo_data
from books.models import Book, Borrower


class Command(BaseCommand):
    help = (
        "Load the demo borrowers and books (also loaded automatically by `migrate`). "
        "Safe to run repeatedly (no duplicates)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete ALL books and borrowers first, then load a fresh copy of the demo data.",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            self.reset()
        with transaction.atomic():
            borrowers_created, books_created = load_demo_data(Borrower, Book)
        self.stdout.write(self.style.SUCCESS(
            f"Borrowers: {borrowers_created} created, {Borrower.objects.count()} total. "
            f"Books: {books_created} created, {Book.objects.count()} total."
        ))

    def reset(self):
        with transaction.atomic():
            Book.objects.all().delete()  # books first: borrowers are protected while referenced
            Borrower.objects.all().delete()
        # Restart IDs at 1 so the demo data always has the same IDs (/api/books/1/ ...).
        with connection.cursor() as cursor:
            for model in (Book, Borrower):
                cursor.execute(f"ALTER TABLE {connection.ops.quote_name(model._meta.db_table)} AUTO_INCREMENT = 1")
