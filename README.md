# Library Management System

A basic Library Management System built with **Django + Django REST Framework + MySQL**,
with a simple web UI (Django templates, CSS, vanilla JavaScript).

This is the application phase of a DevOps assignment. It will later be deployed with
Docker, Helm, Kubernetes (RKE2), Traefik Ingress and Ansible. The code is designed to
move into those environments **without source changes**: all configuration comes from
environment variables.

## Architecture

```
Browser (HTML/CSS/JS)
   │  fetch() JSON
   ▼
Django  ──  REST API (Django REST Framework: serializers + viewsets)
   │
   ▼
Django ORM
   │  TCP (DB_HOST:DB_PORT)
   ▼
MySQL  (local: 127.0.0.1:3306  →  Kubernetes later: mysql:3306)
```

## Project layout

```
library_management/settings.py  All settings; reads environment variables, MySQL only
library_management/urls.py      /admin/ + the books app
books/models.py         Borrower, Book (+ shared validation rules)
books/serializers.py    JSON <-> model conversion and validation for the API
books/views.py          BookViewSet (CRUD, search, status filter, stats), borrowers, health
books/urls.py           API routes
books/exceptions.py     Turns database outages into a safe 503 JSON message
books/admin.py          Django admin registration
books/demo_data.py      Demo borrowers + books (single source of the sample data)
books/migrations/0002_demo_data.py       Loads the demo data during `migrate`
books/management/commands/seed_data.py   Reload / reset the demo data on demand
books/templates/books/index.html         The single page UI
books/static/books/css/app.css, js/app.js
books/tests.py          Automated tests (run against MySQL)
```

## Configuration (environment variables)

| Variable | Example (local) | Notes |
|---|---|---|
| `DJANGO_SECRET_KEY` | long random string | **Required** |
| `DJANGO_DEBUG` | `True` | Defaults to `False` |
| `DJANGO_ALLOWED_HOSTS` | `*` | Defaults to `*` (Ingress host, Service name and pod-IP probes all work) |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://library.local` | Optional, only needed when served over HTTPS |
| `DB_NAME` | `library_db` | **Required** |
| `DB_USER` | `library_user` | **Required** |
| `DB_PASSWORD` | | **Required** |
| `DB_HOST` | `127.0.0.1` | **Required**. In Kubernetes: `mysql` |
| `DB_PORT` | `3306` | Defaults to 3306 |

Locally these live in `.env` (git-ignored). Copy `.env.example` to `.env` to start.
If a required variable is missing, Django stops with a clear error. There is **no SQLite fallback**.

## Run locally

One-time MySQL setup (as root):

```sql
CREATE DATABASE IF NOT EXISTS library_db;
CREATE USER IF NOT EXISTS 'library_user'@'%' IDENTIFIED BY '<password>';
GRANT ALL PRIVILEGES ON library_db.* TO 'library_user'@'%';
GRANT ALL PRIVILEGES ON test_library_db.* TO 'library_user'@'%';
FLUSH PRIVILEGES;
```

Then:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env          # then edit the values
python manage.py migrate        # creates the tables AND loads the demo data
python manage.py createsuperuser   # optional, for /admin/
python manage.py runserver
```

Open http://127.0.0.1:8000/

## Demo data

The sample data is defined in code (`books/demo_data.py`), not only in a database:
**10 borrowers (B001-B010)** and **15 books** (7 Available, 5 Borrowed, 3 Overdue).
The dates are fixed and planned for the demo on **15 Oct 2026**: borrowed books are
due after that day, overdue books were due before it.

- **Loaded automatically by `python manage.py migrate`** (data migration `0002_demo_data`).
  Any new, empty database - local, Docker or Kubernetes - gets the demo data with no extra step.
- `python manage.py seed_data` adds any missing demo records (never duplicates, never overwrites UI edits).
- `python manage.py seed_data --reset` deletes all books and borrowers and loads a fresh
  copy with IDs starting at 1 (use this right before the demo).

## Tests

Run the automated tests (uses a temporary `test_library_db`):

```powershell
python manage.py test
```

## REST API

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/books/` | List books (`?search=<term>`, `?status=available\|borrowed\|overdue`) |
| POST | `/api/books/` | Create |
| GET | `/api/books/<id>/` | Retrieve |
| PUT | `/api/books/<id>/` | Full update |
| PATCH | `/api/books/<id>/` | Partial update |
| DELETE | `/api/books/<id>/` | Delete |
| GET | `/api/books/stats/` | Dashboard counts |
| GET | `/api/borrowers/` | Borrower list |
| GET | `/healthz/` | Liveness (no DB) |
| GET | `/readyz/` | Readiness (checks MySQL) |

