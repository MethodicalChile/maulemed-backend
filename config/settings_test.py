"""
Settings para el entorno de CI / tests.
Hereda de settings.py y sobreescribe solo lo necesario para correr en CI
sin credenciales de base de datos reales.

Uso:
    python manage.py test --settings=config.settings_test
    pytest --ds=config.settings_test
"""
from config.settings import *  # noqa: F401, F403

# ── Base de datos ─────────────────────────────────────────────────────────────
# Usa SQLite en memoria para que los tests sean rápidos y no necesiten
# credenciales externas. No requiere instalación adicional.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# ── Seguridad / rendimiento ───────────────────────────────────────────────────
# Hash de contraseñas más rápido en tests (no importa la seguridad aquí)
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Sin throttling en tests para no interferir con las aserciones HTTP
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []  # noqa: F405
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {}    # noqa: F405

# Silenciar logs innecesarios durante los tests
LOGGING = {
    "version": 1,
    "disable_existing_loggers": True,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "root": {"handlers": ["null"]},
}
