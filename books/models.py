from django.core.exceptions import ValidationError
from django.db import models


class Borrower(models.Model):
    """A pre-populated library member (not a login account)."""

    name = models.CharField(max_length=100)
    borrower_id = models.CharField(max_length=20, unique=True, help_text="Library card ID, e.g. B001")

    class Meta:
        ordering = ["borrower_id"]

    def __str__(self):
        return f"{self.borrower_id} - {self.name}"


class Book(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        BORROWED = "borrowed", "Borrowed"
        OVERDUE = "overdue", "Overdue"

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.AVAILABLE)
    title = models.CharField(max_length=200)
    number_of_copies = models.PositiveIntegerField(default=1)
    author = models.CharField(max_length=150)
    date_of_borrow = models.DateField(null=True, blank=True)
    return_due_date = models.DateField(null=True, blank=True)
    # PROTECT: a borrower who still has books on record cannot be deleted.
    borrower = models.ForeignKey(
        Borrower, on_delete=models.PROTECT, null=True, blank=True, related_name="books"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]  # same order as the rows in MySQL (order of insertion)

    def __str__(self):
        return f"{self.title} by {self.author}"

    def clean(self):
        """Used by Django admin forms; the API uses the same rules via the serializer."""
        if self.status == self.Status.AVAILABLE:
            self.borrower = None
            self.date_of_borrow = None
            self.return_due_date = None
        errors = loan_rule_errors(self.status, self.borrower, self.date_of_borrow, self.return_due_date)
        if errors:
            raise ValidationError(errors)


def loan_rule_errors(status, borrower, date_of_borrow, return_due_date):
    """Business rules shared by the admin (Model.clean) and the REST API (serializer).

    Returns a dict of {field_name: message}; empty dict means valid.
    """
    errors = {}
    if status in (Book.Status.BORROWED, Book.Status.OVERDUE):
        label = Book.Status(status).label
        if borrower is None:
            errors["borrower"] = f"A {label.lower()} book must have a borrower."
        if date_of_borrow is None:
            errors["date_of_borrow"] = f"Date of borrow is required for {label.lower()} books."
        if return_due_date is None:
            errors["return_due_date"] = f"Return due date is required for {label.lower()} books."
    if date_of_borrow and return_due_date and return_due_date < date_of_borrow:
        errors["return_due_date"] = "Return due date cannot be before the date of borrow."
    return errors


class ActivityLog(models.Model):
    """One stored application log record, shown on the View Logs page.

    Rows are written by books.log_handlers.ActivityLogHandler (a standard
    logging handler); the same records are also printed to stdout.
    """

    class Action(models.TextChoices):
        CREATE = "CREATE"
        READ = "READ"
        UPDATE = "UPDATE"
        DELETE = "DELETE"
        REFRESH = "REFRESH"
        ERROR = "ERROR"

    timestamp = models.DateTimeField(db_index=True)
    action = models.CharField(max_length=10, choices=Action.choices, db_index=True)
    level = models.CharField(max_length=10)
    message = models.CharField(max_length=500)
    # Plain number, not a ForeignKey: the log must survive the book being deleted.
    book_id = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"[{self.level}] {self.action}: {self.message}"
