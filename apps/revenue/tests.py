"""
Tests de la app revenue.

El más importante es el que carga el archivo real de la carpeta Reportes Liz y
contrasta contra las cifras que el análisis de datos ya verificó a mano: 37
prestaciones, $797.040, y el desglose por prestador.
"""

from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import UserProfile
from apps.organizations.models import (
    Organization,
    LegalEntity,
    Branch,
    LegalEntityAlias,
)
from apps.revenue.models import (
    Financier,
    FinancierAlias,
    RevenueEntry,
    RevenueImportBatch,
)

User = get_user_model()


REPORTES_DIR = Path(
    "/home/josetomasrobert/Desktop/Methodical/MauleMed-2026/Reportes Liz 24-07"
)
REPORTE_XLSX = REPORTES_DIR / "reporte - 2026-07-21T150838.563.xlsx"


def make_superuser(username="revadmin", password="revpass"):
    u = User.objects.create_user(
        username=username, password=password, is_superuser=True, is_staff=True
    )
    UserProfile.objects.get_or_create(user=u, defaults={})
    return u


def setup_sociedades():
    org = Organization.objects.create(name="MauleMed", is_active=True)

    irama = LegalEntity.objects.create(
        organization=org, name="Imágenes Radiológicas Maule", rut="76100001-1"
    )
    iral = LegalEntity.objects.create(
        organization=org, name="Instituto Radiológico Linares", rut="76869710-8"
    )
    sodiagma = LegalEntity.objects.create(
        organization=org, name="Soc. de Diagnóstico Maule", rut="76551640-4"
    )

    for entidad, codigo in (
        (irama, "IRAMA"),
        (iral, "IRAL"),
        (sodiagma, "SODIAGMA"),
    ):
        LegalEntityAlias.objects.create(
            legal_entity=entidad,
            alias_type=LegalEntityAlias.TYPE_PROVIDER_CODE,
            value=codigo,
        )

    Branch.objects.create(
        organization=org,
        legal_entity=sodiagma,
        name="SODIAGMA LINARES",
        code="SL01",
    )

    return org, {"IRAMA": irama, "IRAL": iral, "SODIAGMA": sodiagma}


def setup_financiadores():
    """
    Los diez financiadores de la muestra. Los dos de Linares apuntan al mismo
    financiador a propósito: el archivo real trae ambas grafías.
    """

    definiciones = [
        ("FONASA-N3", "FONASA Nivel 3", Financier.TYPE_FONASA, ["FONASA N3"]),
        ("PARTICULAR", "Particular", Financier.TYPE_PRIVATE, ["PARTICULAR"]),
        (
            "MUN-LINARES",
            "Municipalidad de Linares",
            Financier.TYPE_AGREEMENT,
            ["MUNICIPALIDAD DE LINARES", "MUNICIP. LINARES"],
        ),
        ("MUN-VALEGRE", "Municipalidad de Villa Alegre", Financier.TYPE_AGREEMENT, ["MUNICIP. VILLA ALEGRE"]),
        ("DIPRECA", "DIPRECA", Financier.TYPE_AGREEMENT, ["DIPRECA"]),
        ("NMV", "Nueva Más Vida", Financier.TYPE_ISAPRE, ["NUEVA MAS VIDA"]),
        ("LONGAVI", "Dpto. Salud Longaví", Financier.TYPE_AGREEMENT, ["DPTO SALUD LONGAVÍ", "DPTO SALUD LONGAVI"]),
        ("MUN-YBUENAS", "Municipalidad de Yerbas Buenas", Financier.TYPE_AGREEMENT, ["MUNICIP. YERBAS BUENAS"]),
        ("MUN-COLBUN", "Municipalidad de Colbún", Financier.TYPE_AGREEMENT, ["MUNICIP COLBÚN", "MUNICIP COLBUN"]),
    ]

    creados = {}
    for code, name, tipo, alias_list in definiciones:
        financier = Financier.objects.create(
            code=code,
            name=name,
            financier_type=tipo,
            generates_receivable=(tipo != Financier.TYPE_PRIVATE),
        )
        for alias in alias_list:
            FinancierAlias.objects.create(financier=financier, raw_name=alias)
        creados[code] = financier

    return creados


# ---------------------------------------------------------------------------
# Normalización de catálogos
# ---------------------------------------------------------------------------

