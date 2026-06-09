from rest_framework import serializers
from apps.orders.models import Order, Ticket, OrderItem
from apps.products.models import Product

# ==========================================
# 📥 SERIALIZADORES DE ENTRADA (INPUT)
# ==========================================

class ProductInputSerializer(serializers.Serializer):
    """
    Recibe productos de la tienda (combos, comida, merch).
    """
    product_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)

class CreateOrderSerializer(serializers.Serializer):
    """
    Contrato maestro de compra.
    Maneja la lógica mixta: Boletas (Texto) + Productos.
    """
    function_id = serializers.UUIDField(required=True)
    
    # ✅ CORRECCIÓN: Agregamos este campo que FALTABA.
    # Acepta la lista de nombres de sillas que envía el mapa (Ej: ["A-1", "B-2"])
    seat_labels = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list
    )
    
    # Mantenemos products por si acaso vendes comida después
    products = ProductInputSerializer(many=True, required=False, default=list)

    def validate(self, data):
        """
        🛡️ VALIDACIÓN DE NEGOCIO:
        Evita que se creen órdenes vacías.
        """
        seat_labels = data.get('seat_labels', [])
        products = data.get('products', [])

        # Si no hay ni sillas (seat_labels) ni productos, rechazamos la compra.
        # Antes fallaba porque buscaba 'tickets' que no existía.
        if not seat_labels and not products:
            raise serializers.ValidationError(
                "El carrito de compras no puede estar vacío. Selecciona sillas o productos."
            )
        
        return data

# ==========================================
# 📤 SERIALIZADORES DE SALIDA (OUTPUT)
# ==========================================

class TicketDetailSerializer(serializers.ModelSerializer):
    """Detalle de boleta para el resumen"""
    # Leemos la etiqueta directamente del Ticket (campo seat_label)
    seat_label = serializers.CharField(read_only=True)
    
    # Calculamos la categoría visualmente (VIP/General) basada en el precio
    # Esto evita errores si la relación 'seat' no existe.
    category_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Ticket
        fields = ['id', 'seat_label', 'category_name', 'price_at_purchase', 'qr_token']

    def get_category_name(self, obj):
        # Lógica simple: Si pagó más de 40.000, asumimos VIP para mostrar en el recibo
        if obj.price_at_purchase and obj.price_at_purchase > 40000:
            return "VIP"
        return "General"

class OrderItemDetailSerializer(serializers.ModelSerializer):
    """Detalle de comida para el resumen"""
    product_name = serializers.CharField(source='product.name', read_only=True)
    total_line = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = ['product_name', 'quantity', 'price_at_purchase', 'total_line']

    def get_total_line(self, obj):
        # Calcula el total de la línea al vuelo
        return obj.price_at_purchase * obj.quantity

class OrderSummarySerializer(serializers.ModelSerializer):
    """
    Resumen COMPLETO para el usuario.
    Incluye los datos de seguridad requeridos por Wompi.
    """
    # Nested Serializers: Inyectamos el detalle visual
    tickets = TicketDetailSerializer(many=True, read_only=True)
    items = OrderItemDetailSerializer(many=True, read_only=True) 

    # 🔐 CAMPOS CRÍTICOS PARA WOMPI (Inyectados por la Vista)
    wompi_signature = serializers.CharField(read_only=True)
    wompi_public_key = serializers.CharField(read_only=True)
    amount_in_cents = serializers.IntegerField(read_only=True)
    wompi_currency = serializers.CharField(default="COP", read_only=True)
    
    # Campo extra para referencia
    reference = serializers.CharField(source='wompi_reference', read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 
            'reference',
            'wompi_reference', 
            'total_amount', 
            'amount_in_cents', # Necesario para el widget
            'wompi_signature', # Necesario para el widget
            'wompi_public_key',# Necesario para el widget
            'wompi_currency',
            'status', 
            'created_at',
            'tickets', 
            'items'
        ]