import re
from decimal import Decimal
from rest_framework import serializers
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _
from apps.orders.models import Order, Ticket, OrderItem
from apps.products.models import Product

# ==============================================================================
# 📥 1. SERIALIZADORES DE ENTRADA (ESCUDO ZERO-TRUST / GRADO MILITAR)
# ==============================================================================

class ProductInputSerializer(serializers.Serializer):
    """
    Recibe productos adicionales.
    🛡️ Anti-Hoarding: Límite estricto de compra por transacción para evitar que
    un bot vacíe el inventario.
    """
    product_id = serializers.UUIDField(required=True)
    quantity = serializers.IntegerField(
        required=True,
        validators=[
            MinValueValidator(1, message="La cantidad no puede ser menor a 1."),
            MaxValueValidator(50, message="Violación de Límite: Máximo 50 unidades por ítem.")
        ]
    )

class PayerIdentificationSerializer(serializers.Serializer):
    """Estructura de identificación exigida por Mercado Pago"""
    type = serializers.CharField(required=False, allow_blank=True, max_length=20)
    number = serializers.CharField(required=False, allow_blank=True, max_length=50)

class PayerSerializer(serializers.Serializer):
    """Datos encriptados del pagador"""
    email = serializers.EmailField(required=True)
    identification = PayerIdentificationSerializer(required=False)

class PaymentBrickInputSerializer(serializers.Serializer):
    """
    🛡️ CONTRATO MAESTRO DE COMPRA (MERCADO PAGO BRICKS):
    Inspección Profunda de Paquetes (DPI) en capa de aplicación.
    """
    # --- Credenciales y Datos del Banco ---
    token = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=255)
    payment_method_id = serializers.CharField(required=True, max_length=100)
    installments = serializers.IntegerField(
        required=False, 
        default=1,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(36) # Previene inyección de plazos absurdos
        ]
    )
    
    # 🛡️ Protección de Overflow Financiero: Tope transaccional ($99,999,999.99)
    transaction_amount = serializers.DecimalField(
        required=True,
        max_digits=10, 
        decimal_places=2,
        min_value=Decimal('100.00'), # Cobro mínimo para evitar ataques de micro-testing de tarjetas
        max_value=Decimal('99999999.99') 
    )
    payer = PayerSerializer(required=True)
    
    # --- Datos del Dominio (El Evento) ---
    function_id = serializers.UUIDField(required=True)
    seat_labels = serializers.ListField(
        child=serializers.CharField(max_length=50),
        allow_empty=False, 
        required=True,
        max_length=10 # 🛡️ Límite absoluto impuesto a nivel de estructura de datos
    )
    products = ProductInputSerializer(many=True, required=False, default=list, max_length=20)

    def validate_seat_labels(self, value):
        """
        🛡️ SANITIZACIÓN ESTRICTA DE ETIQUETAS:
        Evita inyección SQL secundaria o XSS si estos labels se usan luego.
        Solo permite letras, números y guiones medios (Ej: "A-12", "VIP-1").
        """
        pattern = re.compile(r'^[A-Za-z0-9\-]+$')
        for label in value:
            if not pattern.match(label):
                raise serializers.ValidationError(
                    f"Violación de Integridad: La silla '{label}' contiene caracteres no permitidos."
                )
        return value

    def validate(self, data):
        """🛡️ REGLAS DE NEGOCIO ESTRICTAS (Validación Cruzada)"""
        seat_labels = data.get('seat_labels', [])
        
        # Validación de duplicados (Anti-Tampering)
        if len(seat_labels) != len(set(seat_labels)):
            raise serializers.ValidationError("Violación Lógica: El carrito contiene sillas duplicadas.")
            
        return data


# ==============================================================================
# 📤 2. SERIALIZADORES DE SALIDA (PRESENTACIÓN SEGURA & ANTI-REVERSE ENGINEERING)
# ==============================================================================

class TicketDetailSerializer(serializers.ModelSerializer):
    """Detalle inmutable de la boleta para el cliente."""
    class Meta:
        model = Ticket
        fields = [
            'id', 
            'seat_label', 
            'seat_category', 
            'price_at_purchase', 
            'qr_token',
            'state'
        ]

class OrderItemDetailSerializer(serializers.ModelSerializer):
    """Detalle de productos adicionales."""
    product_name = serializers.CharField(source='product.name', read_only=True)
    total_line = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ['product_name', 'quantity', 'price_at_purchase', 'discount_applied', 'total_line']

class OrderSummarySerializer(serializers.ModelSerializer):
    """Resumen de compra estandarizado. Protege variables internas."""
    tickets = TicketDetailSerializer(many=True, read_only=True)
    items = OrderItemDetailSerializer(many=True, read_only=True) 
    reference = serializers.CharField(source='wompi_reference', read_only=True) 

    class Meta:
        model = Order
        fields = [
            'id', 
            'reference',
            'status', 
            'currency',
            'total_amount', 
            'tax_amount',
            'fee_amount',
            'amount_paid',
            'created_at',
            'tickets', 
            'items'
        ]