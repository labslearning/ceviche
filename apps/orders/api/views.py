import logging
from decimal import Decimal
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.core.exceptions import ValidationError
from django.db import DatabaseError

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.throttling import UserRateThrottle

# --- MODELOS ---
from apps.orders.models import Order, Ticket

# --- SERIALIZADORES ---
from .serializers import (
    CreateOrderSerializer, 
    OrderSummarySerializer, 
    TicketDetailSerializer
)

# --- CAPA DE SERVICIOS ---
from backend.apps.orders.services import OrderService, QRService

logger = logging.getLogger(__name__)

# ==========================================
# 🛡️ LIMITADORES DE VELOCIDAD
# ==========================================

class TicketQRThrottle(UserRateThrottle):
    rate = '20/min'


# ==========================================
# 🛒 CONTROLADOR DE ÓRDENES
# ==========================================

class OrderViewSet(viewsets.GenericViewSet):
    """
    API Gateway para compras.
    Maneja la creación de orden (Tickets + Productos) y firmas de pago.
    """
    queryset = Order.objects.all()
    # Permitimos crear órdenes sin login (AllowAny), pero ver tickets requiere login
    permission_classes = [AllowAny] 

    def get_permissions(self):
        """
        Permisos dinámicos:
        - create (POST): Público (Cualquiera puede comprar)
        - qr_image / payment_info: Requiere autenticación o validación especial
        """
        if self.action == 'create':
            return [AllowAny()]
        if self.action in ['qr_image', 'list', 'retrieve']:
            return [IsAuthenticated()]
        return super().get_permissions()

    def create(self, request, *args, **kwargs):
        """
        POST /api/orders/orders/
        Payload esperado: 
        { 
            "function_id": "UUID...", 
            "seat_labels": ["A-1", "B-2"], 
            "products": [...] 
        }
        """
        user_info = request.user if request.user.is_authenticated else 'Anónimo'
        logger.info(f"--- 🛒 INICIANDO PROCESO DE COMPRA ---")
        logger.info(f"Usuario: {user_info}")
        logger.info(f"Payload Recibido: {request.data}")
        
        # 1. Validación de Entrada
        serializer = CreateOrderSerializer(data=request.data)
        
        if not serializer.is_valid():
            # 🔍 DETECTIVE DE ERRORES: Imprimimos por qué falló
            logger.error(f"❌ Error de Validación (400): {serializer.errors}")
            return Response({
                "error": "Datos inválidos", 
                "details": serializer.errors,
                "code": "VALIDATION_ERROR"
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            # 2. Lógica de Negocio (Service)
            # Pasamos request.user explícitamente (puede ser AnonymousUser)
            user_obj = request.user if request.user.is_authenticated else None
            
            order = OrderService.create_hybrid_order(
                user=user_obj,
                validated_data=serializer.validated_data
            )
            
            # 3. Firma Wompi (Seguridad)
            order_with_security = OrderService.attach_wompi_data(order)

            # 4. Respuesta Exitosa
            response_serializer = OrderSummarySerializer(order_with_security)
            logger.info(f"✅ Orden {order.id} creada exitosamente. Esperando pago.")
            
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)

        except ValidationError as e:
            logger.warning(f"⚠️ Regla de Negocio: {e}")
            # Error amigable para el usuario (ej: "Silla ya vendida")
            return Response({"error": str(e), "code": "BUSINESS_RULE"}, status=status.HTTP_409_CONFLICT)
            
        except DatabaseError as e:
            logger.error(f"🔥 Error Crítico BD: {e}", exc_info=True)
            return Response({"error": "Error temporal del sistema. Intente nuevamente.", "code": "DB_ERROR"}, status=503)

        except Exception as e:
            logger.critical(f"💀 Error Interno No Manejado: {e}", exc_info=True)
            return Response({"error": "Error interno del servidor", "code": "INTERNAL_ERROR"}, status=500)

    @action(detail=True, methods=['get'])
    def payment_info(self, request, pk=None):
        """
        GET /api/orders/orders/{id}/payment_info/
        Recuperar datos para reintentar pago fallido.
        """
        # Intentamos buscar la orden. 
        # Si el usuario es anónimo, buscamos por ID sin filtro de usuario (Cuidado en producción)
        # Si es autenticado, filtramos por su usuario para seguridad.
        if request.user.is_authenticated:
            order = get_object_or_404(Order, pk=pk, user=request.user)
        else:
            order = get_object_or_404(Order, pk=pk) 
        
        if order.status != Order.Status.PENDING:
            return Response({"error": "Esta orden no está pendiente de pago"}, status=400)
        
        try:
            order_with_security = OrderService.attach_wompi_data(order)
            return Response({
                "reference": order.wompi_reference,
                "amount_in_cents": order_with_security.amount_in_cents,
                "currency": order_with_security.wompi_currency,
                "public_key": order_with_security.wompi_public_key,
                "signature": order_with_security.wompi_signature,
                "redirect_url": f"/orders/{order.id}/status" 
            })
        except Exception as e:
            logger.error(f"Error generando info pago: {e}")
            return Response({"error": "Error de configuración de pago"}, status=500)


# ==========================================
# 🎟️ VISOR DE TICKETS & QR
# ==========================================

class TicketViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API para ver tickets comprados y descargar QR.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = TicketDetailSerializer

    def get_queryset(self):
        # Optimizamos la consulta para no matar la base de datos
        return Ticket.objects.filter(
            order__user=self.request.user,
            order__status=Order.Status.APPROVED
        ).select_related('function', 'function__venue')

    @action(detail=True, methods=['get'], throttle_classes=[TicketQRThrottle])
    def qr_image(self, request, pk=None):
        """
        Genera imagen QR al vuelo (Streaming).
        """
        try:
            ticket = self.get_object() 
            
            if ticket.order.status != Order.Status.APPROVED:
                return Response({"error": "Ticket no pagado o inválido"}, status=403)

            qr_bytes = QRService.generate_qr_image(ticket.qr_token)

            response = HttpResponse(qr_bytes, content_type="image/png")
            filename = f"ticket_{str(ticket.id)[:8]}.png"
            response['Content-Disposition'] = f'inline; filename="{filename}"'
            # Cacheamos el QR 1 hora en el navegador del cliente para ahorrar CPU
            response['Cache-Control'] = 'public, max-age=3600, immutable'
            return response
            
        except Exception as e:
            logger.error(f"Error generando QR: {e}")
            return Response({"error": "Error generando código QR"}, status=500)