class AliasResolutionTests(TestCase):

    def setUp(self):
        self.org, self.sociedades = setup_sociedades()
        self.financiadores = setup_financiadores()

    def test_codigo_de_prestador_resuelve_a_razon_social(self):
        """El maestro que no existía: IRAMA/IRAL/SODIAGMA → RUT."""
        self.assertEqual(
            LegalEntityAlias.resolve("IRAMA"), self.sociedades["IRAMA"]
        )

    def test_resolucion_ignora_mayusculas_y_espacios(self):
        self.assertEqual(
            LegalEntityAlias.resolve("  irama  "), self.sociedades["IRAMA"]
        )

    def test_prestador_desconocido_devuelve_none(self):
        self.assertIsNone(LegalEntityAlias.resolve("SOCIEDAD FANTASMA"))

    def test_dos_grafias_colapsan_en_un_financiador(self):
        """
        En 37 filas convivían "MUNICIPALIDAD DE LINARES" y "MUNICIP. LINARES"
        como entidades distintas. Con doce meses eso es doble conteo silencioso.
        """
        uno = FinancierAlias.resolve("MUNICIPALIDAD DE LINARES")
        otro = FinancierAlias.resolve("MUNICIP. LINARES")

        self.assertIsNotNone(uno)
        self.assertEqual(uno, otro)


# ---------------------------------------------------------------------------
# Importación
# ---------------------------------------------------------------------------

