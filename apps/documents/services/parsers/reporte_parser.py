from collections import Counter
from datetime import datetime
from typing import Any


class ReporteParser:
    """
    Parser específico para:

        REPORTE.xlsx

    El archivo contiene información de atenciones /
    procedimientos médicos.

    Extrae y analiza:
    - atenciones
    - procedimientos
    - pacientes
    - salas
    - sucursales
    - prioridades
    - prestadores
    - financiadores
    - valores
    - tiempos de espera
    - tiempos de atención

    Construye:
    - métricas
    - gráficos
    - tablas
    - resumen automático

    No persiste información.
    """

    DOCUMENT_TYPE = "reporte"

    REQUIRED_HEADERS = {
        "ID",
        "FECHA Y HORA",
        "DNI",
        "NOMBRE",
        "SALA",
        "CODIGO",
        "PROCEDIMIENTO",
        "ESTADO",
        "SUCURSAL",
        "PRIORIDAD",
        "PRESTADOR",
        "FINANCIADOR",
        "VALOR",
    }

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

        if not sheets:
            return self._empty_result()

        sheet = sheets[0]

        rows = sheet.get(
            "rows",
            [],
        )

        header_index = self._find_header_row(
            rows
        )

        if header_index is None:
            return self._empty_result(
                message=(
                    "No se encontró la estructura "
                    "esperada del archivo REPORTE."
                )
            )

        headers = rows[
            header_index
        ]

        column_map = self._build_column_map(
            headers
        )

        records = self._extract_records(
            rows=rows[
                header_index + 1:
            ],
            column_map=column_map,
        )

        statistics = self._build_statistics(
            records
        )

        dashboard = self._build_dashboard(
            records=records,
            statistics=statistics,
        )

        return {
            "document_type": (
                self.DOCUMENT_TYPE
            ),

            "title": (
                "Reporte de Atenciones"
            ),

            "record_count": len(
                records
            ),

            "records": records,

            "statistics": statistics,

            "dashboard": dashboard,
        }

    # =========================================================
    # RESULTADO VACÍO
    # =========================================================

    def _empty_result(
        self,
        message=None,
    ):
        return {
            "document_type": (
                self.DOCUMENT_TYPE
            ),

            "title": (
                "Reporte de Atenciones"
            ),

            "record_count": 0,

            "records": [],

            "statistics": {
                "total_records": 0,
                "unique_appointments": 0,
                "unique_patients": 0,
                "total_value": 0,
                "total_discount": 0,
                "average_value": 0,
                "average_wait_minutes": 0,
                "average_attention_minutes": 0,
                "date_from": None,
                "date_to": None,
                "procedures": [],
                "rooms": [],
                "branches": [],
                "priorities": [],
                "providers": [],
                "financiers": [],
                "statuses": [],
                "daily_activity": [],
            },

            "dashboard": {
                "metrics": [],
                "charts": [],
                "tables": [],
                "summary": {
                    "title": (
                        "Resumen del reporte"
                    ),
                    "text": (
                        message
                        or (
                            "No se encontró información "
                            "para construir el dashboard."
                        )
                    ),
                    "highlights": [],
                },
            },
        }

    # =========================================================
    # HEADER
    # =========================================================

    def _find_header_row(
        self,
        rows,
    ):
        """
        Busca la fila que contiene los encabezados
        reales del reporte.

        El archivo actual tiene:

            fila 1 -> reporte
            fila 2 -> encabezados
        """

        for index, row in enumerate(
            rows[:20]
        ):
            normalized_values = {
                self._normalize_text(
                    value
                )
                for value in row
                if value not in (
                    None,
                    "",
                )
            }

            matches = len(
                normalized_values
                & self.REQUIRED_HEADERS
            )

            if matches >= 8:
                return index

        return None

    def _build_column_map(
        self,
        headers,
    ):
        """
        Algunas columnas vienen repetidas:

            RESPONSABLE ATENCIÓN
            RESPONSABLE ATENCIÓN
            RESPONSABLE ATENCIÓN

        Por eso guardamos todas sus posiciones.
        """

        column_map = {
            "responsibles": [],
        }

        for index, header in enumerate(
            headers
        ):
            normalized = self._normalize_text(
                header
            )

            if normalized == "ID":
                column_map["id"] = index

            elif normalized == "FECHA Y HORA":
                column_map[
                    "scheduled_datetime"
                ] = index

            elif normalized == "HORA LLEGADA":
                column_map[
                    "arrival_time"
                ] = index

            elif normalized == "HORA INGRESO":
                column_map[
                    "entry_time"
                ] = index

            elif normalized == "DNI":
                column_map["dni"] = index

            elif normalized == "NOMBRE":
                column_map["patient"] = index

            elif normalized == "SALA":
                column_map["room"] = index

            elif normalized == "CODIGO":
                column_map[
                    "procedure_code"
                ] = index

            elif normalized == "PROCEDIMIENTO":
                column_map[
                    "procedure"
                ] = index

            elif normalized == "MODALIDAD":
                column_map[
                    "modality"
                ] = index

            elif normalized == "ESTADO":
                column_map[
                    "status"
                ] = index

            elif normalized == "USUARIO DEL TURNO":
                column_map[
                    "shift_user"
                ] = index

            elif normalized == "M. REFERENCIA":
                column_map[
                    "reference_doctor"
                ] = index

            elif normalized == "MED. INF.":
                column_map[
                    "reporting_doctor"
                ] = index

            elif (
                normalized
                == "RESPONSABLE ATENCION"
            ):
                column_map[
                    "responsibles"
                ].append(
                    index
                )

            elif normalized == "SUCURSAL":
                column_map[
                    "branch"
                ] = index

            elif normalized == "PRIORIDAD":
                column_map[
                    "priority"
                ] = index

            elif normalized == "CONTRASTE":
                column_map[
                    "contrast"
                ] = index

            elif normalized == "PRESTADOR":
                column_map[
                    "provider"
                ] = index

            elif normalized == "FINANCIADOR":
                column_map[
                    "financier"
                ] = index

            elif normalized == "VALOR":
                column_map[
                    "value"
                ] = index

            elif normalized == "DESCUENTO":
                column_map[
                    "discount"
                ] = index

        return column_map

    # =========================================================
    # REGISTROS
    # =========================================================

    def _extract_records(
        self,
        rows,
        column_map,
    ):
        records = []

        for row in rows:

            if not self._row_has_data(
                row
            ):
                continue

            scheduled_datetime = (
                self._get_value(
                    row,
                    column_map.get(
                        "scheduled_datetime"
                    ),
                )
            )

            arrival_time = self._get_value(
                row,
                column_map.get(
                    "arrival_time"
                ),
            )

            entry_time = self._get_value(
                row,
                column_map.get(
                    "entry_time"
                ),
            )

            normalized_datetime = (
                self._normalize_datetime(
                    scheduled_datetime
                )
            )

            normalized_arrival = (
                self._normalize_time(
                    arrival_time
                )
            )

            normalized_entry = (
                self._normalize_time(
                    entry_time
                )
            )

            responsibles = []

            for index in column_map.get(
                "responsibles",
                [],
            ):
                value = self._get_value(
                    row,
                    index,
                )

                if value not in (
                    None,
                    "",
                    "-",
                ):
                    responsibles.append(
                        str(value).strip()
                    )

            value = self._number(
                self._get_value(
                    row,
                    column_map.get(
                        "value"
                    ),
                    0,
                )
            )

            discount = self._number(
                self._get_value(
                    row,
                    column_map.get(
                        "discount"
                    ),
                    0,
                )
            )

            wait_minutes = (
                self._calculate_wait_minutes(
                    normalized_datetime,
                    normalized_arrival,
                )
            )

            attention_minutes = (
                self._calculate_attention_minutes(
                    normalized_arrival,
                    normalized_entry,
                )
            )

            records.append(
                {
                    "id": self._get_value(
                        row,
                        column_map.get(
                            "id"
                        ),
                    ),

                    "scheduled_datetime": (
                        normalized_datetime
                    ),

                    "date": (
                        self._extract_date(
                            normalized_datetime
                        )
                    ),

                    "scheduled_time": (
                        self._extract_time(
                            normalized_datetime
                        )
                    ),

                    "arrival_time": (
                        normalized_arrival
                    ),

                    "entry_time": (
                        normalized_entry
                    ),

                    "dni": self._text(
                        self._get_value(
                            row,
                            column_map.get(
                                "dni"
                            ),
                        )
                    ),

                    "patient": self._text(
                        self._get_value(
                            row,
                            column_map.get(
                                "patient"
                            ),
                        )
                    ),

                    "room": self._text(
                        self._get_value(
                            row,
                            column_map.get(
                                "room"
                            ),
                        )
                    ),

                    "procedure_code": (
                        self._text(
                            self._get_value(
                                row,
                                column_map.get(
                                    "procedure_code"
                                ),
                            )
                        )
                    ),

                    "procedure": (
                        self._text(
                            self._get_value(
                                row,
                                column_map.get(
                                    "procedure"
                                ),
                            )
                        )
                    ),

                    "modality": self._text(
                        self._get_value(
                            row,
                            column_map.get(
                                "modality"
                            ),
                        )
                    ),

                    "status": self._text(
                        self._get_value(
                            row,
                            column_map.get(
                                "status"
                            ),
                        )
                    ),

                    "shift_user": (
                        self._text(
                            self._get_value(
                                row,
                                column_map.get(
                                    "shift_user"
                                ),
                            )
                        )
                    ),

                    "reference_doctor": (
                        self._text(
                            self._get_value(
                                row,
                                column_map.get(
                                    "reference_doctor"
                                ),
                            )
                        )
                    ),

                    "reporting_doctor": (
                        self._text(
                            self._get_value(
                                row,
                                column_map.get(
                                    "reporting_doctor"
                                ),
                            )
                        )
                    ),

                    "responsibles": (
                        responsibles
                    ),

                    "branch": self._text(
                        self._get_value(
                            row,
                            column_map.get(
                                "branch"
                            ),
                        )
                    ),

                    "priority": self._text(
                        self._get_value(
                            row,
                            column_map.get(
                                "priority"
                            ),
                        )
                    ),

                    "contrast": self._text(
                        self._get_value(
                            row,
                            column_map.get(
                                "contrast"
                            ),
                        )
                    ),

                    "provider": self._text(
                        self._get_value(
                            row,
                            column_map.get(
                                "provider"
                            ),
                        )
                    ),

                    "financier": self._text(
                        self._get_value(
                            row,
                            column_map.get(
                                "financier"
                            ),
                        )
                    ),

                    "value": value,

                    "discount": discount,

                    "net_value": (
                        value
                        - discount
                    ),

                    "wait_minutes": (
                        wait_minutes
                    ),

                    "attention_minutes": (
                        attention_minutes
                    ),
                }
            )

        return records

    # =========================================================
    # ESTADÍSTICAS
    # =========================================================

    def _build_statistics(
        self,
        records,
    ):
        if not records:
            return self._empty_result()[
                "statistics"
            ]

        procedure_counter = Counter(
            record["procedure"]
            for record in records
            if record["procedure"]
        )

        room_counter = Counter(
            record["room"]
            for record in records
            if record["room"]
        )

        branch_counter = Counter(
            record["branch"]
            for record in records
            if record["branch"]
        )

        priority_counter = Counter(
            record["priority"]
            for record in records
            if record["priority"]
        )

        provider_counter = Counter(
            record["provider"]
            for record in records
            if record["provider"]
        )

        financier_counter = Counter(
            record["financier"]
            for record in records
            if record["financier"]
        )

        status_counter = Counter(
            record["status"]
            for record in records
            if record["status"]
        )

        daily_counter = Counter(
            record["date"]
            for record in records
            if record["date"]
        )

        unique_appointments = len(
            {
                str(
                    record["id"]
                )
                for record in records
                if record["id"]
                not in (
                    None,
                    "",
                )
            }
        )

        unique_patients = len(
            {
                record["dni"]
                for record in records
                if record["dni"]
            }
        )

        total_value = sum(
            record["value"]
            for record in records
        )

        total_discount = sum(
            record["discount"]
            for record in records
        )

        net_value = sum(
            record["net_value"]
            for record in records
        )

        wait_values = [
            record["wait_minutes"]
            for record in records
            if record["wait_minutes"]
            is not None
        ]

        attention_values = [
            record["attention_minutes"]
            for record in records
            if record[
                "attention_minutes"
            ]
            is not None
        ]

        dates = sorted(
            daily_counter.keys()
        )

        return {
            "total_records": len(
                records
            ),

            "unique_appointments": (
                unique_appointments
            ),

            "unique_patients": (
                unique_patients
            ),

            "total_value": (
                total_value
            ),

            "total_discount": (
                total_discount
            ),

            "net_value": net_value,

            "average_value": (
                round(
                    total_value
                    / len(records),
                    2,
                )
                if records
                else 0
            ),

            "average_wait_minutes": (
                round(
                    sum(wait_values)
                    / len(wait_values),
                    2,
                )
                if wait_values
                else 0
            ),

            "average_attention_minutes": (
                round(
                    sum(
                        attention_values
                    )
                    / len(
                        attention_values
                    ),
                    2,
                )
                if attention_values
                else 0
            ),

            "date_from": (
                dates[0]
                if dates
                else None
            ),

            "date_to": (
                dates[-1]
                if dates
                else None
            ),

            "procedures": (
                self._counter_to_list(
                    procedure_counter,
                    "procedure",
                )
            ),

            "rooms": (
                self._counter_to_list(
                    room_counter,
                    "room",
                )
            ),

            "branches": (
                self._counter_to_list(
                    branch_counter,
                    "branch",
                )
            ),

            "priorities": (
                self._counter_to_list(
                    priority_counter,
                    "priority",
                )
            ),

            "providers": (
                self._counter_to_list(
                    provider_counter,
                    "provider",
                )
            ),

            "financiers": (
                self._counter_to_list(
                    financier_counter,
                    "financier",
                )
            ),

            "statuses": (
                self._counter_to_list(
                    status_counter,
                    "status",
                )
            ),

            "daily_activity": [
                {
                    "date": date_value,
                    "count": daily_counter[
                        date_value
                    ],
                }
                for date_value
                in dates
            ],
        }

    def _counter_to_list(
        self,
        counter,
        key_name,
    ):
        return [
            {
                key_name: key,
                "count": value,
            }
            for key, value
            in counter.most_common()
        ]

    # =========================================================
    # DASHBOARD
    # =========================================================

    def _build_dashboard(
        self,
        records,
        statistics,
    ):
        return {
            "title": (
                "Reporte de Atenciones"
            ),

            "period": {
                "date_from": (
                    statistics[
                        "date_from"
                    ]
                ),
                "date_to": (
                    statistics[
                        "date_to"
                    ]
                ),
            },

            "metrics": (
                self._build_metrics(
                    statistics
                )
            ),

            "charts": [
                self._build_daily_chart(
                    statistics
                ),

                self._build_procedures_chart(
                    statistics
                ),

                self._build_financiers_chart(
                    statistics
                ),

                self._build_priorities_chart(
                    statistics
                ),

                self._build_rooms_chart(
                    statistics
                ),
            ],

            "tables": [
                self._build_procedures_table(
                    records
                ),

                self._build_financiers_table(
                    records
                ),

                self._build_recent_records_table(
                    records
                ),
            ],

            "summary": (
                self._build_summary(
                    statistics
                )
            ),
        }

    # =========================================================
    # MÉTRICAS
    # =========================================================

    def _build_metrics(
        self,
        statistics,
    ):
        return [
            {
                "key": "appointments",
                "label": "Atenciones",
                "value": (
                    statistics[
                        "unique_appointments"
                    ]
                ),
                "format": "number",
            },

            {
                "key": "procedures",
                "label": "Procedimientos",
                "value": (
                    statistics[
                        "total_records"
                    ]
                ),
                "format": "number",
            },

            {
                "key": "patients",
                "label": "Pacientes",
                "value": (
                    statistics[
                        "unique_patients"
                    ]
                ),
                "format": "number",
            },

            {
                "key": "total_value",
                "label": "Valor total",
                "value": (
                    statistics[
                        "total_value"
                    ]
                ),
                "format": "currency",
            },

            {
                "key": "average_value",
                "label": "Ticket promedio",
                "value": (
                    statistics[
                        "average_value"
                    ]
                ),
                "format": "currency",
            },

            {
                "key": "average_wait",
                "label": (
                    "Espera promedio"
                ),
                "value": (
                    statistics[
                        "average_wait_minutes"
                    ]
                ),
                "format": "minutes",
            },

            {
                "key": "average_attention",
                "label": (
                    "Tiempo atención promedio"
                ),
                "value": (
                    statistics[
                        "average_attention_minutes"
                    ]
                ),
                "format": "minutes",
            },
        ]

    # =========================================================
    # GRÁFICOS
    # =========================================================

    def _build_daily_chart(
        self,
        statistics,
    ):
        return {
            "key": "daily_activity",

            "title": (
                "Procedimientos por día"
            ),

            "type": "line",

            "format": "number",

            "series": [
                {
                    "key": "count",
                    "label": (
                        "Procedimientos"
                    ),
                }
            ],

            "data": (
                statistics[
                    "daily_activity"
                ]
            ),
        }

    def _build_procedures_chart(
        self,
        statistics,
    ):
        return {
            "key": "procedures",

            "title": (
                "Procedimientos más realizados"
            ),

            "type": "bar",

            "format": "number",

            "data": [
                {
                    "label": item[
                        "procedure"
                    ],
                    "value": item[
                        "count"
                    ],
                }
                for item
                in statistics[
                    "procedures"
                ][:10]
            ],
        }

    def _build_financiers_chart(
        self,
        statistics,
    ):
        return {
            "key": "financiers",

            "title": (
                "Distribución por financiador"
            ),

            "type": "bar",

            "format": "number",

            "data": [
                {
                    "label": item[
                        "financier"
                    ],
                    "value": item[
                        "count"
                    ],
                }
                for item
                in statistics[
                    "financiers"
                ][:10]
            ],
        }

    def _build_priorities_chart(
        self,
        statistics,
    ):
        return {
            "key": "priorities",

            "title": (
                "Atenciones por prioridad"
            ),

            "type": "donut",

            "format": "number",

            "data": [
                {
                    "label": item[
                        "priority"
                    ],
                    "value": item[
                        "count"
                    ],
                }
                for item
                in statistics[
                    "priorities"
                ]
            ],
        }

    def _build_rooms_chart(
        self,
        statistics,
    ):
        return {
            "key": "rooms",

            "title": (
                "Actividad por sala"
            ),

            "type": "bar",

            "format": "number",

            "data": [
                {
                    "label": item[
                        "room"
                    ],
                    "value": item[
                        "count"
                    ],
                }
                for item
                in statistics[
                    "rooms"
                ][:10]
            ],
        }

    # =========================================================
    # TABLAS
    # =========================================================

    def _build_procedures_table(
        self,
        records,
    ):
        grouped = {}

        for record in records:

            procedure = (
                record[
                    "procedure"
                ]
                or "Sin procedimiento"
            )

            if procedure not in grouped:
                grouped[
                    procedure
                ] = {
                    "procedure": (
                        procedure
                    ),
                    "count": 0,
                    "total_value": 0,
                }

            grouped[
                procedure
            ]["count"] += 1

            grouped[
                procedure
            ]["total_value"] += (
                record["value"]
            )

        rows = sorted(
            grouped.values(),
            key=lambda item: (
                item[
                    "count"
                ]
            ),
            reverse=True,
        )

        return {
            "key": "procedures",

            "title": (
                "Resumen por procedimiento"
            ),

            "columns": [
                {
                    "key": "procedure",
                    "label": (
                        "Procedimiento"
                    ),
                    "format": "text",
                },
                {
                    "key": "count",
                    "label": "Cantidad",
                    "format": "number",
                },
                {
                    "key": "total_value",
                    "label": (
                        "Valor total"
                    ),
                    "format": "currency",
                },
            ],

            "rows": rows,
        }

    def _build_financiers_table(
        self,
        records,
    ):
        grouped = {}

        for record in records:

            financier = (
                record[
                    "financier"
                ]
                or "Sin financiador"
            )

            if financier not in grouped:
                grouped[
                    financier
                ] = {
                    "financier": (
                        financier
                    ),
                    "count": 0,
                    "total_value": 0,
                }

            grouped[
                financier
            ]["count"] += 1

            grouped[
                financier
            ]["total_value"] += (
                record["value"]
            )

        rows = sorted(
            grouped.values(),
            key=lambda item: (
                item[
                    "total_value"
                ]
            ),
            reverse=True,
        )

        return {
            "key": "financiers",

            "title": (
                "Resumen por financiador"
            ),

            "columns": [
                {
                    "key": "financier",
                    "label": "Financiador",
                    "format": "text",
                },
                {
                    "key": "count",
                    "label": "Procedimientos",
                    "format": "number",
                },
                {
                    "key": "total_value",
                    "label": "Valor total",
                    "format": "currency",
                },
            ],

            "rows": rows,
        }

    def _build_recent_records_table(
        self,
        records,
    ):
        rows = sorted(
            records,
            key=lambda item: (
                item[
                    "scheduled_datetime"
                ]
                or ""
            ),
            reverse=True,
        )[:100]

        return {
            "key": "recent_records",

            "title": (
                "Atenciones recientes"
            ),

            "columns": [
                {
                    "key": "scheduled_datetime",
                    "label": "Fecha y hora",
                    "format": "datetime",
                },
                {
                    "key": "patient",
                    "label": "Paciente",
                    "format": "text",
                },
                {
                    "key": "procedure",
                    "label": "Procedimiento",
                    "format": "text",
                },
                {
                    "key": "room",
                    "label": "Sala",
                    "format": "text",
                },
                {
                    "key": "priority",
                    "label": "Prioridad",
                    "format": "text",
                },
                {
                    "key": "provider",
                    "label": "Prestador",
                    "format": "text",
                },
                {
                    "key": "financier",
                    "label": "Financiador",
                    "format": "text",
                },
                {
                    "key": "value",
                    "label": "Valor",
                    "format": "currency",
                },
            ],

            "rows": rows,
        }

    # =========================================================
    # RESUMEN
    # =========================================================

    def _build_summary(
        self,
        statistics,
    ):
        if (
            statistics[
                "total_records"
            ]
            == 0
        ):
            return {
                "title": (
                    "Resumen del reporte"
                ),
                "text": (
                    "No se encontraron "
                    "procedimientos."
                ),
                "highlights": [],
            }

        top_procedure = (
            statistics[
                "procedures"
            ][0]
            if statistics[
                "procedures"
            ]
            else None
        )

        top_financier = (
            statistics[
                "financiers"
            ][0]
            if statistics[
                "financiers"
            ]
            else None
        )

        top_priority = (
            statistics[
                "priorities"
            ][0]
            if statistics[
                "priorities"
            ]
            else None
        )

        text = (
            f"El reporte contiene "
            f"{statistics['total_records']:,} "
            f"procedimientos asociados a "
            f"{statistics['unique_appointments']:,} "
            f"atenciones y "
            f"{statistics['unique_patients']:,} "
            f"pacientes. "
            f"El valor total registrado es "
            f"{self._format_currency(statistics['total_value'])}."
        ).replace(
            ",",
            ".",
        )

        if top_procedure:
            text += (
                f" El procedimiento más frecuente "
                f"es {top_procedure['procedure']} "
                f"con {top_procedure['count']} registros."
            )

        if top_financier:
            text += (
                f" El financiador con mayor cantidad "
                f"de procedimientos es "
                f"{top_financier['financier']}."
            )

        text += (
            f" El tiempo promedio entre llegada "
            f"e ingreso es de "
            f"{statistics['average_attention_minutes']} minutos."
        )

        return {
            "title": (
                "Resumen del reporte"
            ),

            "text": text,

            "highlights": [
                {
                    "key": (
                        "top_procedure"
                    ),
                    "label": (
                        "Procedimiento más frecuente"
                    ),
                    "value": (
                        top_procedure[
                            "procedure"
                        ]
                        if top_procedure
                        else None
                    ),
                },

                {
                    "key": (
                        "top_financier"
                    ),
                    "label": (
                        "Financiador principal"
                    ),
                    "value": (
                        top_financier[
                            "financier"
                        ]
                        if top_financier
                        else None
                    ),
                },

                {
                    "key": (
                        "top_priority"
                    ),
                    "label": (
                        "Prioridad más frecuente"
                    ),
                    "value": (
                        top_priority[
                            "priority"
                        ]
                        if top_priority
                        else None
                    ),
                },

                {
                    "key": (
                        "average_attention"
                    ),
                    "label": (
                        "Espera llegada / ingreso"
                    ),
                    "value": (
                        statistics[
                            "average_attention_minutes"
                        ]
                    ),
                    "format": "minutes",
                },
            ],
        }

    # =========================================================
    # FECHAS / HORAS
    # =========================================================

    def _normalize_datetime(
        self,
        value,
    ):
        if value in (
            None,
            "",
        ):
            return None

        if isinstance(
            value,
            datetime,
        ):
            return value.strftime(
                "%Y-%m-%dT%H:%M:%S"
            )

        text = str(
            value
        ).strip()

        formats = [
            "%d-%m-%Y %H:%M",
            "%d/%m/%Y %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
        ]

        for date_format in formats:
            try:
                parsed = datetime.strptime(
                    text,
                    date_format,
                )

                return parsed.strftime(
                    "%Y-%m-%dT%H:%M:%S"
                )

            except ValueError:
                continue

        return text

    def _normalize_time(
        self,
        value,
    ):
        if value in (
            None,
            "",
        ):
            return None

        text = str(
            value
        ).strip()

        # ExcelParser puede entregar datetime/time
        # serializado o simplemente HH:MM:SS.
        if "T" in text:
            return text.split(
                "T",
                1,
            )[1]

        return text

    def _extract_date(
        self,
        datetime_value,
    ):
        if not datetime_value:
            return None

        return str(
            datetime_value
        )[:10]

    def _extract_time(
        self,
        datetime_value,
    ):
        if not datetime_value:
            return None

        text = str(
            datetime_value
        )

        if "T" not in text:
            return None

        return text.split(
            "T",
            1,
        )[1]

    def _calculate_wait_minutes(
        self,
        scheduled_datetime,
        arrival_time,
    ):
        """
        Diferencia entre hora agendada y hora de llegada.

        Puede ser negativa si el paciente llegó antes.
        """

        scheduled_time = (
            self._extract_time(
                scheduled_datetime
            )
        )

        return self._time_difference_minutes(
            scheduled_time,
            arrival_time,
        )

    def _calculate_attention_minutes(
        self,
        arrival_time,
        entry_time,
    ):
        """
        Tiempo transcurrido entre llegada e ingreso.
        """

        return self._time_difference_minutes(
            arrival_time,
            entry_time,
        )

    def _time_difference_minutes(
        self,
        start_time,
        end_time,
    ):
        if (
            not start_time
            or not end_time
        ):
            return None

        start = self._parse_time(
            start_time
        )

        end = self._parse_time(
            end_time
        )

        if (
            start is None
            or end is None
        ):
            return None

        difference = (
            end
            - start
        ).total_seconds() / 60

        return round(
            difference,
            2,
        )

    def _parse_time(
        self,
        value,
    ):
        text = str(
            value
        ).strip()

        formats = [
            "%H:%M:%S",
            "%H:%M",
        ]

        for time_format in formats:
            try:
                return datetime.strptime(
                    text,
                    time_format,
                )

            except ValueError:
                continue

        return None

    # =========================================================
    # UTILIDADES
    # =========================================================

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

    def _get_value(
        self,
        row,
        index,
        default=None,
    ):
        if index is None:
            return default

        if index >= len(
            row
        ):
            return default

        value = row[
            index
        ]

        if value in (
            None,
            "",
        ):
            return default

        return value

    def _row_has_data(
        self,
        row,
    ):
        return any(
            value not in (
                None,
                "",
            )
            for value in row
        )

    def _text(
        self,
        value,
    ):
        if value in (
            None,
            "",
            "-",
        ):
            return ""

        return str(
            value
        ).strip()

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

        text = (
            text
            .replace("$", "")
            .replace(" ", "")
        )

        if (
            "." in text
            and "," not in text
        ):
            text = text.replace(
                ".",
                "",
            )

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

    def _format_currency(
        self,
        value,
    ):
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


reporte_parser = ReporteParser()