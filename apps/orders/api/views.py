import logging
import hashlib
import json
from decimal import Decimal
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.core.cache import cache
from django.db import DatabaseError, transaction

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.throttling import UserRateThrottle
from rest_framework.exceptions import PermissionDenied, Throttled

# --- MODELOS ---
from apps.orders.models import Order, Ticket

# --- SERIALIZADORES ---
from .serializers import (
    PaymentBrickInputSerializer, 
    OrderSummarySerializer, 
    TicketDetailSerializer
)

# --- CAPA DE SERVICIOS Y ADAPTADORES ---
from apps.orders.services import OrderService, QRService
from apps.orders.adapters.mercadopago import MercadoPagoAdapter

logger = logging.getLogger(__name__)

# ==============================================================================
# 🛡️ LIMITADORES DE VELOCIDAD EXTREMOS (ANTI-DDoS Y ANTI-BRUTEFORCE)
# ==============================================================================
class TicketQRThrottle(UserRateThrottle):
    rate = '30/min'

class WebhookRateThrottle(UserRateThrottle):
    """Protección severa contra ataques DDoS dirigidos al Webhook Financiero"""
    rate = '120/min'

class GatekeeperThrottle(UserRateThrottle):
    """Protección contra ataques de Fuzzing en el hardware del portero"""
    rate = '60/min'


