"""Production settings — optimized for Railway deployment."""
import dj_database_url

from .base import *  # noqa: F401, F403

DEBUG = False

# ── Database (Railway provides DATABASE_URL) ──
if database_url := config("DATABASE_URL", default=""):  # noqa: F405
    DATABASES = {"default": dj_database_url.parse(database_url)}

# ── Security ──
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)  # noqa: F405
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # Railway is behind a proxy

# ── Static files with WhiteNoise ──
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")  # noqa: F405
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ── Email (use SMTP in production) ──
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

# ── ALLOWED_HOSTS (Railway sets RAILWAY_PUBLIC_DOMAIN) ──
RAILWAY_DOMAIN = config("RAILWAY_PUBLIC_DOMAIN", default="")  # noqa: F405
if RAILWAY_DOMAIN:
    ALLOWED_HOSTS.append(RAILWAY_DOMAIN)  # noqa: F405
