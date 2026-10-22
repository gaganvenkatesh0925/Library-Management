"""Data migration: load the demo borrowers and books.

Runs automatically as part of `python manage.py migrate`, right after the tables
are created in 0001_initial. A brand-new database therefore comes up with the
demo data already in it - no extra command needed after deployment.
"""
from django.db import migrations

from books.demo_data import load_demo_data


def load(apps, schema_editor):
    load_demo_data(apps.get_model("books", "Borrower"), apps.get_model("books", "Book"))


class Migration(migrations.Migration):
    dependencies = [("books", "0001_initial")]

    # Reverse is a no-op: un-applying this migration keeps the data.
    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
