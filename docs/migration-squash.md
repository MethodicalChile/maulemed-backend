# Guía de squash de migraciones

## Estado actual

Las siguientes apps tienen migraciones acumuladas que conviene squashear antes de
ir a producción limpia:

| App          | Migraciones actuales         | Acción                  |
|--------------|------------------------------|-------------------------|
| accounts     | 0001, 0002, 0003             | Squash → 0001_squashed  |
| evaluations  | 0001, 0002                   | Squash → 0001_squashed  |
| products     | 0001, 0002                   | Squash → 0001_squashed  |
| suppliers    | 0001, 0002                   | Squash → 0001_squashed  |
| (resto)      | solo 0001_initial            | Sin cambios necesarios  |

---

## Cuándo hacer el squash

**Antes de producción** (base de datos vacía o recién creada) → puede hacerse sin
restricciones.

**Con base de datos existente** → hay que marcar las migraciones antiguas como
"reemplazadas" y solo borrarlas después de confirmar que **todos los entornos**
tienen aplicada la migración squasheada. Ver paso 5.

---

## Procedimiento por app

### 1. Generar la migración squasheada

```bash
# Activar el entorno virtual
source .venv/bin/activate   # Linux/Mac
.venv\Scripts\activate      # Windows

# Squash de accounts (0001 → 0003)
python manage.py squashmigrations accounts 0001 0003 --squashed-name 0001_squashed

# Squash de evaluations (0001 → 0002)
python manage.py squashmigrations evaluations 0001 0002 --squashed-name 0001_squashed

# Squash de products (0001 → 0002)
python manage.py squashmigrations products 0001 0002 --squashed-name 0001_squashed

# Squash de suppliers (0001 → 0002)
python manage.py squashmigrations suppliers 0001 0002 --squashed-name 0001_squashed
```

### 2. Revisar la migración generada

Django crea `0001_squashed.py` con un atributo `replaces = [...]`. Revisarlo
manualmente para confirmar que las operaciones son correctas. Puede contener
optimizaciones automáticas.

### 3. Verificar que los tests pasan

```bash
python manage.py test --settings=config.settings_test
```

### 4. Para base de datos nueva / entorno de CI

```bash
# Aplicar directamente la migración squasheada
python manage.py migrate
```

### 5. Para base de datos existente con datos

```bash
# Marcar la squashed como aplicada sin ejecutarla
# (los datos ya están, la estructura ya existe)
python manage.py migrate --fake accounts 0001_squashed
python manage.py migrate --fake evaluations 0001_squashed
python manage.py migrate --fake products 0001_squashed
python manage.py migrate --fake suppliers 0001_squashed
```

### 6. Eliminar las migraciones originales (solo después del paso 5)

Una vez confirmado que **todos los entornos** (dev, staging, prod) tienen la
squashed aplicada, eliminar los archivos originales:

```
apps/accounts/migrations/0002_remove_role_choices.py
apps/accounts/migrations/0003_add_role_permissions.py

apps/evaluations/migrations/0002_remove_days_to_complete.py

apps/products/migrations/0002_product_image_path.py

apps/suppliers/migrations/0002_supplierproductpricehistory.py
```

Y quitar el atributo `replaces` de las migraciones squasheadas, renombrándolas a
`0001_initial.py`.

---

## Notas importantes

- No hacer squash de migraciones con `RunPython` que tengan lógica de datos sin
  revisar — el squash mantiene esas operaciones pero hay que verificar que el
  orden siga siendo correcto.
- El CI (`ci.yml`) ya usa `settings_test.py` que arranca con SQLite en memoria, por
  lo que siempre aplica las migraciones desde cero y no se ve afectado por el squash.
