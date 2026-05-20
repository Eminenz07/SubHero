"""
SubHero — Production Settings
===============================
Hardened for production deployment.
"""

import dj_database_url

from .base import *  # noqa: F401, F403

# =============================================================
# DEBUG — NEVER True in production (PRD Section 7.1)
# =============================================================
DEBUG = False

# =============================================================
# ALLOWED HOSTS & SECURITY — PRD Section 7.1
# =============================================================
ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default="subhero.fly.dev,localhost,127.0.0.1",
    cast=Csv(),
)
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="https://subhero.fly.dev",
    cast=Csv(),
)

# =============================================================
# DATABASE — PostgreSQL (PRD Section 3.1)
# =============================================================
DATABASES = {
    "default": dj_database_url.config(
        default=config("DATABASE_URL", default="sqlite:///db.sqlite3"),
        conn_max_age=CONN_MAX_AGE,
    )
}

# =============================================================
# CACHE & SESSIONS — Resilient Production Fallbacks
# =============================================================
REDIS_URL = config("REDIS_URL", default="")

if REDIS_URL:
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
else:
    # Safe fallback if Redis is not provisioned or attached yet
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "unique-snowflake",
        },
        "sessions": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "unique-snowflake-sessions",
        },
    }
    # Fall back to database for persistent sessions, so user logins are saved safely
    SESSION_ENGINE = "django.contrib.sessions.backends.db"

# =============================================================
# STATIC FILES — WhiteNoise (PRD Section 6 optimisation)
# =============================================================
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")  # noqa: F405
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# =============================================================
# EMAIL — Real SMTP
# =============================================================
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = config("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="SubHero <noreply@subhero.ng>")

# =============================================================
# TERMII — Real SMS in production
# =============================================================
TERMII_MOCK = False

# =============================================================
# CELERY — Real async in production
# =============================================================
CELERY_TASK_ALWAYS_EAGER = False
