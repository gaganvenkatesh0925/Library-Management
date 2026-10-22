"""
Django settings for the Library Management System.

All environment-specific values (secrets, database location, allowed hosts)
come from environment variables, so the same code runs unchanged locally,
in Docker and in Kubernetes. Locally they are loaded from a `.env` file;
in Kubernetes they will come from a ConfigMap and a Secret.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env if present (local development only). Real environment variables
# always win, so container/Kubernetes configuration is never overridden.
load_dotenv(BASE_DIR / ".env", override=False)


def required_env(name):
    """Return an environment variable or fail loudly if it is missing."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(
            f"Required environment variable '{name}' is not set. "
            "Copy .env.example to .env (local) or provide it via the "
            "container environment (Docker/Kubernetes)."
        )
    return value


def env_list(name, default=""):
    """Parse a comma-separated environment variable into a list."""
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# --- Core security settings -------------------------------------------------

SECRET_KEY = required_env("DJANGO_SECRET_KEY")

# Safe default: DEBUG is OFF unless explicitly enabled.
DEBUG = env_bool("DJANGO_DEBUG", False)

# "*" accepts any Host header. In Kubernetes the app is reached through the
# Ingress hostname, the Service name and the pod IP (used by health probes),
# so all of them must be accepted. Can be narrowed via the environment.
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "*")

# Optional: extra origins allowed to submit forms (e.g. the admin login) when
# the site is served over HTTPS, e.g. DJANGO_CSRF_TRUSTED_ORIGINS=https://library.local
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# Traefik terminates TLS and forwards plain HTTP to the pod; this header tells
# Django the original request was HTTPS (correct redirects and CSRF checks).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# --- Application definition --------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "books",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "library_management.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "library_management.wsgi.application"


# --- Database: MySQL only, over TCP -------------------------------------------
# There is deliberately NO SQLite fallback. If any DB_* variable is missing,
# Django refuses to start with a clear error.
# Local:      DB_HOST=127.0.0.1
# Kubernetes: DB_HOST=mysql   (the MySQL Service name)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": required_env("DB_NAME"),
        "USER": required_env("DB_USER"),
        "PASSWORD": required_env("DB_PASSWORD"),
        "HOST": required_env("DB_HOST"),
        "PORT": os.environ.get("DB_PORT", "3306"),
        "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", "60")),
        "OPTIONS": {
            "charset": "utf8mb4",
            "connect_timeout": 5,
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}


# --- Django REST Framework ----------------------------------------------------
# No login system is required, so the API is open and uses no authentication.

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "EXCEPTION_HANDLER": "books.exceptions.api_exception_handler",
}


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# --- Internationalization ------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Asia/Kolkata")
USE_I18N = True
USE_TZ = True


# --- Static files ---------------------------------------------------------------
# WhiteNoise serves CSS/JS directly from each app's static/ folder (books,
# admin, rest_framework), so no `collectstatic` step is needed - also when
# running under Gunicorn in the container.

STATIC_URL = "static/"
WHITENOISE_USE_FINDERS = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --- Logging: everything to stdout (container-friendly) -------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    # action_tag shows e.g. "[UPDATE book=16] " for library activity, "" otherwise.
    "filters": {"activity_tag": {"()": "books.log_handlers.ActivityTagFilter"}},
    "formatters": {"simple": {"format": "[{asctime}] {levelname} {name}: {action_tag}{message}", "style": "{"}},
    "handlers": {
        # StreamHandler defaults to stderr; send logs to stdout as intended.
        "console": {
            "class": "logging.StreamHandler", "stream": "ext://sys.stdout",
            "formatter": "simple", "filters": ["activity_tag"],
            "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
        },
        # Stores tagged activity records in MySQL for the View Logs page
        # (stdout and container files are lost on restart).
        "activity_db": {"class": "books.log_handlers.ActivityLogHandler", "level": "INFO"},
    },
    "root": {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {
        # Always INFO so the View Logs page keeps working even if DJANGO_LOG_LEVEL
        # quiets stdout; records still propagate to the root console handler.
        "books": {"handlers": ["activity_db"], "level": "INFO"},
        # Replace Django's default handlers on the "django" logger (an unformatted
        # console handler when DEBUG=True) so its records are not printed twice.
        "django": {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"), "propagate": False},
    },
}
