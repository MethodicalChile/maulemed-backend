"""
Genera doce meses de historia para que el tablero tenga forma.

Los datos reales de la carpeta de reportes son de un solo día: el reporte de
prestaciones del 21-07 y el informe de depósitos del 24-07. Una tendencia
mensual sobre eso es un punto. Este comando extiende hacia atrás con datos
sintéticos que respetan los patrones medidos sobre el archivo real:

- ticket promedio $21.542, rango $10.000 a $41.000
- el mix de financiadores de la muestra, con FONASA dominando
- copago ~61,6 % de la caja y 56,5 % cobrado con tarjeta
- sin actividad los domingos, sábados con volumen bajo

    python manage.py seed_demo_historia --months 12

Es idempotente: cada lote queda marcado y volver a correrlo reemplaza lo que
generó antes, no lo duplica. La semilla es fija para que dos corridas den lo
mismo.
"""

import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum, Value
from django.db.models.functions import Coalesce
from django.db import transaction
from django.utils import timezone

from apps.finance.models import (
    Budget,
    BudgetCategory,
    SupplierInvoice,
    SupplierInvoiceItem,
)
from apps.finance.services import register_supplier_invoice
from apps.inventory.models import InventoryLot, InventoryStock, Warehouse
from apps.organizations.models import Branch, CostCenter, LegalEntity
from apps.products.models import (
    BranchProduct,
    Product,
    ProductCategory,
    UnitOfMeasure,
)
from apps.purchasing.models import (
    PurchaseOrder,
    PurchaseOrderItem,
    SupplyRequest,
    SupplyRequestItem,
)
from apps.revenue.models import (
    CashCollection,
    Financier,
    RevenueEntry,
    RevenueImportBatch,
)
from apps.revenue.services.receivables import build_receivables_from_revenue
from apps.suppliers.models import Supplier


MARCA = "demo:historia"
SEMILLA = 20260824

# Mix de financiadores medido sobre las 37 prestaciones del archivo real.
MIX_FINANCIADORES = [
    ("FONASA-N3", 0.35),
    ("PARTICULAR", 0.11),
    ("MUN-VILLA-ALEGRE", 0.11),
    ("DIPRECA", 0.11),
    ("NUEVA-MAS-VIDA", 0.08),
    ("SALUD-LONGAVI", 0.08),
    ("MUN-YERBAS-BUENAS", 0.08),
    ("MUN-LINARES", 0.05),
    ("MUN-COLBUN", 0.03),
]

PRESTACIONES = [
    ("0401070", "RADIOGRAFIA DE TORAX FRONTAL Y LATERAL", "cr"),
    ("0401009", "RADIOGRAFIA DE TORAX SIMPLE FRONTAL O LATERAL", "cr"),
    ("0403014", "RX COLUMNA TOTAL FRONTAL", "cr"),
    ("0403015", "RX COLUMNA TOTAL LATERAL", "cr"),
    ("0404012", "RADIOGRAFIA DE RODILLA", "cr"),
    ("0406021", "TOMOGRAFIA COMPUTADA DE ABDOMEN", "ct"),
    ("0407011", "RESONANCIA MAGNETICA DE CEREBRO", "mr"),
    ("0402005", "RADIOGRAFIA DE CAVIDADES PERINASALES", "cr"),
]

# Estacionalidad suave: enero y febrero bajos por vacaciones, invierno alto.
ESTACIONALIDAD = {
    1: 0.72, 2: 0.70, 3: 1.02, 4: 1.05, 5: 1.14, 6: 1.20,
    7: 1.22, 8: 1.16, 9: 1.04, 10: 1.03, 11: 0.98, 12: 0.85,
}