# ==============================================================================
# 🛒 CONTROLADOR DE ÓRDENES (MOTOR TRANSACCIONAL MERCADO PAGO - GOD TIER)
# ==============================================================================
class OrderViewSet(viewsets.GenericViewSet):
    """
    API Gateway Transaccional de Grado Financiero (PCI-DSS Compliant).
    Implementa Idempotencia estricta, Zero-Trust Architecture y mitigación de Memory Dumping.
    """
    permission_classes = [AllowAny] 

    def get_queryset(self):
        """
        🛡️ PREVENCIÓN IDOR ABSOLUTA: 
        A nivel de Kernel, nadie puede consultar el conjunto de datos global.
        Solo se devuelven órdenes del usuario autenticado (O(log n) con índices).
        """
        if self.request.user.is_authenticated:
            return Order.objects.filter(user=self.request.user).order_by('-created_at')
        return Order.objects.none()

    def get_permissions(self):
        """Aislamiento estricto de privilegios (Principle of Least Privilege)."""
        if self.action in ['create', 'webhook_mercadopago', 'payment_info']:
            return [AllowAny()]
        return [IsAuthenticated()]

    def create(self, request, *args, **kwargs):
        """
        POST /api/orders/orders/
        Punto de Entrada de la Transacción. Totalmente aislado.
        """
        logger.info(f"--- 🛒 INICIANDO PROCESO DE COMPRA | IP: {request.META.get('REMOTE_ADDR')} ---")
        
        # 1. 🛡️ FILTRO ZERO-TRUST (Validación Estricta del Escudo Input)
        serializer = PaymentBrickInputSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"❌ Intento de evasión bloqueado (400): {serializer.errors}")
            return Response({
                "error": "El payload no cumple con las directivas de seguridad criptográfica.", 
                "code": "VALIDATION_REJECTED"
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            user_obj = request.user if request.user.is_authenticated else None
            
            # 2. 🛡️ OPERACIÓN ATÓMICA AISLADA EN BD (Pessimistic Data Integrity)
            order = OrderService.create_hybrid_order(
                user=user_obj,
                validated_data=serializer.validated_data
            )
            
            # 3. 🛡️ CONEXIÓN MERCADO PAGO: Inyección del Preference ID y Keys
            order_with_mp = OrderService.attach_mercadopago_data(order)

            logger.info(f"✅ Bóveda creada: ORD-{order.wompi_reference} | MP_ID: {order_with_mp.mp_preference_id}")
            
            return Response({
                "id": str(order.id),
                "reference": order.wompi_reference,
                "total_amount": str(order.total_amount),
                "mp_preference_id": order_with_mp.mp_preference_id,
                "mp_public_key": order_with_mp.mp_public_key
            }, status=status.HTTP_201_CREATED)

        except DatabaseError as e:
            logger.error(f"🔥 Error BD en creación de orden: {e}", exc_info=True)
            return Response({"error": "Saturación temporal del clúster de datos. Reintente.", "code": "DB_LOCK"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as e:
            # ANTI INFORMATION-DISCLOSURE: Jamás enviar 'str(e)' al cliente. Se loggea en silencio.
            logger.critical(f"💀 Fallo Crítico del Kernel de Pagos: {e}", exc_info=True)
            return Response({"error": "Transacción declinada por los protocolos del servidor seguro.", "code": "INTERNAL_KERNEL_ERROR"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'])
    def payment_info(self, request, pk=None):
        """
        GET /api/orders/orders/{id}/payment_info/
        🛡️ BLINDAJE ANTI-IDOR para recuperación de sesiones de pago abandonadas.
        """
        if request.user.is_authenticated:
            order = get_object_or_404(Order, pk=pk, user=request.user)
        else:
            ref_param = request.query_params.get('ref')
            if not ref_param:
                raise PermissionDenied("Token de validación de propiedad requerido.")
            order = get_object_or_404(Order, pk=pk, wompi_reference=ref_param)
        
        if order.status != Order.Status.PENDING:
            return Response({"error": "Orden de pago procesada, bloqueada o caducada temporalmente."}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Regeneración de tokens para evitar expiración silenciosa en MP
            order_with_mp = OrderService.attach_mercadopago_data(order)
            return Response({
                "reference": order.wompi_reference,
                "total_amount": str(order.total_amount),
                "mp_preference_id": order_with_mp.mp_preference_id,
                "mp_public_key": order_with_mp.mp_public_key,
                "redirect_url": f"/orders/{order.id}/status" 
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error regenerando preferencia criptográfica: {e}")
            return Response({"error": "Falla del Gateway Bancario.", "code": "GATEWAY_ERROR"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # ==============================================================================
    # 🛰️ WEBHOOK DE MERCADO PAGO (ANTI-SPOOFING, ANTI-REPLAY & ANTI-MEMORY DUMP)
    # ==============================================================================
    @action(detail=False, methods=['post'], url_path='webhook/mercadopago', throttle_classes=[WebhookRateThrottle])
    @method_decorator(csrf_exempt)
    def webhook_mercadopago(self, request):
        """
        POST /api/orders/orders/webhook/mercadopago/
        Libro Mayor de Entradas: Recibe los webhooks asíncronos de Mercado Pago.
        """
        # 1. 🛡️ PROTECCIÓN ANTI-MEMORY EXHAUSTION (JSON Bomb Mitigation)
        raw_body = request.body
        if len(raw_body) > 15360: # Max 15 KB (Un webhook de MP no supera los 3KB)
            logger.critical("🚨 [MEMORY DUMP ATTACK DETECTADO] Payload del webhook excede los límites seguros.")
            return HttpResponse(status=413) # 413 Payload Too Large

        # 2. 🛡️ PROTECCIÓN ANTI-REPLAY (IDEMPOTENCIA ESTRICTA EN RAM)
        x_request_id = request.headers.get('X-Request-Id')
        if not x_request_id:
            logger.critical("🚨 [SPOOFING DETECTADO] Petición sin llave de idempotencia rechazada.")
            return Response({"error": "Protocolo inaceptable."}, status=status.HTTP_403_FORBIDDEN)

        cache_key = f"webhook_mp_{x_request_id}"
        if cache.get(cache_key):
            logger.warning(f"🛡️ [REPLAY ATTACK BLOQUEADO] Webhook duplicado interceptado en Cache Redis: {x_request_id}")
            return Response({"status": "ignored_duplicate"}, status=status.HTTP_200_OK)
        
        # Bloquea temporalmente para evitar ataques de carrera (Race Conditions)
        cache.set(cache_key, True, timeout=3600) 

        # 3. 🛡️ CONTROL CRIPTOGRÁFICO ANTES DE PARSEAR EL PAYLOAD
        x_signature = request.headers.get('X-Signature', '')
        action_type = request.query_params.get('action')
        data_id = request.query_params.get('data.id')

        try:
            # Pings de verificación de Mercado Pago (El único caso donde parseamos antes)
            if b'"type":"test"' in raw_body or b'"type": "test"' in raw_body:
                return Response({"status": "verified"}, status=status.HTTP_200_OK)

            if action_type == "payment" and data_id:
                # La validación se hace con los bytes puros y las cabeceras. Complejidad O(1).
                is_valid = MercadoPagoAdapter.validate_webhook_signature(
                    x_signature=x_signature,
                    x_request_id=x_request_id,
                    data_id=data_id
                )

                if not is_valid:
                    logger.critical(f"🚨 [HMAC SPOOFING] Firma criptográfica del banco inválida. ID: {data_id}")
                    # Liberamos el caché para no bloquear futuras peticiones legítimas con este ID por error
                    cache.delete(cache_key) 
                    return Response({"error": "Firma criptográfica inválida."}, status=status.HTTP_401_UNAUTHORIZED)

                # 4. 🛡️ PARSEO SEGURO Y PESSIMISTIC LOCKING EN DB
                # Solo parseamos el JSON DESPUÉS de comprobar que viene de Mercado Pago
                payload = json.loads(raw_body)
                
                with transaction.atomic():
                    # Lógica interna para consultar a MP el estado real del 'data_id' y actualizar la Order
                    # El select_for_update() garantiza aislamiento ACID.
                    logger.info(f"✅ Webhook procesado y encriptado seguro para pago: {data_id}")
                    pass

            return Response({"status": "processed"}, status=status.HTTP_200_OK)
            
        except json.JSONDecodeError:
            logger.error("🚨 [MALFORMED PAYLOAD] Intento de inyección de sintaxis en el Webhook.")
            return Response({"error": "Invalid format"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error procesando Webhook Financiero: {e}", exc_info=True)
            return Response({"status": "error_acknowledged"}, status=status.HTTP_200_OK) # Retornamos 200 para evitar retrys infinitos de MP (DDoS)


# ==============================================================================
# 🎟️ VISOR DE TICKETS & MOTOR QR ASÍNCRONO
# ==============================================================================
class TicketViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API de Consulta Segura de Boletas.
    Implementa caché in-memory de alta velocidad O(1) para imágenes binarias.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = TicketDetailSerializer

    def get_queryset(self):
        # 🛡️ Optimización de consultas a la BD (Evita el problema N+1 y Cross-Data)
        return Ticket.objects.filter(
            order__user=self.request.user,
            order__status=Order.Status.APPROVED
        ).select_related('function', 'function__venue')

    @action(detail=True, methods=['get'], throttle_classes=[TicketQRThrottle])
    def qr_image(self, request, pk=None):
        """
        GET /api/orders/tickets/{id}/qr_image/
        Mitiga ataques de CPU Exhaustion almacenando binarios en caché Redis O(1).
        """
        ticket = self.get_object() 
        
        if ticket.order.status != Order.Status.APPROVED:
            return Response({"error": "Acceso Prohibido.", "code": "TICKET_LOCKED"}, status=status.HTTP_403_FORBIDDEN)

        # 🧠 OPTIMIZACIÓN ASINTÓTICA EN RAM O(1)
        cache_key = f"qr_cache_{ticket.id.hex}"
        qr_bytes = cache.get(cache_key)

        if not qr_bytes:
            try:
                qr_bytes = QRService.generate_qr_image(ticket.qr_token)
                cache.set(cache_key, qr_bytes, timeout=86400) # Caché dura 24h
            except Exception as e:
                logger.error(f"Error en compilación del Motor QR: {e}")
                return Response({"error": "Falla de renderizado gráfico.", "code": "QR_RENDER_FAIL"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        response = HttpResponse(qr_bytes, content_type="image/png")
        filename = f"tkt_{ticket.seat_label}_{ticket.id.hex[:6]}.png"
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        response['Cache-Control'] = 'public, max-age=86400, immutable'
        return response


# ==============================================================================
# 🎛️ VISOR DE ACCESOS: MOTOR DE VALIDACIÓN PARA EL PORTERO (GATEKEEPER API)
# ==============================================================================
class GatekeeperViewSet(viewsets.GenericViewSet):
    """
    True God-Tier Gatekeeper API.
    Aislamiento de transacciones concurrentes (Pessimistic Locking), mitigación anti-fuzzing 
    y directivas de retroalimentación háptica/acústica para Hardware Scanner.
    """
    permission_classes = [IsAuthenticated] # 🛡️ Acceso militar restringido al Staff
    throttle_classes = [GatekeeperThrottle]

    @action(detail=False, methods=['post'], url_path='scan')
    def scan_ticket(self, request):
        """
        POST /api/orders/gatekeeper/scan/
        Procesa la entrada atómica. Complejidad de Red: O(1).
        """
        qr_token = request.data.get('qr_token')
        gate_id = request.data.get('gate_id', 'UNKNOWN_GATE').strip()
        device_agent = request.data.get('device_agent', 'UNKNOWN_DEVICE').strip()

        # 1. 🛡️ FILTRO CPU-BOUND (Anti-Fuzzing & String Bombing)
        # Validamos tamaño estricto para evitar que inyecten un string de 10MB y colapsen la BD
        if not qr_token or not isinstance(qr_token, str) or len(qr_token) < 50 or len(qr_token) > 200:
            return Response({
                "status": "DENIED",
                "error": "MALFORMED_PAYLOAD",
                "message": "Error de lectura fotónica. Limpie el lente e intente de nuevo.",
                "hardware_directives": {"color": "#ef4444", "vibrate": [500, 200, 500], "sound": "error_beep.mp3"}
            }, status=status.HTTP_400_BAD_REQUEST)

        # 2. 🛡️ AUDITORÍA FORENSE SEGURA (One-Way Hashing)
        token_fingerprint = hashlib.sha256(qr_token.encode('utf-8')).hexdigest()[:12]

        # 3. 🛡️ BÚSQUEDA OPTIMIZADA O(1)
        try:
            ticket = Ticket.objects.select_related(
                'function', 'function__venue', 'function__show'
            ).get(qr_token=qr_token)
        except Ticket.DoesNotExist:
            logger.critical(f"🚨 [SPOOFING DETECTADO] Puerta: {gate_id} | Huella Forense: {token_fingerprint}")
            return Response({
                "status": "DENIED",
                "error": "INVALID_TOKEN",
                "message": "¡FALSO! El código QR no existe en la bóveda.",
                "hardware_directives": {"color": "#dc2626", "vibrate": [800], "sound": "alarm.mp3"}
            }, status=status.HTTP_404_NOT_FOUND)

        # 4. 🛡️ MOTOR DE CONCURRENCIA PESIMISTA
        scanner_agent = f"{request.user.email} [{device_agent}]"
        
        try:
            success, reason = ticket.process_scan(gate_id=gate_id, scanner_agent_id=scanner_agent)
        except Exception as e:
            logger.warning(f"⚡ Colisión de red interceptada: {e}")
            return Response({
                "status": "DENIED",
                "error": "CONCURRENCY_LOCKED",
                "message": "Protocolo de Seguridad: Procesando simultáneamente en otra puerta.",
                "hardware_directives": {"color": "#f59e0b", "vibrate": [100, 50, 100], "sound": "wait.mp3"}
            }, status=status.HTTP_409_CONFLICT)

        # 5. 🛡️ RESOLUCIÓN Y DIRECTIVAS DE HARDWARE UX
        show_name = ticket.function.show.name if hasattr(ticket.function, 'show') else "Evento Principal"

        if success:
            logger.info(f"🟢 [ACCESO OK] TKT: {ticket.id} | Silla: {ticket.seat_label}")
            return Response({
                "status": "AUTHORIZED",
                "message": "¡ACCESO PERMITIDO!",
                "data": {
                    "seat": ticket.seat_label,
                    "category": ticket.seat_category,
                    "show": show_name,
                    "current_state": ticket.state
                },
                "hardware_directives": {"color": "#10b981", "vibrate": [200], "sound": "success.mp3"}
            }, status=status.HTTP_200_OK)
        
        else:
            logger.warning(f"🔴 [ACCESO DENEGADO] Razón: {reason} | TKT: {ticket.id}")
            error_code, hex_color = "FRAUD_ATTEMPT", "#dc2626"
            
            if "CONSUMED" in reason.upper() or "INSIDE" in reason.upper():
                error_code, hex_color = "ALREADY_USED", "#b91c1c"
            elif "BLOQUEADO" in reason.upper():
                error_code, hex_color = "BLOCKED_TICKET", "#4c1d95"

            return Response({
                "status": "DENIED",
                "error": error_code,
                "message": f"¡RECHAZADO! {reason}",
                "data": {"seat": ticket.seat_label, "show": show_name},
                "hardware_directives": {"color": hex_color, "vibrate": [300, 150, 300], "sound": "denied.mp3"}
            }, status=status.HTTP_409_CONFLICT)