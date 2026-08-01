"""
Configuración global de pytest para MauleMed-backend.
Ejecutar con: python manage.py test  o  pytest
"""
import os
import django

# Aseguramos que Django esté configurado antes de que pytest importe los módulos
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
