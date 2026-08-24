from typing import Any


class FlujoCajaPptoParser:
    """
    Parser específico para:

        FLUJO-CAJA-PPTO.xlsx

    Espera recibir la estructura genérica ya procesada
    por ExcelParser.

    El archivo contempla principalmente:

    - DASHBOARD
    - FLUJO MENSUAL
    - PROYECCION
    - PRESUPUESTO

    Construye información preparada para:
    - métricas
    - gráficos
    - tablas
    - resumen
    """

    DOCUMENT_TYPE = "flujo_caja_ppto"

    MONTH_NAMES = [
        "Ene",
        "Feb",
        "Mar",
        "Abr",
        "May",
        "Jun",
        "Jul",
        "Ago",
        "Sep",
        "Oct",
        "Nov",
        "Dic",
    ]

    def parse(
        self,
        spreadsheet_data: dict[str, Any],
    ) -> dict[str, Any]:

        if not spreadsheet_data:
            return self._empty_result()

        sheets = spreadsheet_data.get(
            "sheets",
            [],
        )

        dashboard_sheet = self._find_sheet(
            sheets,
            "DASHBOARD",
        )

        flujo_sheet = self._find_sheet(
            sheets,
            "FLUJO MENSUAL",
        )

        proyeccion_sheet = self._find_sheet(
            sheets,
            "PROYECCION",
        )

        presupuesto_sheet = self._find_sheet(
            sheets,
            "PRESUPUESTO",
        )

        monthly_flow = self._extract_monthly_flow(
            flujo_sheet
        )

        budget = self._extract_budget(
            presupuesto_sheet
        )

        projection = self._extract_projection(
            proyeccion_sheet
        )

        dashboard_source = self._extract_dashboard_source(
            dashboard_sheet
        )

        totals = self._calculate_totals(
            monthly_flow
        )

        dashboard = self._build_dashboard(
            monthly_flow=monthly_flow,
            budget=budget,
            projection=projection,
            totals=totals,
            dashboard_source=dashboard_source,
        )

        return {
            "document_type": self.DOCUMENT_TYPE,
            "title": "Flujo de Caja y Presupuesto",

            "monthly_flow": monthly_flow,
            "budget": budget,
            "projection": projection,

            "totals": totals,

            "dashboard_source": (
                dashboard_source
            ),

            "dashboard": dashboard,
        }

    # =========================================================
    # RESULTADO VACÍO
    # =========================================================

    def _empty_result(
        self,
    ):
        return {
            "document_type": self.DOCUMENT_TYPE,
            "title": "Flujo de Caja y Presupuesto",

            "monthly_flow": [],
            "budget": [],
            "projection": [],

            "totals": {
                "income": 0,
                "expenses": 0,
                "net_flow": 0,
                "final_balance": 0,
            },

            "dashboard_source": {},

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
    # UTILIDADES DE HOJAS
    # =========================================================

    def _find_sheet(
        self,
        sheets,
        expected_name,
    ):
        expected = self._normalize_text(
            expected_name
        )

        for sheet in sheets:
            current = self._normalize_text(
                sheet.get(
                    "name",
                    "",
                )
            )

            if current == expected:
                return sheet

        return None

    def _normalize_text(
        self,
        value,
    ):
        if value is None:
            return ""

        text = str(
            value
        ).strip().upper()

        replacements = {
            "Á": "A",
            "É": "E",
            "Í": "I",
            "Ó": "O",
            "Ú": "U",
            "Ü": "U",
            "Ñ": "N",
        }

        for original, replacement in (
            replacements.items()
        ):
            text = text.replace(
                original,
                replacement,
            )

        return " ".join(
            text.split()
        )

    def _rows(
        self,
        sheet,
    ):
        if not sheet:
            return []

        return sheet.get(
            "rows",
            [],
        )

    def _safe_value(
        self,
        row,
        index,
        default=None,
    ):
        if not row:
            return default

        if index >= len(row):
            return default

        value = row[index]

        if value in (
            None,
            "",
        ):
            return default

        return value

    def _number(
        self,
        value,
    ):
        if value in (
            None,
            "",
        ):
            return 0

        if isinstance(
            value,
            bool,
        ):
            return int(
                value
            )

        if isinstance(
            value,
            (
                int,
                float,
            ),
        ):
            return value

        text = str(
            value
        ).strip()

        if not text:
            return 0

        text = (
            text
            .replace("$", "")
            .replace(" ", "")
        )

        # Formato chileno simple:
        # 1.234.567
        if (
            "." in text
            and "," not in text
        ):
            text = text.replace(
                ".",
                "",
            )

        # 1.234.567,89
        elif "," in text:
            text = (
                text
                .replace(".", "")
                .replace(",", ".")
            )

        try:
            number = float(
                text
            )

            if number.is_integer():
                return int(
                    number
                )

            return number

        except (
            TypeError,
            ValueError,
        ):
            return 0

    # =========================================================
    # FLUJO MENSUAL
    # =========================================================

    def _extract_monthly_flow(
        self,
        sheet,
    ):
        """
        Busca las filas:

        TOTAL INGRESOS OPERACIONALES
        TOTAL EGRESOS OPERACIONALES
        FLUJO NETO OPERACIONAL
        SALDO FINAL

        y construye una fila por mes.
        """

        rows = self._rows(
            sheet
        )

        if not rows:
            return []

        income_row = self._find_row(
            rows,
            "TOTAL INGRESOS OPERACIONALES",
        )

        expense_row = self._find_row(
            rows,
            "TOTAL EGRESOS OPERACIONALES",
        )

        net_row = self._find_row(
            rows,
            "FLUJO NETO OPERACIONAL",
        )

        final_balance_row = self._find_row(
            rows,
            "SALDO FINAL",
        )

        monthly_flow = []

        for month_index, month in enumerate(
            self.MONTH_NAMES,
            start=1,
        ):
            income = self._number(
                self._safe_value(
                    income_row,
                    month_index,
                    0,
                )
            )

            expenses = self._number(
                self._safe_value(
                    expense_row,
                    month_index,
                    0,
                )
            )

            net_flow = self._number(
                self._safe_value(
                    net_row,
                    month_index,
                    income - expenses,
                )
            )

            final_balance = self._number(
                self._safe_value(
                    final_balance_row,
                    month_index,
                    0,
                )
            )

            monthly_flow.append(
                {
                    "month": month,
                    "income": income,
                    "expenses": expenses,
                    "net_flow": net_flow,
                    "final_balance": final_balance,
                }
            )

        return monthly_flow

    def _find_row(
        self,
        rows,
        label,
    ):
        expected = self._normalize_text(
            label
        )

        for row in rows:

            first_value = self._safe_value(
                row,
                0,
                "",
            )

            current = self._normalize_text(
                first_value
            )

            if current == expected:
                return row

        return []

    # =========================================================
    # PRESUPUESTO
    # =========================================================

    def _extract_budget(
        self,
        sheet,
    ):
        """
        Extrae categorías mensuales desde la hoja PRESUPUESTO.

        Devuelve solamente filas que tengan un concepto
        y que no correspondan a títulos de sección.
        """

        rows = self._rows(
            sheet
        )

        if not rows:
            return []

        ignored_sections = {
            "OPERACION - INGRESO",
            "OPERACION - EGRESO",
            "INVERSION - EGRESO",
            "FINANCIAMIENTO - INGRESO",
            "FINANCIAMIENTO - EGRESO",
        }

        budget_rows = []

        # En el archivo actual el encabezado está
        # alrededor de la fila 5.
        for row in rows:

            concept = self._safe_value(
                row,
                0,
                "",
            )

            normalized_concept = (
                self._normalize_text(
                    concept
                )
            )

            if not normalized_concept:
                continue

            if normalized_concept in (
                ignored_sections
            ):
                continue

            if normalized_concept in {
                "CATEGORIA",
                "PRESUPUESTO MENSUAL DE CAJA 2026",
            }:
                continue

            monthly_values = []

            has_numeric_value = False

            for month_index, month in enumerate(
                self.MONTH_NAMES,
                start=1,
            ):
                value = self._number(
                    self._safe_value(
                        row,
                        month_index,
                        0,
                    )
                )

                if value != 0:
                    has_numeric_value = True

                monthly_values.append(
                    {
                        "month": month,
                        "value": value,
                    }
                )

            total_annual = self._number(
                self._safe_value(
                    row,
                    13,
                    0,
                )
            )

            if total_annual != 0:
                has_numeric_value = True

            # Igual conservamos las filas conocidas,
            # aunque hoy estén en cero.
            if (
                has_numeric_value
                or normalized_concept
            ):
                budget_rows.append(
                    {
                        "category": str(
                            concept
                        ).strip(),
                        "months": monthly_values,
                        "annual_total": (
                            total_annual
                        ),
                    }
                )

        return budget_rows

    # =========================================================
    # PROYECCIÓN
    # =========================================================

    def _extract_projection(
        self,
        sheet,
    ):
        rows = self._rows(
            sheet
        )

        if not rows:
            return []

        balance_row = self._find_row(
            rows,
            "SALDO FINAL",
        )

        minimum_cash_row = self._find_row(
            rows,
            "CAJA MINIMA",
        )

        deficit_row = self._find_row(
            rows,
            "HOLGURA / DEFICIT",
        )

        variation_row = self._find_row(
            rows,
            "VARIACION NETA",
        )

        projection = []

        for week_index in range(
            1,
            14,
        ):
            projection.append(
                {
                    "week": (
                        f"Semana {week_index}"
                    ),

                    "net_variation": (
                        self._number(
                            self._safe_value(
                                variation_row,
                                week_index,
                                0,
                            )
                        )
                    ),

                    "final_balance": (
                        self._number(
                            self._safe_value(
                                balance_row,
                                week_index,
                                0,
                            )
                        )
                    ),

                    "minimum_cash": (
                        self._number(
                            self._safe_value(
                                minimum_cash_row,
                                week_index,
                                0,
                            )
                        )
                    ),

                    "surplus_deficit": (
                        self._number(
                            self._safe_value(
                                deficit_row,
                                week_index,
                                0,
                            )
                        )
                    ),
                }
            )

        return projection

    # =========================================================
    # DASHBOARD ORIGINAL DEL EXCEL
    # =========================================================

    def _extract_dashboard_source(
        self,
        sheet,
    ):
        """
        El Excel ya posee una hoja DASHBOARD.

        Extraemos algunos indicadores de esa hoja para
        mantenerlos disponibles, pero el frontend no queda
        acoplado a ella.
        """

        rows = self._rows(
            sheet
        )

        if not rows:
            return {}

        return {
            "real_income": self._find_value_next_to_label(
                rows,
                "INGRESOS REALES",
            ),

            "operational_expenses": (
                self._find_value_next_to_label(
                    rows,
                    "EGRESOS OPERACIONALES",
                )
            ),

            "operational_net_flow": (
                self._find_value_next_to_label(
                    rows,
                    "FLUJO NETO OPERACIONAL",
                )
            ),

            "december_final_balance": (
                self._find_value_next_to_label(
                    rows,
                    "SALDO FINAL DICIEMBRE",
                )
            ),

            "months_below_minimum_cash": (
                self._find_value_next_to_label(
                    rows,
                    "MESES BAJO CAJA MINIMA",
                )
            ),

            "income_budget_compliance": (
                self._find_value_next_to_label(
                    rows,
                    "INGRESOS / PRESUPUESTO",
                )
            ),

            "expense_budget_compliance": (
                self._find_value_next_to_label(
                    rows,
                    "EGRESOS / PRESUPUESTO",
                )
            ),

            "annual_cash_deviation": (
                self._find_value_next_to_label(
                    rows,
                    "DESVIACION CAJA ANUAL",
                )
            ),

            "minimum_projected_balance": (
                self._find_value_next_to_label(
                    rows,
                    "SALDO MINIMO PROYECTADO",
                )
            ),

            "weeks_with_deficit": (
                self._find_value_next_to_label(
                    rows,
                    "SEMANAS CON DEFICIT",
                )
            ),
        }

    def _find_value_next_to_label(
        self,
        rows,
        label,
    ):
        expected = self._normalize_text(
            label
        )

        for row in rows:

            for index, value in enumerate(
                row
            ):
                current = self._normalize_text(
                    value
                )

                if current != expected:
                    continue

                next_index = index + 1

                return self._number(
                    self._safe_value(
                        row,
                        next_index,
                        0,
                    )
                )

        return 0

    # =========================================================
    # TOTALES
    # =========================================================

    def _calculate_totals(
        self,
        monthly_flow,
    ):
        if not monthly_flow:
            return {
                "income": 0,
                "expenses": 0,
                "net_flow": 0,
                "final_balance": 0,
            }

        income = sum(
            item["income"]
            for item in monthly_flow
        )

        expenses = sum(
            item["expenses"]
            for item in monthly_flow
        )

        net_flow = sum(
            item["net_flow"]
            for item in monthly_flow
        )

        final_balance = monthly_flow[
            -1
        ]["final_balance"]

        return {
            "income": income,
            "expenses": expenses,
            "net_flow": net_flow,
            "final_balance": final_balance,
        }

    # =========================================================
    # DASHBOARD
    # =========================================================

    def _build_dashboard(
        self,
        monthly_flow,
        budget,
        projection,
        totals,
        dashboard_source,
    ):
        return {
            "title": (
                "Flujo de Caja y Presupuesto"
            ),

            "metrics": (
                self._build_metrics(
                    totals=totals,
                    projection=projection,
                    dashboard_source=(
                        dashboard_source
                    ),
                )
            ),

            "charts": [
                self._build_monthly_flow_chart(
                    monthly_flow
                ),
                self._build_balance_chart(
                    monthly_flow
                ),
                self._build_projection_chart(
                    projection
                ),
            ],

            "tables": [
                self._build_monthly_flow_table(
                    monthly_flow
                ),
                self._build_projection_table(
                    projection
                ),
            ],

            "summary": (
                self._build_summary(
                    totals=totals,
                    monthly_flow=monthly_flow,
                    projection=projection,
                )
            ),
        }

    # =========================================================
    # MÉTRICAS
    # =========================================================

    def _build_metrics(
        self,
        totals,
        projection,
        dashboard_source,
    ):
        deficit_weeks = sum(
            1
            for item in projection
            if item[
                "surplus_deficit"
            ] < 0
        )

        balances = [
            item["final_balance"]
            for item in projection
        ]

        minimum_projected_balance = (
            min(balances)
            if balances
            else 0
        )

        return [
            {
                "key": "income",
                "label": "Ingresos",
                "value": totals["income"],
                "format": "currency",
            },
            {
                "key": "expenses",
                "label": "Egresos",
                "value": totals["expenses"],
                "format": "currency",
            },
            {
                "key": "net_flow",
                "label": "Flujo neto",
                "value": totals["net_flow"],
                "format": "currency",
            },
            {
                "key": "final_balance",
                "label": "Saldo final",
                "value": totals[
                    "final_balance"
                ],
                "format": "currency",
            },
            {
                "key": "minimum_projected_balance",
                "label": (
                    "Saldo mínimo proyectado"
                ),
                "value": (
                    minimum_projected_balance
                ),
                "format": "currency",
            },
            {
                "key": "deficit_weeks",
                "label": "Semanas con déficit",
                "value": deficit_weeks,
                "format": "number",
            },
        ]

    # =========================================================
    # GRÁFICOS
    # =========================================================

    def _build_monthly_flow_chart(
        self,
        monthly_flow,
    ):
        return {
            "key": "monthly_income_expenses",
            "title": (
                "Ingresos y egresos mensuales"
            ),
            "type": "bar",
            "format": "currency",

            "series": [
                {
                    "key": "income",
                    "label": "Ingresos",
                },
                {
                    "key": "expenses",
                    "label": "Egresos",
                },
            ],

            "data": monthly_flow,
        }

    def _build_balance_chart(
        self,
        monthly_flow,
    ):
        return {
            "key": "monthly_balance",
            "title": "Saldo mensual",
            "type": "line",
            "format": "currency",

            "series": [
                {
                    "key": "final_balance",
                    "label": "Saldo final",
                },
            ],

            "data": monthly_flow,
        }

    def _build_projection_chart(
        self,
        projection,
    ):
        return {
            "key": "liquidity_projection",
            "title": (
                "Proyección de liquidez"
            ),
            "type": "line",
            "format": "currency",

            "series": [
                {
                    "key": "final_balance",
                    "label": "Saldo final",
                },
                {
                    "key": "minimum_cash",
                    "label": "Caja mínima",
                },
            ],

            "data": projection,
        }

    # =========================================================
    # TABLAS
    # =========================================================

    def _build_monthly_flow_table(
        self,
        monthly_flow,
    ):
        return {
            "key": "monthly_flow",

            "title": (
                "Resumen mensual de caja"
            ),

            "columns": [
                {
                    "key": "month",
                    "label": "Mes",
                    "format": "text",
                },
                {
                    "key": "income",
                    "label": "Ingresos",
                    "format": "currency",
                },
                {
                    "key": "expenses",
                    "label": "Egresos",
                    "format": "currency",
                },
                {
                    "key": "net_flow",
                    "label": "Flujo neto",
                    "format": "currency",
                },
                {
                    "key": "final_balance",
                    "label": "Saldo final",
                    "format": "currency",
                },
            ],

            "rows": monthly_flow,
        }

    def _build_projection_table(
        self,
        projection,
    ):
        return {
            "key": "projection",

            "title": (
                "Proyección de liquidez"
            ),

            "columns": [
                {
                    "key": "week",
                    "label": "Semana",
                    "format": "text",
                },
                {
                    "key": "net_variation",
                    "label": "Variación neta",
                    "format": "currency",
                },
                {
                    "key": "final_balance",
                    "label": "Saldo final",
                    "format": "currency",
                },
                {
                    "key": "minimum_cash",
                    "label": "Caja mínima",
                    "format": "currency",
                },
                {
                    "key": "surplus_deficit",
                    "label": "Holgura / déficit",
                    "format": "currency",
                },
            ],

            "rows": projection,
        }

    # =========================================================
    # RESUMEN
    # =========================================================

    def _build_summary(
        self,
        totals,
        monthly_flow,
        projection,
    ):
        best_month = None
        worst_month = None

        if monthly_flow:
            best_month = max(
                monthly_flow,
                key=lambda item: item[
                    "net_flow"
                ],
            )

            worst_month = min(
                monthly_flow,
                key=lambda item: item[
                    "net_flow"
                ],
            )

        deficit_weeks = [
            item
            for item in projection
            if item[
                "surplus_deficit"
            ] < 0
        ]

        text = (
            "El flujo de caja registra "
            f"{self._format_currency(totals['income'])} "
            "en ingresos y "
            f"{self._format_currency(totals['expenses'])} "
            "en egresos, con un flujo neto de "
            f"{self._format_currency(totals['net_flow'])}."
        )

        if best_month:
            text += (
                f" El mes con mejor flujo neto es "
                f"{best_month['month']} con "
                f"{self._format_currency(best_month['net_flow'])}."
            )

        if worst_month:
            text += (
                f" El mes con menor flujo neto es "
                f"{worst_month['month']} con "
                f"{self._format_currency(worst_month['net_flow'])}."
            )

        if deficit_weeks:
            text += (
                f" La proyección presenta "
                f"{len(deficit_weeks)} semanas "
                f"con déficit de caja."
            )
        else:
            text += (
                " La proyección no presenta "
                "semanas bajo el nivel mínimo de caja."
            )

        return {
            "title": (
                "Resumen financiero"
            ),

            "text": text,

            "highlights": [
                {
                    "key": "best_month",
                    "label": (
                        "Mejor mes"
                    ),
                    "value": (
                        best_month[
                            "month"
                        ]
                        if best_month
                        else None
                    ),
                },
                {
                    "key": "worst_month",
                    "label": (
                        "Mes con menor flujo"
                    ),
                    "value": (
                        worst_month[
                            "month"
                        ]
                        if worst_month
                        else None
                    ),
                },
                {
                    "key": "deficit_weeks",
                    "label": (
                        "Semanas con déficit"
                    ),
                    "value": len(
                        deficit_weeks
                    ),
                    "format": "number",
                },
            ],
        }

    # =========================================================
    # FORMATO
    # =========================================================

    def _format_currency(
        self,
        value,
    ):
        try:
            value = int(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            value = 0

        return (
            f"${value:,}"
            .replace(",", ".")
        )


flujo_caja_ppto_parser = FlujoCajaPptoParser()