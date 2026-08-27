import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, UserProfile, UserRoleAssignment
from apps.audit.models import AuditLog
from apps.documents.models import Document
from apps.evaluations.models import (
    EvaluationForm,
    EvaluationFormQuestion,
    UserEvaluation,
    UserEvaluationAnswer,
)
from apps.finance.models import Payment, SupplierInvoice
from apps.inventory.models import (
    InventoryLot,
    InventoryMovement,
    InventoryStock,
    Warehouse,
)
from apps.notifications.models import Notification
from apps.organizations.models import Branch, CostCenter, LegalEntity, Organization
from apps.products.models import BranchProduct, Product, ProductCategory, UnitOfMeasure
from apps.purchasing.models import (
    PurchaseOrder,
    PurchaseReceipt,
    PurchaseReceiptItem,
    SupplierClaim,
)
from apps.suppliers.models import (
    Supplier,
    SupplierProduct,
    SupplierProductPrice,
    SupplierProductPriceHistory,
)
from apps.transfers.models import StockTransfer, StockTransferItem


MARCA = "DEMO-MAULEMED"
SEMILLA = 20260826
PASSWORD_DEMO = "MauleMedDemo2026!"


ROLE_NAMES = {
    "ADMIN": "Administrador",
    "GERENTE": "Gerencia",
    "ABASTECIMIENTO": "Abastecimiento",
    "FINANZAS": "Finanzas",
    "BODEGUERO": "Bodeguero",
    "JEFA_SUCURSAL": "Jefatura de sucursal",
    "SECRETARIA": "Secretaría",
    "TENS": "TENS",
    "TECNOLOGA_MEDICA": "Tecnóloga Médica",
    "DOCTOR": "Doctor",
}

USER_DEMOS = [
    ("admin.demo", "Admin", "MauleMed", "ADMIN", None, "Administrador de plataforma"),
    ("gerente.demo", "Gabriela", "Rojas", "GERENTE", None, "Gerente general"),
    ("abastecimiento.demo", "Felipe", "Contreras", "ABASTECIMIENTO", None, "Encargado de abastecimiento"),
    ("finanzas.demo", "Carolina", "Muñoz", "FINANZAS", None, "Analista de finanzas"),
    ("bodega.linares", "Marco", "Sepúlveda", "BODEGUERO", "LIN-CENTRO", "Encargado de bodega"),
    ("bodega.parral", "Paula", "Vega", "BODEGUERO", "PARRAL", "Encargada de bodega"),
    ("jefatura.linares", "Andrea", "Silva", "JEFA_SUCURSAL", "LIN-CENTRO", "Jefa de sucursal"),
    ("jefatura.parral", "Claudia", "Mora", "JEFA_SUCURSAL", "PARRAL", "Jefa de sucursal"),
    ("secretaria.linares", "Daniela", "Araya", "SECRETARIA", "LIN-CENTRO", "Secretaria"),
    ("tecnologa.linares", "Francisca", "Pérez", "TECNOLOGA_MEDICA", "LIN-CENTRO", "Tecnóloga médica"),
    ("tecnologa.parral", "Camila", "Torres", "TECNOLOGA_MEDICA", "PARRAL", "Tecnóloga médica"),
    ("tens.linares", "Valentina", "Gómez", "TENS", "LIN-CENTRO", "TENS"),
    ("doctor.demo", "Rodrigo", "Fuentes", "DOCTOR", "LIN-CENTRO", "Médico radiólogo"),
]

SUPPLIER_NAMES = [
    "Distribuidora Médica Centro SpA",
    "Insumos Clínicos del Maule Ltda.",
    "TecnoSalud Chile SpA",
    "Suministros Hospitalarios Sur Ltda.",
    "Imágenes Médicas Chile SpA",
    "Farmacéutica Central SpA",
    "Diagnóstico Supply Ltda.",
    "MedEquip Chile SpA",
    "Bodega Clínica Sur SpA",
    "Servicios TI Médicos SpA",
    "Comercial Aseo Institucional Ltda.",
    "Oficina y Gestión Maule SpA",
]

PRODUCT_BASE = {
    "Contraste y medicamentos": [
        "Medio de contraste yodado 100 ml",
        "Medio de contraste yodado 50 ml",
        "Suero fisiológico 500 ml",
        "Suero fisiológico 100 ml",
        "Lidocaína 2% ampolla",
        "Adrenalina ampolla",
        "Dexametasona ampolla",
        "Clorfenamina ampolla",
    ],
    "Insumos clínicos": [
        "Guantes de nitrilo caja 100",
        "Jeringa 20 ml caja 100",
        "Jeringa 10 ml caja 100",
        "Jeringa 5 ml caja 100",
        "Gasa estéril paquete",
        "Algodón hidrófilo 500 g",
        "Bajada de suero macrogoteo",
        "Bránula 20G caja 50",
        "Bránula 22G caja 50",
        "Tela adhesiva hipoalergénica",
        "Mascarilla quirúrgica caja 50",
        "Pechera desechable",
    ],
    "Radiología": [
        "Película radiográfica 35x43",
        "Película radiográfica 24x30",
        "Sobre radiográfico 35x43",
        "Protector tiroideo plomado",
        "Delantal plomado adulto",
        "Gel conductor ecográfico 5L",
        "Marcador radiopaco derecha",
        "Marcador radiopaco izquierda",
    ],
    "Aseo": [
        "Alcohol gel 1L",
        "Alcohol 70% 1L",
        "Desinfectante superficies 5L",
        "Cloro gel 5L",
        "Toalla papel jumbo",
        "Papel higiénico institucional",
        "Bolsa basura 80x110",
        "Jabón clínico 1L",
    ],
    "Oficina": [
        "Resma papel carta",
        "Resma papel oficio",
        "Tóner impresora negro",
        "Carpeta archivador",
        "Etiqueta térmica rollo",
        "Lápiz pasta azul caja 50",
    ],
    "Tecnología": [
        "Teclado USB clínico",
        "Mouse USB clínico",
        "Disco SSD 1TB",
        "UPS 1500VA",
        "Cable de red CAT6 3m",
        "Lector código de barras USB",
    ],
}