# Las líneas del presupuesto que la demo carga, con su monto mensual por
# sociedad. Son las que el ciclo de compra puede llegar a consumir.
PRESUPUESTO_LINEAS = [
    ("OP-EGR-07", Decimal("450000")),   # Insumos clínicos
    ("OP-EGR-08", Decimal("380000")),   # Contraste y medicamentos
    ("OP-EGR-01", Decimal("1400000")),  # Honorarios informes médicos
    ("OP-EGR-02", Decimal("2200000")),  # Remuneraciones
    ("OP-EGR-04", Decimal("520000")),   # Arriendo
    ("OP-EGR-12", Decimal("310000")),   # Licencias RIS/PACS y software
]

# Cada insumo con su precio y la línea del presupuesto a la que se imputa. Sin
# esa línea, todas las facturas caían sobre la primera fila que encontrara la
# búsqueda y la ejecución presupuestaria salía repartida al azar.
INSUMOS = [
    ("Medio de contraste yodado", Decimal("48000"), "OP-EGR-08"),
    ("Película radiográfica 35x43", Decimal("9500"), "OP-EGR-07"),
    ("Guantes de nitrilo caja 100", Decimal("12800"), "OP-EGR-07"),
    ("Alcohol gel 1L", Decimal("4200"), "OP-EGR-07"),
    ("Jeringa 20ml caja 100", Decimal("18500"), "OP-EGR-07"),
    ("Gasa estéril paquete", Decimal("3100"), "OP-EGR-07"),
]


