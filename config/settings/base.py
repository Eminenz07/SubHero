"""
SubHero — Base Settings
=======================
Shared settings for all environments.
Security hardened per PRD Section 7.1.
"""

import os
from pathlib import Path

from decouple import Csv, config

# =============================================================
# PATHS
# =============================================================
# BASE_DIR points to the project root (where manage.py lives)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# =============================================================
# SECURITY — PRD Section 7.1
# =============================================================
SECRET_KEY = config("SECRET_KEY", default="django-insecure-fallback-key-for-migrations-only-12345")

ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

# Admin URL — configurable via .env, randomised in production
ADMIN_URL = config("ADMIN_URL", default="admin/")

# HTTPS / SSL
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# HSTS — enforce HTTPS for 1 year (PRD: max-age=31536000; includeSubDomains)
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Clickjacking — PRD: X-Frame-Options DENY
X_FRAME_OPTIONS = "DENY"

# Content-Type sniffing — PRD: True
SECURE_CONTENT_TYPE_NOSNIFF = True

# Browser XSS filter
SECURE_BROWSER_XSS_FILTER = True

# =============================================================
# SESSION SECURITY — PRD Section 7.1
# =============================================================
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "sessions"
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
SESSION_COOKIE_AGE = 86400  # 24 hours default
SESSION_SAVE_EVERY_REQUEST = True

# =============================================================
# CSRF — PRD Section 7.1
# =============================================================
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="https://localhost",
    cast=Csv(),
)

# =============================================================
# APPLICATIONS
# =============================================================
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "django_ratelimit",
]

LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.wallet",
    "apps.payments",
    "apps.vtu",
    "apps.smm",
    "apps.transactions",
    "apps.notifications",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# =============================================================
# MIDDLEWARE
# =============================================================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.PinSetupMiddleware",
]

# =============================================================
# URL CONFIGURATION
# =============================================================
ROOT_URLCONF = "config.urls"

# =============================================================
# TEMPLATES
# =============================================================
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

# =============================================================
# WSGI
# =============================================================
WSGI_APPLICATION = "config.wsgi.application"

# =============================================================
# DATABASE — PostgreSQL (PRD Section 3.1)
# =============================================================
# Configured per-environment in development.py / production.py
# CONN_MAX_AGE for connection pooling (PRD: 60 seconds)
CONN_MAX_AGE = 60

# =============================================================
# CACHE — Redis (PRD Section 3.1)
# =============================================================
REDIS_URL = config("REDIS_URL", default="redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    },
    "sessions": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": config("REDIS_SESSION_URL", default=REDIS_URL),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    },
}

# =============================================================
# AUTH — Custom User Model (PRD Section 5.1)
# =============================================================
AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "apps.accounts.backends.PhoneAuthBackend",
    "django.contrib.auth.backends.ModelBackend",
]

LOGIN_URL = "/auth/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/auth/login/"

# =============================================================
# PASSWORD HASHERS — Argon2 Primary (PRD Section 7.1)
# =============================================================
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# =============================================================
# INTERNATIONALIZATION
# =============================================================
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Lagos"
USE_I18N = True
USE_TZ = True

# =============================================================
# STATIC FILES — PRD Section 9
# =============================================================
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# =============================================================
# MEDIA FILES
# =============================================================
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# =============================================================
# DEFAULT PRIMARY KEY — UUID (PRD: UUIDs on ALL models)
# =============================================================
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# =============================================================
# CELERY — Async Task Queue (PRD Section 3.1)
# =============================================================
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "Africa/Lagos"
CELERY_TASK_ALWAYS_EAGER = False

# =============================================================
# TERMII — SMS / OTP (PRD Section 10)
# =============================================================
TERMII_API_KEY = config("TERMII_API_KEY", default="")
TERMII_SECRET_KEY = config("TERMII_SECRET_KEY", default="")
TERMII_SENDER_ID = config("TERMII_SENDER_ID", default="SubHero")
TERMII_MOCK = config("TERMII_MOCK", default=True, cast=bool)
TERMII_BASE_URL = "https://api.ng.termii.com/api"

# OTP settings
OTP_LENGTH = 6
OTP_EXPIRY_SECONDS = 600  # 10 minutes
OTP_MAX_ATTEMPTS = 3

# =============================================================
# PROVIDUS BANK — Virtual Accounts (PRD Section 8)
# =============================================================
PROVIDUS_API_KEY = config("PROVIDUS_API_KEY", default="")
PROVIDUS_SECRET_KEY = config("PROVIDUS_SECRET_KEY", default="")
PROVIDUS_WEBHOOK_SECRET = config("PROVIDUS_WEBHOOK_SECRET", default="")
PROVIDUS_BASE_URL = config("PROVIDUS_BASE_URL", default="https://vps.providusbank.com/vps/api")
PROVIDUS_MOCK = config("PROVIDUS_MOCK", default=True, cast=bool)

# Wallet limits — PRD Section 6.2
FUND_MIN_AMOUNT = 100          # ₦100 minimum funding
FUND_MAX_AMOUNT = 500_000      # ₦500,000 max single funding
FUND_DAILY_LIMIT = 1_000_000   # ₦1,000,000 daily cumulative funding
P2P_MIN_AMOUNT = 50            # ₦50 minimum transfer
P2P_MAX_AMOUNT = 100_000       # ₦100,000 max single transfer
P2P_DAILY_LIMIT = 200_000      # ₦200,000 daily P2P send limit

# =============================================================
# RATE LIMITING — PRD Section 7.3
# =============================================================
RATELIMIT_USE_CACHE = "default"
RATELIMIT_FAIL_OPEN = False

# =============================================================
# LOGGING — PRD Section 7.5 (structured JSON)
# =============================================================
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "django.utils.log.ServerFormatter",
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
        "file": {
            "class": "logging.FileHandler",
            "filename": LOG_DIR / "subhero.log",
            "formatter": "json",
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "apps": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# =============================================================
# SECURITY — Login / PIN Lockout (PRD Section 6.1)
# =============================================================
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 900  # 15 minutes
MAX_PIN_ATTEMPTS = 3
PIN_LOCKOUT_SECONDS = 1800  # 30 minutes
