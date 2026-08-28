from django.apps import apps
from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.utils import timezone
from apps.common.scopes import apply_branch_scope, apply_organization_scope
from apps.common.services.chat_dashboard_summary import get_dashboard_summary_data

# Definición de modelos expuestos al chat y su lógica de alcance
MODELS_TO_EXPOSE = {
    # ... (Keep existing definitions)
    'Product': {
        'model_path': 'products.Product',
        'scope_func': apply_branch_scope,
        'field': 'branch_products__branch',
        'fields_to_serialize': ['name', 'description', 'sku']
    },
    'Branch': {
        'model_path': 'organizations.Branch',
        'scope_func': apply_branch_scope,
        'field': 'self',
        'fields_to_serialize': ['name', 'code', 'city']
    },
    'Supplier': {
        'model_path': 'suppliers.Supplier',
        'scope_func': lambda qs, user, **kwargs: qs, # Ajustar scope si es necesario
        'field': None,
        'fields_to_serialize': ['name', 'rut', 'email']
    },
    'User': {
        'model_path': 'auth.User',
        'scope_func': lambda qs, user, **kwargs: qs if user.is_superuser else qs.none(),
        'field': None,
        'fields_to_serialize': ['username', 'first_name', 'last_name', 'email']
    },
    'PurchaseOrder': {
        'model_path': 'purchasing.PurchaseOrder',
        'scope_func': apply_branch_scope,
        'field': 'branch',
        'fields_to_serialize': ['order_number', 'status', 'total_amount', 'supplier__name']
    },
    'SupplyRequest': {
        'model_path': 'purchasing.SupplyRequest',
        'scope_func': apply_branch_scope,
        'field': 'branch',
        'fields_to_serialize': ['status', 'period_year', 'period_month', 'comments']
    },
    'SupplierInvoice': {
        'model_path': 'finance.SupplierInvoice',
        'scope_func': apply_branch_scope,
        'field': 'branch',
        'fields_to_serialize': ['invoice_number', 'status', 'total_amount', 'due_date']
    },
    'Budget': {
        'model_path': 'finance.Budget',
        'scope_func': apply_branch_scope,
        'field': 'branch',
        'fields_to_serialize': ['period_year', 'period_month', 'budget_amount', 'consumed_amount']
    },
    'RevenueEntry': {
        'model_path': 'revenue.RevenueEntry',
        'scope_func': apply_branch_scope,
        'field': 'branch',
        'fields_to_serialize': ['service_date', 'procedure_name', 'net_amount'],
        'summary_func': lambda qs: qs.values('service_date__year', 'service_date__month').annotate(total=Sum('net_amount'))
    },
    'AccountReceivable': {
        'model_path': 'revenue.AccountReceivable',
        'scope_func': apply_branch_scope,
        'field': 'legal_entity', # Using legal_entity as it's the direct scope for AR
        'fields_to_serialize': ['period_year', 'period_month', 'billed_amount', 'status'],
        'summary_func': lambda qs: qs.values('period_year', 'period_month').annotate(total=Sum('billed_amount'))
    },
    'InventoryMovement': {
        'model_path': 'inventory.InventoryMovement',
        'scope_func': apply_branch_scope,
        'field': 'warehouse_origin__branch',
        'fields_to_serialize': ['product__name', 'quantity', 'created_at'],
        'summary_func': lambda qs: qs.filter(movement_type='EGRESO_CONSUMO')
                                      .values('product__name', 'created_at__year', 'created_at__month')
                                      .annotate(total=Sum('quantity'))
    }
}

def get_chat_context(user):
    # Obtener KPIs exactos del dashboard
    dashboard_data = get_dashboard_summary_data(user)
    
    context = "Indicadores clave del dashboard (datos exactos):\n"
    for kpi, value in dashboard_data['kpis'].items():
        context += f"- {kpi.replace('_', ' ').capitalize()}: {value}\n"
    
    context += "\nInformación detallada disponible en la base de datos según tus permisos:\n"
    
    for model_name, config in MODELS_TO_EXPOSE.items():
        # ... (Keep existing queryset loop)
        model_class = apps.get_model(config['model_path'])
        
        # Omitir filtro is_active si el modelo no lo tiene (caso de auth.User)
        if hasattr(model_class, 'is_active'):
            queryset = model_class.objects.filter(is_active=True)
        else:
            queryset = model_class.objects.all()
        
        # Aplicar el filtro de permisos según el usuario
        try:
            if config['field']:
                queryset = config['scope_func'](queryset, user, branch_field=config['field'])
            else:
                queryset = config['scope_func'](queryset, user)
        except Exception:
            queryset = queryset.none()
        
        # Añadir resumen si existe
        if 'summary_func' in config:
            # Obtener resumen completo ordenado por fecha
            qs_summary = config['summary_func'](queryset)
            
            # Ordenar específicamente si es RevenueEntry, AccountReceivable o InventoryMovement
            if model_name == 'RevenueEntry':
                summary = list(qs_summary.order_by('-service_date__year', '-service_date__month'))
            elif model_name == 'InventoryMovement':
                summary = list(qs_summary.order_by('-created_at__year', '-created_at__month'))
            else:
                summary = list(qs_summary.order_by('-period_year', '-period_month'))
                
            if summary:
                context += f"\nResumen completo de {model_name} (totales por periodo):\n"
                for item in summary:
                    # Ajustar según las keys de agrupamiento
                    if 'service_date__year' in item:
                        context += f"- Año: {item['service_date__year']}, Mes: {item['service_date__month']}, Total: {item['total']}\n"
                    elif 'created_at__year' in item:
                        context += f"- Año: {item['created_at__year']}, Mes: {item['created_at__month']}, Producto: {item['product__name']}, Total: {item['total']}\n"
                    else:
                        context += f"- Año: {item.get('period_year')}, Mes: {item.get('period_month')}, Total: {item.get('total')}\n"

        # Serializar una muestra (limitada para no exceder el contexto)
        data = list(queryset.values(*config['fields_to_serialize'])[:5])
        
        if data:
            context += f"\nTabla {model_name} (muestra de registros permitidos):\n"
            for item in data:
                context += f"- {', '.join([f'{k}: {v}' for k, v in item.items()])}\n"
        else:
            context += f"\nNo tienes registros permitidos en la tabla {model_name}.\n"
            
    return context
