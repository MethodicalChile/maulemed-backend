from collections import Counter, defaultdict
from datetime import datetime
from typing import Any


class LogsParser:
    """
    Parser específico para:

        LOGS.xlsx

    Estructura esperada:

        ID
        Fecha
        Hora
        Usuario
        Tabla
        ID Manipulado
        Tipo de manipulación
        Descripción

    Construye:
    - logs normalizados
    - estadísticas generales
    - actividad por usuario
    - actividad por tabla
    - actividad por tipo
    - actividad por fecha
    - dashboard
    """

    DOCUMENT_TYPE = "logs"

    EXPECTED_HEADERS = {
        "ID",
        "FECHA",
        "HORA",
        "USUARIO",
        "TABLA",
        "ID MANIPULADO",
        "TIPO DE MANIPULACION",
        "DESCRIPCION",
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

        # LOGS actualmente viene en una sola hoja.
        sheet = sheets[0]

        rows = sheet.get(
            "rows",
            [],
        )

        header_index = (
            self._find_header_row(
                rows
            )
        )

        if header_index is None:
            return self._empty_result(
                message=(
                    "No se encontró la estructura "
                    "esperada del archivo LOGS."
                )
            )

        headers = rows[
            header_index
        ]

        column_map = self._build_column_map(
            headers
        )

        logs = self._extract_logs(
            rows=rows[
                header_index + 1:
            ],
            column_map=column_map,
        )

        statistics = self._build_statistics(
            logs
        )

        dashboard = self._build_dashboard(
            logs=logs,
            statistics=statistics,
        )

        return {
            "document_type": (
                self.DOCUMENT_TYPE
            ),

            "title": (
                "Logs del Sistema"
            ),

            "record_count": len(
                logs
            ),

            "logs": logs,

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
                "Logs del Sistema"
            ),

            "record_count": 0,

            "logs": [],

            "statistics": {
                "total_logs": 0,
                "unique_users": 0,
                "unique_tables": 0,
                "date_from": None,
                "date_to": None,
                "users": [],
                "tables": [],
                "manipulation_types": [],
                "daily_activity": [],
            },

            "dashboard": {
                "metrics": [],
                "charts": [],
                "tables": [],
                "summary": {
                    "title": (
                        "Resumen de actividad"
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
    # DETECCIÓN DE HEADER
    # =========================================================

    def _find_header_row(
        self,
        rows,
    ):
        """
        Busca específicamente la fila de encabezados
        del archivo LOGS.

        En el archivo actual:

            fila 1 -> Logs del Sistema
            fila 2 -> encabezados
        """

        for index, row in enumerate(
            rows[:20]
        ):
            normalized = {
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
                normalized
                & self.EXPECTED_HEADERS
            )

            # No exigimos las 8 columnas por si
            # cambia levemente una versión futura.
            if matches >= 6:
                return index

        return None

    def _build_column_map(
        self,
        headers,
    ):
        column_map = {}

        for index, header in enumerate(
            headers
        ):
            normalized = self._normalize_text(
                header
            )

            if normalized == "ID":
                column_map["id"] = index

            elif normalized == "FECHA":
                column_map["date"] = index

            elif normalized == "HORA":
                column_map["time"] = index

            elif normalized == "USUARIO":
                column_map["user"] = index

            elif normalized == "TABLA":
                column_map["table"] = index

            elif (
                normalized
                == "ID MANIPULADO"
            ):
                column_map[
                    "manipulated_id"
                ] = index

            elif (
                normalized
                == "TIPO DE MANIPULACION"
            ):
                column_map[
                    "manipulation_type"
                ] = index

            elif normalized == "DESCRIPCION":
                column_map[
                    "description"
                ] = index

        return column_map

    # =========================================================
    # EXTRACCIÓN
    # =========================================================

    def _extract_logs(
        self,
        rows,
        column_map,
    ):
        logs = []

        for row in rows:

            if not self._row_has_data(
                row
            ):
                continue

            log_id = self._get_value(
                row,
                column_map.get(
                    "id"
                ),
            )

            date_value = self._get_value(
                row,
                column_map.get(
                    "date"
                ),
            )

            time_value = self._get_value(
                row,
                column_map.get(
                    "time"
                ),
            )

            user = self._get_value(
                row,
                column_map.get(
                    "user"
                ),
            )

            table = self._get_value(
                row,
                column_map.get(
                    "table"
                ),
            )

            manipulated_id = (
                self._get_value(
                    row,
                    column_map.get(
                        "manipulated_id"
                    ),
                )
            )

            manipulation_type = (
                self._get_value(
                    row,
                    column_map.get(
                        "manipulation_type"
                    ),
                )
            )

            description = self._get_value(
                row,
                column_map.get(
                    "description"
                ),
            )

            normalized_date = (
                self._normalize_date(
                    date_value
                )
            )

            normalized_time = (
                self._normalize_time(
                    time_value
                )
            )

            logs.append(
                {
                    "id": log_id,

                    "date": (
                        normalized_date
                    ),

                    "time": (
                        normalized_time
                    ),

                    "datetime": (
                        self._build_datetime(
                            normalized_date,
                            normalized_time,
                        )
                    ),

                    "user": (
                        str(user).strip()
                        if user not in (
                            None,
                            "",
                        )
                        else ""
                    ),

                    "table": (
                        str(table).strip()
                        if table not in (
                            None,
                            "",
                        )
                        else ""
                    ),

                    "manipulated_id": (
                        manipulated_id
                    ),

                    "manipulation_type": (
                        str(
                            manipulation_type
                        ).strip()
                        if manipulation_type
                        not in (
                            None,
                            "",
                        )
                        else ""
                    ),

                    "description": (
                        str(
                            description
                        ).strip()
                        if description
                        not in (
                            None,
                            "",
                        )
                        else ""
                    ),

                    "event_category": (
                        self._detect_event_category(
                            description
                        )
                    ),
                }
            )

        return logs

    # =========================================================
    # CLASIFICACIÓN DE EVENTOS
    # =========================================================

    def _detect_event_category(
        self,
        description,
    ):
        """
        Categoriza las descripciones para entregar
        información más útil en el dashboard.

        No modifica el dato original.
        """

        text = self._normalize_text(
            description
        )

        if not text:
            return "OTRO"

        if (
            "AGENDAMIENTO PAGADO"
            in text
            or "ESTADO AGENDAMIENTO: PAGADO"
            in text
            or "CAMBIO DE ESTADO A: PAGADO"
            in text
        ):
            return "PAGO"

        if (
            "CAMBIO DE ESTADO"
            in text
        ):
            return "CAMBIO_ESTADO"

        if (
            "CAMBIO DE HORA"
            in text
            or "CAMBIO DE FECHA"
            in text
        ):
            return "CAMBIO_AGENDA"

        if (
            "AGENDAMIENTO ACTUALIZADO"
            in text
        ):
            return "ACTUALIZACION_AGENDA"

        if (
            "SEPARACION DE PROCED"
            in text
        ):
            return "PROCEDIMIENTO"

        if (
            "PACIENTE MODIFICADO"
            in text
        ):
            return "PACIENTE"

        if (
            "CLAVE TEMPORAL"
            in text
        ):
            return "SEGURIDAD"

        if (
            "CALENDAR_EXAM"
            in text
            or "CALENDAR EXAM"
            in text
        ):
            return "PRESTACION"

        return "OTRO"

    # =========================================================
    # ESTADÍSTICAS
    # =========================================================

    def _build_statistics(
        self,
        logs,
    ):
        if not logs:
            return {
                "total_logs": 0,
                "unique_users": 0,
                "unique_tables": 0,
                "date_from": None,
                "date_to": None,
                "users": [],
                "tables": [],
                "manipulation_types": [],
                "event_categories": [],
                "daily_activity": [],
            }

        user_counter = Counter(
            log["user"]
            for log in logs
            if log["user"]
        )

        table_counter = Counter(
            log["table"]
            for log in logs
            if log["table"]
        )

        manipulation_counter = Counter(
            log["manipulation_type"]
            for log in logs
            if log["manipulation_type"]
        )

        category_counter = Counter(
            log["event_category"]
            for log in logs
            if log["event_category"]
        )

        daily_counter = Counter(
            log["date"]
            for log in logs
            if log["date"]
        )

        dates = sorted(
            daily_counter.keys()
        )

        return {
            "total_logs": len(
                logs
            ),

            "unique_users": len(
                user_counter
            ),

            "unique_tables": len(
                table_counter
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

            "users": self._counter_to_list(
                user_counter,
                key_name="user",
            ),

            "tables": self._counter_to_list(
                table_counter,
                key_name="table",
            ),

            "manipulation_types": (
                self._counter_to_list(
                    manipulation_counter,
                    key_name="type",
                )
            ),

            "event_categories": (
                self._counter_to_list(
                    category_counter,
                    key_name="category",
                )
            ),

            "daily_activity": [
                {
                    "date": date_value,
                    "count": (
                        daily_counter[
                            date_value
                        ]
                    ),
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
        logs,
        statistics,
    ):
        return {
            "title": (
                "Actividad del Sistema"
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

                self._build_users_chart(
                    statistics
                ),

                self._build_tables_chart(
                    statistics
                ),

                self._build_categories_chart(
                    statistics
                ),
            ],

            "tables": [
                self._build_recent_logs_table(
                    logs
                ),

                self._build_users_table(
                    statistics
                ),

                self._build_tables_table(
                    statistics
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
        most_active_user = (
            statistics["users"][0]
            if statistics["users"]
            else None
        )

        most_modified_table = (
            statistics["tables"][0]
            if statistics["tables"]
            else None
        )

        return [
            {
                "key": "total_logs",
                "label": "Eventos registrados",
                "value": (
                    statistics[
                        "total_logs"
                    ]
                ),
                "format": "number",
            },

            {
                "key": "unique_users",
                "label": "Usuarios activos",
                "value": (
                    statistics[
                        "unique_users"
                    ]
                ),
                "format": "number",
            },

            {
                "key": "unique_tables",
                "label": "Tablas afectadas",
                "value": (
                    statistics[
                        "unique_tables"
                    ]
                ),
                "format": "number",
            },

            {
                "key": "most_active_user",
                "label": (
                    "Usuario más activo"
                ),
                "value": (
                    most_active_user[
                        "user"
                    ]
                    if most_active_user
                    else "-"
                ),
                "format": "text",
            },

            {
                "key": "most_modified_table",
                "label": (
                    "Tabla con mayor actividad"
                ),
                "value": (
                    most_modified_table[
                        "table"
                    ]
                    if most_modified_table
                    else "-"
                ),
                "format": "text",
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
                "Actividad por fecha"
            ),

            "type": "line",

            "format": "number",

            "series": [
                {
                    "key": "count",
                    "label": "Eventos",
                }
            ],

            "data": (
                statistics[
                    "daily_activity"
                ]
            ),
        }

    def _build_users_chart(
        self,
        statistics,
    ):
        data = [
            {
                "label": item[
                    "user"
                ],
                "value": item[
                    "count"
                ],
            }
            for item
            in statistics["users"][:10]
        ]

        return {
            "key": "users_activity",

            "title": (
                "Usuarios con mayor actividad"
            ),

            "type": "bar",

            "format": "number",

            "data": data,
        }

    def _build_tables_chart(
        self,
        statistics,
    ):
        data = [
            {
                "label": item[
                    "table"
                ],
                "value": item[
                    "count"
                ],
            }
            for item
            in statistics["tables"][:10]
        ]

        return {
            "key": "tables_activity",

            "title": (
                "Actividad por tabla"
            ),

            "type": "bar",

            "format": "number",

            "data": data,
        }

    def _build_categories_chart(
        self,
        statistics,
    ):
        data = [
            {
                "label": self._category_label(
                    item[
                        "category"
                    ]
                ),
                "value": item[
                    "count"
                ],
            }
            for item
            in statistics[
                "event_categories"
            ]
        ]

        return {
            "key": "event_categories",

            "title": (
                "Tipos de eventos detectados"
            ),

            "type": "donut",

            "format": "number",

            "data": data,
        }

    # =========================================================
    # TABLAS
    # =========================================================

    def _build_recent_logs_table(
        self,
        logs,
    ):
        """
        Entregamos los últimos 100 eventos para
        la tabla resumen del dashboard.

        La vista de datos extraídos seguirá teniendo
        acceso a todo el Excel original.
        """

        recent_logs = sorted(
            logs,
            key=lambda item: (
                item[
                    "datetime"
                ]
                or ""
            ),
            reverse=True,
        )[:100]

        return {
            "key": "recent_logs",

            "title": (
                "Actividad reciente"
            ),

            "columns": [
                {
                    "key": "date",
                    "label": "Fecha",
                    "format": "date",
                },

                {
                    "key": "time",
                    "label": "Hora",
                    "format": "text",
                },

                {
                    "key": "user",
                    "label": "Usuario",
                    "format": "text",
                },

                {
                    "key": "table",
                    "label": "Tabla",
                    "format": "text",
                },

                {
                    "key": "manipulation_type",
                    "label": "Acción",
                    "format": "text",
                },

                {
                    "key": "event_category",
                    "label": "Categoría",
                    "format": "text",
                },

                {
                    "key": "description",
                    "label": "Descripción",
                    "format": "text",
                },
            ],

            "rows": recent_logs,
        }

    def _build_users_table(
        self,
        statistics,
    ):
        rows = [
            {
                "user": item[
                    "user"
                ],
                "events": item[
                    "count"
                ],
            }
            for item
            in statistics["users"]
        ]

        return {
            "key": "users",

            "title": (
                "Actividad por usuario"
            ),

            "columns": [
                {
                    "key": "user",
                    "label": "Usuario",
                    "format": "text",
                },
                {
                    "key": "events",
                    "label": "Eventos",
                    "format": "number",
                },
            ],

            "rows": rows,
        }

    def _build_tables_table(
        self,
        statistics,
    ):
        rows = [
            {
                "table": item[
                    "table"
                ],
                "events": item[
                    "count"
                ],
            }
            for item
            in statistics["tables"]
        ]

        return {
            "key": "tables",

            "title": (
                "Actividad por tabla"
            ),

            "columns": [
                {
                    "key": "table",
                    "label": "Tabla",
                    "format": "text",
                },
                {
                    "key": "events",
                    "label": "Eventos",
                    "format": "number",
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
        total = statistics[
            "total_logs"
        ]

        if total == 0:
            return {
                "title": (
                    "Resumen de actividad"
                ),
                "text": (
                    "No se encontraron eventos "
                    "en el archivo."
                ),
                "highlights": [],
            }

        top_user = (
            statistics["users"][0]
            if statistics["users"]
            else None
        )

        top_table = (
            statistics["tables"][0]
            if statistics["tables"]
            else None
        )

        top_category = (
            statistics[
                "event_categories"
            ][0]
            if statistics[
                "event_categories"
            ]
            else None
        )

        text = (
            f"Se analizaron {total:,} eventos "
            f"registrados por "
            f"{statistics['unique_users']} usuarios "
            f"sobre {statistics['unique_tables']} "
            f"tablas del sistema."
        ).replace(
            ",",
            ".",
        )

        if (
            statistics["date_from"]
            and statistics["date_to"]
        ):
            text += (
                f" El período analizado va desde "
                f"{statistics['date_from']} hasta "
                f"{statistics['date_to']}."
            )

        if top_user:
            text += (
                f" El usuario con mayor actividad "
                f"es {top_user['user']} con "
                f"{top_user['count']:,} eventos."
            ).replace(
                ",",
                ".",
            )

        if top_table:
            text += (
                f" La tabla con mayor número de "
                f"interacciones es "
                f"{top_table['table']} con "
                f"{top_table['count']:,} eventos."
            ).replace(
                ",",
                ".",
            )

        return {
            "title": (
                "Resumen de actividad"
            ),

            "text": text,

            "highlights": [
                {
                    "key": "top_user",
                    "label": (
                        "Usuario más activo"
                    ),
                    "value": (
                        top_user["user"]
                        if top_user
                        else None
                    ),
                },

                {
                    "key": "top_user_events",
                    "label": (
                        "Eventos del usuario"
                    ),
                    "value": (
                        top_user["count"]
                        if top_user
                        else 0
                    ),
                    "format": "number",
                },

                {
                    "key": "top_table",
                    "label": (
                        "Tabla más modificada"
                    ),
                    "value": (
                        top_table["table"]
                        if top_table
                        else None
                    ),
                },

                {
                    "key": "top_category",
                    "label": (
                        "Categoría más frecuente"
                    ),
                    "value": (
                        self._category_label(
                            top_category[
                                "category"
                            ]
                        )
                        if top_category
                        else None
                    ),
                },
            ],
        }

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

    def _normalize_date(
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
            return value.date().isoformat()

        text = str(
            value
        ).strip()

        # ExcelParser normalmente ya convierte
        # datetime a ISO.
        if len(text) >= 10:
            candidate = text[:10]

            try:
                return datetime.strptime(
                    candidate,
                    "%Y-%m-%d",
                ).date().isoformat()

            except ValueError:
                pass

        formats = [
            "%d-%m-%Y",
            "%d/%m/%Y",
        ]

        for date_format in formats:
            try:
                return datetime.strptime(
                    text,
                    date_format,
                ).date().isoformat()

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

        if isinstance(
            value,
            datetime,
        ):
            return value.strftime(
                "%H:%M:%S"
            )

        return str(
            value
        ).strip()

    def _build_datetime(
        self,
        date_value,
        time_value,
    ):
        if not date_value:
            return None

        if not time_value:
            return date_value

        return (
            f"{date_value}T"
            f"{time_value}"
        )

    def _category_label(
        self,
        category,
    ):
        labels = {
            "PAGO": "Pagos",
            "CAMBIO_ESTADO": (
                "Cambios de estado"
            ),
            "CAMBIO_AGENDA": (
                "Cambios de agenda"
            ),
            "ACTUALIZACION_AGENDA": (
                "Actualizaciones de agenda"
            ),
            "PROCEDIMIENTO": (
                "Procedimientos"
            ),
            "PACIENTE": (
                "Pacientes"
            ),
            "SEGURIDAD": (
                "Seguridad"
            ),
            "PRESTACION": (
                "Prestaciones"
            ),
            "OTRO": "Otros",
        }

        return labels.get(
            category,
            category,
        )


logs_parser = LogsParser()