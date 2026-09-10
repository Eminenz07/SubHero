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

_raw_hosts = config("ALLOWED_HOSTS", default="*", cast=Csv())
ALLOWED_HOSTS = list(_raw_hosts)
for h in ["subhero-smm.onrender.com", ".onrender.com", "subhero.fly.dev", "localhost", "127.0.0.1", "*"]:
    if h not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(h)

# Redis / Celery Connection URL with Upstash SSL auto-upgrade
REDIS_URL = config("REDIS_URL", default="")
if "upstash.io" in REDIS_URL and REDIS_URL.startswith("redis://"):
    REDIS_URL = "rediss://" + REDIS_URL[len("redis://"):]

# Site URL for absolute links (Giveaways, emails, etc.)
SITE_URL = config("SITE_URL", default="http://localhost:8000")

# Admin URL — configurable via .env, randomised in production
ADMIN_URL = config("ADMIN_URL", default="admin/")
ADMIN_HQ_URL = config("ADMIN_HQ_URL", default="subhero-hq-sh9k4x2/")

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
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_CACHE_ALIAS = "sessions"
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 86400  # 24 hours default
SESSION_SAVE_EVERY_REQUEST = True

# =============================================================
# CSRF — PRD Section 7.1
# =============================================================
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="https://localhost",
    cast=Csv(),
)
CSRF_FAILURE_VIEW = "apps.core.views.csrf_failure"

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
    "apps.admin_panel",
    "apps.giveaway",
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
    "apps.admin_panel.middleware.MaintenanceModeMiddleware",
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
                "apps.notifications.context_processors.unread_notifications",
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
import ssl

RAW_REDIS_URL = config("REDIS_URL", default="redis://localhost:6379/0")
if RAW_REDIS_URL.startswith("rediss://") and "ssl_cert_reqs" not in RAW_REDIS_URL:
    sep = "&" if "?" in RAW_REDIS_URL else "?"
    REDIS_URL = f"{RAW_REDIS_URL}{sep}ssl_cert_reqs=none"
else:
    REDIS_URL = RAW_REDIS_URL

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "IGNORE_EXCEPTIONS": True,
        },
    },
    "sessions": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": config("REDIS_SESSION_URL", default=REDIS_URL),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "IGNORE_EXCEPTIONS": True,
        },
    },
    "ratelimit": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unique-ratelimit-cache",
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

if REDIS_URL.startswith("rediss://"):
    CELERY_BROKER_USE_SSL = {
        'ssl_cert_reqs': ssl.CERT_NONE,
    }
    CELERY_REDIS_BACKEND_USE_SSL = {
        'ssl_cert_reqs': ssl.CERT_NONE,
    }

# =============================================================
# TERMII — SMS / OTP (PRD Section 10)
# =============================================================
TERMII_API_KEY = config("TERMII_API_KEY", default="REDACTED_TERMII_KEY")
TERMII_SECRET_KEY = config("TERMII_SECRET_KEY", default="")
TERMII_SENDER_ID = config("TERMII_SENDER_ID", default="SubHero")
TERMII_MOCK = config("TERMII_MOCK", default=False, cast=bool)
TERMII_BASE_URL = config("TERMII_BASE_URL", default="https://v4.api.termii.com/api")

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

# VTU/CheapDataHub/Sabuss Mock Toggle
VTU_MOCK = config("VTU_MOCK", default=True, cast=bool)

# =============================================================
# SQUAD PAYMENT GATEWAY (GTBank Integration)
# =============================================================
SQUAD_ENV = config('SQUAD_ENV', default='sandbox')

SQUAD_SANDBOX_SECRET_KEY = config('SQUAD_SANDBOX_SECRET_KEY', default="")
SQUAD_SANDBOX_PUBLIC_KEY = config('SQUAD_SANDBOX_PUBLIC_KEY', default="")
SQUAD_LIVE_SECRET_KEY = config('SQUAD_LIVE_SECRET_KEY', default="")
SQUAD_LIVE_PUBLIC_KEY = config('SQUAD_LIVE_PUBLIC_KEY', default="")

if SQUAD_ENV == 'live':
    SQUAD_SECRET_KEY = SQUAD_LIVE_SECRET_KEY
    SQUAD_PUBLIC_KEY = SQUAD_LIVE_PUBLIC_KEY
    SQUAD_BASE_URL = 'https://api-d.squadco.com'
