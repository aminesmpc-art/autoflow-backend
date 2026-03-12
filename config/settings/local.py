"""Local development settings."""
from .base import *  # noqa: F401, F403

DEBUG = True

# Use SQLite for quick local dev without Docker
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
    }
}

# Console email backend
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Allow all origins in dev
CORS_ALLOW_ALL_ORIGINS = True

# Disable throttling in dev
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []  # noqa: F405
