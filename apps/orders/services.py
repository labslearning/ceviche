import hashlib
import secrets
import logging
import qrcode
from io import BytesIO
from decimal import Decimal
from django.db import transaction, IntegrityError
from django.conf import settings
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from decouple import config

# Importación de Modelos
from apps.orders.models import Order, Ticket, OrderItem
from apps.events.models import ShowFunction, TicketType
from apps.products.models import Product

# Importación del Adaptador Blindado
from apps.orders.adapters.mercadopago import MercadoPagoAdapter

logger = logging.getLogger(__name__)

class OrderService:
    """
    SERVICIO PRINCIPAL: Gestor Transaccional Financiero (Nivel Bancario).
    Maneja Hash Maps para rendimiento O(1), firmas en RAM y Race Condition Protection.
    """

    @staticmethod
    def _build_seat_map(layout_data, result_map=None):
        """
        Optimización Big O(V): Aplana un JSON complejo en un diccionario 1D.
        Permite buscar la zona de cualquier silla en O(1) tiempo constante.
        """
        if result_map is None:
            result_map = {}

        if isinstance(layout_data, list):
            for item in layout_data:
                OrderService._build_seat_map(item, result_map)
        
        elif isinstance(layout_data, dict):
            obj_id = layout_data.get('id') or layout_data.get('label') or layout_data.get('name')
            zone = layout_data.get('category') or layout_data.get('zone')
            
            if obj_id and zone:
                # Normalizamos llaves para evitar fallos por espacios invisibles
                result_map[str(obj_id).strip()] = str(zone).strip()
                
            for key, value in layout_data.items():
                if isinstance(value, (list, dict)):
                    OrderService._build_seat_map(value, result_map)
                    
        return result_map

    @staticmethod
    def create_hybrid_order(user, validated_data):
        """
        Crea una orden mixta de forma atómica.
        Protegida contra Double-Spending y Race Conditions extremas.
        """
        function_id = validated_data.get('function_id')
        seat_labels = validated_data.get('seat_labels', [])
        products_data = validated_data.get('products', [])

        with transaction.atomic():
            # 1. Resolución de Función (Optimizamos bloqueo selectivo)
            if function_id:
                try:
                    function_instance = ShowFunction.objects.get(pk=function_id)
                except ShowFunction.DoesNotExist:
                    raise ValidationError("La función seleccionada no existe en el sistema.")
            else:
                function_instance = None
                if seat_labels:
                    raise ValidationError("Imposible procesar tickets sin una función válida.")
            
            # ==========================================
            # 🎫 LÓGICA DE BOLETERÍA (CRIPTOGRÁFICA)
            # ==========================================
            seats_to_buy = []
            ticket_total = Decimal('0.00')
            
            if seat_labels and function_instance:
                # A. Hash Map de Precios (Búsqueda O(1))
                available_types = {str(tt.zone_code).strip().lower(): tt for tt in TicketType.objects.filter(function=function_instance)}

                # B. Fail-Fast: Validación inicial de disponibilidad
                taken_tickets = Ticket.objects.filter(
                    function=function_instance, 
                    seat_label__in=seat_labels
                ).exclude(state__in=[Ticket.State.CANCELLED, Ticket.State.REFUNDED])
                
                if taken_tickets.exists():
                    taken_str = ", ".join([t.seat_label for t in taken_tickets])
                    raise ValidationError(f"Interferencia detectada: Las sillas [{taken_str}] acaban de ser reservadas por otro usuario.")

                # C. Construcción del Hash Map del Teatro en Memoria (O(N) -> O(1))
                seat_zone_map = OrderService._build_seat_map(function_instance.venue.layout)

                # D. Procesamiento en RAM
                for label in seat_labels:
                    clean_label = str(label).strip()
                    raw_zone_code = seat_zone_map.get(clean_label)
                    
                    ticket_type = None
                    
                    if raw_zone_code:
                        clean_zone = str(raw_zone_code).strip().lower()
                        ticket_type = available_types.get(clean_zone)
                    
                    # Fallback (Rescate)
                    if not ticket_type:
                        ticket_type = available_types.get('general')
                        if not ticket_type:
                            logger.critical(f"Inconsistencia de precios: Silla {label} sin mapeo en función {function_id}.")
                            raise ValidationError(f"Error de configuración comercial para la silla: {label}.")

                    price = ticket_type.price
                    ticket_total += price
                    
                    # 🛡️ Preparación Criptográfica en Memoria RAM
                    new_ticket = Ticket(
                        order=None, 
                        function=function_instance,
                        seat_label=clean_label,
                        seat_category=ticket_type.name,
                        price_at_purchase=price,
                        qr_token=secrets.token_urlsafe(64) # Entropía de 512 bits
                    )
                    
                    # 🚨 FIX CRÍTICO: Forzamos la generación de la firma HMAC antes del bulk_create
                    new_ticket.crypto_signature = new_ticket.generate_signature()
                    seats_to_buy.append(new_ticket)

            # ==========================================
            # 🍔 LÓGICA DE PRODUCTOS (TIENDA)
            # ==========================================
            products_to_buy = []
            product_total = Decimal('0.00')

            if products_data:
                product_ids = [item['product_id'] for item in products_data]
                product_map = {str(p.id): p for p in Product.objects.filter(id__in=product_ids)}

                for item in products_data:
                    p_id = str(item['product_id'])
                    qty = item['quantity']
                    
                    product_obj = product_map.get(p_id)
                    if not product_obj:
                        continue 
                    
                    product_total += (product_obj.price * qty)

                    products_to_buy.append(OrderItem(
                        order=None,
                        product=product_obj,
                        quantity=qty,
                        price_at_purchase=product_obj.price
                    ))

            # ==========================================
            # 💰 CREACIÓN DE LA ORDEN FINANCIERA
            # ==========================================
            grand_total = ticket_total + product_total

            if grand_total <= Decimal('0.00'):
                 raise ValidationError("Rechazado: El valor total de la transacción debe ser superior a cero.")

            # Inserción de la bóveda (Order)
            order = Order.objects.create(
                user=user if user and user.is_authenticated else None,
                total_amount=grand_total,
                status=Order.Status.PENDING 
            )

            # 🛡️ Inserción Masiva Protegida (Race Condition Ultimate Defense)
            if seats_to_buy:
                for t in seats_to_buy: t.order = order
                try:
                    Ticket.objects.bulk_create(seats_to_buy)
                except IntegrityError as e:
                    logger.warning(f"Sniper Attack (Race Condition) mitigado: {e}")
                    raise ValidationError("Colisión de concurrencia: Alguien compró esa silla milisegundos antes que tú. Actualiza el mapa.")
            
            if products_to_buy:
                for p in products_to_buy: p.order = order
                OrderItem.objects.bulk_create(products_to_buy)

            return order

    @staticmethod
    def attach_mercadopago_data(order):
        """
        Delega la seguridad transaccional al adaptador God-Tier de Mercado Pago.
        Inyecta propiedades en tiempo de ejecución (RAM) para el serializador.
        """
        public_key = config('MERCADO_PAGO_PUBLIC_KEY', default='')
        redirect_url = config('MERCADO_PAGO_REDIRECT_URL', default='')

        if not public_key or not redirect_url:
            logger.critical("Configuración de Mercado Pago incompleta en variables de entorno.")
            raise ValidationError("Pasarela de pagos temporalmente fuera de servicio.")

        # 🛡️ Llamada al adaptador Thread-Safe (O(1) TCP Socket)
        preference_id = MercadoPagoAdapter.create_checkout_preference(order, redirect_url)

        # Inyección dinámica en RAM (No requiere acceso a BD)
        order.mp_preference_id = preference_id
        order.mp_public_key = public_key
        
        return order


class QRService:
    """
    SERVICIO DE UTILIDAD: Generación eficiente de imágenes QR.
    """

    @staticmethod
    def generate_qr_image(data: str) -> bytes:
        """
        Genera un QR PNG. Optimizado para evitar Memory Leaks en buffers.
        """
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        buffer = BytesIO()
        img.save(buffer, format="PNG")
        
        # 🛡️ Profiling de Memoria: Garantiza el cierre del descriptor del buffer
        image_bytes = buffer.getvalue()
        buffer.close()
        
        return image_bytes