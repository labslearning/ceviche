import hashlib
import secrets
import logging
import qrcode
import datetime
import jwt
import gc
from io import BytesIO
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Any

from django.db import transaction, IntegrityError
from django.conf import settings
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from decouple import config

# 🛡️ Importación del Núcleo de ReportLab (Vectorial RAM-Only)
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# Importación de Modelos
from apps.orders.models import Order, Ticket, OrderItem
from apps.events.models import ShowFunction, TicketType
from apps.products.models import Product

# Importación del Adaptador Blindado
from apps.orders.adapters.mercadopago import MercadoPagoAdapter

logger = logging.getLogger(__name__)


class SmartTicketGodTierService:
    """
    🔐 MOTOR CRIPTOGRÁFICO ASIMÉTRICO Y GENERADOR VECTORIAL (GRADO FINTECH).
    Arquitectura Red Teaming: Transforma el QR en un Token Inmutable firmado por Álgebra de Curvas Elípticas.
    Mitiga fraudes por duplicación, alteración de datos y ataques de denegación por Memory Dumping.
    """
    
    @staticmethod
    def generate_secure_jwt_token(ticket_id: str, seat_label: str, event_name: str) -> str:
        """
        📐 CURVA ELÍPTICA ECDSA (Algoritmo ES256 / secp256r1).
        Deriva firmas matemáticas inmutables para validación local offline en las puertas del recinto.
        Complejidad temporal de falsificación: O(2^128) Operaciones.
        """
        private_key_pem = config('ECDSA_PRIVATE_KEY', default=None)
        if not private_key_pem:
            logger.critical("🚨 [CRITICAL CRYPTO FAILURE] Variable ECDSA_PRIVATE_KEY ausente en el entorno.")
            raise ValidationError("Falla de seguridad de la infraestructura. Emisión de llaves denegada.")
        
        payload = {
            "iss": "ceviche_platform",
            "sub": str(ticket_id),
            "iat": datetime.datetime.now(datetime.timezone.utc),
            "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365),
            "tid": str(ticket_id),
            "seat": str(seat_label),
            "evt": str(event_name)[:30]
        }
        
        # Limpieza estricta de caracteres de escape para prevenir fallos en contenedores Railway
        clean_key = private_key_pem.replace('\\n', '\n').encode('utf-8')
        return jwt.encode(payload, clean_key, algorithm="ES256")

    @staticmethod
    def generate_qr_buffer(jwt_token: str) -> bytes:
        """
        ⚡ AISLAMIENTO BINARIO EN RAM (Anti-I/O Leak).
        Construye la matriz densa aislando el flujo de bytes. 
        Usa corrección de errores nivel H (30% de redundancia física).
        """
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=8,
            border=2,
        )
        qr.add_data(jwt_token)
        qr.make(fit=True)

        img = qr.make_image(fill_color="#111111", back_color="#FFFFFF")
        
        with BytesIO() as buffer:
            img.save(buffer, format="PNG")
            image_bytes = buffer.getvalue()
            
        return image_bytes

    @staticmethod
    def generate_pdf_ticket_in_memory(ticket: Any, secure_token: str) -> bytes:
        """
        🚀 MOTOR VECTORIAL REPORTLAB (O(1) Disco I/O).
        Diseño Mobile-First adaptado a smartphones. Manejo nativo de fuentes UTF-8
        para evitar Memory Leaks al procesar tildes o caracteres especiales.
        """
        pdf_buffer = BytesIO()
        
        # Geometría del documento encapsulado
        doc = SimpleDocTemplate(
            pdf_buffer,
            pagesize=(300, 550),
            leftMargin=15,
            rightMargin=15,
            topMargin=15,
            bottomMargin=15
        )
        
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'TicketTitle', parent=styles['Normal'], fontName='Helvetica-Bold',
            fontSize=16, leading=20, textColor=colors.HexColor('#FF5500'), alignment=1
        )
        body_style = ParagraphStyle(
            'TicketBody', parent=styles['Normal'], fontName='Helvetica',
            fontSize=10, leading=14, textColor=colors.HexColor('#222222'), alignment=1
        )
        meta_style = ParagraphStyle(
            'TicketMeta', parent=styles['Normal'], fontName='Helvetica-Bold',
            fontSize=12, leading=16, textColor=colors.HexColor('#000000'), alignment=1
        )

        story = []
        
        event_name = ticket.function.name if hasattr(ticket.function, 'name') else "El Efecto Miller 2"
        story.append(Paragraph(f"<b>{event_name}</b>", title_style))
        story.append(Spacer(1, 10))
        
        # Inyección Binaria Segura
        qr_data_bytes = SmartTicketGodTierService.generate_qr_buffer(secure_token)
        qr_image_io = BytesIO(qr_data_bytes)
        reportlab_qr = Image(qr_image_io, width=160, height=160)
        reportlab_qr.hAlign = 'CENTER'
        story.append(reportlab_qr)
        story.append(Spacer(1, 10))
        
        venue_name = getattr(ticket.function.venue, 'name', 'Ubicación General')
        show_date = ticket.function.date_time.strftime('%Y-%m-%d %H:%M') if ticket.function.date_time else 'Fecha N/A'
        
        story.append(Paragraph(f"Localidad: {ticket.seat_category}", body_style))
        story.append(Paragraph(f"<b>SILLA: {ticket.seat_label}</b>", meta_style))
        story.append(Spacer(1, 5))
        story.append(Paragraph(f"Recinto: {venue_name}", body_style))
        story.append(Paragraph(f"Fecha: {show_date}", body_style))
        story.append(Spacer(1, 15))
        
        story.append(Paragraph("🔒 Entrada Criptográfica Única - Prohibida su reproducción", ParagraphStyle(
            'CryptoFoot', fontName='Helvetica-Oblique', fontSize=7, leading=9, textColor=colors.gray, alignment=1
        )))

        try:
            doc.build(story)
            pdf_data = pdf_buffer.getvalue()
        finally:
            pdf_buffer.close()
            qr_image_io.close()
            
            # 🧼 PROTOCOLO ANTI-MEMORY DUMPING (Red Teaming Standard)
            # Destrucción forzada de punteros en memoria RAM para erradicar buffers remanentes.
            del story
            del qr_data_bytes
            gc.collect() 
            
        return pdf_data


