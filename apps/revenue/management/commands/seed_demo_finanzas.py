"""
Siembra los catálogos del lado del ingreso y, opcionalmente, carga los archivos
reales de la carpeta de reportes.

    python manage.py seed_demo_finanzas
    python manage.py seed_demo_finanzas --reportes-dir "/ruta/Reportes Liz 24-07"

Sin la ruta siembra sólo financiadores y sus alias. Los alias de prestador
dependen de qué razones sociales existan en la base, así que se crean sólo para
las que ya estén cargadas: inventar sociedades aquí ensuciaría el maestro.
"""

from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.organizations.models import LegalEntity, LegalEntityAlias
from apps.revenue.models import Financier, FinancierAlias


# (código, nombre, tipo, [grafías con que aparece en las exportaciones])
FINANCIADORES = [
    ("PARTICULAR", "Particular", Financier.TYPE_PRIVATE, ["PARTICULAR"]),
    ("FONASA-N1", "FONASA Nivel 1", Financier.TYPE_FONASA, ["FONASA N1"]),
    ("FONASA-N2", "FONASA Nivel 2", Financier.TYPE_FONASA, ["FONASA N2"]),
    ("FONASA-N3", "FONASA Nivel 3", Financier.TYPE_FONASA, ["FONASA N3"]),
    ("DIPRECA", "DIPRECA", Financier.TYPE_AGREEMENT, ["DIPRECA"]),
    (
        "NUEVA-MAS-VIDA",
        "Isapre Nueva Más Vida",
        Financier.TYPE_ISAPRE,
        ["NUEVA MAS VIDA", "NUEVA MÁS VIDA"],
    ),
    (
        "MUN-LINARES",
        "Municipalidad de Linares",
        Financier.TYPE_AGREEMENT,
        # Las dos grafías del archivo real. Es el caso que motiva el catálogo:
        # convivían como entidades distintas en una muestra de 37 filas.
        ["MUNICIPALIDAD DE LINARES", "MUNICIP. LINARES"],
    ),
    (
        "MUN-VILLA-ALEGRE",
        "Municipalidad de Villa Alegre",
        Financier.TYPE_AGREEMENT,
        ["MUNICIP. VILLA ALEGRE", "MUNICIPALIDAD DE VILLA ALEGRE"],
    ),
    (
        "MUN-YERBAS-BUENAS",
        "Municipalidad de Yerbas Buenas",
        Financier.TYPE_AGREEMENT,
        ["MUNICIP. YERBAS BUENAS"],
    ),
    (
        "MUN-COLBUN",
        "Municipalidad de Colbún",
        Financier.TYPE_AGREEMENT,
        ["MUNICIP COLBÚN", "MUNICIP COLBUN", "MUNICIP. COLBÚN"],
    ),
    (
        "SALUD-LONGAVI",
        "Departamento de Salud de Longaví",
        Financier.TYPE_AGREEMENT,
        ["DPTO SALUD LONGAVÍ", "DPTO SALUD LONGAVI"],
    ),
]


# Código de prestador → RUT de la sociedad, según el informe de depósitos.
PRESTADORES = {
    "IRAL": "76869710-8",
    "SODIAGMA": "76551640-4",
}


