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
# DATABASE — PostgreSQL (PRD Section 3.1)
# =============================================================
DATABASES = {
    "default": dj_database_url.config(
        default=config("DATABASE_URL"),
        conn_max_age=CONN_MAX_AGE,
    )
}

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
