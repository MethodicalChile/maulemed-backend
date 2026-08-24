from django.apps import apps
from django.contrib.auth import get_user_model
from apps.common.scopes import apply_branch_scope, apply_organization_scope

# Definición de modelos expuestos al chat y su lógica de alcance
MODELS_TO_EXPOSE = {
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
    }
}

def get_chat_context(user):
    context = "Información disponible en la base de datos según tus permisos:\n"
    
    for model_name, config in MODELS_TO_EXPOSE.items():
        model_class = apps.get_model(config['model_path'])
        
        # Omitir filtro is_active si el modelo no lo tiene (caso de auth.User)
        if hasattr(model_class, 'is_active'):
            queryset = model_class.objects.filter(is_active=True)
        else:
            queryset = model_class.objects.all()
        
        # Aplicar el filtro de permisos según el usuario
        # IMPORTANTE: Asegurar que el filtro devuelva un QuerySet vacío si no hay permisos,
        # sin causar una consulta lenta o bloqueante.
        try:
            if config['field']:
                queryset = config['scope_func'](queryset, user, branch_field=config['field'])
            else:
                queryset = config['scope_func'](queryset, user)
        except Exception:
            queryset = queryset.none()
        
        # Serializar una muestra (limitada para no exceder el contexto)
        data = list(queryset.values(*config['fields_to_serialize'])[:5])
        
        if data:
            context += f"\nTabla {model_name} (muestra de registros permitidos):\n"
            for item in data:
                context += f"- {', '.join([f'{k}: {v}' for k, v in item.items()])}\n"
        else:
            context += f"\nNo tienes registros permitidos en la tabla {model_name}.\n"
            
    return context