class Command(BaseCommand):
    help = "Siembra financiadores, alias y carga los archivos de la carpeta de reportes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reportes-dir",
            dest="reportes_dir",
            default=None,
            help="Carpeta con los archivos del sistema clínico.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self._seed_financiadores()
        self._seed_prestadores()

        carpeta = options.get("reportes_dir")
        if carpeta:
            self._cargar_archivos(Path(carpeta))
        else:
            self.stdout.write(
                "Sin --reportes-dir: se sembraron sólo los catálogos."
            )

    # ── Catálogos ──────────────────────────────────────────────────────────

    def _seed_financiadores(self):
        creados = 0

        for code, name, tipo, grafias in FINANCIADORES:
            financier, was_created = Financier.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "financier_type": tipo,
                    "generates_receivable": tipo != Financier.TYPE_PRIVATE,
                    "is_active": True,
                },
            )
            creados += int(was_created)

            for grafia in grafias:
                FinancierAlias.objects.update_or_create(
                    raw_name=FinancierAlias.normalize(grafia),
                    defaults={"financier": financier, "is_active": True},
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Financiadores: {len(FINANCIADORES)} ({creados} nuevos)."
            )
        )

    def _seed_prestadores(self):
        from apps.revenue.services.import_depositos import normalize_rut

        creados = 0
        faltantes = []

        for codigo, rut in PRESTADORES.items():
            entidad = next(
                (
                    e
                    for e in LegalEntity.objects.all()
                    if normalize_rut(e.rut) == normalize_rut(rut)
                ),
                None,
            )

            if entidad is None:
                faltantes.append(f"{codigo} ({rut})")
                continue

            _, was_created = LegalEntityAlias.objects.update_or_create(
                value=LegalEntityAlias.normalize(codigo),
                defaults={
                    "legal_entity": entidad,
                    "alias_type": LegalEntityAlias.TYPE_PROVIDER_CODE,
                    "is_active": True,
                },
            )
            creados += int(was_created)

        self.stdout.write(
            self.style.SUCCESS(f"Alias de prestador: {creados} nuevos.")
        )

        if faltantes:
            self.stdout.write(
                self.style.WARNING(
                    "Sin sociedad cargada para: "
                    + ", ".join(faltantes)
                    + ". Crea la razón social con ese RUT y vuelve a correrlo."
                )
            )

    # ── Carga de archivos ──────────────────────────────────────────────────

    def _cargar_archivos(self, carpeta):
        if not carpeta.is_dir():
            self.stdout.write(
                self.style.ERROR(f"No existe la carpeta {carpeta}.")
            )
            return

        self._cargar_reporte(carpeta)
        self._cargar_depositos(carpeta)

    def _archivo(self, carpeta, patron):
        coincidencias = sorted(carpeta.glob(patron))
        return coincidencias[0] if coincidencias else None

    def _subir(self, ruta, nombre):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return SimpleUploadedFile(nombre, ruta.read_bytes())

    def _cargar_reporte(self, carpeta):
        from apps.revenue.services.import_reporte import (
            import_records,
            parse_uploaded_reporte,
        )

        ruta = self._archivo(carpeta, "reporte*.xlsx")
        if ruta is None:
            self.stdout.write("No se encontró el reporte de prestaciones.")
            return

        records, file_name = parse_uploaded_reporte(
            self._subir(ruta, "reporte.xlsx")
        )
        batch = import_records(records, file_name=file_name)

        self.stdout.write(
            self.style.SUCCESS(
                f"Libro de ingresos: {batch.rows_imported}/{batch.rows_total} filas."
            )
        )

        if batch.unmapped_providers:
            self.stdout.write(
                self.style.WARNING(
                    "Prestadores sin alias: "
                    + ", ".join(batch.unmapped_providers)
                )
            )
        if batch.unmapped_financiers:
            self.stdout.write(
                self.style.WARNING(
                    "Financiadores sin alias: "
                    + ", ".join(batch.unmapped_financiers)
                )
            )

    def _cargar_depositos(self, carpeta):
        from apps.revenue.services.import_depositos import (
            import_providers,
            parse_uploaded_depositos,
        )

        ruta = self._archivo(carpeta, "detalle caja*.pdf")
        if ruta is None:
            self.stdout.write("No se encontró el informe de depósitos.")
            return

        providers, fecha, _ = parse_uploaded_depositos(
            self._subir(ruta, "DETALLE-CAJA.pdf")
        )

        if fecha is None:
            self.stdout.write(
                self.style.WARNING("El informe no trae fecha legible.")
            )
            return

        creadas = import_providers(providers, collection_date=fecha)
        self.stdout.write(
            self.style.SUCCESS(
                f"Recaudación del {fecha}: {len(creadas)} sociedades."
            )
        )