else:
    SQUAD_SECRET_KEY = SQUAD_SANDBOX_SECRET_KEY
    SQUAD_PUBLIC_KEY = SQUAD_SANDBOX_PUBLIC_KEY
    SQUAD_BASE_URL = 'https://sandbox-api-d.squadco.com'

SQUAD_WEBHOOK_SECRET = SQUAD_SECRET_KEY

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
RATELIMIT_USE_CACHE = "ratelimit"
RATELIMIT_FAIL_OPEN = True
SILENCED_SYSTEM_CHECKS = ["django_ratelimit.E002", "django_ratelimit.E003", "django_ratelimit.W001"]

# Optimize Celery Redis polling frequency to stay within free tier quotas
CELERY_BROKER_TRANSPORT_OPTIONS = {
    'visibility_timeout': 3600,
    'polling_interval': 5.0,
}

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
PIN_LOCKOUT_SECONDS = 900  # 15 minutes

# =============================================================
# CHEAPDATAHUB — Outbound VTU API
# =============================================================
CHEAPDATAHUB_API_KEY = config("CHEAPDATAHUB_API_KEY", default="")
CHEAPDATAHUB_BASE_URL = config("CHEAPDATAHUB_BASE_URL", default="https://www.cheapdatahub.ng")

# =============================================================
# SABUSS — Outbound Data & Airtime API
# =============================================================
SABUSS_API_KEY = config("SABUSS_API_KEY", default="REDACTED_SABUSS_KEY")
SABUSS_PIN = config("SABUSS_PIN", default="1282")
SABUSS_BASE_URL = config("SABUSS_BASE_URL", default="https://sabuss.com")
SABUSS_PROFIT_MARGIN = config("SABUSS_PROFIT_MARGIN", default=0.10, cast=float)


# =============================================================
# OGAVIRAL — Outbound SMM API
# =============================================================
OGAVIRAL_API_KEY = config("OGAVIRAL_API_KEY", default="REDACTED_OGAVIRAL_KEY")
OGAVIRAL_API_URL = config("OGAVIRAL_API_URL", default="https://ogaviral.com/api/v2")

# =============================================================
# CELERY BEAT SCHEDULE
# =============================================================
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    'sync-vtu-plans': {
        'task': 'apps.vtu.tasks.sync_vtu_plans',
        'schedule': crontab(minute=0, hour='*/6'),
    },
    'sync-cable-plans': {
        'task': 'apps.vtu.tasks.sync_cable_plans',
        'schedule': crontab(minute=30, hour='*/6'),
    },
    'sync-exam-products': {
        'task': 'apps.vtu.tasks.sync_exam_products',
        'schedule': crontab(minute=0, hour='*/12'),
    },
    'sync-smm-catalogue': {
        'task': 'apps.smm.tasks.sync_smm_catalogue',
        'schedule': crontab(minute=0, hour=3),
    },
    'poll-smm-orders': {
        'task': 'apps.smm.tasks.poll_smm_orders',
        'schedule': crontab(minute='*/30'),
    },
    'check-api-wallet-balance': {
        'task': 'apps.vtu.tasks.check_api_wallet_balance',
        'schedule': crontab(minute=0, hour='*/2'),
    },
    'expire-giveaways': {
        'task': 'apps.giveaway.tasks.expire_giveaways',
        'schedule': crontab(minute=0),  # every hour
    },
}

# =============================================================
# WEB PUSH NOTIFICATIONS — VAPID KEYS
# =============================================================
VAPID_PUBLIC_KEY = config(
    "VAPID_PUBLIC_KEY",
    default="REDACTED_VAPID_PUBLIC_KEY"
)
VAPID_PRIVATE_KEY = config(
    "VAPID_PRIVATE_KEY",
    default="-----BEGIN PRIVATE KEY-----\nREDACTED_VAPID_KEY_L1\nREDACTED_VAPID_KEY_L2\nREDACTED_VAPID_KEY_L3\n-----END PRIVATE KEY-----"
)
VAPID_ADMIN_EMAIL = config("VAPID_ADMIN_EMAIL", default="mailto:admin@subhero.com.ng")

# =============================================================
# BREVO EMAIL API — HTTP REST API (Port 443 HTTPS)
# =============================================================
BREVO_API_KEY = config("BREVO_API_KEY", default="")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="SubHero <noreply@subhero.com.ng>")
SERVER_EMAIL = config("SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)
SUPPORT_EMAIL = config("SUPPORT_EMAIL", default="support@subhero.com.ng")