class Command(BaseCommand):
    help = "Carga una base demo integral e idempotente para presentar MauleMed a clientes."

    def add_arguments(self, parser):
        parser.add_argument("--months", type=int, default=12)
        parser.add_argument(
            "--password",
            default=PASSWORD_DEMO,
            help="Contraseña para los usuarios demo.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self.rng = random.Random(SEMILLA)
        self.password = options["password"]
        self.months = max(1, min(options["months"], 36))

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== MAULEMED: CARGA DEMO INTEGRAL ==="))

        self.organization, self.entities, self.branches = self._seed_organization()
        self.cost_centers = self._seed_cost_centers()
        self.roles, self.users = self._seed_users()
        self.products = self._seed_products()
        self.suppliers = self._seed_suppliers()
        self._seed_supplier_products()

        # Reutiliza la lógica financiera/histórica que ya existe en el proyecto.
        call_command("seed_budget_categories", verbosity=0)
        call_command("seed_demo_finanzas", verbosity=0)
        call_command("seed_demo_historia", months=self.months, verbosity=0)

        self._seed_branch_products()
        self._enrich_inventory()
        self._seed_receipts_and_claims()
        self._seed_payments()
        self._seed_transfers()
        self._seed_evaluations()
        self._seed_notifications()
        self._seed_documents()
        self._seed_audit()

        self._print_summary()

    def _seed_organization(self):
        organization, _ = Organization.objects.update_or_create(
            name="MauleMed Servicios Médicos",
            defaults={
                "rut": "76.999.999-9",
                "description": f"Organización ficticia para demostración. {MARCA}",
                "is_active": True,
            },
        )

        entity_data = [
            ("76869710-8", "Instituto Radiológico del Maule SpA", "Servicios de imagenología"),
            ("76551640-4", "Sociedad Diagnóstica del Maule SpA", "Servicios de diagnóstico médico"),
        ]
        entities = []
        for rut, name, activity in entity_data:
            entity, _ = LegalEntity.objects.update_or_create(
                rut=rut,
                defaults={
                    "organization": organization,
                    "name": name,
                    "business_activity": activity,
                    "address": "Región del Maule, Chile",
                    "is_active": True,
                },
            )
            entities.append(entity)

        branch_data = [
            ("LIN-CENTRO", "MauleMed Linares Centro", "Linares", entities[0], True),
            ("LIN-ORIENTE", "MauleMed Linares Oriente", "Linares", entities[1], False),
            ("SAN-JAVIER", "MauleMed San Javier", "San Javier", entities[0], False),
            ("PARRAL", "MauleMed Parral", "Parral", entities[1], False),
            ("CONSTITUCION", "MauleMed Constitución", "Constitución", entities[0], False),
        ]
        branches = []
        for code, name, city, legal_entity, is_main in branch_data:
            branch, _ = Branch.objects.update_or_create(
                code=code,
                defaults={
                    "organization": organization,
                    "legal_entity": legal_entity,
                    "name": name,
                    "city": city,
                    "address": f"Centro de {city}, Región del Maule",
                    "phone": "+56 9 5555 0000",
                    "email": f"{code.lower()}@demo.maulemed.cl",
                    "is_main_branch": is_main,
                    "is_active": True,
                },
            )
            branches.append(branch)

        self.stdout.write(self.style.SUCCESS(f"[OK] Empresa: {len(entities)} sociedades, {len(branches)} sucursales"))
        return organization, entities, branches

    def _seed_cost_centers(self):
        definitions = [
            ("IMG", "Imagenología"),
            ("RX", "Radiología"),
            ("TAC", "Scanner / TAC"),
            ("RM", "Resonancia Magnética"),
            ("ADM", "Administración"),
            ("BOD", "Bodega"),
            ("FIN", "Finanzas"),
            ("TI", "Tecnología"),
        ]
        result = []
        for branch in self.branches:
            for suffix, name in definitions:
                code = f"{branch.code[:8]}-{suffix}"
                cc, _ = CostCenter.objects.update_or_create(
                    legal_entity=branch.legal_entity,
                    code=code,
                    defaults={
                        "branch": branch,
                        "name": name,
                        "description": f"{name} - {branch.name} - {MARCA}",
                        "is_active": True,
                    },
                )
                result.append(cc)
        self.stdout.write(self.style.SUCCESS(f"[OK] Centros de costo: {len(result)}"))
        return result

    def _seed_users(self):
        User = get_user_model()

        roles = {}

        # -------------------------------------------------------------------------
        # ROLES
        # -------------------------------------------------------------------------
        # Usamos all_objects porque Role tiene soft-delete.
        # Puede existir físicamente un role con code=ADMIN pero con deleted_at != NULL.
        # En ese caso Role.objects no lo encontraría y update_or_create intentaría
        # insertar otro registro, provocando:
        #
        # duplicate key value violates unique constraint "roles_code_key"
        #
        # Por eso buscamos incluyendo eliminados y, si existe, lo restauramos.
        # -------------------------------------------------------------------------
        for code, name in ROLE_NAMES.items():
            role = Role.all_objects.filter(code=code).first()

            if role:
                role.name = name
                role.description = f"Rol demo {name}"
                role.is_active = True

                # Restaurar si estaba eliminado lógicamente.
                if role.deleted_at is not None:
                    role.deleted_at = None

                role.save(
                    update_fields=[
                        "name",
                        "description",
                        "is_active",
                        "deleted_at",
                        "updated_at",
                    ]
                )

            else:
                role = Role.objects.create(
                    code=code,
                    name=name,
                    description=f"Rol demo {name}",
                    is_active=True,
                )

            roles[code] = role

        # -------------------------------------------------------------------------
        # USUARIOS
        # -------------------------------------------------------------------------
        branch_by_code = {
            branch.code: branch
            for branch in self.branches
        }

        users = {}

        for idx, (
            username,
            first,
            last,
            role_code,
            branch_code,
            position,
        ) in enumerate(USER_DEMOS, start=1):

            user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@demo.maulemed.cl",
                    "first_name": first,
                    "last_name": last,
                    "is_active": True,
                },
            )

            user.email = f"{username}@demo.maulemed.cl"
            user.first_name = first
            user.last_name = last
            user.is_active = True

            # No dejar privilegios antiguos si volvemos a ejecutar el seed.
            user.is_staff = role_code == "ADMIN"
            user.is_superuser = role_code == "ADMIN"

            user.set_password(self.password)
            user.save()

            branch = branch_by_code.get(branch_code)

            # ---------------------------------------------------------------------
            # PERFIL
            # ---------------------------------------------------------------------
            UserProfile.objects.update_or_create(
                user=user,
                defaults={
                    "rut": f"19.900.{idx:03d}-{idx % 9}",
                    "phone": f"+56 9 7000 {idx:04d}",
                    "position": position,
                    "organization": self.organization,
                    "is_active": True,
                },
            )

            # ---------------------------------------------------------------------
            # ASIGNACIÓN DE ROL
            # ---------------------------------------------------------------------
            # También usa BaseModel, por lo que podría existir una asignación
            # soft-deleted. Buscamos primero con all_objects.
            # ---------------------------------------------------------------------
            role_assignment = UserRoleAssignment.all_objects.filter(
                user=user,
                role=roles[role_code],
                organization=self.organization,
                legal_entity=branch.legal_entity if branch else None,
                branch=branch,
            ).first()

            if role_assignment:
                role_assignment.is_active = True

                if role_assignment.deleted_at is not None:
                    role_assignment.deleted_at = None

                role_assignment.save(
                    update_fields=[
                        "is_active",
                        "deleted_at",
                        "updated_at",
                    ]
                )

            else:
                UserRoleAssignment.objects.create(
                    user=user,
                    role=roles[role_code],
                    organization=self.organization,
                    legal_entity=branch.legal_entity if branch else None,
                    branch=branch,
                    is_active=True,
                )

            users[username] = user

        self.stdout.write(
            self.style.SUCCESS(
                f"[OK] Usuarios demo: {len(users)}"
            )
        )

        return roles, users

    def _seed_products(self):
        units = {}
        for code, name in [("UN", "Unidad"), ("CAJA", "Caja"), ("LT", "Litro"), ("PAQ", "Paquete")]:
            units[code], _ = UnitOfMeasure.objects.update_or_create(
                code=code, defaults={"name": name, "is_active": True}
            )

        products = []
        counter = 1
        for category_name, names in PRODUCT_BASE.items():
            category, _ = ProductCategory.objects.update_or_create(
                name=category_name,
                defaults={"description": f"Categoría demo {category_name}", "is_active": True},
            )
            for name in names:
                medical = category_name in {"Contraste y medicamentos", "Insumos clínicos"}
                unit = units["CAJA"] if "caja" in name.lower() else units["UN"]
                product, _ = Product.objects.update_or_create(
                    internal_code=f"DEMO-P{counter:04d}",
                    defaults={
                        "category": category,
                        "unit": unit,
                        "name": name,
                        "description": f"Producto demostración MauleMed. {MARCA}",
                        "sku": f"MM-{counter:05d}",
                        "barcode": f"7809000{counter:06d}",
                        "requires_lot": medical,
                        "requires_expiration_date": medical,
                        "requires_sanitary_resolution": medical,
                        "is_medication": category_name == "Contraste y medicamentos",
                        "is_controlled": False,
                        "is_active": True,
                        "quality_rating": Decimal(str(self.rng.choice([4.2, 4.4, 4.6, 4.8, 5.0]))),
                    },
                )
                products.append(product)
                counter += 1

        self.stdout.write(self.style.SUCCESS(f"[OK] Productos: {len(products)}"))
        return products

    def _seed_suppliers(self):
        suppliers = []
        for idx, name in enumerate(SUPPLIER_NAMES, start=1):
            supplier, _ = Supplier.objects.update_or_create(
                rut=f"77.{100 + idx:03d}.{200 + idx:03d}-{idx % 9}",
                defaults={
                    "name": name,
                    "contact_name": f"Ejecutivo Comercial {idx}",
                    "email": f"ventas{idx}@proveedor-demo.cl",
                    "phone": f"+56 2 2400 {idx:04d}",
                    "address": "Región Metropolitana, Chile",
                    "payment_terms": f"{self.rng.choice([15, 30, 45, 60])} días fecha factura",
                    "payment_terms_days": self.rng.choice([15, 30, 45, 60]),
                    "delivery_days": self.rng.choice([2, 3, 5, 7, 10]),
                    "is_active": True,
                },
            )
            suppliers.append(supplier)
        self.stdout.write(self.style.SUCCESS(f"[OK] Proveedores: {len(suppliers)}"))
        return suppliers

    def _seed_supplier_products(self):
        today = timezone.localdate()
        count = 0
        for product_index, product in enumerate(self.products):
            # 2 o 3 alternativas por producto.
            selected = [
                self.suppliers[product_index % len(self.suppliers)],
                self.suppliers[(product_index + 3) % len(self.suppliers)],
            ]
            if product_index % 3 == 0:
                selected.append(self.suppliers[(product_index + 6) % len(self.suppliers)])

            base_price = Decimal(str(2500 + (product_index + 1) * 850))
            for supplier_index, supplier in enumerate(selected):
                price = (base_price * Decimal(str(1 + supplier_index * 0.07))).quantize(Decimal("1"))
                sp, _ = SupplierProduct.objects.update_or_create(
                    supplier=supplier,
                    product=product,
                    defaults={
                        "supplier_sku": f"{supplier.id}-{product.internal_code}",
                        "last_price": price,
                        "currency": "CLP",
                        "price_valid_from": today - timedelta(days=90),
                        "min_purchase_quantity": Decimal("1"),
                        "requires_purchase_order": supplier_index == 0,
                        "allows_credit": True,
                        "allows_cash_purchase": True,
                        "is_active": True,
                    },
                )
                SupplierProductPrice.objects.update_or_create(
                    supplier_product=sp,
                    valid_from=today - timedelta(days=90),
                    defaults={
                        "price": price,
                        "currency": "CLP",
                        "valid_to": None,
                        "source": MARCA,
                    },
                )
                if not SupplierProductPriceHistory.objects.filter(
                    supplier_product=sp,
                    change_reason__startswith=MARCA,
                ).exists():
                    previous = None
                    for months_ago, factor in [(9, "0.88"), (6, "0.93"), (3, "0.97"), (0, "1.00")]:
                        hist_price = (price * Decimal(factor)).quantize(Decimal("1"))
                        history = SupplierProductPriceHistory.objects.create(
                            supplier_product=sp,
                            price=hist_price,
                            currency="CLP",
                            previous_price=previous,
                            change_reason=f"{MARCA} evolución histórica",
                            source="INITIAL" if months_ago == 9 else "IMPORT",
                            changed_by=self.users.get("abastecimiento.demo"),
                        )
                        SupplierProductPriceHistory.objects.filter(pk=history.pk).update(
                            effective_date=timezone.now() - timedelta(days=months_ago * 30)
                        )
                        previous = hist_price
                count += 1
        self.stdout.write(self.style.SUCCESS(f"[OK] Alternativas proveedor-producto: {count}"))

    def _seed_branch_products(self):
        for branch in self.branches:
            cc = next((c for c in self.cost_centers if c.branch_id == branch.id and c.code.endswith("-BOD")), None)
            for index, product in enumerate(self.products):
                min_stock = Decimal(str(5 + (index % 8) * 2))
                BranchProduct.objects.update_or_create(
                    branch=branch,
                    product=product,
                    defaults={
                        "cost_center": cc,
                        "min_stock": min_stock,
                        "critical_stock": max(Decimal("1"), min_stock / 2),
                        "max_stock": min_stock * 5,
                        "usual_monthly_quantity": min_stock * 3,
                        "is_active": True,
                    },
                )

    def _warehouse_for_product(self, branch, product):
        if product.is_medication:
            kind = Warehouse.WAREHOUSE_TYPE_MEDICATION
        elif product.category.name in {"Insumos clínicos", "Radiología", "Contraste y medicamentos"}:
            kind = Warehouse.WAREHOUSE_TYPE_MEDICAL
        elif product.category.name == "Aseo":
            kind = Warehouse.WAREHOUSE_TYPE_CLEANING
        elif product.category.name == "Oficina":
            kind = Warehouse.WAREHOUSE_TYPE_OFFICE
        else:
            kind = Warehouse.WAREHOUSE_TYPE_GENERAL
        return Warehouse.objects.filter(branch=branch, warehouse_type=kind).first()

    def _enrich_inventory(self):
        today = timezone.localdate()
        movements = 0
        lots = 0
        warehouse_types = [
            ("Bodega General", Warehouse.WAREHOUSE_TYPE_GENERAL),
            ("Bodega Insumos Médicos", Warehouse.WAREHOUSE_TYPE_MEDICAL),
            ("Bodega Medicamentos", Warehouse.WAREHOUSE_TYPE_MEDICATION),
            ("Bodega Aseo", Warehouse.WAREHOUSE_TYPE_CLEANING),
            ("Bodega Oficina", Warehouse.WAREHOUSE_TYPE_OFFICE),
        ]
        for branch in self.branches:
            for name, kind in warehouse_types:
                Warehouse.objects.update_or_create(
                    branch=branch,
                    name=name,
                    defaults={"warehouse_type": kind, "is_active": True},
                )

        for branch_index, branch in enumerate(self.branches):
            for product_index, product in enumerate(self.products):
                warehouse = self._warehouse_for_product(branch, product)
                bp = BranchProduct.objects.get(branch=branch, product=product)
                mode = (branch_index + product_index) % 10
                if mode == 0:
                    qty = Decimal("0")
                elif mode in (1, 2):
                    qty = max(Decimal("1"), bp.min_stock - Decimal("1"))
                elif mode == 3:
                    qty = bp.min_stock
                else:
                    qty = bp.min_stock * Decimal(str(self.rng.randint(2, 4)))
                reserved = Decimal("0") if qty == 0 else min(qty, Decimal(str(self.rng.randint(0, 3))))
                InventoryStock.objects.update_or_create(
                    warehouse=warehouse,
                    product=product,
                    defaults={
                        "quantity": qty,
                        "reserved_quantity": reserved,
                        "min_level": bp.min_stock,
                        "max_level": bp.max_stock or bp.min_stock * 5,
                        "last_count_date": today - timedelta(days=self.rng.randint(0, 30)),
                    },
                )

                if product.requires_lot:
                    for lot_index in range(2):
                        if lot_index == 0 and mode == 4:
                            exp = today - timedelta(days=10)
                            status = InventoryLot.STATUS_EXPIRED
                        elif lot_index == 0 and mode == 5:
                            exp = today + timedelta(days=20)
                            status = InventoryLot.STATUS_AVAILABLE
                        else:
                            exp = today + timedelta(days=180 + self.rng.randint(0, 400))
                            status = InventoryLot.STATUS_AVAILABLE
                        supplier = self.suppliers[(product_index + lot_index) % len(self.suppliers)]
                        lot, _ = InventoryLot.objects.update_or_create(
                            warehouse=warehouse,
                            product=product,
                            lot_number=f"DEMO-{branch.code[:5]}-{product.internal_code}-{lot_index+1}",
                            defaults={
                                "supplier": supplier,
                                "expiration_date": exp,
                                "quantity": max(Decimal("0"), qty / 2),
                                "status": status,
                                "received_at": timezone.now() - timedelta(days=90 + lot_index * 20),
                            },
                        )
                        lots += 1

                reason = f"{MARCA} historial consumo {branch.code} {product.internal_code}"
                if not InventoryMovement.objects.filter(reason=reason).exists():
                    for offset in (150, 120, 90, 60, 30, 7):
                        movement = InventoryMovement.objects.create(
                            movement_type=InventoryMovement.TYPE_CONSUMPTION_OUT,
                            warehouse_origin=warehouse,
                            product=product,
                            quantity=Decimal(str(1 + (product_index + offset) % 5)),
                            reason=reason,
                            reference_type="DEMO",
                            created_by_uuid=self.users["bodega.linares"].profile.uuid if branch.code == "LIN-CENTRO" else None,
                        )
                        InventoryMovement.objects.filter(pk=movement.pk).update(
                            created_at=timezone.now() - timedelta(days=offset)
                        )
                        movements += 1
        self.stdout.write(self.style.SUCCESS(f"[OK] Inventario enriquecido: {lots} lotes, {movements} movimientos nuevos"))

    def _seed_receipts_and_claims(self):
        orders = list(PurchaseOrder.objects.filter(notes="demo:historia").select_related("branch", "supplier"))
        user = self.users.get("bodega.linares")
        receipts_created = claims_created = 0
        for index, order in enumerate(orders[:80]):
            if not order.branch:
                continue
            marker = f"{MARCA} recepción {order.order_number}"
            receipt = PurchaseReceipt.objects.filter(comments=marker).first()
            if receipt is None:
                warehouse = Warehouse.objects.filter(branch=order.branch).first()
                incident = index % 9 == 0
                partial = index % 7 == 0 and not incident
                receipt = PurchaseReceipt.objects.create(
                    purchase_order=order,
                    branch=order.branch,
                    warehouse=warehouse,
                    received_by=user,
                    status=(PurchaseReceipt.STATUS_WITH_INCIDENT if incident else PurchaseReceipt.STATUS_PARTIAL if partial else PurchaseReceipt.STATUS_OK),
                    received_at=order.received_at or timezone.now() - timedelta(days=index % 60),
                    comments=marker,
                )
                for item in order.items.all():
                    ordered = item.quantity
                    if incident:
                        received = max(Decimal("0"), ordered - Decimal("2"))
                        accepted = received
                        rejected = Decimal("0")
                        incident_type = PurchaseReceiptItem.INCIDENT_MISSING
                    elif partial:
                        received = max(Decimal("1"), (ordered * Decimal("0.75")).quantize(Decimal("0.001")))
                        accepted = received
                        rejected = Decimal("0")
                        incident_type = PurchaseReceiptItem.INCIDENT_WRONG_QUANTITY
                    else:
                        received = ordered
                        accepted = ordered
                        rejected = Decimal("0")
                        incident_type = None
                    PurchaseReceiptItem.objects.create(
                        purchase_receipt=receipt,
                        product=item.product,
                        lot_number=f"REC-{order.order_number}-{item.product_id}" if item.product.requires_lot else None,
                        expiration_date=timezone.localdate() + timedelta(days=365) if item.product.requires_expiration_date else None,
                        ordered_quantity=ordered,
                        received_quantity=received,
                        accepted_quantity=accepted,
                        rejected_quantity=rejected,
                        incident_type=incident_type,
                        comments=marker,
                    )
                receipts_created += 1

            if receipt.status == PurchaseReceipt.STATUS_WITH_INCIDENT:
                description = f"{MARCA} faltante detectado en {order.order_number}"
                if not SupplierClaim.objects.filter(description=description).exists():
                    SupplierClaim.objects.create(
                        purchase_receipt=receipt,
                        supplier=order.supplier,
                        claim_type=SupplierClaim.CLAIM_REPLACEMENT,
                        status=SupplierClaim.STATUS_RESOLVED if index % 2 == 0 else SupplierClaim.STATUS_IN_PROGRESS,
                        description=description,
                        requested_solution="Reposición de unidades faltantes sin costo adicional.",
                        resolution="Proveedor coordinó reposición." if index % 2 == 0 else None,
                        created_by=self.users.get("abastecimiento.demo"),
                        resolved_at=timezone.now() - timedelta(days=2) if index % 2 == 0 else None,
                    )
                    claims_created += 1
        self.stdout.write(self.style.SUCCESS(f"[OK] Recepciones: +{receipts_created}; reclamos: +{claims_created}"))

    def _seed_payments(self):
        invoices = list(SupplierInvoice.objects.filter(notes="demo:historia").select_related("legal_entity"))
        created = 0
        for index, invoice in enumerate(invoices):
            ref = f"{MARCA}-PAY-{invoice.uuid}"
            if Payment.objects.filter(transaction_reference=ref).exists():
                continue
            if index % 10 == 0:
                status = Payment.STATUS_PENDING
                amount = invoice.total_amount
                payment_date = None
            elif index % 7 == 0:
                status = Payment.STATUS_PAID
                amount = (invoice.total_amount * Decimal("0.50")).quantize(Decimal("0.01"))
                payment_date = (invoice.due_date or timezone.localdate()) - timedelta(days=2)
                invoice.status = SupplierInvoice.STATUS_PARTIALLY_PAID
                invoice.save(update_fields=["status", "updated_at"])
            else:
                status = Payment.STATUS_PAID
                amount = invoice.total_amount
                payment_date = (invoice.due_date or timezone.localdate()) - timedelta(days=self.rng.randint(0, 8))
                invoice.status = SupplierInvoice.STATUS_PAID
                invoice.save(update_fields=["status", "updated_at"])
            Payment.objects.create(
                supplier_invoice=invoice,
                legal_entity=invoice.legal_entity,
                payment_method=Payment.METHOD_TRANSFER,
                payment_date=payment_date,
                amount=max(Decimal("1"), amount),
                status=status,
                bank_account="Banco Demo ****4321",
                transaction_reference=ref,
                created_by=self.users.get("finanzas.demo"),
                notes=MARCA,
            )
            created += 1
        self.stdout.write(self.style.SUCCESS(f"[OK] Pagos: +{created}"))

    def _seed_transfers(self):
        created = 0
        products = self.products[:20]
        for index in range(30):
            origin = self.branches[index % len(self.branches)]
            destination = self.branches[(index + 1) % len(self.branches)]
            reason = f"{MARCA} transferencia {index+1:03d}"
            if StockTransfer.objects.filter(reason=reason).exists():
                continue
            transfer_type = StockTransfer.TRANSFER_TYPE_LOAN if index % 5 == 0 else StockTransfer.TRANSFER_TYPE_TRANSFER
            status = [
                StockTransfer.STATUS_REQUESTED,
                StockTransfer.STATUS_APPROVED,
                StockTransfer.STATUS_SENT,
                StockTransfer.STATUS_RECEIVED,
                StockTransfer.STATUS_CLOSED,
            ][index % 5]
            now = timezone.now() - timedelta(days=index * 3)
            transfer = StockTransfer.objects.create(
                origin_branch=origin,
                destination_branch=destination,
                transfer_type=transfer_type,
                requested_by=self.users.get("abastecimiento.demo"),
                approved_by=self.users.get("gerente.demo") if status != StockTransfer.STATUS_REQUESTED else None,
                sent_by=self.users.get("bodega.linares") if status in {StockTransfer.STATUS_SENT, StockTransfer.STATUS_RECEIVED, StockTransfer.STATUS_CLOSED} else None,
                received_by=self.users.get("bodega.parral") if status in {StockTransfer.STATUS_RECEIVED, StockTransfer.STATUS_CLOSED} else None,
                status=status,
                reason=reason,
                dispatch_guide_number=f"GD-DEMO-{index+1:04d}" if status in {StockTransfer.STATUS_SENT, StockTransfer.STATUS_RECEIVED, StockTransfer.STATUS_CLOSED} else None,
                requested_at=now,
                approved_at=now + timedelta(hours=2) if status != StockTransfer.STATUS_REQUESTED else None,
                sent_at=now + timedelta(hours=5) if status in {StockTransfer.STATUS_SENT, StockTransfer.STATUS_RECEIVED, StockTransfer.STATUS_CLOSED} else None,
                received_at=now + timedelta(days=1) if status in {StockTransfer.STATUS_RECEIVED, StockTransfer.STATUS_CLOSED} else None,
                closed_at=now + timedelta(days=1, hours=2) if status == StockTransfer.STATUS_CLOSED else None,
            )
            product = products[index % len(products)]
            qty = Decimal(str(4 + index % 7))
            StockTransferItem.objects.create(
                stock_transfer=transfer,
                product=product,
                requested_quantity=qty,
                approved_quantity=qty if status != StockTransfer.STATUS_REQUESTED else None,
                sent_quantity=qty if status in {StockTransfer.STATUS_SENT, StockTransfer.STATUS_RECEIVED, StockTransfer.STATUS_CLOSED} else Decimal("0"),
                received_quantity=qty if status in {StockTransfer.STATUS_RECEIVED, StockTransfer.STATUS_CLOSED} else Decimal("0"),
                comments=MARCA,
            )
            created += 1
        self.stdout.write(self.style.SUCCESS(f"[OK] Transferencias: +{created}"))

    def _seed_evaluations(self):
        form_defs = [
            ("Evaluación trimestral de desempeño", "Seguimiento de desempeño y cumplimiento operacional."),
            ("Checklist operacional de bodega", "Control de orden, trazabilidad y vencimientos."),
            ("Evaluación de atención y servicio", "Evaluación interna de calidad de atención."),
        ]
        forms = []
        for title, description in form_defs:
            form, _ = EvaluationForm.objects.update_or_create(
                title=title,
                defaults={
                    "description": f"{description} {MARCA}",
                    "is_active": True,
                    "created_by": self.users.get("admin.demo"),
                },
            )
            forms.append(form)
            questions = [
                (1, "Cumple los procedimientos definidos para su función", EvaluationFormQuestion.TYPE_RATING, 5),
                (2, "Mantiene registros y trazabilidad de manera correcta", EvaluationFormQuestion.TYPE_RATING, 5),
                (3, "¿Requiere plan de mejora?", EvaluationFormQuestion.TYPE_BOOLEAN, None),
                (4, "Observaciones del evaluador", EvaluationFormQuestion.TYPE_TEXT, None),
            ]
            for order, text, qtype, rating_max in questions:
                EvaluationFormQuestion.objects.update_or_create(
                    evaluation_form=form,
                    order=order,
                    defaults={
                        "question_text": text,
                        "question_type": qtype,
                        "rating_max": rating_max,
                        "is_required": order != 4,
                    },
                )

        created = 0
        candidates = [u for name, u in self.users.items() if name != "admin.demo"]
        for idx, user in enumerate(candidates):
            form = forms[idx % len(forms)]
            if UserEvaluation.objects.filter(evaluation_form=form, evaluated_user=user, notes__startswith=MARCA).exists():
                continue
            status = [UserEvaluation.STATUS_COMPLETED, UserEvaluation.STATUS_COMPLETED, UserEvaluation.STATUS_IN_PROGRESS, UserEvaluation.STATUS_PENDING][idx % 4]
            ue = UserEvaluation.objects.create(
                evaluation_form=form,
                evaluated_user=user,
                assigned_by=self.users.get("gerente.demo"),
                status=status,
                branch=self.branches[idx % len(self.branches)],
                due_date=timezone.localdate() + timedelta(days=15 - idx),
                completed_at=timezone.now() - timedelta(days=idx) if status == UserEvaluation.STATUS_COMPLETED else None,
                score=Decimal(str(76 + (idx % 6) * 4)) if status == UserEvaluation.STATUS_COMPLETED else None,
                notes=f"{MARCA} evaluación generada para presentación",
                source="WEB",
            )
            if status == UserEvaluation.STATUS_COMPLETED:
                for q in form.questions.all():
                    UserEvaluationAnswer.objects.create(
                        user_evaluation=ue,
                        question=q,
                        answer_rating=(4 + idx % 2) if q.question_type == EvaluationFormQuestion.TYPE_RATING else None,
                        answer_text=("No" if q.question_type == EvaluationFormQuestion.TYPE_BOOLEAN else "Buen desempeño general." if q.question_type == EvaluationFormQuestion.TYPE_TEXT else None),
                    )
            created += 1
        self.stdout.write(self.style.SUCCESS(f"[OK] Evaluaciones: +{created}"))

    def _seed_notifications(self):
        templates = [
            (Notification.TYPE_STOCK_LOW, "Stock bajo detectado", "Un producto se encuentra bajo su nivel mínimo."),
            (Notification.TYPE_PURCHASE_ORDER, "Orden de compra aprobada", "Una orden de compra quedó disponible para gestión."),
            (Notification.TYPE_TRANSFER, "Transferencia recibida", "Una transferencia entre sucursales fue recepcionada."),
            (Notification.TYPE_SUPPLIER_CLAIM, "Reclamo de proveedor actualizado", "Existe una novedad en un reclamo de proveedor."),
            (Notification.TYPE_PAYMENT, "Pago registrado", "Finanzas registró un pago a proveedor."),
            (Notification.TYPE_SYSTEM, "Resumen operativo disponible", "El tablero mensual fue actualizado con nueva información."),
        ]
        created = 0
        for user_idx, user in enumerate(self.users.values()):
            for idx, (kind, title, message) in enumerate(templates[:3]):
                final_title = f"{title} · DEMO {user_idx+1}-{idx+1}"
                if Notification.objects.filter(user=user, title=final_title).exists():
                    continue
                Notification.objects.create(
                    user=user,
                    title=final_title,
                    message=f"{message} {MARCA}",
                    notification_type=kind,
                    is_read=(idx == 2),
                    read_at=timezone.now() - timedelta(hours=2) if idx == 2 else None,
                )
                created += 1
        self.stdout.write(self.style.SUCCESS(f"[OK] Notificaciones: +{created}"))

    def _seed_documents(self):
        doc_defs = [
            (Document.TYPE_PURCHASE_ORDER_PDF, "OC-DEMO-2026-001.pdf", "purchasing", "PurchaseOrder"),
            (Document.TYPE_INVOICE, "FACTURA-DEMO-8741.pdf", "finance", "SupplierInvoice"),
            (Document.TYPE_DISPATCH_GUIDE, "GUIA-DEMO-5521.pdf", "purchasing", "PurchaseReceipt"),
            (Document.TYPE_QUOTATION, "COTIZACION-DEMO-119.pdf", "suppliers", "Supplier"),
            (Document.TYPE_PAYMENT_RECEIPT, "COMPROBANTE-DEMO-884.pdf", "finance", "Payment"),
        ]
        created = 0
        for kind, filename, app, model in doc_defs:
            _, was_created = Document.objects.update_or_create(
                file_name=filename,
                defaults={
                    "document_type": kind,
                    "file_url": f"demo://maulemed/{filename}",
                    "file_size": 120000,
                    "mime_type": "application/pdf",
                    "related_app": app,
                    "related_model": model,
                    "uploaded_by": self.users.get("admin.demo"),
                    "notes": f"Documento referencial. {MARCA}",
                },
            )
            created += int(was_created)
        self.stdout.write(self.style.SUCCESS(f"[OK] Documentos metadata: +{created}"))

    def _seed_audit(self):
        if AuditLog.objects.filter(notes__startswith=MARCA).exists():
            return
        models = ["PurchaseOrder", "SupplierInvoice", "InventoryStock", "StockTransfer", "SupplyRequest"]
        actions = [AuditLog.ACTION_CREATE, AuditLog.ACTION_UPDATE, AuditLog.ACTION_APPROVE, AuditLog.ACTION_EXPORT]
        users = list(self.users.values())
        for idx in range(120):
            log = AuditLog.objects.create(
                user=users[idx % len(users)],
                action=actions[idx % len(actions)],
                entity_app="demo",
                entity_model=models[idx % len(models)],
                old_data={"status": "ANTERIOR"} if idx % 2 else None,
                new_data={"status": "ACTUALIZADO", "demo": True},
                ip_address="10.10.0.25",
                user_agent="MauleMed Demo Browser",
                notes=f"{MARCA} evento de auditoría {idx+1:03d}",
            )
            AuditLog.objects.filter(pk=log.pk).update(
                created_at=timezone.now() - timedelta(hours=idx * 4)
            )
        self.stdout.write(self.style.SUCCESS("[OK] Auditoría: +120"))

    def _print_summary(self):
        self.stdout.write(self.style.MIGRATE_HEADING("\n=== RESUMEN DEMO ==="))
        rows = [
            ("Sucursales", Branch.objects.filter(organization=self.organization).count()),
            ("Usuarios", len(self.users)),
            ("Productos demo", Product.objects.filter(internal_code__startswith="DEMO-P").count()),
            ("Proveedores demo", Supplier.objects.filter(email__endswith="@proveedor-demo.cl").count()),
            ("Stocks", InventoryStock.objects.count()),
            ("Lotes", InventoryLot.objects.filter(lot_number__startswith="DEMO-").count()),
            ("Movimientos demo", InventoryMovement.objects.filter(reason__startswith=MARCA).count()),
            ("Órdenes de compra", PurchaseOrder.objects.count()),
            ("Recepciones demo", PurchaseReceipt.objects.filter(comments__startswith=MARCA).count()),
            ("Reclamos demo", SupplierClaim.objects.filter(description__startswith=MARCA).count()),
            ("Facturas", SupplierInvoice.objects.count()),
            ("Pagos demo", Payment.objects.filter(notes=MARCA).count()),
            ("Transferencias demo", StockTransfer.objects.filter(reason__startswith=MARCA).count()),
            ("Evaluaciones demo", UserEvaluation.objects.filter(notes__startswith=MARCA).count()),
            ("Notificaciones demo", Notification.objects.filter(message__contains=MARCA).count()),
            ("Auditoría demo", AuditLog.objects.filter(notes__startswith=MARCA).count()),
        ]
        for label, value in rows:
            self.stdout.write(f"{label:<28} {value:>8}")
        self.stdout.write(self.style.SUCCESS("\nDemo MauleMed cargada correctamente."))
        self.stdout.write(self.style.WARNING(f"Usuarios demo: *.demo / contraseña: {self.password}"))