class ImportRecordsTests(TestCase):

    def setUp(self):
        self.org, self.sociedades = setup_sociedades()
        self.financiadores = setup_financiadores()

    def _record(self, **kwargs):
        base = {
            "id": "1001",
            "date": "2026-07-21",
            "provider": "IRAMA",
            "financier": "FONASA N3",
            "branch": "SODIAGMA LINARES",
            "procedure_code": "RX-01",
            "procedure": "Radiografía de tórax",
            "modality": "cr",
            "status": "finalizado",
            "value": 23000,
            "discount": 0,
            "dni": "11111111-1",
            "patient": "Paciente de Prueba",
        }
        base.update(kwargs)
        return base

    def test_no_persiste_datos_del_paciente(self):
        """
        El reporte trae RUT y nombre; la carga los descarta. Para el control
        financiero basta la referencia de la cita.
        """
        from apps.revenue.services.import_reporte import import_records

        import_records([self._record()], file_name="reporte.xlsx")

        entry = RevenueEntry.objects.get()
        campos = {f.name for f in RevenueEntry._meta.get_fields()}

        self.assertNotIn("dni", campos)
        self.assertNotIn("patient", campos)

        guardado = str(entry.__dict__)
        self.assertNotIn("11111111-1", guardado)
        self.assertNotIn("Paciente de Prueba", guardado)

    def test_fila_sin_prestador_mapeado_no_se_importa_y_queda_listada(self):
        """
        Atribuirla "a la que más se parece" destruiría en silencio la apertura
        por sociedad que este módulo existe para conservar.
        """
        from apps.revenue.services.import_reporte import import_records

        batch = import_records(
            [
                self._record(),
                self._record(id="1002", provider="SOCIEDAD NUEVA"),
            ],
            file_name="reporte.xlsx",
        )

        self.assertEqual(batch.rows_total, 2)
        self.assertEqual(batch.rows_imported, 1)
        self.assertEqual(batch.rows_skipped, 1)
        self.assertIn("SOCIEDAD NUEVA", batch.unmapped_providers)
        self.assertFalse(batch.is_complete)

    def test_fila_sin_financiador_mapeado_tampoco_entra(self):
        from apps.revenue.services.import_reporte import import_records

        batch = import_records(
            [self._record(financier="ISAPRE DESCONOCIDA")],
            file_name="reporte.xlsx",
        )

        self.assertEqual(batch.rows_imported, 0)
        self.assertIn("ISAPRE DESCONOCIDA", batch.unmapped_financiers)

    def test_neto_descuenta_el_descuento(self):
        from apps.revenue.services.import_reporte import import_records

        import_records(
            [self._record(value=30000, discount=5000)], file_name="reporte.xlsx"
        )

        entry = RevenueEntry.objects.get()
        self.assertEqual(entry.gross_amount, Decimal("30000"))
        self.assertEqual(entry.discount_amount, Decimal("5000"))
        self.assertEqual(entry.net_amount, Decimal("25000"))

    def test_misma_cita_con_procedimiento_repetido_no_se_pierde(self):
        """
        Una atención puede repetir código —rodilla izquierda y derecha—. La
        clave de unicidad las colapsaría; se desambiguan en vez de perderlas.
        """
        from apps.revenue.services.import_reporte import import_records

        batch = import_records(
            [
                self._record(id="2001", procedure_code="RX-RODILLA"),
                self._record(id="2001", procedure_code="RX-RODILLA"),
            ],
            file_name="reporte.xlsx",
        )

        self.assertEqual(batch.rows_imported, 2)
        self.assertEqual(RevenueEntry.objects.count(), 2)

    def test_reimportar_crea_un_lote_nuevo_sin_chocar(self):
        from apps.revenue.services.import_reporte import import_records

        import_records([self._record()], file_name="reporte.xlsx")
        import_records([self._record()], file_name="reporte.xlsx")

        self.assertEqual(RevenueImportBatch.objects.count(), 2)
        self.assertEqual(RevenueEntry.objects.count(), 2)

    def test_analyze_no_escribe_nada(self):
        from apps.revenue.services.import_reporte import analyze_records

        analisis = analyze_records([self._record(), self._record(provider="X")])

        self.assertEqual(analisis["rows_total"], 2)
        self.assertEqual(analisis["rows_mappable"], 1)
        self.assertEqual(RevenueEntry.objects.count(), 0)
        self.assertEqual(RevenueImportBatch.objects.count(), 0)

    def test_periodo_del_lote_sale_de_las_fechas_cargadas(self):
        from apps.revenue.services.import_reporte import import_records
        from datetime import date

        batch = import_records(
            [
                self._record(id="3001", date="2026-07-01"),
                self._record(id="3002", date="2026-07-31"),
            ],
            file_name="reporte.xlsx",
        )

        self.assertEqual(batch.period_from, date(2026, 7, 1))
        self.assertEqual(batch.period_to, date(2026, 7, 31))


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class RevenueAPITests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.admin = make_superuser()
        self.client.force_authenticate(user=self.admin)

        self.org, self.sociedades = setup_sociedades()
        self.financiadores = setup_financiadores()

        from apps.revenue.services.import_reporte import import_records

        import_records(
            [
                {
                    "id": "1",
                    "date": "2026-07-21",
                    "provider": "IRAMA",
                    "financier": "FONASA N3",
                    "value": 100000,
                    "discount": 0,
                    "procedure_code": "A",
                },
                {
                    "id": "2",
                    "date": "2026-07-21",
                    "provider": "IRAL",
                    "financier": "PARTICULAR",
                    "value": 40000,
                    "discount": 0,
                    "procedure_code": "B",
                },
            ],
            file_name="reporte.xlsx",
        )

    def test_ingreso_por_razon_social(self):
        resp = self.client.get("/api/revenue-entries/by-legal-entity/")

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        filas = resp.json()["data"]

        self.assertEqual(len(filas), 2)
        self.assertEqual(Decimal(str(filas[0]["net_amount"])), Decimal("100000"))

    def test_ingreso_por_financiador(self):
        resp = self.client.get("/api/revenue-entries/by-financier/")

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.json()["data"]), 2)

    def test_preview_sin_archivo_devuelve_400(self):
        resp = self.client.post("/api/revenue-imports/preview/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Contraste contra el archivo real
# ---------------------------------------------------------------------------

class ImportarReporteRealTests(TestCase):
    """
    Carga el reporte de prestaciones que entregó la Jefatura y contrasta contra
    las cifras que el análisis de datos verificó a mano sobre el mismo archivo.

    Se salta si el archivo no está: el test documenta el contrato con la fuente
    real, y no debe romper la suite en una máquina que no tenga la carpeta.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not REPORTE_XLSX.exists():
            raise cls.skipException  # pragma: no cover

    def setUp(self):
        if not REPORTE_XLSX.exists():
            self.skipTest(f"No está {REPORTE_XLSX}")

        self.org, self.sociedades = setup_sociedades()
        self.financiadores = setup_financiadores()

    def _importar(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.revenue.services.import_reporte import (
            import_records,
            parse_uploaded_reporte,
        )

        subido = SimpleUploadedFile(
            "reporte - 2026-07-21T150838.563.xlsx",
            REPORTE_XLSX.read_bytes(),
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )

        records, file_name = parse_uploaded_reporte(subido)
        return import_records(records, file_name=file_name)

    def test_importa_las_37_prestaciones_por_797040(self):
        batch = self._importar()

        self.assertEqual(batch.rows_total, 37)
        self.assertEqual(batch.rows_imported, 37)
        self.assertEqual(batch.rows_skipped, 0)
        self.assertTrue(batch.is_complete)

        bruto = sum(e.gross_amount for e in RevenueEntry.objects.all())
        self.assertEqual(bruto, Decimal("797040"))

    def test_el_descuento_se_resta_y_no_se_suma(self):
        """
        El archivo consigna los descuentos en negativo y el net_value del
        parser los resta con ese signo, dando $817.590 — más ingreso del que
        hubo. Cuatro prestaciones traen descuento, por $20.550 en total.
        """
        self._importar()

        descuentos = sum(e.discount_amount for e in RevenueEntry.objects.all())
        neto = sum(e.net_amount for e in RevenueEntry.objects.all())

        self.assertEqual(descuentos, Decimal("20550"))
        self.assertEqual(neto, Decimal("776490"))

        # Ningún descuento queda guardado en negativo.
        self.assertFalse(
            RevenueEntry.objects.filter(discount_amount__lt=0).exists()
        )

    def test_desglose_por_prestador_coincide_con_el_analisis(self):
        """IRAMA 16 / $360.160 · IRAL 10 / $233.880 · SODIAGMA 11 / $203.000."""
        from django.db.models import Count, Sum

        self._importar()

        # El análisis sumó la columna VALOR, es decir el bruto.
        esperado = {
            "IRAMA": (16, Decimal("360160")),
            "IRAL": (10, Decimal("233880")),
            "SODIAGMA": (11, Decimal("203000")),
        }

        for codigo, (filas, monto) in esperado.items():
            resumen = RevenueEntry.objects.filter(
                legal_entity=self.sociedades[codigo]
            ).aggregate(filas=Count("id"), monto=Sum("gross_amount"))

            self.assertEqual(resumen["filas"], filas, f"filas de {codigo}")
            self.assertEqual(resumen["monto"], monto, f"monto de {codigo}")

    def test_las_dos_grafias_de_linares_quedan_en_un_solo_financiador(self):
        """
        En el archivo real conviven "MUNICIPALIDAD DE LINARES" y
        "MUNICIP. LINARES". Después de cargar deben ser el mismo financiador,
        con las dos prestaciones sumadas.
        """
        self._importar()

        linares = self.financiadores["MUN-LINARES"]
        entradas = RevenueEntry.objects.filter(financier=linares)

        self.assertEqual(entradas.count(), 2)
        self.assertEqual(
            sum(e.gross_amount for e in entradas), Decimal("39000")
        )

    def test_31_citas_distintas_en_37_prestaciones(self):
        """
        Una fila es un procedimiento, no una cita: contar filas sobreestima
        pacientes en un 19 %.
        """
        self._importar()

        citas = (
            RevenueEntry.objects.values("appointment_ref").distinct().count()
        )
        self.assertEqual(citas, 31)


# ---------------------------------------------------------------------------
# D2 · Cuentas por cobrar institucionales
# ---------------------------------------------------------------------------

DETALLE_CAJA_PDF = REPORTES_DIR / "detalle caja.pdf"


class ReceivablesTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.admin = make_superuser("recadmin", "recpass")
        self.client.force_authenticate(user=self.admin)

        self.org, self.sociedades = setup_sociedades()
        self.financiadores = setup_financiadores()

        from apps.revenue.services.import_reporte import import_records

        import_records(
            [
                {
                    "id": "1",
                    "date": "2026-07-10",
                    "provider": "IRAMA",
                    "financier": "FONASA N3",
                    "value": 100000,
                    "discount": 0,
                    "procedure_code": "A",
                },
                {
                    "id": "2",
                    "date": "2026-07-11",
                    "provider": "IRAMA",
                    "financier": "FONASA N3",
                    "value": 50000,
                    "discount": 0,
                    "procedure_code": "B",
                },
                {
                    "id": "3",
                    "date": "2026-07-12",
                    "provider": "IRAMA",
                    "financier": "PARTICULAR",
                    "value": 70000,
                    "discount": 0,
                    "procedure_code": "C",
                },
            ],
            file_name="reporte.xlsx",
        )

    def test_el_particular_no_genera_deuda(self):
        """El paciente particular paga en el mesón y ahí se acaba."""
        from apps.revenue.models import AccountReceivable
        from apps.revenue.services.receivables import build_receivables_from_revenue

        build_receivables_from_revenue(period_year=2026, period_month=7)

        self.assertEqual(AccountReceivable.objects.count(), 1)

        cuenta = AccountReceivable.objects.get()
        self.assertEqual(cuenta.financier, self.financiadores["FONASA-N3"])
        self.assertEqual(cuenta.billed_amount, Decimal("150000"))

    def test_la_cuenta_queda_ligada_a_las_prestaciones_que_cobra(self):
        """
        Es lo que desagrega la factura cruzada aunque no pueda emitirse
        separada.
        """
        from apps.revenue.services.receivables import build_receivables_from_revenue

        cuentas = build_receivables_from_revenue(period_year=2026, period_month=7)
        cuenta = cuentas[0]

        self.assertEqual(cuenta.items.count(), 2)
        self.assertEqual(
            sum(i.amount for i in cuenta.items.all()), Decimal("150000")
        )

    def test_reconstruir_no_borra_lo_ya_cobrado(self):
        from apps.revenue.services.receivables import (
            build_receivables_from_revenue,
            register_collection,
        )

        cuenta = build_receivables_from_revenue(
            period_year=2026, period_month=7
        )[0]
        register_collection(receivable=cuenta, amount=Decimal("60000"))

        build_receivables_from_revenue(period_year=2026, period_month=7)

        cuenta.refresh_from_db()
        self.assertEqual(cuenta.collected_amount, Decimal("60000"))
        self.assertEqual(cuenta.pending_amount, Decimal("90000"))
        self.assertEqual(cuenta.status, cuenta.STATUS_PARTIAL)

    def test_reconstruir_no_duplica_los_items(self):
        from apps.revenue.services.receivables import build_receivables_from_revenue

        build_receivables_from_revenue(period_year=2026, period_month=7)
        cuenta = build_receivables_from_revenue(
            period_year=2026, period_month=7
        )[0]

        self.assertEqual(cuenta.items.count(), 2)

    def test_cobro_total_cierra_la_cuenta(self):
        from apps.revenue.services.receivables import (
            build_receivables_from_revenue,
            register_collection,
        )

        cuenta = build_receivables_from_revenue(
            period_year=2026, period_month=7
        )[0]
        register_collection(receivable=cuenta, amount=Decimal("150000"))

        self.assertEqual(cuenta.status, cuenta.STATUS_COLLECTED)
        self.assertEqual(cuenta.pending_amount, Decimal("0"))

    def test_tramos_de_antiguedad(self):
        from datetime import timedelta
        from django.utils import timezone
        from apps.revenue.models import AccountReceivable
        from apps.revenue.services.receivables import build_receivables_from_revenue

        cuenta = build_receivables_from_revenue(
            period_year=2026, period_month=7
        )[0]

        hoy = timezone.localdate()

        cuenta.due_date = hoy - timedelta(days=45)
        cuenta.save()
        self.assertEqual(cuenta.aging_bucket, "31-60")

        cuenta.due_date = hoy + timedelta(days=10)
        cuenta.save()
        self.assertEqual(cuenta.aging_bucket, "Sin vencer")

        cuenta.due_date = hoy - timedelta(days=200)
        cuenta.save()
        self.assertEqual(cuenta.aging_bucket, "90+")

    def test_deuda_sin_fecha_no_se_esconde_en_un_tramo(self):
        """
        "Sin fecha" es deuda que nadie sabe cuándo debía cobrarse. Meterla en
        un tramo la haría desaparecer del análisis.
        """
        from apps.revenue.services.receivables import build_receivables_from_revenue

        cuenta = build_receivables_from_revenue(
            period_year=2026, period_month=7
        )[0]

        self.assertIsNone(cuenta.due_date)
        self.assertEqual(cuenta.aging_bucket, "Sin fecha")

    def test_endpoint_aging_agrupa_por_financiador(self):
        from apps.revenue.services.receivables import build_receivables_from_revenue

        build_receivables_from_revenue(period_year=2026, period_month=7)

        resp = self.client.get("/api/receivables/aging/")

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        filas = resp.json()["data"]

        self.assertEqual(len(filas), 1)
        self.assertEqual(Decimal(str(filas[0]["total_pending"])), Decimal("150000"))

    def test_endpoint_rebuild_exige_periodo(self):
        resp = self.client.post("/api/receivables/rebuild/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_endpoint_register_collection_rechaza_monto_no_positivo(self):
        from apps.revenue.services.receivables import build_receivables_from_revenue

        cuenta = build_receivables_from_revenue(
            period_year=2026, period_month=7
        )[0]

        resp = self.client.post(
            f"/api/receivables/{cuenta.uuid}/register-collection/",
            {"amount": "0"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class CashCollectionTests(TestCase):

    def setUp(self):
        self.org, self.sociedades = setup_sociedades()

    def test_rut_se_compara_normalizado(self):
        """
        El informe trae "76.869.710-8" y la ficha guarda "76869710-8". Sin
        normalizar, ninguna sociedad se resolvería.
        """
        from apps.revenue.services.import_depositos import resolve_legal_entity

        entidad = resolve_legal_entity(rut="76.869.710-8")

        self.assertEqual(entidad, self.sociedades["IRAL"])

    def test_fila_de_totales_no_se_carga_como_sociedad(self):
        from apps.revenue.models import CashCollection
        from apps.revenue.services.import_depositos import import_providers
        from datetime import date

        providers = [
            {
                "rut": "76.869.710-8",
                "name": "Instituto Radiológico Linares Ltda.",
                "totals": {"particular": 108800, "copay": 0, "total": 108800},
                "payments": [
                    {"payment_method": "EFECTIVO", "total": 108800},
                ],
            },
            {"rut": None, "name": "TOTAL", "totals": {"total": 108800}},
        ]

        import_providers(providers, collection_date=date(2026, 7, 24))

        self.assertEqual(CashCollection.objects.count(), 1)

    def test_recargar_el_mismo_dia_actualiza_en_vez_de_duplicar(self):
        from apps.revenue.models import CashCollection
        from apps.revenue.services.import_depositos import import_providers
        from datetime import date

        providers = [
            {
                "rut": "76.869.710-8",
                "name": "IRAL",
                "totals": {"particular": 100000, "copay": 0, "total": 100000},
                "payments": [],
            }
        ]
        import_providers(providers, collection_date=date(2026, 7, 24))

        providers[0]["totals"]["total"] = 120000
        import_providers(providers, collection_date=date(2026, 7, 24))

        self.assertEqual(CashCollection.objects.count(), 1)
        self.assertEqual(
            CashCollection.objects.get().total_amount, Decimal("120000")
        )


class ImportarDepositosRealTests(TestCase):
    """Carga el informe de depósitos real y contrasta con el análisis."""

    def setUp(self):
        if not DETALLE_CAJA_PDF.exists():
            self.skipTest(f"No está {DETALLE_CAJA_PDF}")

        self.org = Organization.objects.create(name="MauleMed", is_active=True)

        # Las seis sociedades del informe del 24-07, con sus RUT reales.
        self.ruts = {
            "76792250-7": "Soc. Médica y de Diagnóstico Nova Imagen Ltda.",
            "76480670-0": "Soc. Médica Maule Sur S.A.",
            "76212446-7": "Imágenes Médicas Cauquenes SpA",
            "76551640-4": "Soc. Médica y de Diagnóstico Maule Ltda.",
            "76067669-1": "Densitometría Ósea Linares Ltda.",
            "76869710-8": "Instituto Radiológico Linares Ltda.",
        }
        for rut, nombre in self.ruts.items():
            LegalEntity.objects.create(
                organization=self.org, name=nombre, rut=rut
            )

    def _importar(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.revenue.services.import_depositos import (
            import_providers,
            parse_uploaded_depositos,
        )

        subido = SimpleUploadedFile(
            "DETALLE-CAJA.pdf",
            DETALLE_CAJA_PDF.read_bytes(),
            content_type="application/pdf",
        )
        providers, fecha, _ = parse_uploaded_depositos(subido)
        return import_providers(providers, collection_date=fecha), fecha

    def test_carga_las_seis_sociedades_por_3050736(self):
        from apps.revenue.models import CashCollection
        from datetime import date

        creadas, fecha = self._importar()

        self.assertEqual(fecha, date(2026, 7, 24))
        self.assertEqual(len(creadas), 6)

        total = sum(c.total_amount for c in CashCollection.objects.all())
        self.assertEqual(total, Decimal("3050736"))

    def test_el_copago_es_la_mayor_parte_de_la_caja(self):
        """
        $1.877.736 de copago sobre $3.050.736: el 61,6 % de la recaudación
        tiene detrás una cuenta por cobrar institucional que hoy no se ve.
        """
        from apps.revenue.models import CashCollection

        self._importar()

        copago = sum(c.copay_amount for c in CashCollection.objects.all())
        particular = sum(
            c.particular_amount for c in CashCollection.objects.all()
        )

        self.assertEqual(copago, Decimal("1877736"))
        self.assertEqual(particular, Decimal("1173000"))

    def test_el_cheque_no_es_medio_de_cobro(self):
        """
        "Los pagos los realizamos todos con cheque. No hacemos transferencia."
        El cheque es el medio de pago a proveedores, por eso nunca aparece en
        la recaudación.
        """
        from apps.revenue.models import CashCollection

        self._importar()

        cheques = sum(c.check_amount for c in CashCollection.objects.all())
        self.assertEqual(cheques, Decimal("0"))

    def test_sociedad_repetida_en_dos_bloques_se_suma(self):
        """
        Maule Sur figura dos veces en el informe del 24-07, por $832.416 y
        $113.680, porque el documento abre por punto de recaudación sin nombrar
        la sucursal. Guardarlos uno por uno con la misma clave hacía que el
        segundo pisara al primero: la caja del día perdía $596.816 en silencio.
        """
        from apps.revenue.models import CashCollection

        self._importar()

        maule_sur = LegalEntity.objects.get(rut="76480670-0")
        collection = CashCollection.objects.get(legal_entity=maule_sur)

        self.assertEqual(collection.total_amount, Decimal("946096"))
        self.assertEqual(collection.copay_amount, Decimal("673496"))


# ---------------------------------------------------------------------------
# Seed de demo
# ---------------------------------------------------------------------------

class SeedDemoFinanzasTests(TestCase):

    def test_seed_crea_financiadores_y_sus_grafias(self):
        from django.core.management import call_command

        call_command("seed_demo_finanzas", verbosity=0)

        self.assertEqual(Financier.objects.count(), 11)

        # Las dos grafías de Linares apuntan al mismo financiador.
        uno = FinancierAlias.resolve("MUNICIPALIDAD DE LINARES")
        otro = FinancierAlias.resolve("MUNICIP. LINARES")
        self.assertEqual(uno, otro)

    def test_seed_no_inventa_razones_sociales(self):
        """
        Si el RUT del prestador no está cargado, lo reporta como faltante en vez
        de crearlo: ensuciar el maestro haría irreconocible qué es dato real.
        """
        from django.core.management import call_command

        call_command("seed_demo_finanzas", verbosity=0)

        self.assertEqual(LegalEntity.objects.count(), 0)
        self.assertEqual(LegalEntityAlias.objects.count(), 0)

    def test_seed_liga_el_prestador_cuando_la_sociedad_existe(self):
        from django.core.management import call_command

        org = Organization.objects.create(name="MauleMed", is_active=True)
        iral = LegalEntity.objects.create(
            organization=org,
            name="Instituto Radiológico Linares Ltda.",
            rut="76869710-8",
        )

        call_command("seed_demo_finanzas", verbosity=0)

        self.assertEqual(LegalEntityAlias.resolve("IRAL"), iral)

    def test_seed_es_idempotente(self):
        from django.core.management import call_command

        call_command("seed_demo_finanzas", verbosity=0)
        call_command("seed_demo_finanzas", verbosity=0)

        self.assertEqual(Financier.objects.count(), 11)

    def test_seed_carga_los_archivos_reales_si_se_le_pasa_la_carpeta(self):
        from django.core.management import call_command

        if not REPORTE_XLSX.exists():
            self.skipTest(f"No está {REPORTES_DIR}")

        org = Organization.objects.create(name="MauleMed", is_active=True)
        for rut, nombre in (
            ("76869710-8", "Instituto Radiológico Linares Ltda."),
            ("76551640-4", "Soc. Médica y de Diagnóstico Maule Ltda."),
        ):
            LegalEntity.objects.create(
                organization=org, name=nombre, rut=rut
            )

        call_command(
            "seed_demo_finanzas",
            reportes_dir=str(REPORTES_DIR),
            verbosity=0,
        )

        batch = RevenueImportBatch.objects.first()
        self.assertIsNotNone(batch)
        self.assertEqual(batch.rows_total, 37)

        # IRAMA no está cargada como sociedad, así que sus filas quedan fuera y
        # listadas — no se atribuyen a otra.
        self.assertIn("IRAMA", batch.unmapped_providers)
        self.assertEqual(batch.rows_imported, 21)