Search covers title, author, borrower name, borrower ID and status.
The `borrower` field uses the library card ID (e.g. `"B001"`).

```bash
curl http://127.0.0.1:8000/api/books/?search=django

curl -X POST http://127.0.0.1:8000/api/books/ -H "Content-Type: application/json" \
  -d '{"title":"Clean Architecture","author":"Robert C. Martin","number_of_copies":2,
       "status":"borrowed","borrower":"B001","date_of_borrow":"2026-10-07","return_due_date":"2026-10-21"}'

curl http://127.0.0.1:8000/api/books/1/

# use the "id" returned by the POST above
curl -X PATCH http://127.0.0.1:8000/api/books/<id>/ -H "Content-Type: application/json" -d '{"status":"available"}'

curl -X DELETE http://127.0.0.1:8000/api/books/<id>/
```

## Validation rules

- Title and author cannot be empty; number of copies cannot be negative.
- Borrowed / Overdue books need a borrower, a date of borrow and a return due date.
- Return due date cannot be before the date of borrow.
- Setting a book to Available clears its borrower and dates automatically.
- Only existing borrowers can be assigned.

## Verify directly in MySQL

```sql
USE library_db;
SHOW TABLES;
SELECT * FROM books_borrower;
SELECT b.id, b.status, b.title, b.number_of_copies, b.author,
       b.date_of_borrow, b.return_due_date, r.name AS borrower_name, r.borrower_id
FROM books_book b LEFT JOIN books_borrower r ON r.id = b.borrower_id
ORDER BY b.title;
```

Note: `books_book.borrower_id` is the foreign key (a number pointing to `books_borrower.id`).
`books_borrower.borrower_id` is the card ID such as `B001`.

## Docker

```dockerfile
FROM python:3.14
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
EXPOSE 8000
CMD python manage.py migrate && gunicorn library_management.wsgi -b 0.0.0.0:8000
```

- `python:3.14` (full image) already contains the compiler and MySQL client library that
  `mysqlclient` needs, so no extra system packages are installed.
- `.dockerignore` keeps `.env`, `.venv` and caches out of the image, so **no secrets are baked in**.
- On every container start: `migrate` (tables + demo data on a new database; nothing duplicated
  on later starts), then Gunicorn on port 8000.
- No `collectstatic` step: WhiteNoise (`WHITENOISE_USE_FINDERS = True`) serves CSS/JS straight
  from the apps' `static/` folders.

Build and run (MySQL must be reachable from the container):

```bash
docker build -t library-app:1.0 .

docker run -d --name library-app -p 8000:8000   -e DJANGO_SECRET_KEY='<long-random-string>'   -e DB_HOST=<mysql-host> -e DB_PORT=3306   -e DB_NAME=library_db -e DB_USER=library_user -e DB_PASSWORD='<password>'   library-app:1.0

docker logs -f library-app            # migrate output + gunicorn access logs
curl http://localhost:8000/readyz/    # {"status": "ok", "database": "ok"}
```

`DB_HOST` is the only value that differs per environment (e.g. the MySQL VM's IP for a
plain `docker run`, `mysql` in Kubernetes). If the MySQL user was created as
`'library_user'@'%'`, connections from the container are allowed.

## Container / deployment readiness

- All configuration comes from environment variables; `DJANGO_DEBUG` defaults to `False`.
- `ALLOWED_HOSTS` defaults to `*` so Kubernetes probes (pod IP), the Service name and the Ingress host all work.
- `SECURE_PROXY_SSL_HEADER` is set, so HTTPS terminated at Traefik is recognised (admin login works over HTTPS).
- TCP connection to MySQL; no socket, no SQLite, no Windows paths.
- Stateless: no files are written by the app; all data lives in MySQL.
- Logs go to stdout/stderr.
- `/healthz/` (liveness) and `/readyz/` (readiness) for Kubernetes probes.
  If MySQL is unreachable, `/healthz/` stays 200, `/readyz/` returns 503 and the API returns a safe 503 message.
- If MySQL is not reachable at startup, `migrate` fails and the container exits; Docker/Kubernetes restarts it
  until MySQL is up.
- `manage.py check --deploy` only reports HTTPS hardening warnings (secure cookies, HSTS, SSL redirect);
  these apply once TLS is enabled at the Ingress.
