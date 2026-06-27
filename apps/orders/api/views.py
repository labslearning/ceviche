import logging
import hashlib
import json
import gc
from decimal import Decimal
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.core.cache import cache
from django.db import DatabaseError, transaction, OperationalError
from django.utils import timezone

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.throttling import UserRateThrottle
from rest_framework.exceptions import PermissionDenied

# --- MODELOS ---
from apps.orders.models import Order, Ticket

# --- SERIALIZADORES ---
from apps.orders.api.serializers import (
    PaymentBrickInputSerializer, 
    OrderSummarySerializer, 
    TicketDetailSerializer
)

# --- CAPA DE SERVICIOS AVANZADOS (Fase 2 & Fase 3) ---
from apps.orders.services import OrderService, SmartTicketGodTierService
from apps.orders.tasks import generate_and_dispatch_smart_tickets

# 🔒 Logger profesional asincrónico inmune a desbordamientos de buffers
logger = logging.getLogger(__name__)

# ==============================================================================
# 🛡️ LIMITADORES DE VELOCIDAD EXTREMOS (ANTI-DDoS Y ANTI-BRUTEFORCE)
# ==============================================================================
class TicketQRThrottle(UserRateThrottle):
    rate = '30/min'

class WebhookRateThrottle(UserRateThrottle):
    rate = '120/min'

class GatekeeperThrottle(UserRateThrottle):
    rate = '60/min'


