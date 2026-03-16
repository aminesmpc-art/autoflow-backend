"""
AutoFlow backend – base settings.
Shared across all environments. Never import this directly;
use local.py or production.py instead.
"""
import os
from datetime import timedelta
from pathlib import Path

from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ── Security ──
SECRET_KEY = config("SECRET_KEY", default="insecure-dev-key-change-me")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

# ── Apps ──
DJANGO_APPS = [
    "unfold",  # Must be before django.contrib.admin
    "unfold.contrib.filters",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "corsheaders",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
]

LOCAL_APPS = [
    "apps.users",
    "apps.plans",
    "apps.usage",
    "apps.rewards",
    "apps.webhooks",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ── Unfold Admin Theme ──
UNFOLD = {
    "SITE_TITLE": "AutoFlow Admin",
    "SITE_HEADER": "AutoFlow",
    "SITE_SUBHEADER": "Manage Users, Plans & Usage",
    "SITE_URL": "/api/health",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "THEME": "dark",
    "DASHBOARD_CALLBACK": "apps.dashboard.dashboard_callback",
    "COLORS": {
        "primary": {
            "50": "#ecfeff",
            "100": "#cffafe",
            "200": "#a5f3fc",
            "300": "#67e8f9",
            "400": "#22d3ee",
            "500": "#06b6d4",
            "600": "#0891b2",
            "700": "#0e7490",
            "800": "#155e75",
            "900": "#164e63",
            "950": "#083344",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Users & Auth",
                "separator": True,
                "items": [
                    {
                        "title": "All Users",
                        "icon": "person",
                        "link": "/admin/users/customuser/",
                        "badge": "apps.dashboard.badge_callback_users",
                    },
                    {
                        "title": "Verification Tokens",
                        "icon": "verified",
                        "link": "/admin/users/emailverificationtoken/",
                    },
                    {
                        "title": "Groups",
                        "icon": "group",
                        "link": "/admin/auth/group/",
                    },
                ],
            },
            {
                "title": "Plans & Usage",
                "separator": True,
                "items": [
                    {
                        "title": "Plans & Profiles",
                        "icon": "badge",
                        "link": "/admin/plans/profile/",
                        "badge": "apps.dashboard.badge_callback_pro",
                    },
                    {
                        "title": "Daily Stats",
                        "icon": "analytics",
                        "link": "/admin/usage/dailyusage/",
                        "badge": "apps.dashboard.badge_callback_today_usage",
                    },
                    {
                        "title": "Activity Log",
                        "icon": "event",
                        "link": "/admin/usage/usageevent/",
                    },
                ],
            },
            {
                "title": "Rewards & Webhooks",
                "separator": True,
                "items": [
                    {
                        "title": "Bonus Credits",
                        "icon": "stars",
                        "link": "/admin/rewards/rewardcreditledger/",
                    },
                    {
                        "title": "Payment Webhooks",
                        "icon": "webhook",
                        "link": "/admin/webhooks/webhookevent/",
                        "badge": "apps.dashboard.badge_callback_pending_webhooks",
                    },
                ],
            },
        ],
    },
}


# ── Middleware ──
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ── Database ──
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="autoflow"),
        "USER": config("DB_USER", default="autoflow"),
        "PASSWORD": config("DB_PASSWORD", default="autoflow"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
    }
}

# ── Custom user model ──
AUTH_USER_MODEL = "users.CustomUser"

# ── Password validation ──
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ── i18n ──
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ── Static files ──
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Django REST Framework ──
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
    ),
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/minute",
        "user": "120/minute",
    },
    "EXCEPTION_HANDLER": "apps.api.exceptions.custom_exception_handler",
}

# ── Simple JWT ──
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=config("JWT_ACCESS_LIFETIME_MINUTES", default=60, cast=int)
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=config("JWT_REFRESH_LIFETIME_DAYS", default=7, cast=int)
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# ── CORS ──
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:3000",
    cast=Csv(),
)
CORS_ALLOW_CREDENTIALS = True

# ── Email (Resend) ──
RESEND_API_KEY = config("RESEND_API_KEY", default="")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="AutoFlow <noreply@auto-flow.studio>")

# ── App config ──
VERIFY_EMAIL_BASE_URL = config(
    "VERIFY_EMAIL_BASE_URL",
    default="https://api.auto-flow.studio/api/auth/verify-email",
)
VERIFICATION_TOKEN_EXPIRY_HOURS = config(
    "VERIFICATION_TOKEN_EXPIRY_HOURS", default=24, cast=int
)
FREE_DAILY_PROMPT_LIMIT = config("FREE_DAILY_PROMPT_LIMIT", default=30, cast=int)

# ── Whop ──
WHOP_WEBHOOK_SECRET = config("WHOP_WEBHOOK_SECRET", default="")

# ── Logging ──
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "apps": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
    },
}
