import hashlib
import secrets
import logging
import qrcode
from io import BytesIO
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Any

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
    🚀 SERVICIO PRINCIPAL: Gestor Transaccional Financiero (God-Tier / Nivel Bancario).
    Maneja Hash Maps para rendimiento O(1), firmas criptográficas en RAM y mitigación 
    avanzada de Race Conditions y DoS.
    """

    @staticmethod
    def _build_seat_map(layout_data: Any) -> Dict[str, str]:
        """
        🛡️ ANTI-STACK OVERFLOW SHIELD (Algoritmo Iterativo DFS).
        Aplana un JSON complejo en un diccionario 1D. Reemplaza la recursividad 
        por una pila iterativa para evitar ataques de desbordamiento de memoria (OOM).
        Rendimiento: O(V) en tiempo, O(V) en espacio.
        """
        result_map: Dict[str, str] = {}
        if not layout_data:
            return result_map

        stack = [layout_data]
        
        while stack:
            current = stack.pop()
            
            if isinstance(current, list):
                # Desacopla la lista en memoria y la añade a la pila
                stack.extend(current)
                
            elif isinstance(current, dict):
                obj_id = current.get('id') or current.get('label') or current.get('name')
                zone = current.get('category') or current.get('zone')
                
                if obj_id and zone:
                    result_map[str(obj_id).strip()] = str(zone).strip()
                    
                # Extrae los valores anidados dinámicamente sin recursión
                for key, value in current.items():
                    if isinstance(value, (list, dict)):
                        stack.append(value)
                        
        return result_map

    @staticmethod
    def create_hybrid_order(user, validated_data: dict) -> Order:
        """
        Crea una orden mixta de forma atómica.
        Protegida contra Double-Spending, DDoS y Race Conditions extremas.
        """
        function_id = validated_data.get('function_id')
        seat_labels = validated_data.get('seat_labels', [])
        products_data = validated_data.get('products', [])

        # 🛡️ HARD LIMIT: Prevención de ataques de agotamiento de DB (DDoS)
        if isinstance(seat_labels, list) and len(seat_labels) > 20:
            logger.warning(f"🚨 [DDoS MITIGADO] Intento de compra masiva superado: {len(seat_labels)} sillas. IP/User: {user}")
            raise ValidationError("Por seguridad, el límite máximo es de 20 tickets por transacción.")

        with transaction.atomic():
            # 1. Resolución de Función (Optimizamos bloqueo selectivo)
            function_instance = None
            if function_id:
                try:
                    function_instance = ShowFunction.objects.get(pk=function_id)
                except ShowFunction.DoesNotExist:
                    raise ValidationError("Violación de Integridad: La función seleccionada no existe.")
            elif seat_labels:
                raise ValidationError("Imposible procesar tickets sin una función válida en el nodo.")
            
            # ==========================================
            # 🎫 LÓGICA DE BOLETERÍA (CRIPTOGRÁFICA)
            # ==========================================
            seats_to_buy = []
            ticket_total = Decimal('0.00')
            
            if seat_labels and function_instance:
                # A. Hash Map de Precios en RAM (Búsqueda Constante O(1))
                available_types = {str(tt.zone_code).strip().lower(): tt for tt in TicketType.objects.filter(function=function_instance)}

                # B. Fail-Fast: Validación inicial de disponibilidad
                # 🚀 HOTFIX APLICADO: CANCELLED ha sido erradicado, operamos con VOIDED.
                taken_tickets = Ticket.objects.filter(
                    function=function_instance, 
                    seat_label__in=seat_labels
                ).exclude(state__in=[Ticket.State.VOIDED, Ticket.State.REFUNDED])
                
                if taken_tickets.exists():
                    taken_str = ", ".join([t.seat_label for t in taken_tickets])
                    raise ValidationError(f"Interferencia detectada: Las sillas [{taken_str}] acaban de ser aseguradas por otro nodo.")

                # C. Construcción Topológica Segura
                seat_zone_map = OrderService._build_seat_map(function_instance.venue.layout)

                # D. Procesamiento Aislado
                for label in seat_labels:
                    clean_label = str(label).strip()
                    raw_zone_code = seat_zone_map.get(clean_label)
                    
                    ticket_type = None
                    
                    if raw_zone_code:
                        clean_zone = str(raw_zone_code).strip().lower()
                        ticket_type = available_types.get(clean_zone)
                    
                    # Fallback de Rescate Comercial
                    if not ticket_type:
                        ticket_type = available_types.get('general')
                        if not ticket_type:
                            logger.critical(f"Inconsistencia Físico-Digital: Silla {clean_label} carece de valor financiero.")
                            raise ValidationError(f"Anomalía comercial en la silla: {clean_label}.")

                    # Conversión FinTech estricta
                    price = Decimal(str(ticket_type.price))
                    ticket_total += price
                    
                    # 🛡️ Preparación Criptográfica (512 bits entropía)
                    new_ticket = Ticket(
                        order=None, 
                        function=function_instance,
                        seat_label=clean_label,
                        seat_category=ticket_type.name,
                        price_at_purchase=price,
                        qr_token=secrets.token_urlsafe(64) 
                    )
                    
                    # Firmware criptográfico embebido antes de volcar a base de datos
                    new_ticket.crypto_signature = new_ticket.generate_signature()
                    seats_to_buy.append(new_ticket)

            # ==========================================
            # 🍔 LÓGICA DE PRODUCTOS E-COMMERCE
            # ==========================================
            products_to_buy = []
            product_total = Decimal('0.00')

            if products_data:
                product_ids = [str(item['product_id']) for item in products_data if 'product_id' in item]
                product_map = {str(p.id): p for p in Product.objects.filter(id__in=product_ids)}

                for item in products_data:
                    p_id = str(item.get('product_id', ''))
                    
                    try:
                        qty = int(item.get('quantity', 0))
                        if qty <= 0: continue
                    except (ValueError, TypeError):
                        continue
                    
                    product_obj = product_map.get(p_id)
                    if not product_obj:
                        continue 
                    
                    base_price = Decimal(str(product_obj.price))
                    product_total += (base_price * qty)

                    products_to_buy.append(OrderItem(
                        order=None,
                        product=product_obj,
                        quantity=qty,
                        price_at_purchase=base_price
                    ))

            # ==========================================
            # 💰 CREACIÓN DE LA ORDEN FINANCIERA (BÓVEDA)
            # ==========================================
            grand_total = ticket_total + product_total

            if grand_total <= Decimal('0.00'):
                 raise ValidationError("Rechazado: Transacción estéril. El valor total debe ser superior a cero.")

            # Inserción Maestra
            order = Order.objects.create(
                user=user if user and user.is_authenticated else None,
                total_amount=grand_total,
                status=Order.Status.PENDING 
            )

            # 🛡️ BULK INSERT CON PROTECCIÓN DE INTEGRIDAD Y LOCKEO DE CARRERA
            if seats_to_buy:
                for t in seats_to_buy: 
                    t.order = order
                try:
                    # Ignore_conflicts=False asegura que si hay choque en el unique_together, Postgres aborte.
                    Ticket.objects.bulk_create(seats_to_buy, ignore_conflicts=False)
                except IntegrityError as e:
                    logger.warning(f"🚨 [RACE CONDITION NEUTRALIZADA] Choque de inserción concurrente detectado.")
                    raise ValidationError("Colisión de concurrencia: Otro usuario aseguró esta silla milisegundos antes que tú. Actualiza el mapa.")
            
            if products_to_buy:
                for p in products_to_buy: 
                    p.order = order
                OrderItem.objects.bulk_create(products_to_buy)

            return order

    @staticmethod
    def attach_mercadopago_data(order: Order) -> Order:
        """
        Delega la seguridad transaccional al adaptador de Mercado Pago.
        Maneja fallos externos para que la orden no quede huérfana en un 500 silencioso.
        """
        public_key = config('MERCADO_PAGO_PUBLIC_KEY', default='')
        redirect_url = config('MERCADO_PAGO_REDIRECT_URL', default='')

        if not public_key or not redirect_url:
            logger.critical("Configuración de Mercado Pago incompleta (Faltan ENVs).")
            raise ValidationError("Pasarela de pagos temporalmente desconectada de la matriz.")

        try:
            # 🛡️ Llamada al adaptador Thread-Safe
            preference_id = MercadoPagoAdapter.create_checkout_preference(order, redirect_url)
        except Exception as e:
            logger.error(f"Falla crítica contactando SDK de MercadoPago: {str(e)}")
            raise ValidationError("Error estableciendo túnel seguro con la entidad bancaria. Intenta en unos minutos.")

        # Inyección dinámica en RAM
        order.mp_preference_id = preference_id
        order.mp_public_key = public_key
        
        return order


class QRService:
    """
    SERVICIO DE UTILIDAD: Generación eficiente de activos binarios (QR).
    """

    @staticmethod
    def generate_qr_image(data: str) -> bytes:
        """
        🚀 MEMORY-LEAK PROOF ENGINE:
        Genera un código QR y garantiza la limpieza de la pila de memoria del Garbage Collector
        utilizando manejadores de contexto (with) para el descriptor del buffer.
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

        # 🛡️ Context Manager: Asegura la liberación de RAM sin importar si ocurre una excepción
        with BytesIO() as buffer:
            img.save(buffer, format="PNG")
            image_bytes = buffer.getvalue()
        
        return image_bytes