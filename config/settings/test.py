"""
SubHero — Test Settings
Forces SQLite so tests run without a live Neon Postgres database.
"""
from .development import *  # noqa: F401, F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