class Command(BaseCommand):
    help = "Genera doce meses de historia sintética para la demo."

    def add_arguments(self, parser):
        parser.add_argument("--months", type=int, default=12)
        parser.add_argument(
            "--limpiar",
            action="store_true",
            help="Borra la historia generada antes y termina.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self.rng = random.Random(SEMILLA)

        borrados = self._limpiar()
        if options["limpiar"]:
            self.stdout.write(self.style.SUCCESS(f"Historia borrada ({borrados})."))
            return

        sociedades = list(LegalEntity.objects.filter(is_active=True))
        if not sociedades:
            self.stdout.write(
                self.style.ERROR(
                    "No hay razones sociales cargadas. Créalas antes de sembrar."
                )
            )
            return

        financiadores = self._financiadores()
        if not financiadores:
            self.stdout.write(
                self.style.ERROR(
                    "No hay financiadores. Corre primero seed_demo_finanzas."
                )
            )
            return

        meses = self._meses(options["months"])

        lote = RevenueImportBatch.objects.create(
            file_name=MARCA,
            status=RevenueImportBatch.STATUS_IMPORTED,
            period_from=meses[0],
            period_to=meses[-1],
            notes=MARCA,
        )

        prestaciones = self._sembrar_ingresos(lote, meses, sociedades, financiadores)
        cajas = self._sembrar_recaudacion(meses, sociedades)
        self._sembrar_presupuestos(meses, sociedades)
        compras = self._sembrar_compras(meses, sociedades)
        solicitudes = self._sembrar_solicitudes(meses, sociedades)
        inventario = self._sembrar_inventario(sociedades)
        cuentas = self._reconstruir_cobranza(meses)

        lote.rows_total = prestaciones
        lote.rows_imported = prestaciones
        lote.save(update_fields=["rows_total", "rows_imported", "updated_at"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Historia de {options['months']} meses: "
                f"{prestaciones} prestaciones, {cajas} cierres de caja, "
                f"{compras} órdenes con su factura, {solicitudes} solicitudes, "
                f"{inventario} posiciones de stock y {cuentas} cuentas por cobrar."
            )
        )

    # ── Limpieza ───────────────────────────────────────────────────────────

    def _limpiar(self):
        lotes = RevenueImportBatch.all_objects.filter(notes=MARCA)
        n_prest = RevenueEntry.all_objects.filter(import_batch__in=lotes).count()

        RevenueEntry.all_objects.filter(import_batch__in=lotes).delete()
        lotes.delete()

        n_caja = CashCollection.all_objects.filter(source_document__isnull=True).exclude(
            collection_date=date(2026, 7, 24)
        ).count()
        CashCollection.all_objects.filter(source_document__isnull=True).exclude(
            collection_date=date(2026, 7, 24)
        ).delete()

        solicitudes = SupplyRequest.all_objects.filter(comments=MARCA)
        SupplyRequestItem.all_objects.filter(
            supply_request__in=solicitudes
        ).delete()
        solicitudes.delete()

        ordenes = PurchaseOrder.all_objects.filter(notes=MARCA)
        n_ord = ordenes.count()
        facturas = SupplierInvoice.all_objects.filter(notes=MARCA)
        SupplierInvoiceItem.all_objects.filter(supplier_invoice__in=facturas).delete()
        facturas.delete()
        PurchaseOrderItem.all_objects.filter(purchase_order__in=ordenes).delete()
        ordenes.delete()

        return f"{n_prest} prestaciones, {n_caja} cajas, {n_ord} órdenes"

    # ── Utilidades ─────────────────────────────────────────────────────────

    def _meses(self, cantidad):
        """Primer día de cada mes, del más antiguo al actual."""
        hoy = timezone.localdate()
        meses = []
        año, mes = hoy.year, hoy.month

        for _ in range(cantidad):
            meses.append(date(año, mes, 1))
            mes -= 1
            if mes == 0:
                mes, año = 12, año - 1

        return list(reversed(meses))

    def _dias_habiles(self, primero):
        """Días del mes con actividad. Domingo cerrado, sábado a media máquina."""
        if primero.month == 12:
            siguiente = date(primero.year + 1, 1, 1)
        else:
            siguiente = date(primero.year, primero.month + 1, 1)

        hoy = timezone.localdate()
        dias = []
        d = primero

        while d < siguiente and d <= hoy:
            if d.weekday() != 6:  # domingo
                dias.append(d)
            d += timedelta(days=1)

        return dias

    def _financiadores(self):
        por_codigo = {f.code: f for f in Financier.objects.filter(is_active=True)}
        pares = [
            (por_codigo[code], peso)
            for code, peso in MIX_FINANCIADORES
            if code in por_codigo
        ]
        return pares

    def _elegir_financiador(self, pares):
        total = sum(p for _, p in pares)
        r = self.rng.uniform(0, total)
        acumulado = 0
        for financiador, peso in pares:
            acumulado += peso
            if r <= acumulado:
                return financiador
        return pares[-1][0]

    def _valor(self):
        """Ticket con la forma del archivo real: promedio $21.542, tope $41.000."""
        valor = self.rng.gauss(21542, 7800)
        valor = max(10000, min(41000, valor))
        return Decimal(int(round(valor / 10) * 10))

    # ── Ingresos ───────────────────────────────────────────────────────────

    def _sembrar_ingresos(self, lote, meses, sociedades, financiadores):
        sucursales = {
            le.id: list(Branch.objects.filter(legal_entity=le, is_active=True))
            for le in sociedades
        }

        entradas = []
        contador = 0

        for primero in meses:
            factor = ESTACIONALIDAD[primero.month]

            for dia in self._dias_habiles(primero):
                base = 14 if dia.weekday() < 5 else 5
                cantidad = max(1, int(self.rng.gauss(base * factor, 3)))

                for _ in range(cantidad):
                    le = self.rng.choice(sociedades)
                    financiador = self._elegir_financiador(financiadores)
                    codigo, nombre, modalidad = self.rng.choice(PRESTACIONES)

                    bruto = self._valor()
                    # Uno de cada diez lleva descuento, como en el archivo real.
                    descuento = (
                        Decimal(int(bruto * Decimal("0.15")))
                        if self.rng.random() < 0.10
                        else Decimal("0")
                    )

                    contador += 1
                    ramas = sucursales.get(le.id) or []

                    entradas.append(
                        RevenueEntry(
                            legal_entity=le,
                            branch=self.rng.choice(ramas) if ramas else None,
                            financier=financiador,
                            service_date=dia,
                            appointment_ref=f"H{contador:06d}",
                            procedure_code=codigo,
                            procedure_name=nombre,
                            modality=modalidad,
                            status="finalizado",
                            gross_amount=bruto,
                            discount_amount=descuento,
                            net_amount=bruto - descuento,
                            import_batch=lote,
                        )
                    )

        RevenueEntry.objects.bulk_create(entradas, batch_size=1000)
        return len(entradas)

    # ── Recaudación ────────────────────────────────────────────────────────

    def _sembrar_recaudacion(self, meses, sociedades):
        """
        La caja del día se deriva de las prestaciones de ese día, no se inventa
        aparte.

        Es la relación que el informe describe y que el tablero tiene que
        mostrar sin contradicciones:

            devengado = recaudado en mesón + deuda institucional

        El particular paga el total en el mesón. El paciente con previsión paga
        sólo el copago —en la muestra real, el 61,6 % de la caja del día— y la
        bonificación queda por cobrar al financiador. Generar la caja como un
        número independiente daba una recaudación diez veces mayor que el
        ingreso, que es imposible.
        """
        from django.db.models import Q

        COPAGO_INSTITUCIONAL = Decimal("0.30")  # parte que paga el paciente

        entradas = (
            RevenueEntry.objects.filter(service_date__gte=meses[0])
            .values("legal_entity_id", "service_date")
            .annotate(
                particular=Coalesce(
                    Sum(
                        "net_amount",
                        filter=Q(financier__financier_type=Financier.TYPE_PRIVATE),
                    ),
                    Value(Decimal("0")),
                ),
                institucional=Coalesce(
                    Sum(
                        "net_amount",
                        filter=~Q(financier__financier_type=Financier.TYPE_PRIVATE),
                    ),
                    Value(Decimal("0")),
                ),
            )
        )

        existentes = set(
            CashCollection.objects.values_list("legal_entity_id", "collection_date")
        )

        cajas = []

        for fila in entradas:
            clave = (fila["legal_entity_id"], fila["service_date"])
            if clave in existentes:
                continue

            particular = Decimal(fila["particular"] or 0)
            copago = Decimal(
                int(Decimal(fila["institucional"] or 0) * COPAGO_INSTITUCIONAL)
            )
            total = particular + copago

            if total <= 0:
                continue

            # Mix de medios de pago del informe del 24-07: débito 49,8 %,
            # efectivo 43,4 %, crédito 6,7 %, cheque 0.
            efectivo = Decimal(int(total * Decimal("0.434")))
            debito = Decimal(int(total * Decimal("0.498")))
            credito = total - efectivo - debito

            cajas.append(
                CashCollection(
                    legal_entity_id=fila["legal_entity_id"],
                    branch=None,
                    collection_date=fila["service_date"],
                    particular_amount=particular,
                    copay_amount=copago,
                    withdrawal_amount=Decimal("0"),
                    total_amount=total,
                    cash_amount=efectivo,
                    debit_amount=debito,
                    credit_amount=credito,
                    # El cheque es el medio de pago a proveedores, no de cobro:
                    # por eso nunca aparece en la recaudación.
                    check_amount=Decimal("0"),
                )
            )

        CashCollection.objects.bulk_create(cajas, batch_size=1000)
        return len(cajas)

    # ── Compras ────────────────────────────────────────────────────────────

    def _sembrar_compras(self, meses, sociedades):
        proveedores = self._proveedores()
        productos = self._productos()

        creadas = 0

        for primero in meses:
            for le in sociedades:
                centros = list(CostCenter.objects.filter(legal_entity=le))
                sucursales = list(Branch.objects.filter(legal_entity=le))
                if not centros:
                    continue

                for _ in range(self.rng.randint(1, 3)):
                    proveedor = self.rng.choice(proveedores)
                    centro = self.rng.choice(centros)
                    dia = primero + timedelta(days=self.rng.randint(0, 25))
                    if dia > timezone.localdate():
                        continue

                    items = self.rng.sample(productos, self.rng.randint(1, 3))
                    neto = Decimal("0")

                    orden = PurchaseOrder.objects.create(
                        order_number=f"OC-DEMO-{creadas + 1:05d}",
                        supplier=proveedor,
                        legal_entity=le,
                        branch=self.rng.choice(sucursales) if sucursales else None,
                        cost_center=centro,
                        status=PurchaseOrder.STATUS_RECEIVED,
                        purchase_type=self._tipo_compra(),
                        expected_delivery_date=dia + timedelta(days=self.rng.randint(3, 12)),
                        notes=MARCA,
                    )

                    for producto, precio, _linea in items:
                        cantidad = Decimal(self.rng.randint(2, 20))
                        subtotal = cantidad * precio
                        neto += subtotal
                        PurchaseOrderItem.objects.create(
                            purchase_order=orden,
                            product=producto,
                            quantity=cantidad,
                            unit_price=precio,
                            total_amount=subtotal,
                        )

                    iva = Decimal(int(neto * Decimal("0.19")))
                    PurchaseOrder.objects.filter(pk=orden.pk).update(
                        subtotal_amount=neto,
                        tax_amount=iva,
                        total_amount=neto + iva,
                        created_at=timezone.make_aware(
                            timezone.datetime.combine(dia, timezone.datetime.min.time())
                        ),
                    )

                    factura = SupplierInvoice.objects.create(
                        supplier=proveedor,
                        legal_entity=le,
                        branch=orden.branch,
                        cost_center=centro,
                        purchase_order=orden,
                        invoice_number=f"F-DEMO-{creadas + 1:05d}",
                        issue_date=dia + timedelta(days=self.rng.randint(1, 8)),
                        net_amount=neto,
                        tax_amount=iva,
                        total_amount=neto + iva,
                        status=SupplierInvoice.STATUS_PAID,
                        notes=MARCA,
                    )

                    # Detalle por ítem con su línea presupuestaria: es lo que
                    # permite que cada gasto caiga donde corresponde en vez de
                    # cargarse entero a la cabecera.
                    for producto, precio, linea in items:
                        item = next(
                            i for i in orden.items.all() if i.product_id == producto.id
                        )
                        SupplierInvoiceItem.objects.create(
                            supplier_invoice=factura,
                            product=producto,
                            cost_center=centro,
                            budget_category=linea,
                            quantity=item.quantity,
                            unit_price=precio,
                            tax_amount=Decimal(int(item.quantity * precio * Decimal("0.19"))),
                        )

                    # Se pasa por el servicio, no se escribe el consumo a mano:
                    # así la ejecución presupuestaria del tablero sale del mismo
                    # camino que sigue una factura registrada por la interfaz.
                    register_supplier_invoice(factura)

                    creadas += 1

        return creadas

    # ── Solicitudes de insumos ─────────────────────────────────────────────

    def _sembrar_solicitudes(self, meses, sociedades):
        """
        Solicitudes repartidas por las fases del ciclo.

        Sin esto el gráfico de estado de compras muestra una sola barra: todo
        cerrado. La operación real tiene siempre algo en revisión y algo por
        enviar, y eso es lo que el tablero debe dejar ver.
        """
        productos = self._productos()

        # Las proporciones de una operación en marcha: la mayoría ya convertida
        # en compra, unas pocas esperando revisión, alguna rechazada.
        REPARTO = [
            (SupplyRequest.STATUS_CONVERTED_TO_PURCHASE, 0.55),
            (SupplyRequest.STATUS_APPROVED, 0.15),
            (SupplyRequest.STATUS_IN_REVIEW, 0.10),
            (SupplyRequest.STATUS_SUBMITTED, 0.08),
            (SupplyRequest.STATUS_OBSERVED, 0.05),
            (SupplyRequest.STATUS_DRAFT, 0.04),
            (SupplyRequest.STATUS_REJECTED, 0.03),
        ]

        creadas = 0

        for primero in meses:
            for le in sociedades:
                sucursales = list(Branch.objects.filter(legal_entity=le, is_active=True))
                centros = list(CostCenter.objects.filter(legal_entity=le))
                if not sucursales or not centros:
                    continue

                for _ in range(self.rng.randint(1, 3)):
                    estado = self._elegir_estado(REPARTO)

                    solicitud = SupplyRequest.objects.create(
                        branch=self.rng.choice(sucursales),
                        legal_entity=le,
                        cost_center=self.rng.choice(centros),
                        period_year=primero.year,
                        period_month=primero.month,
                        status=estado,
                        comments=MARCA,
                    )

                    for producto, precio, _linea in self.rng.sample(
                        productos, self.rng.randint(1, 3)
                    ):
                        pedida = Decimal(self.rng.randint(5, 40))
                        SupplyRequestItem.objects.create(
                            supply_request=solicitud,
                            product=producto,
                            requested_quantity=pedida,
                            # El consumo habitual y el stock del momento: los dos
                            # datos con los que la Encargada valida la cantidad.
                            usual_quantity=pedida * Decimal(
                                str(round(self.rng.uniform(0.7, 1.3), 2))
                            ),
                            current_stock_snapshot=Decimal(self.rng.randint(0, 30)),
                        )

                    creadas += 1

        return creadas

    def _elegir_estado(self, reparto):
        r = self.rng.random()
        acumulado = 0
        for estado, peso in reparto:
            acumulado += peso
            if r <= acumulado:
                return estado
        return reparto[-1][0]

    # ── Presupuestos ───────────────────────────────────────────────────────

    def _sembrar_presupuestos(self, meses, sociedades):
        """
        Presupuesto mensual por sociedad, centro de costo y línea.

        Sin esto la fila de medidores del tablero queda vacía y el control
        presupuestario no tiene contra qué comparar.
        """
        lineas = list(
            BudgetCategory.objects.filter(
                code__in=[c for c, _ in PRESUPUESTO_LINEAS]
            )
        )
        montos = dict(PRESUPUESTO_LINEAS)

        creados = 0
        for le in sociedades:
            centros = list(CostCenter.objects.filter(legal_entity=le))
            if not centros:
                continue
            centro = centros[0]

            for primero in meses:
                for linea in lineas:
                    _, nuevo = Budget.objects.get_or_create(
                        legal_entity=le,
                        branch=None,
                        cost_center=centro,
                        budget_category=linea,
                        period_year=primero.year,
                        period_month=primero.month,
                        defaults={"budget_amount": montos[linea.code]},
                    )
                    creados += int(nuevo)

        return creados

    # ── Inventario ─────────────────────────────────────────────────────────

    def _sembrar_inventario(self, sociedades):
        """
        Bodega, umbrales, stock y lotes por sucursal.

        Se dejan a propósito algunos productos bajo el umbral crítico y algunos
        lotes por vencer dentro de treinta días: son los dos avisos que el
        tablero tiene que poder mostrar.
        """
        productos = self._productos()
        posiciones = 0

        for le in sociedades:
            for sucursal in Branch.objects.filter(legal_entity=le, is_active=True):
                bodega, _ = Warehouse.objects.get_or_create(
                    branch=sucursal,
                    name="Bodega central",
                    defaults={"warehouse_type": Warehouse.WAREHOUSE_TYPE_GENERAL},
                )

                for indice, (producto, precio, _linea) in enumerate(productos):
                    minimo = Decimal(self.rng.randint(20, 60))
                    critico = Decimal(int(minimo / 2))

                    BranchProduct.objects.get_or_create(
                        branch=sucursal,
                        product=producto,
                        defaults={
                            "min_stock": minimo,
                            "critical_stock": critico,
                            "usual_monthly_quantity": minimo * 2,
                            "is_active": True,
                        },
                    )

                    # Uno de cada tres queda bajo el umbral crítico.
                    if indice % 3 == 0:
                        cantidad = Decimal(self.rng.randint(0, int(critico)))
                    else:
                        cantidad = Decimal(self.rng.randint(int(minimo), int(minimo) * 4))

                    _, nuevo = InventoryStock.objects.get_or_create(
                        warehouse=bodega,
                        product=producto,
                        defaults={
                            "quantity": cantidad,
                            "min_level": minimo,
                            "max_level": minimo * 5,
                        },
                    )
                    posiciones += int(nuevo)

                    # Un lote por vencer y otro con holgura.
                    for dias in (self.rng.randint(5, 28), self.rng.randint(120, 400)):
                        InventoryLot.objects.get_or_create(
                            warehouse=bodega,
                            product=producto,
                            lot_number=f"L{sucursal.id}{producto.id}{dias}",
                            defaults={
                                "expiration_date": timezone.localdate()
                                + timedelta(days=dias),
                                "quantity": Decimal(self.rng.randint(5, 40)),
                                "status": InventoryLot.STATUS_AVAILABLE,
                            },
                        )

        return posiciones

    # ── Cobranza ───────────────────────────────────────────────────────────

    def _reconstruir_cobranza(self, meses):
        """La deuda institucional de cada mes, desde el libro de ingresos."""
        total = 0
        for primero in meses:
            cuentas = build_receivables_from_revenue(
                period_year=primero.year,
                period_month=primero.month,
            )
            total += len(cuentas)

            # Un cobro parcial en los meses viejos, para que la antigüedad
            # tenga tramos distintos y no todo caiga en "90+".
            antiguedad = (timezone.localdate() - primero).days
            for cuenta in cuentas:
                cuenta.due_date = primero + timedelta(days=self.rng.randint(30, 75))
                if antiguedad > 120 and self.rng.random() < 0.7:
                    cuenta.collected_amount = Decimal(
                        int(cuenta.billed_amount * Decimal(str(self.rng.uniform(0.5, 1.0))))
                    )
                cuenta.recalculate_status()
                cuenta.save(
                    update_fields=["due_date", "collected_amount", "status", "updated_at"]
                )

        return total

    def _tipo_compra(self):
        """Una de cada seis es extraordinaria — el indicador que el informe pide."""
        r = self.rng.random()
        if r < 0.10:
            return PurchaseOrder.PURCHASE_TYPE_URGENT
        if r < 0.16:
            return PurchaseOrder.PURCHASE_TYPE_MANAGEMENT
        return PurchaseOrder.PURCHASE_TYPE_PURCHASE_ORDER

    def _proveedores(self):
        nombres = [
            ("Distribuidora Clínica S.A.", "96500000-1", 30),
            ("Insumos Médicos del Maule Ltda.", "76300100-2", 45),
            ("Comercial Radiológica SpA", "77200300-4", 30),
            ("Suministros Generales Linares", "78100400-6", 15),
        ]
        creados = []
        for nombre, rut, plazo in nombres:
            proveedor, _ = Supplier.objects.get_or_create(
                rut=rut,
                defaults={
                    "name": nombre,
                    "payment_terms_days": plazo,
                    "payment_terms": f"{plazo} días fecha factura",
                    "is_active": True,
                },
            )
            creados.append(proveedor)
        return creados

    def _productos(self):
        categoria, _ = ProductCategory.objects.get_or_create(name="Insumos clínicos")
        unidad, _ = UnitOfMeasure.objects.get_or_create(
            code="UN", defaults={"name": "Unidad"}
        )

        lineas = {
            c.code: c for c in BudgetCategory.objects.filter(
                code__in={codigo for _, _, codigo in INSUMOS}
            )
        }

        creados = []
        for nombre, precio, codigo in INSUMOS:
            producto, _ = Product.objects.get_or_create(
                name=nombre,
                defaults={"category": categoria, "unit": unidad},
            )
            creados.append((producto, precio, lineas.get(codigo)))
        return creados
