from apps.products.models import Product

def get_product_context():
    # Fetch a few products as a simple context
    products = Product.objects.filter(is_active=True).values('name', 'description', 'sku')[:10]
    
    context = "Aquí hay algunos productos disponibles en la plataforma:\n"
    for product in products:
        context += f"- Producto: {product['name']}, SKU: {product['sku']}, Descripción: {product['description']}\n"
        
    return context
