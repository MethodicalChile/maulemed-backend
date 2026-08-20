import re
from typing import Any


class InformeDepositosParser:
    """
    Parser específico para:

        DETALLE-CAJA.pdf

    El contenido interno corresponde actualmente a:

        INFORME DE DEPOSITOS

    Extrae:
    - fecha desde
    - fecha hasta
    - usuario
    - sucursales
    - prestadores
    - medios de pago
    - totales generales
    - indicadores de dashboard
    - gráficos
    - tablas resumen
    - resumen automático

    No persiste información.
    """

    DOCUMENT_TYPE = "detalle_caja"

    PAYMENT_METHODS = {
        "EFECTIVO",
        "DEBITO",
        "DÉBITO",
        "CREDITO",
        "CRÉDITO",
        "CHEQUE",
    }

    def parse(
        self,
        text: str,
    ) -> dict[str, Any]:

        if not text:
            return self._empty_result()

        normalized_text = self._normalize_text(
            text
        )

        date_from = self._extract_date_from(
            normalized_text
        )

        date_to = self._extract_date_to(
            normalized_text
        )

        user = self._extract_user(
            normalized_text
        )

        branches = self._extract_branches(
            normalized_text
        )

        providers = self._extract_providers(
            normalized_text
        )

        totals = self._calculate_general_totals(
            providers
        )

        payment_method_totals = (
            self._calculate_payment_method_totals(
                providers
            )
        )

        dashboard = self._build_dashboard(
            date_from=date_from,
            date_to=date_to,
            branches=branches,
            providers=providers,
            totals=totals,
            payment_method_totals=payment_method_totals,
        )

        return {
            "document_type": self.DOCUMENT_TYPE,
            "title": "Detalle de Caja",

            "source_document_title": (
                "Informe de Depósitos"
            ),

            "date_from": date_from,
            "date_to": date_to,
            "user": user,

            "branches": branches,

            "providers": providers,

            "totals": totals,

            "payment_method_totals": (
                payment_method_totals
            ),

            "dashboard": dashboard,
        }

    def _empty_result(
        self,
    ):
        totals = self._empty_totals()

        return {
            "document_type": self.DOCUMENT_TYPE,
            "title": "Detalle de Caja",

            "source_document_title": (
                "Informe de Depósitos"
            ),

            "date_from": None,
            "date_to": None,
            "user": None,

            "branches": [],
            "providers": [],

            "totals": totals,

            "payment_method_totals": (
                self._empty_payment_method_totals()
            ),

            "dashboard": {
                "metrics": [],
                "charts": [],
                "tables": [],
                "summary": {
                    "title": "Resumen",
                    "text": (
                        "No se encontró información "
                        "para construir el dashboard."
                    ),
                },
            },
        }

    # =========================================================
    # NORMALIZACIÓN
    # =========================================================

    def _normalize_text(
        self,
        text: str,
    ) -> str:
        """
        Limpieza básica del texto extraído desde PDF.
        """

        text = text.replace(
            "\r\n",
            "\n",
        )

        text = text.replace(
            "\r",
            "\n",
        )

        lines = []

        for raw_line in text.split("\n"):
            line = re.sub(
                r"[ \t]+",
                " ",
                raw_line,
            ).strip()

            if not line:
                continue

            # Ignorar URL generada por impresión.
            if re.search(
                r"https?://",
                line,
                re.IGNORECASE,
            ):
                continue

            # Ignorar encabezado/pie con fecha y hora.
            if re.search(
                r"\d{1,2}/\d{1,2}/\d{2,4},?"
                r"\s+\d{1,2}:\d{2}",
                line,
            ):
                continue

            lines.append(
                line
            )

        return "\n".join(
            lines
        )

    # =========================================================
    # INFORMACIÓN GENERAL
    # =========================================================

    def _extract_date_from(
        self,
        text: str,
    ):
        match = re.search(
            r"Desde\s+(\d{2}-\d{2}-\d{4})",
            text,
            re.IGNORECASE,
        )

        return (
            match.group(1)
            if match
            else None
        )

    def _extract_date_to(
        self,
        text: str,
    ):
        match = re.search(
            r"Hasta\s+(\d{2}-\d{2}-\d{4})",
            text,
            re.IGNORECASE,
        )

        return (
            match.group(1)
            if match
            else None
        )

    def _extract_user(
        self,
        text: str,
    ):
        match = re.search(
            r"Usuario:\s*([^\n]+)",
            text,
            re.IGNORECASE,
        )

        if not match:
            return None

        return (
            match
            .group(1)
            .strip()
            .rstrip(".")
        )

    def _extract_branches(
        self,
        text: str,
    ):
        match = re.search(
            r"Sucursal:\s*(.+?)"
            r"(?=\nPRESTADOR:)",
            text,
            re.IGNORECASE | re.DOTALL,
        )

        if not match:
            return []

        branch_text = match.group(1)

        branches = re.split(
            r"\s+-\s+",
            branch_text,
        )

        return [
            branch.strip(" -")
            for branch in branches
            if branch.strip(" -")
        ]

    # =========================================================
    # PRESTADORES
    # =========================================================

    def _extract_providers(
        self,
        text: str,
    ):
        """
        Divide el documento por bloques PRESTADOR.
        """

        provider_pattern = re.compile(
            r"PRESTADOR:\s*"
            r"(?P<rut>\d{1,2}\.\d{3}\.\d{3}-[\dkK])"
            r"\s*-\s*"
            r"(?P<name>[^\n]+)",
            re.IGNORECASE,
        )

        matches = list(
            provider_pattern.finditer(
                text
            )
        )

        providers = []

        for index, match in enumerate(
            matches
        ):
            rut = (
                match.group("rut")
                .strip()
            )

            name = (
                match.group("name")
                .strip()
            )

            block_start = match.end()

            if index + 1 < len(matches):
                block_end = (
                    matches[
                        index + 1
                    ].start()
                )
            else:
                block_end = len(
                    text
                )

            block = text[
                block_start:block_end
            ]

            payments = self._extract_payments(
                block
            )

            totals = (
                self._calculate_provider_totals(
                    payments
                )
            )

            providers.append(
                {
                    "rut": rut,
                    "name": name,
                    "payments": payments,
                    "totals": totals,
                }
            )

        return providers

    # =========================================================
    # MEDIOS DE PAGO
    # =========================================================

    def _extract_payments(
        self,
        block: str,
    ):
        payments = []

        for line in block.split("\n"):
            line = line.strip()

            if not line:
                continue

            upper_line = line.upper()

            # Saltar encabezado.
            if (
                "PARTICULAR" in upper_line
                and "COPAGO" in upper_line
                and "TOTALES" in upper_line
            ):
                continue

            match = re.match(
                r"^"
                r"(EFECTIVO|DEBITO|DÉBITO|"
                r"CREDITO|CRÉDITO|CHEQUE)"
                r"\s+(.+)$",
                line,
                re.IGNORECASE,
            )

            if not match:
                continue

            method = match.group(1)
            values_text = match.group(2)

            numbers = re.findall(
                r"-?[\d\.]+",
                values_text,
            )

            if len(numbers) < 4:
                continue

            numbers = numbers[:4]

            particular = self._parse_amount(
                numbers[0]
            )

            copay = self._parse_amount(
                numbers[1]
            )

            withdrawal = self._parse_amount(
                numbers[2]
            )

            total = self._parse_amount(
                numbers[3]
            )

            payments.append(
                {
                    "payment_method": (
                        self._normalize_payment_method(
                            method
                        )
                    ),
                    "particular": particular,
                    "copay": copay,
                    "withdrawal": withdrawal,
                    "total": total,
                }
            )

        return payments

    def _parse_amount(
        self,
        value: str,
    ) -> int:
        """
        Ejemplos:

        24.000
            -> 24000

        545.000
            -> 545000

        0
            -> 0
        """

        if not value:
            return 0

        cleaned = (
            value
            .replace(".", "")
            .replace(",", "")
        )

        try:
            return int(
                cleaned
            )

        except (
            TypeError,
            ValueError,
        ):
            return 0

    def _normalize_payment_method(
        self,
        value: str,
    ) -> str:

        value = value.upper()

        replacements = {
            "DÉBITO": "DEBITO",
            "CRÉDITO": "CREDITO",
        }

        return replacements.get(
            value,
            value,
        )

    # =========================================================
    # TOTALES
    # =========================================================

    def _empty_totals(
        self,
    ):
        return {
            "particular": 0,
            "copay": 0,
            "withdrawal": 0,
            "total": 0,
        }

    def _empty_payment_method_totals(
        self,
    ):
        return {
            "EFECTIVO": 0,
            "DEBITO": 0,
            "CREDITO": 0,
            "CHEQUE": 0,
        }

    def _calculate_provider_totals(
        self,
        payments,
    ):
        return {
            "particular": sum(
                payment["particular"]
                for payment in payments
            ),
            "copay": sum(
                payment["copay"]
                for payment in payments
            ),
            "withdrawal": sum(
                payment["withdrawal"]
                for payment in payments
            ),
            "total": sum(
                payment["total"]
                for payment in payments
            ),
        }

    def _calculate_general_totals(
        self,
        providers,
    ):
        """
        Suma los totales de todos los prestadores.
        """

        return {
            "particular": sum(
                provider["totals"]["particular"]
                for provider in providers
            ),

            "copay": sum(
                provider["totals"]["copay"]
                for provider in providers
            ),

            "withdrawal": sum(
                provider["totals"]["withdrawal"]
                for provider in providers
            ),

            "total": sum(
                provider["totals"]["total"]
                for provider in providers
            ),
        }

    def _calculate_payment_method_totals(
        self,
        providers,
    ):
        """
        Agrupa el total por medio de pago:

        EFECTIVO
        DEBITO
        CREDITO
        CHEQUE
        """

        totals = (
            self._empty_payment_method_totals()
        )

        for provider in providers:

            for payment in provider[
                "payments"
            ]:
                method = payment[
                    "payment_method"
                ]

                if method not in totals:
                    totals[
                        method
                    ] = 0

                totals[
                    method
                ] += payment[
                    "total"
                ]

        return totals

    # =========================================================
    # DASHBOARD
    # =========================================================

    def _build_dashboard(
        self,
        date_from,
        date_to,
        branches,
        providers,
        totals,
        payment_method_totals,
    ):
        """
        Construye una representación genérica del
        dashboard.

        El frontend solamente deberá interpretar:

        - metrics
        - charts
        - tables
        - summary
        """

        return {
            "title": "Detalle de Caja",

            "period": {
                "date_from": date_from,
                "date_to": date_to,
            },

            "metrics": self._build_metrics(
                branches=branches,
                providers=providers,
                totals=totals,
            ),

            "charts": [
                self._build_provider_chart(
                    providers
                ),
                self._build_payment_method_chart(
                    payment_method_totals
                ),
                self._build_income_type_chart(
                    totals
                ),
            ],

            "tables": [
                self._build_provider_table(
                    providers
                ),
                self._build_payment_method_table(
                    payment_method_totals
                ),
            ],

            "summary": self._build_summary(
                branches=branches,
                providers=providers,
                totals=totals,
                payment_method_totals=(
                    payment_method_totals
                ),
            ),
        }

    # =========================================================
    # DASHBOARD - MÉTRICAS
    # =========================================================

    def _build_metrics(
        self,
        branches,
        providers,
        totals,
    ):
        return [
            {
                "key": "total",
                "label": "Total recaudado",
                "value": totals["total"],
                "format": "currency",
            },
            {
                "key": "particular",
                "label": "Particular",
                "value": totals["particular"],
                "format": "currency",
            },
            {
                "key": "copay",
                "label": "Copago",
                "value": totals["copay"],
                "format": "currency",
            },
            {
                "key": "providers",
                "label": "Prestadores",
                "value": len(
                    providers
                ),
                "format": "number",
            },
            {
                "key": "branches",
                "label": "Sucursales",
                "value": len(
                    branches
                ),
                "format": "number",
            },
            {
                "key": "withdrawal",
                "label": "Retiros",
                "value": totals["withdrawal"],
                "format": "currency",
            },
        ]

    # =========================================================
    # DASHBOARD - GRÁFICOS
    # =========================================================

    def _build_provider_chart(
        self,
        providers,
    ):
        """
        Ranking de ingresos por prestador.
        """

        data = [
            {
                "label": provider["name"],
                "rut": provider["rut"],
                "value": provider[
                    "totals"
                ]["total"],
            }
            for provider in providers
        ]

        data.sort(
            key=lambda item: item[
                "value"
            ],
            reverse=True,
        )

        return {
            "key": "providers_total",
            "title": "Total por prestador",
            "type": "bar",
            "format": "currency",
            "data": data,
        }

    def _build_payment_method_chart(
        self,
        payment_method_totals,
    ):
        data = [
            {
                "label": method.title(),
                "value": value,
            }
            for method, value
            in payment_method_totals.items()
        ]

        return {
            "key": "payment_methods",
            "title": "Medios de pago",
            "type": "donut",
            "format": "currency",
            "data": data,
        }

    def _build_income_type_chart(
        self,
        totals,
    ):
        return {
            "key": "income_types",
            "title": (
                "Distribución Particular / Copago"
            ),
            "type": "donut",
            "format": "currency",
            "data": [
                {
                    "label": "Particular",
                    "value": totals[
                        "particular"
                    ],
                },
                {
                    "label": "Copago",
                    "value": totals[
                        "copay"
                    ],
                },
                {
                    "label": "Retiro",
                    "value": totals[
                        "withdrawal"
                    ],
                },
            ],
        }

    # =========================================================
    # DASHBOARD - TABLAS
    # =========================================================

    def _build_provider_table(
        self,
        providers,
    ):
        rows = []

        for provider in providers:

            totals = provider[
                "totals"
            ]

            rows.append(
                {
                    "rut": provider[
                        "rut"
                    ],
                    "provider": provider[
                        "name"
                    ],
                    "particular": totals[
                        "particular"
                    ],
                    "copay": totals[
                        "copay"
                    ],
                    "withdrawal": totals[
                        "withdrawal"
                    ],
                    "total": totals[
                        "total"
                    ],
                }
            )

        rows.sort(
            key=lambda item: item[
                "total"
            ],
            reverse=True,
        )

        return {
            "key": "providers",
            "title": "Resumen por prestador",

            "columns": [
                {
                    "key": "rut",
                    "label": "RUT",
                    "format": "text",
                },
                {
                    "key": "provider",
                    "label": "Prestador",
                    "format": "text",
                },
                {
                    "key": "particular",
                    "label": "Particular",
                    "format": "currency",
                },
                {
                    "key": "copay",
                    "label": "Copago",
                    "format": "currency",
                },
                {
                    "key": "withdrawal",
                    "label": "Retiro",
                    "format": "currency",
                },
                {
                    "key": "total",
                    "label": "Total",
                    "format": "currency",
                },
            ],

            "rows": rows,
        }

    def _build_payment_method_table(
        self,
        payment_method_totals,
    ):
        rows = [
            {
                "payment_method": (
                    method.title()
                ),
                "total": value,
            }
            for method, value
            in payment_method_totals.items()
        ]

        rows.sort(
            key=lambda item: item[
                "total"
            ],
            reverse=True,
        )

        return {
            "key": "payment_methods",
            "title": "Resumen por medio de pago",

            "columns": [
                {
                    "key": "payment_method",
                    "label": "Medio de pago",
                    "format": "text",
                },
                {
                    "key": "total",
                    "label": "Total",
                    "format": "currency",
                },
            ],

            "rows": rows,
        }

    # =========================================================
    # DASHBOARD - RESUMEN
    # =========================================================

    def _build_summary(
        self,
        branches,
        providers,
        totals,
        payment_method_totals,
    ):
        if not providers:
            return {
                "title": "Resumen",
                "text": (
                    "No se encontraron prestadores "
                    "en el documento."
                ),
                "highlights": [],
            }

        sorted_providers = sorted(
            providers,
            key=lambda provider: (
                provider[
                    "totals"
                ]["total"]
            ),
            reverse=True,
        )

        top_provider = (
            sorted_providers[0]
        )

        top_payment_method = max(
            payment_method_totals.items(),
            key=lambda item: item[1],
        )

        total = totals[
            "total"
        ]

        top_provider_percentage = 0

        if total > 0:
            top_provider_percentage = round(
                (
                    top_provider[
                        "totals"
                    ]["total"]
                    / total
                )
                * 100,
                2,
            )

        text = (
            f"El documento registra un total "
            f"de {self._format_currency(total)} "
            f"distribuido entre "
            f"{len(providers)} prestadores "
            f"y {len(branches)} sucursales. "
            f"El prestador con mayor monto es "
            f"{top_provider['name']} con "
            f"{self._format_currency(top_provider['totals']['total'])}. "
            f"El medio de pago con mayor recaudación "
            f"es {top_payment_method[0].title()} con "
            f"{self._format_currency(top_payment_method[1])}."
        )

        if totals[
            "withdrawal"
        ] == 0:
            text += (
                " No se registran retiros "
                "en el período."
            )

        return {
            "title": "Resumen del documento",

            "text": text,

            "highlights": [
                {
                    "key": "top_provider",
                    "label": (
                        "Prestador con mayor recaudación"
                    ),
                    "value": top_provider[
                        "name"
                    ],
                },
                {
                    "key": "top_provider_amount",
                    "label": (
                        "Monto principal prestador"
                    ),
                    "value": top_provider[
                        "totals"
                    ]["total"],
                    "format": "currency",
                },
                {
                    "key": "top_provider_percentage",
                    "label": (
                        "Participación principal prestador"
                    ),
                    "value": (
                        top_provider_percentage
                    ),
                    "format": "percentage",
                },
                {
                    "key": "top_payment_method",
                    "label": (
                        "Principal medio de pago"
                    ),
                    "value": (
                        top_payment_method[
                            0
                        ].title()
                    ),
                },
            ],
        }

    # =========================================================
    # FORMATOS
    # =========================================================

    def _format_currency(
        self,
        value,
    ):
        """
        Formato de moneda chilena para textos.

        3050736
            ->
        $3.050.736
        """

        try:
            number = int(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            number = 0

        return (
            f"${number:,}"
            .replace(",", ".")
        )


informe_depositos_parser = InformeDepositosParser()