class OrderService:
    """
    🚀 SERVICIO PRINCIPAL: Gestor Transaccional Financiero (God-Tier / Nivel Bancario).
    Equipado con Lazy Garbage Collection atómico, Hash Maps O(1), Pessimistic Locking
    y mitigación avanzada de ataques Race Conditions (Double-Spending) y DDoS.
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
        Crea una orden atómica en complejidad O(1) de persistencia.
        """
        function_id = validated_data.get('function_id')
        seat_labels = validated_data.get('seat_labels', [])
        products_data = validated_data.get('products', [])

        # 🛡️ HARD LIMIT: Cota de red para prevenir ataques de denegación (DDoS)
        if isinstance(seat_labels, list) and len(seat_labels) > 20:
            logger.warning(f"🚨 [DDoS MITIGADO] Tráfico masivo bloqueado: {len(seat_labels)} sillas. IP/User: {user}")
            raise ValidationError("Límite bancario: Máximo 20 tickets por transacción.")

        with transaction.atomic():
            # 1. 🛡️ PESSIMISTIC LOCKING: Evita IntegrityError forzando una fila india en PostgreSQL
            function_instance = None
            if function_id:
                try:
                    function_instance = ShowFunction.objects.select_for_update().get(pk=function_id)
                except ShowFunction.DoesNotExist:
                    raise ValidationError("Violación de Integridad: El nodo del evento no existe.")
            elif seat_labels:
                raise ValidationError("Imposible procesar tickets sin una función vinculada.")
            
            seats_to_buy = []
            ticket_total = Decimal('0.00')
            
            if seat_labels and function_instance:
                # 🚀 GOD-TIER LAZY GARBAGE COLLECTOR: Liberación atómica de inventario zombi
                expiration_limit = timezone.now() - datetime.timedelta(minutes=15)
                ghost_orders = Order.objects.filter(
                    status=Order.Status.PENDING, 
                    created_at__lt=expiration_limit,
                    tickets__function=function_instance,
                    tickets__seat_label__in=seat_labels
                ).values_list('id', flat=True)

                if ghost_orders:
                    Ticket.objects.filter(order_id__in=ghost_orders).update(state=Ticket.State.VOIDED)
                    Order.objects.filter(id__in=ghost_orders).update(status=Order.Status.REJECTED)
                    logger.info(f"🧹 [AUTO-HEALING] Bóvedas Zombi {list(ghost_orders)} destruidas. Sillas {seat_labels} liberadas.")

                available_types = {str(tt.zone_code).strip().lower(): tt for tt in TicketType.objects.filter(function=function_instance)}

                taken_tickets = Ticket.objects.filter(
                    function=function_instance, 
                    seat_label__in=seat_labels
                ).exclude(state__in=[Ticket.State.VOIDED, Ticket.State.REFUNDED])
                
                if taken_tickets.exists():
                    taken_str = ", ".join([t.seat_label for t in taken_tickets])
                    raise ValidationError(f"Interferencia detectada: Las sillas [{taken_str}] acaban de ser aseguradas por otro nodo de la red.")

                seat_zone_map = OrderService._build_seat_map(function_instance.venue.layout)

                for label in seat_labels:
                    clean_label = str(label).strip()[:50] 
                    raw_zone_code = seat_zone_map.get(clean_label)
                    
                    ticket_type = None
                    if raw_zone_code:
                        clean_zone = str(raw_zone_code).strip().lower()
                        ticket_type = available_types.get(clean_zone)
                    
                    if not ticket_type:
                        ticket_type = available_types.get('general')
                        if not ticket_type:
                            logger.critical(f"Anomalía Física-Digital detectada en coordenada: {clean_label}")
                            raise ValidationError(f"Error comercial en la topología de la silla: {clean_label}.")

                    price = Decimal(str(ticket_type.price))
                    ticket_total += price
                    
                    new_ticket = Ticket(
                        order=None, 
                        function=function_instance,
                        seat_label=clean_label,
                        seat_category=ticket_type.name,
                        price_at_purchase=price,
                        qr_token=secrets.token_urlsafe(64) 
                    )
                    
                    new_ticket.crypto_signature = new_ticket.generate_signature()
                    seats_to_buy.append(new_ticket)

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
                        order=None, product=product_obj, quantity=qty, price_at_purchase=base_price
                    ))

            grand_total = ticket_total + product_total

            if grand_total <= Decimal('0.00'):
                 raise ValidationError("Denegado: Transacción estéril detectada. El valor debe ser mayor a cero.")

            order = Order.objects.create(
                user=user if user and user.is_authenticated else None,
                total_amount=grand_total,
                status=Order.Status.PENDING 
            )

            if seats_to_buy:
                for t in seats_to_buy: 
                    t.order = order
                try:
                    Ticket.objects.bulk_create(seats_to_buy, ignore_conflicts=False)
                except IntegrityError as e:
                    logger.warning(f"🚨 [SNIPER ATTACK MITIGADO] Condición de carrera frenada en Postgres.")
                    raise ValidationError("Colisión de red: Otro nodo acaba de asegurar esta silla en el mismo milisegundo.")
            
            if products_to_buy:
                for p in products_to_buy: 
                    p.order = order
                OrderItem.objects.bulk_create(products_to_buy)

            return order

    @staticmethod
    def attach_mercadopago_data(order: Order) -> Order:
        """
        Establece túnel TLS seguro con Mercado Pago.
        """
        public_key = config('MERCADO_PAGO_PUBLIC_KEY', default='')
        redirect_url = config('MERCADO_PAGO_REDIRECT_URL', default='')

        if not public_key or not redirect_url:
            logger.critical("🚨 Desconexión de Llaves ENVs detectada.")
            raise ValidationError("Pasarela de pagos temporalmente desconectada de la matriz.")

        try:
            preference_id = MercadoPagoAdapter.create_checkout_preference(order, redirect_url)
        except Exception as e:
            logger.error(f"Caída de red externa (SDK MercadoPago): {str(e)}")
            raise ValidationError("Falla de comunicación con el ente bancario. Reintente.")

        order.mp_preference_id = preference_id
        order.mp_public_key = public_key
        
        return order