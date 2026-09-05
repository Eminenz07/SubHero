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
_raw_hosts = config("ALLOWED_HOSTS", default="*", cast=Csv())
ALLOWED_HOSTS = list(_raw_hosts)
for h in [
    "subhero.com.ng",
    "www.subhero.com.ng",
    "subhero-p3zo.onrender.com",
    "subhero-smm.onrender.com",
    ".onrender.com",
    "subhero.fly.dev",
    "localhost",
    "127.0.0.1",
    "*",
]:
    if h not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(h)

_raw_csrf = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())
CSRF_TRUSTED_ORIGINS = list(_raw_csrf)
for c in [
    "https://subhero.com.ng",
    "https://www.subhero.com.ng",
    "http://subhero.com.ng",
    "http://www.subhero.com.ng",
    "https://subhero-p3zo.onrender.com",
    "https://subhero-smm.onrender.com",
    "https://*.onrender.com",
    "https://subhero.fly.dev",
]:
    if c not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(c)

# Support reverse proxy HTTPS headers from Render and Cloudflare
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# =============================================================
# DATABASE — PostgreSQL (PRD Section 3.1)
# =============================================================
DATABASES = {
    "default": dj_database_url.config(
        default=config("DATABASE_URL", default="sqlite:///db.sqlite3"),
        conn_max_age=CONN_MAX_AGE,
    )
}
DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True

# =============================================================
# CACHE & SESSIONS — Resilient Production Fallbacks
# =============================================================
REDIS_URL = config("REDIS_URL", default="")
if "upstash.io" in REDIS_URL and REDIS_URL.startswith("redis://"):
    REDIS_URL = "rediss://" + REDIS_URL[len("redis://"):]

if REDIS_URL:
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
        "ratelimit": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "unique-ratelimit-cache",
        },
    }
# Use cached_db for resilient persistent sessions (cached in Redis, saved to Postgres)
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"

# =============================================================
# STATIC FILES — WhiteNoise (PRD Section 6 optimisation)
# =============================================================
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")  # noqa: F405
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
WHITENOISE_MANIFEST_STRICT = False

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
TERMII_MOCK = config("TERMII_MOCK", default=False, cast=bool)
VTU_MOCK = config("VTU_MOCK", default=False, cast=bool)

# =============================================================
# CELERY — Real async in production if REDIS_URL provided, else eager fallback
# =============================================================
if REDIS_URL:
    CELERY_TASK_ALWAYS_EAGER = False
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL
else:
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True
