"""
Settings para levantar la app en esta máquina.

Usa SQLite en disco en vez de la base Supabase que configura .env: así se puede
migrar, sembrar y probar sin tocar una base que el equipo comparte.

    python manage.py migrate --settings=config.settings_local
    python manage.py runserver --settings=config.settings_local
"""
from config.settings import *  # noqa: F401, F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db_local.sqlite3",  # noqa: F405
    }
}

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]

CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# Sin throttling: la demo hace muchas llamadas seguidas al cargar las pestañas.
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []  # noqa: F405
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {}    # noqa: F405
