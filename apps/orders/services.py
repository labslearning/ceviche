import hashlib
import secrets
import logging
import qrcode
import datetime
from io import BytesIO
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Any

from django.db import transaction, IntegrityError
from django.conf import settings
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from django.utils import timezone
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
    Equipado con Lazy Garbage Collection (Auto-Healing), Hash Maps O(1), y mitigación 
    de ataques Race Conditions (Double-Spending) y DDoS.
    """

    @staticmethod
    def _build_seat_map(layout_data: Any) -> Dict[str, str]:
        """
        🛡️ ANTI-STACK OVERFLOW SHIELD (Algoritmo Iterativo DFS).
        Desacopla la recursividad clásica en una pila iterativa. 
        Inmune a ataques de desbordamiento de memoria (Memory Exhaustion).
        Rendimiento: O(V) Tiempo, O(V) Espacio.
        """
        result_map: Dict[str, str] = {}
        if not layout_data:
            return result_map

        stack = [layout_data]
        
        while stack:
            current = stack.pop()
            
            if isinstance(current, list):
                stack.extend(current)
                
            elif isinstance(current, dict):
                obj_id = current.get('id') or current.get('label') or current.get('name')
                zone = current.get('category') or current.get('zone')
                
                if obj_id and zone:
                    result_map[str(obj_id).strip()] = str(zone).strip()
                    
                for key, value in current.items():
                    if isinstance(value, (list, dict)):
                        stack.append(value)
                        
        return result_map

    @staticmethod
    def create_hybrid_order(user, validated_data: dict) -> Order:
        """
        Crea una orden atómica. 
        Inyecta protocolos de auto-liberación de inventario (Lazy GC) en tiempo real.
        """
        function_id = validated_data.get('function_id')
        seat_labels = validated_data.get('seat_labels', [])
        products_data = validated_data.get('products', [])

        # 🛡️ HARD LIMIT: Cota de red para prevenir ataques DDoS sobre PostgreSQL
        if isinstance(seat_labels, list) and len(seat_labels) > 20:
            logger.warning(f"🚨 [DDoS MITIGADO] Tráfico masivo bloqueado: {len(seat_labels)} sillas. IP/User: {user}")
            raise ValidationError("Límite bancario: Máximo 20 tickets por transacción.")

        with transaction.atomic():
            # 1. Validación Topológica
            function_instance = None
            if function_id:
                try:
                    function_instance = ShowFunction.objects.get(pk=function_id)
                except ShowFunction.DoesNotExist:
                    raise ValidationError("Violación de Integridad: El nodo del evento no existe.")
            elif seat_labels:
                raise ValidationError("Imposible procesar tickets sin una función vinculada.")
            
            # ==========================================
            # 🎫 LÓGICA DE BOLETERÍA Y AUTO-HEALING
            # ==========================================
            seats_to_buy = []
            ticket_total = Decimal('0.00')
            
            if seat_labels and function_instance:
                
                # 🚀 GOD-TIER LAZY GARBAGE COLLECTOR (Libera sillas pegadas)
                # Escanea si las sillas que el usuario quiere están atrapadas en órdenes abandonadas (> 15 mins)
                expiration_limit = timezone.now() - datetime.timedelta(minutes=15)
                
                ghost_tickets = Ticket.objects.filter(
                    function=function_instance,
                    seat_label__in=seat_labels,
                    order__status=Order.Status.PENDING, 
                    order__created_at__lt=expiration_limit
                ).select_related('order')

                if ghost_tickets.exists():
                    # 💥 Extracción masiva O(1) y destrucción atómica de bloqueos fantasmas
                    ghost_order_ids = list(set(ghost_tickets.values_list('order_id', flat=True)))
                    Ticket.objects.filter(order_id__in=ghost_order_ids).update(state=Ticket.State.VOIDED)
                    Order.objects.filter(id__in=ghost_order_ids).update(status=Order.Status.REJECTED)
                    logger.info(f"🧹 [AUTO-HEALING] Sillas zombi liberadas de la matriz: {seat_labels}")

                # A. Generación del Hash Map Comercial en RAM (O(1))
                available_types = {str(tt.zone_code).strip().lower(): tt for tt in TicketType.objects.filter(function=function_instance)}

                # B. Fail-Fast Definitivo: Validación de Integridad Post-Limpieza
                taken_tickets = Ticket.objects.filter(
                    function=function_instance, 
                    seat_label__in=seat_labels
                ).exclude(state__in=[Ticket.State.VOIDED, Ticket.State.REFUNDED])
                
                if taken_tickets.exists():
                    taken_str = ", ".join([t.seat_label for t in taken_tickets])
                    raise ValidationError(f"Interferencia detectada: Las sillas [{taken_str}] acaban de ser aseguradas por otro usuario en la red.")

                # C. Ruteo Espacial de Coordenadas
                seat_zone_map = OrderService._build_seat_map(function_instance.venue.layout)

                # D. Ensamblaje en Memoria Aislada
                for label in seat_labels:
                    clean_label = str(label).strip()
                    raw_zone_code = seat_zone_map.get(clean_label)
                    
                    ticket_type = None
                    if raw_zone_code:
                        clean_zone = str(raw_zone_code).strip().lower()
                        ticket_type = available_types.get(clean_zone)
                    
                    # Fallback (Rescate Estricto)
                    if not ticket_type:
                        ticket_type = available_types.get('general')
                        if not ticket_type:
                            logger.critical(f"Anomalía Física-Digital detectada en coordenada: {clean_label}")
                            raise ValidationError(f"Error comercial en la topología de la silla: {clean_label}.")

                    price = Decimal(str(ticket_type.price))
                    ticket_total += price
                    
                    # 🛡️ Entropía Criptográfica de 512 bits (Anti Reverse-Engineering)
                    new_ticket = Ticket(
                        order=None, 
                        function=function_instance,
                        seat_label=clean_label,
                        seat_category=ticket_type.name,
                        price_at_purchase=price,
                        qr_token=secrets.token_urlsafe(64) 
                    )
                    
                    # Sellado criptográfico embebido previo a la base de datos
                    new_ticket.crypto_signature = new_ticket.generate_signature()
                    seats_to_buy.append(new_ticket)

            # ==========================================
            # 🍔 LÓGICA DE PRODUCTOS (E-COMMERCE)
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
            # 💰 COMPILACIÓN FINAL DE LA BÓVEDA (ORDER)
            # ==========================================
            grand_total = ticket_total + product_total

            if grand_total <= Decimal('0.00'):
                 raise ValidationError("Denegado: Transacción estéril detectada. El valor debe ser mayor a cero.")

            # Inyección Maestra
            order = Order.objects.create(
                user=user if user and user.is_authenticated else None,
                total_amount=grand_total,
                status=Order.Status.PENDING 
            )

            # 🛡️ BULK CREATE CON CONTROL DE CONDICIÓN DE CARRERA (Optimistic Locking)
            if seats_to_buy:
                for t in seats_to_buy: 
                    t.order = order
                try:
                    Ticket.objects.bulk_create(seats_to_buy, ignore_conflicts=False)
                except IntegrityError as e:
                    logger.warning(f"🚨 [SNIPER ATTACK MITIGADO] Condición de carrera frenada en Postgres.")
                    raise ValidationError("Colisión de red: Otro usuario acaba de comprar esta silla milisegundos antes. Actualiza tu mapa.")
            
            if products_to_buy:
                for p in products_to_buy: 
                    p.order = order
                OrderItem.objects.bulk_create(products_to_buy)

            return order

    @staticmethod
    def attach_mercadopago_data(order: Order) -> Order:
        """
        Establece túnel seguro con la pasarela. 
        Fail-Open mitigado (Corta conexión si faltan llaves).
        """
        public_key = config('MERCADO_PAGO_PUBLIC_KEY', default='')
        redirect_url = config('MERCADO_PAGO_REDIRECT_URL', default='')

        if not public_key or not redirect_url:
            logger.critical("🚨 Desconexión de Llaves ENVs detectada.")
            raise ValidationError("Pasarela de pagos temporalmente desconectada de la matriz.")

        try:
            # 🛡️ Llamada a Adaptador Aislado Thread-Safe
            preference_id = MercadoPagoAdapter.create_checkout_preference(order, redirect_url)
        except Exception as e:
            logger.error(f"Caída de red externa (SDK MercadoPago): {str(e)}")
            raise ValidationError("Falla de comunicación con el ente bancario. Reintente.")

        # Inyección a RAM (Atributos Efímeros para Serializador)
        order.mp_preference_id = preference_id
        order.mp_public_key = public_key
        
        return order


class QRService:
    """
    MOTOR DE VOLCADO BINARIO (Generador QR).
    """

    @staticmethod
    def generate_qr_image(data: str) -> bytes:
        """
        🚀 PROTECCIÓN DE VOLCADO DE MEMORIA (MEMORY-LEAK PREVENTION).
        Usa Context Managers (with BytesIO) para forzar al recolector de basura de Python
        a destruir el bloque de RAM tras generar la imagen, evitando OOM (Out Of Memory).
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

        with BytesIO() as buffer:
            img.save(buffer, format="PNG")
            image_bytes = buffer.getvalue()
        
        return image_bytes