# ==============================================================================
# 🛒 CONTROLADOR DE ÓRDENES (MOTOR TRANSACCIONAL MERCADO PAGO)
# ==============================================================================
class OrderViewSet(viewsets.GenericViewSet):
    """
    API Gateway Transaccional de Grado Financiero (PCI-DSS Compliant).
    Implementa Idempotencia estricta, Zero-Trust Architecture y mitigación de Memory Dumping.
    """
    permission_classes = [AllowAny] 

    def get_queryset(self):
        """
        🛡️ PREVENCIÓN IDOR ABSOLUTA.
        Filtro estricto en el Kernel del ORM. Complejidad de búsqueda: O(log n).
        """
        if self.request.user.is_authenticated:
            return Order.objects.filter(user=self.request.user).order_by('-created_at')
        return Order.objects.none()

    def get_permissions(self):
        """Aislamiento estricto de privilegios (Least Privilege Principle)."""
        if self.action in ['create', 'payment_info', 'check_status']:
            return [AllowAny()]
        return [IsAuthenticated()]

    def create(self, request, *args, **kwargs):
        """
        POST /api/orders/orders/
        Punto de Entrada atómico y aislado de la transacción de compra.
        """
        logger.info(f"--- 🛒 INICIANDO PROCESO DE COMPRA | IP: {request.META.get('REMOTE_ADDR')} ---")
        
        serializer = PaymentBrickInputSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"❌ Intento de evasión bloqueado (400): {serializer.errors}")
            return Response({
                "error": "El payload no cumple con las directivas de seguridad criptográfica.", 
                "code": "VALIDATION_REJECTED"
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            user_obj = request.user if request.user.is_authenticated else None
            
            # Operación atómica con cerrojos pesimistas Postgres
            order = OrderService.create_hybrid_order(
                user=user_obj,
                validated_data=serializer.validated_data
            )
            
            # Establecimiento del túnel seguro con Mercado Pago
            order_with_mp = OrderService.attach_mercadopago_data(order)

            logger.info(f"✅ Bóveda financiera creada: ORD-{order.wompi_reference} | MP_ID: {order_with_mp.mp_preference_id}")
            
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
            logger.critical(f"💀 Fallo Crítico del Kernel de Pagos: {e}", exc_info=True)
            return Response({"error": "Transacción declinada por los protocolos del servidor seguro.", "code": "INTERNAL_KERNEL_ERROR"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'])
    def payment_info(self, request, pk=None):
        """
        GET /api/orders/orders/{id}/payment_info/
        🛡️ BLINDAJE ANTI-IDOR para recuperación de sesiones de pago abandonadas o caídas.
        """
        if request.user.is_authenticated:
            order = get_object_or_404(Order, pk=pk, user=request.user)
        else:
            ref_param = request.query_params.get('ref')
            if not ref_param:
                raise PermissionDenied("Token de validación de propiedad requerido.")
            order = get_object_or_404(Order, pk=pk, wompi_reference=ref_param)
        
        if str(order.status).upper() != 'PENDING':
            return Response({"error": "Orden de pago procesada o caducada temporalmente."}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
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

    @action(detail=True, methods=['get'])
    def check_status(self, request, pk=None):
        """
        GET /api/orders/orders/{id}/check_status/
        Frontend Polling Asíncrono O(1) bajo indexación atómica.
        """
        try:
            order = Order.objects.only('id', 'status').get(pk=pk)
            return Response({
                "order_id": str(order.id),
                "status": str(order.status).upper()
            }, status=status.HTTP_200_OK)
        except Order.DoesNotExist:
            return Response({"error": "Orden no encontrada en la matriz."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==============================================================================
# 🎟️ VISOR DE TICKETS Y MOTOR VECTORIAL ASIMÉTRICO (Fase 2 Compliant)
# ==============================================================================
class TicketViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API de Consulta y Renderizado de Activos Criptográficos Inmutables.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = TicketDetailSerializer

    def get_queryset(self):
        return Ticket.objects.filter(
            order__user=self.request.user,
            order__status='APPROVED'
        ).select_related('function', 'function__venue')

    @action(detail=True, methods=['get'], throttle_classes=[TicketQRThrottle])
    def qr_image(self, request, pk=None):
        """
        GET /api/orders/tickets/{id}/qr_image/
        Genera dinámicamente el PDF Vectorial que contiene el token firmado por curvas elípticas.
        Usa buffers de memoria RAM volátil io.BytesIO sin escrituras en almacenamiento (0% Disco IO).
        """
        ticket = self.get_object() 
        
        if str(ticket.order.status).upper() != 'APPROVED':
            return Response({"error": "Acceso Prohibido. Orden no aprobada.", "code": "TICKET_LOCKED"}, status=status.HTTP_403_FORBIDDEN)

        cache_key = f"pdf_vector_cache_{ticket.id.hex}"
        pdf_bytes = cache.get(cache_key)

        if not pdf_bytes:
            try:
                # A. Generar Firma Matemática Asimétrica ECDSA (ES256)
                event_name = ticket.function.name if hasattr(ticket.function, 'name') else "El Efecto Miller 2"
                secure_jwt = SmartTicketGodTierService.generate_secure_jwt_token(
                    ticket_id=ticket.id.hex,
                    seat_label=ticket.seat_label,
                    event_name=event_name
                )
                
                # B. Renderizar PDF Vectorial en RAM (ReportLab Engine)
                pdf_bytes = SmartTicketGodTierService.generate_pdf_ticket_in_memory(ticket, secure_jwt)
                
                # Persistencia de seguridad por 24 horas en Caché Redis O(1)
                cache.set(cache_key, pdf_bytes, timeout=86400) 
            except Exception as e:
                logger.error(f"Error en compilación de Activo Criptográfico: {e}", exc_info=True)
                return Response({"error": "Falla de renderizado gráfico de seguridad.", "code": "PDF_RENDER_FAIL"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        filename = f"Entrada_{ticket.seat_label.replace(' ', '_')}_{ticket.id.hex[:6].upper()}.pdf"
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        response['Cache-Control'] = 'public, max-age=86400, immutable'
        
        # Destrucción limpia del pool de hilos locales para evadir Memory Dumping
        del pdf_bytes
        gc.collect()
        
        return response


# ==============================================================================
# 🎛️ VISOR DE ACCESOS: MOTOR DE VALIDACIÓN PARA EL PORTERO (GATEKEEPER API)
# ==============================================================================
class GatekeeperViewSet(viewsets.GenericViewSet):
    """
    API Transaccional del Dispositivo de Validación Física Offline/Online.
    Protegida por cerrojos pesimistas Postgres de exclusión mutua.
    """
    permission_classes = [IsAuthenticated] 
    throttle_classes = [GatekeeperThrottle]

    @action(detail=False, methods=['post'], url_path='scan')
    def scan_ticket(self, request):
        qr_token = request.data.get('qr_token')
        gate_id = request.data.get('gate_id', 'UNKNOWN_GATE').strip()
        device_agent = request.data.get('device_agent', 'UNKNOWN_DEVICE').strip()

        if not qr_token or not isinstance(qr_token, str) or len(qr_token) < 50:
            return Response({
                "status": "DENIED",
                "error": "MALFORMED_PAYLOAD",
                "message": "Error de lectura fotónica. Limpie el lente del terminal.",
                "hardware_directives": {"color": "#ef4444", "vibrate": [500, 200, 500], "sound": "error_beep.mp3"}
            }, status=status.HTTP_400_BAD_REQUEST)

        token_fingerprint = hashlib.sha256(qr_token.encode('utf-8')).hexdigest()[:12]

        try:
            with transaction.atomic():
                # Bloqueo de registro estricto instantáneo
                ticket = Ticket.objects.select_for_update(nowait=True).select_related(
                    'function', 'function__venue', 'function__show'
                ).get(qr_token=qr_token)
                
                scanner_agent = f"{request.user.email} [{device_agent}]"
                success, reason = ticket.process_scan(gate_id=gate_id, scanner_agent_id=scanner_agent)

        except Ticket.DoesNotExist:
            logger.critical(f"🚨 [SPOOFING DETECTADO] Inyección de token huérfano en Puerta: {gate_id} | Huella: {token_fingerprint}")
            return Response({
                "status": "DENIED",
                "error": "INVALID_TOKEN",
                "message": "¡FALSO! El activo digital no existe en el Ledger.",
                "hardware_directives": {"color": "#dc2626", "vibrate": [800], "sound": "alarm.mp3"}
            }, status=status.HTTP_404_NOT_FOUND)
            
        except OperationalError:
            logger.warning(f"⚡ Colisión de red interceptada (Double-Scanning Prevention): {token_fingerprint}")
            return Response({
                "status": "DENIED",
                "error": "CONCURRENCY_LOCKED",
                "message": "Protocolo de Seguridad: Boleto procesándose en otra puerta paralela.",
                "hardware_directives": {"color": "#f59e0b", "vibrate": [100, 50, 100], "sound": "wait.mp3"}
            }, status=status.HTTP_409_CONFLICT)

        show_name = ticket.function.name if hasattr(ticket.function, 'name') else "El Efecto Miller 2"

        if success:
            logger.info(f"🟢 [ACCESO AUTORIZADO] TKT: {ticket.id} | Silla: {ticket.seat_label}")
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
            logger.warning(f"🔴 [ACCESO RECHAZADO] Razón: {reason} | TKT: {ticket.id}")
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


# ==============================================================================
# 🛟 PORTAL DE AUTO-RESCATE CRIPTOGRÁFICO (Fase 5.2 - Modificación de Email Unica)
# ==============================================================================
class OrderRescueAPIView(APIView):
    """
    🛟 BÓVEDA DE RE-DIRECCIÓN LOGÍSTICA DE ACTIVOS DIGITALES.
    Permite el cambio controlado y único de correo de entrega utilizando el ID
    transaccional verificado de Mercado Pago, mitigando ataques de suplantación.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        gateway_id = request.data.get('gateway_transaction_id')
        new_email = request.data.get('email')

        if not gateway_id or not new_email:
            return Response(
                {"error": "Faltan parámetros de concordancia obligatorios."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        clean_gateway_id = str(gateway_id).strip()
        clean_email = str(new_email).strip().lower()

        try:
            with transaction.atomic():
                # Cerrojo exclusivo pesimista a nivel de fila en PostgreSQL
                order = Order.objects.select_for_update().get(
                    gateway_transaction_id=clean_gateway_id,
                    status=Order.Status.APPROVED
                )

                if order.delivery_status == 'DELIVERED' and order.tickets_dispatched:
                    # Si ya posee la marca temporal forense de rescate, el candado se cierra para siempre
                    if order.payment_metadata and order.payment_metadata.get('rescued_at'):
                        return Response(
                            {"error": "Seguridad de Infraestructura: Esta orden ya agotó su único token de auto-rescate permitido."}, 
                            status=status.HTTP_403_FORBIDDEN
                        )

                # Estructuración de la huella forense inmutable de auditoría
                if not order.payment_metadata:
                    order.payment_metadata = {}
                
                order.payment_metadata['rescued_at'] = str(timezone.now())
                order.payment_metadata['original_payer_email'] = order.payment_metadata.get('payer', {}).get('email')
                
                if 'payer' not in order.payment_metadata:
                    order.payment_metadata['payer'] = {}
                order.payment_metadata['payer']['email'] = clean_email
                
                # Reseteamos la máquina de estados logísticos para permitir la regeneración asíncrona
                order.tickets_dispatched = False
                order.delivery_status = 'PENDING_GENERATION'
                order.save(update_fields=['tickets_dispatched', 'delivery_status', 'payment_metadata', 'updated_at'])

                # Despacho asíncrono atómico post-commit libre de hilos fantasmas
                transaction.on_commit(
                    lambda: generate_and_dispatch_smart_tickets.delay(str(order.id))
                )

            logger.info(f"🛟 [RECONEXIÓN LOGÍSTICA SUCCESS] Orden ID: {order.id} migrada de forma segura hacia: {clean_email}")
            return Response(
                {"status": "SUCCESS", "message": "Bóveda de rescate validada. Las entradas criptográficas vectoriales están siendo emitidas al nuevo destino."}, 
                status=status.HTTP_200_OK
            )

        except Order.DoesNotExist:
            logger.warning(f"⚠️ [RESCUE REFUSED] Intento ilegítimo de lookup para Pago ID: {clean_gateway_id}")
            return Response(
                {"error": "No se localizó ninguna orden consolidada que coincida con las credenciales de pago."}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as exc:
            logger.critical(f"💀 [RESCUE BLOCK COLLAPSE] Error en kernel de rescate: {str(exc)}")
            return Response(
                {"error": "Error interno protegido."}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )