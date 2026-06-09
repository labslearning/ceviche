import hashlib
import secrets
import qrcode
from io import BytesIO
from decimal import Decimal
from django.db import transaction
from django.conf import settings
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404

# Importación de Modelos
from apps.orders.models import Order, Ticket, OrderItem
# 👇 IMPORTANTE: Ahora importamos también TicketType para leer precios reales
from apps.events.models import ShowFunction, TicketType
from apps.products.models import Product

class OrderService:
    """
    SERVICIO PRINCIPAL: Gestor de Transacciones y Compras.
    Encargado de la lógica de negocio, bloqueos de base de datos y seguridad.
    """

    @staticmethod
    def _find_zone_in_layout(layout_data, seat_label):
        """
        Método auxiliar recursivo para encontrar la 'category' o 'zone' de una silla
        dentro del JSON del Venue.
        Retorna el código de zona (ej: 'vip', 'general') o None si no lo encuentra.
        """
        # Si es una lista, iteramos
        if isinstance(layout_data, list):
            for item in layout_data:
                found = OrderService._find_zone_in_layout(item, seat_label)
                if found: return found
        
        # Si es un diccionario (objeto), revisamos si es la silla
        elif isinstance(layout_data, dict):
            # Verificamos si este objeto es la silla que buscamos
            # Aceptamos 'id', 'label' o 'name' como identificador
            obj_id = layout_data.get('id') or layout_data.get('label') or layout_data.get('name')
            
            # Normalizamos (strip) para evitar errores por espacios invisibles
            if str(obj_id).strip() == str(seat_label).strip():
                # ¡Silla encontrada! Devolvemos su categoría
                # Priorizamos 'category' y luego 'zone'
                return layout_data.get('category') or layout_data.get('zone')
            
            # Si tiene hijos (ej: filas, grupos), buscamos adentro
            for key, value in layout_data.items():
                if isinstance(value, (list, dict)):
                    found = OrderService._find_zone_in_layout(value, seat_label)
                    if found: return found
        
        return None

    @staticmethod
    def create_hybrid_order(user, validated_data):
        """
        Crea una orden mixta (Boletas + Productos) en una transacción atómica.
        Ahora soporta PRECIOS DINÁMICOS y LÓGICA DE RESCATE (Fallback).
        """
        function_id = validated_data.get('function_id')
        seat_labels = validated_data.get('seat_labels', []) # Lista de textos: ["A-1", "B-2"]
        products_data = validated_data.get('products', [])

        with transaction.atomic():
            # 1. Validar y Bloquear Función (Concurrency Locking)
            try:
                # select_for_update() bloquea la fila hasta que termine la transacción
                function_instance = ShowFunction.objects.select_for_update().get(pk=function_id)
            except ShowFunction.DoesNotExist:
                # Si no hay función (compra solo productos), permitimos continuar si seat_labels está vacío
                if seat_labels:
                    raise ValidationError("La función seleccionada no existe.")
                function_instance = None
            
            # ==========================================
            # 🎫 LÓGICA DE BOLETERÍA (TICKETS)
            # ==========================================
            seats_to_buy = []
            ticket_total = Decimal('0.00')
            
            if seat_labels and function_instance:
                # A. Pre-cargar Precios y Normalizar Claves (Minúsculas)
                available_types = {}
                for tt in TicketType.objects.filter(function=function_instance):
                    # Usamos minúsculas para que 'General' coincida con 'general'
                    key = str(tt.zone_code).strip().lower()
                    available_types[key] = tt

                # B. Validar Disponibilidad Real (Si ya están vendidas)
                taken_tickets = Ticket.objects.filter(
                    function=function_instance, 
                    seat_label__in=seat_labels
                ).exclude(state=Ticket.State.CANCELLED)
                
                if taken_tickets.exists():
                    taken_str = ", ".join([t.seat_label for t in taken_tickets])
                    raise ValidationError(f"Lo sentimos, las siguientes sillas ya fueron vendidas: {taken_str}")

                # C. Obtener el Layout (JSON) del Teatro para buscar zonas
                venue_layout = function_instance.venue.layout

                # D. Procesar cada silla solicitada
                for label in seat_labels:
                    # 1. Buscar a qué zona pertenece esta silla en el JSON
                    raw_zone_code = OrderService._find_zone_in_layout(venue_layout, label)
                    
                    # --- 🚑 LÓGICA DE RESCATE (SALVAVIDAS) ---
                    ticket_type = None
                    
                    # Intento 1: Buscar coincidencia exacta
                    if raw_zone_code:
                        clean_zone = str(raw_zone_code).strip().lower()
                        ticket_type = available_types.get(clean_zone)
                    
                    # Intento 2: Si no tiene zona o no encontramos el precio, usar 'general'
                    if not ticket_type:
                        if 'general' in available_types:
                            ticket_type = available_types['general']
                        else:
                            # Si no hay ni zona específica ni precio General, ahí sí fallamos
                            msg = f"Error de precio: La silla '{label}' no tiene precio configurado."
                            if raw_zone_code:
                                msg += f" (Zona mapa: '{raw_zone_code}' no coincide con precios)"
                            else:
                                msg += " (No tiene zona en el mapa y no hay precio General por defecto)"
                            raise ValidationError(msg)

                    price = ticket_type.price
                    category_name = ticket_type.name # Ej: "General" o "VIP"

                    ticket_total += price
                    
                    # 3. Preparar Objeto Ticket (En memoria)
                    seats_to_buy.append(Ticket(
                        order=None, # Se asigna después de crear la orden padre
                        function=function_instance,
                        seat_label=label,
                        seat_category=category_name, # Guardamos el nombre real
                        price_at_purchase=price,     # Guardamos el precio exacto pagado
                        qr_token=secrets.token_urlsafe(32) # Token único para el QR
                    ))

            # ==========================================
            # 🍔 LÓGICA DE PRODUCTOS / TIENDA
            # ==========================================
            products_to_buy = []
            product_total = Decimal('0.00')

            if products_data:
                product_ids = [item['product_id'] for item in products_data]
                db_products = Product.objects.filter(id__in=product_ids)
                product_map = {str(p.id): p for p in db_products}

                for item in products_data:
                    p_id = str(item['product_id'])
                    qty = item['quantity']
                    
                    product_obj = product_map.get(p_id)
                    if not product_obj:
                        continue 
                    
                    line_price = product_obj.price * qty
                    product_total += line_price

                    products_to_buy.append(OrderItem(
                        order=None,
                        product=product_obj,
                        quantity=qty,
                        price_at_purchase=product_obj.price
                    ))

            # ==========================================
            # 💰 CREACIÓN DE LA ORDEN MAESTRA
            # ==========================================
            grand_total = ticket_total + product_total

            if grand_total <= 0:
                 raise ValidationError("El total de la orden no puede ser cero. Seleccione entradas o productos.")

            # Crear Orden Padre
            order = Order.objects.create(
                user=user if user and user.is_authenticated else None,
                total_amount=grand_total,
                status=Order.Status.PENDING 
            )

            # Asignar hijos y guardar en lote (Bulk Create para rendimiento)
            if seats_to_buy:
                for t in seats_to_buy: t.order = order
                Ticket.objects.bulk_create(seats_to_buy)
            
            if products_to_buy:
                for p in products_to_buy: p.order = order
                OrderItem.objects.bulk_create(products_to_buy)

            return order

    @staticmethod
    def attach_wompi_data(order):
        """
        Calcula y adjunta los datos de seguridad de Wompi al objeto Order.
        Fórmula: SHA256(Reference + AmountInCents + Currency + IntegritySecret)
        """
        amount_in_cents = int(order.total_amount * 100)
        reference = str(order.wompi_reference)
        currency = "COP"
        
        # Usamos valores por defecto 'test' si no están en settings para evitar crash en desarrollo
        secret = getattr(settings, 'WOMPI_INTEGRITY_SECRET', 'test_integrity_secret')
        public_key = getattr(settings, 'WOMPI_PUBLIC_KEY', 'test_public_key')

        # Generación de firma SHA-256
        raw_str = f"{reference}{amount_in_cents}{currency}{secret}"
        signature = hashlib.sha256(raw_str.encode('utf-8')).hexdigest()

        # Inyectamos atributos dinámicos (No se guardan en BD, solo viajan en la API)
        order.wompi_signature = signature
        order.wompi_public_key = public_key
        order.amount_in_cents = amount_in_cents
        order.wompi_currency = currency
        
        return order


class QRService:
    """
    SERVICIO DE UTILIDAD: Generación de imágenes QR.
    """

    @staticmethod
    def generate_qr_image(data: str) -> bytes:
        """
        Genera un QR PNG a partir de un string (Token).
        Retorna los bytes de la imagen.
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
        image_bytes = buffer.getvalue()
        buffer.close()
        
        return image_bytes