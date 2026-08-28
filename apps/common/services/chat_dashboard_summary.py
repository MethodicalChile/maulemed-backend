from django.utils import timezone
from apps.dashboard import executive as ex

def get_dashboard_summary_data(user):
    # Definir el periodo (últimos 12 meses para el tablero ejecutivo)
    months = ex.month_range(12)
    
    # Obtener los bloques de datos desde el servicio ejecutivo del dashboard
    revenue = ex.revenue_blocks(user, months)
    budget = ex.budget_block(user)
    purchasing = ex.purchasing_block(user, months)
    inventory = ex.inventory_block(user)
    
    # Extraer los KPIs de titular
    series = revenue.pop("_series")
    
    def actual_y_previo(clave):
        serie = series[clave]
        actual = serie[-1] if serie else ex.ZERO
        previo = serie[-2] if len(serie) > 1 else None
        return actual, previo
    
    ingreso_actual, _ = actual_y_previo("revenue")
    caja_actual, _ = actual_y_previo("collected")
    deuda = revenue.pop("_receivable_total")
    
    # Estructurar los datos para el chatbot
    return {
        "kpis": {
            "ingreso_devengado": float(ingreso_actual),
            "recaudado_en_caja": float(caja_actual),
            "deuda_institucional": deuda,
            "ejecucion_presupuestaria": budget["execution_pct"],
            "compras_extraordinarias_pct": purchasing["extraordinary_pct"],
            "ordenes_por_recibir": purchasing["pending_receipts"],
            "productos_bajo_umbral": inventory["low_stock_count"],
        }
    }
