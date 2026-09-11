"""
SubHero — Development Settings
===============================
Local development overrides. DEBUG on, relaxed security.
"""

from .base import *  # noqa: F401, F403

# =============================================================
# DEBUG
# =============================================================
DEBUG = True

# =============================================================
# SECURITY RELAXED FOR LOCAL DEV
# =============================================================
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0

CSRF_TRUSTED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

# =============================================================
# DATABASE — SQLite fallback for quick dev, PostgreSQL preferred
# =============================================================
import dj_database_url  # noqa: E402

DATABASE_URL = config("DATABASE_URL", default="")

if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=CONN_MAX_AGE,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# =============================================================
# CACHE — Redis if available, fallback to local memory
# =============================================================
try:
    import redis as _redis_lib

    _r = _redis_lib.Redis.from_url(REDIS_URL)
    _r.ping()
except Exception:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        },
        "sessions": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "sessions",
        },
        "ratelimit": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "unique-ratelimit-cache",
        },
    }
    SESSION_ENGINE = "django.contrib.sessions.backends.db"

# =============================================================
# EMAIL — Console backend for dev
# =============================================================
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# =============================================================
# TERMII — Mock mode for dev (OTPs logged to console)
# =============================================================
TERMII_MOCK = True

# =============================================================
# CELERY — Run tasks synchronously in dev
# =============================================================
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# =============================================================
# DEBUG TOOLBAR
# =============================================================
INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405
MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")  # noqa: F405
INTERNAL_IPS = ["127.0.0.1"]

# =============================================================
# LOGGING — Verbose in dev
# =============================================================
LOGGING["root"]["level"] = "DEBUG"  # noqa: F405
LOGGING["loggers"]["apps"]["level"] = "DEBUG"  # noqa: F405
