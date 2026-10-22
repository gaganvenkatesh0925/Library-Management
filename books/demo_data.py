"""Demo borrowers and books - the single place where the sample data is defined.

Used by:
  * migration 0002_demo_data  -> loaded automatically by `python manage.py migrate`,
                                 so every new database (local, Docker, Kubernetes) gets it
  * `python manage.py seed_data [--reset]` -> reload it on demand

Planned for the demo on 15 Oct 2026:
  Borrowed -> borrowed on or before 8 Oct, due after 15 Oct (still on time)
  Overdue  -> due date already passed before 15 Oct
"""
from datetime import date

BORROWERS = [
    ("B001", "Gagan Venkatesh"),
    ("B002", "Rahul Kumar"),
    ("B003", "Ananya Sharma"),
    ("B004", "Priya Nair"),
    ("B005", "Arjun Mehta"),
    ("B006", "Sneha Reddy"),
    ("B007", "Karthik Iyer"),
    ("B008", "Divya Menon"),
    ("B009", "Vikram Singh"),
    ("B010", "Meera Joshi"),
]

# (title, author, copies, status, borrower card ID, date of borrow, return due date)
BOOKS = [
    # Statuses are mixed on purpose: the table shows books in ID order (like MySQL),
    # so this order is what the website displays. Totals: 7 available, 5 borrowed, 3 overdue.
    ("Two Scoops of Django", "Daniel & Audrey Feldroy", 3, "borrowed", "B001", date(2026, 10, 6), date(2026, 10, 20)),
    ("Django for Beginners", "William S. Vincent", 4, "available", None, None, None),
    ("Kubernetes Up & Running", "Brendan Burns", 2, "overdue", "B008", date(2026, 9, 10), date(2026, 9, 24)),
    ("Clean Code", "Robert C. Martin", 2, "borrowed", "B002", date(2026, 10, 8), date(2026, 10, 22)),
    ("The Pragmatic Programmer", "Andrew Hunt & David Thomas", 3, "available", None, None, None),
    ("Docker Deep Dive", "Nigel Poulton", 5, "available", None, None, None),
    ("Ansible for DevOps", "Jeff Geerling", 2, "borrowed", "B003", date(2026, 10, 7), date(2026, 10, 21)),
    ("Site Reliability Engineering", "Betsy Beyer", 1, "overdue", "B004", date(2026, 9, 15), date(2026, 9, 29)),
    ("Fluent Python", "Luciano Ramalho", 3, "available", None, None, None),
    ("Learning MySQL", "Vinicius M. Grippa & Sergey Kuzmichev", 2, "borrowed", "B005", date(2026, 10, 3), date(2026, 10, 24)),
    ("Designing Data-Intensive Applications", "Martin Kleppmann", 1, "available", None, None, None),
    ("The DevOps Handbook", "Gene Kim, Jez Humble & Patrick Debois", 2, "overdue", "B007", date(2026, 9, 20), date(2026, 10, 4)),
    ("The Phoenix Project", "Gene Kim", 4, "available", None, None, None),
    ("Learning Helm", "Matt Butcher, Matt Farina & Josh Dolitsky", 1, "borrowed", "B006", date(2026, 10, 5), date(2026, 10, 19)),
    ("Python Crash Course", "Eric Matthes", 3, "available", None, None, None),
]


def load_demo_data(Borrower, Book):
    """Create any demo records that do not exist yet. Returns (borrowers_created, books_created).

    The models are passed in so the migration can use its historical models.
    Existing books (matched by title + author) are left untouched, so edits made
    in the UI are never overwritten.
    """
    borrowers_created = 0
    for card_id, name in BORROWERS:
        _, created = Borrower.objects.get_or_create(borrower_id=card_id, defaults={"name": name})
        borrowers_created += created

    books_created = 0
    for title, author, copies, status, card_id, borrowed_on, due_on in BOOKS:
        _, created = Book.objects.get_or_create(
            title=title,
            author=author,
            defaults={
                "number_of_copies": copies,
                "status": status,
                "borrower": Borrower.objects.get(borrower_id=card_id) if card_id else None,
                "date_of_borrow": borrowed_on,
                "return_due_date": due_on,
            },
        )
        books_created += created
    return borrowers_created, books_created
