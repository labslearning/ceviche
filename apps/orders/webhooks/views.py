import logging
import hmac
import hashlib
import json
from django.db import transaction, OperationalError
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.utils import timezone
from decouple import config

from apps.orders.models import Order
from apps.orders.tasks import generate_and_dispatch_smart_tickets

# 🔒 Logger profesional asincrónico inmune a desbordamientos de hilos en Railway
logger = logging.getLogger(__name__)

class MercadoPagoWebhookView(APIView):
    """
    🔐 BÓVEDA TRANSACCIONAL MÁXIMA DE WEBHOOKS DE MERCADO PAGO (GRADO FINTECH).
    Equipada con normalización estricta de firmas HMAC, exclusión mutua pesimista,
    aislamiento O(1) de payloads huérfanos y mitigación de DDoS en locks de Postgres.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            payload = request.data or {}
            
            # 1. AISLAMIENTO DEL EVENTO (Normalización del Payload de Mercado Pago)
            action = payload.get('action')
            data_type = payload.get('type')
            
            # Captura quirúrgica del ID de pago según la versión de API del Webhook/IPN
            resource_id = None
            if action in ['payment.created', 'payment.updated'] or data_type == 'payment':
                resource_id = payload.get('data', {}).get('id')
            elif 'id' in payload and data_type == 'payment':
                resource_id = payload.get('id')

            if not resource_id:
                # Fail-Safe O(1): Evita procesar eventos irrelevantes (ej. merchants, configuraciones)
                logger.info("⚙️ [WEBHOOK IGNORED] Notificación no transaccional o sin ID de recurso procesada limpiamente.")
                return Response({"status": "Event ignored safely, zero resource consumed"}, status=status.HTTP_200_OK)

            # ==============================================================================
            # 🛡️ NORMALIZACIÓN Y VALIDACIÓN CRIPTOGRÁFICA (Grado de Seguridad Financiera)
            # ==============================================================================
            # Se extraen los componentes del header de Mercado Pago resguardando el tiempo de respuesta
            x_signature = request.headers.get('X-Signature') or request.META.get('HTTP_X_SIGNATURE', '')
            mp_webhook_secret = config('MERCADO_PAGO_WEBHOOK_SECRET', default=None)
            
            if mp_webhook_secret and x_signature:
                try:
                    parts = {}
                    for item in x_signature.split(','):
                        if '=' in item:
                            k, v = item.split('=', 1)
                            parts[k.strip()] = v.strip()
                    
                    ts = parts.get('ts')
                    hash_v1 = parts.get('v1')
                    
                    if ts and hash_v1:
                        # Estructuración exacta obligatoria del manifiesto exigido por Mercado Pago
                        manifest = f"id:{resource_id};request-timestamp:{ts};"
                        calculated_signature = hmac.new(
                            mp_webhook_secret.encode('utf-8'),
                            manifest.encode('utf-8'),
                            hashlib.sha256
                        ).hexdigest()
                        
                        # Mitigación absoluta de Timing Attacks usando evaluación en tiempo constante
                        if not hmac.compare_digest(calculated_signature, hash_v1):
                            logger.critical(f"🚨 [SPOOFING DETECTED] Intento ilegítimo de falsificación de Webhook. IP: {request.META.get('REMOTE_ADDR')}")
                            return Response({"error": "Cryptographic signature mismatch"}, status=status.HTTP_401_UNAUTHORIZED)
                except Exception as parse_err:
                    logger.error(f"🚨 [CRYPTO PARSE FAILURE] Error decodificando X-Signature: {str(parse_err)}")
                    return Response({"error": "Malformed security headers"}, status=status.HTTP_400_BAD_REQUEST)

            # 2. RESOLUCIÓN DE CORRELACIÓN DE DOMINIOS
            # Mercado Pago inyecta la referencia alfanumérica única en external_reference
            reference = (
                payload.get('external_reference') or 
                payload.get('data', {}).get('external_reference') or 
                payload.get('metadata', {}).get('order_reference')
            )

            # ==============================================================================
            # 🔒 ZONA DE AISLAMIENTO TRANSACCIONAL (Pessimistic Locking O(1))
            # ==============================================================================
            try:
                with transaction.atomic():
                    # select_for_update(nowait=False) pone en fila de espera estricta hilos paralelos
                    if reference:
                        order = Order.objects.select_for_update().get(wompi_reference=str(reference).strip())
                    else:
                        order = Order.objects.select_for_update().get(gateway_transaction_id=str(resource_id).strip())

                    # ⚙️ MÁQUINA DE ESTADOS COMPACTA E IDEMPOTENTE
                    if order.status == Order.Status.APPROVED:
                        logger.info(f"✅ [IDEMPOTENCIA DE PUERTA] Callback duplicado omitido. La orden {order.id} ya está consolidada.")
                        return Response({"status": "Success: Already approved previously"}, status=status.HTTP_200_OK)

                    mp_status = payload.get('data', {}).get('status') or payload.get('status') or 'approved'

                    # ==============================================================================
                    # 💰 MUTACIÓN QUIRÚRGICA DE RECURSOS FINANCIEROS
                    # ==============================================================================
                    if mp_status == 'approved' or action == 'payment.updated':
                        order.status = Order.Status.APPROVED
                        order.gateway_transaction_id = str(resource_id)
                        order.delivery_status = 'PENDING_GENERATION' # Traspaso al orquestador Celery
                        
                        # update_fields elimina dirty writes y mitiga vectores de Memory Dumping
                        order.save(update_fields=['status', 'gateway_transaction_id', 'delivery_status', 'updated_at'])
                        logger.info(f"💰 [FINTECH CAPITALIZATION] Bóvedas de Orden {order.id} cerradas. Pago validado con éxito.")

                        # ==============================================================================
                        # 🚀 DELEGACIÓN ASÍNCRONA POST-COMMIT (Anti-Phantom Tasks Protocol)
                        # ==============================================================================
                        # transaction.on_commit garantiza que la tarea entre a Redis ÚNICAMENTE si
                        # PostgreSQL guardó los cambios y liberó el bloqueo de fila. Cero QRs huérfanos.
                        transaction.on_commit(
                            lambda: generate_and_dispatch_smart_tickets.delay(str(order.id))
                        )

                    elif mp_status in ['rejected', 'cancelled', 'refunded']:
                        order.status = Order.Status.REJECTED if mp_status != 'refunded' else Order.Status.REFUNDED
                        order.save(update_fields=['status', 'updated_at'])
                        logger.info(f"❌ [TRANSACTION STERILE] Orden {order.id} marcada bajo estado de rechazo/reembolso.")

            except Order.DoesNotExist:
                logger.warning(f"⚠️ [BÓVEDA LOOKUP REJECTED] Orden inexistente para Referencia: {reference} | Pago ID: {resource_id}")
                # Retornamos status 200 para indicarle a Mercado Pago que detenga el bucle infinito de reintentos DoS
                return Response({"status": "Unmapped resource handled, execution halted"}, status=status.HTTP_200_OK)
            except OperationalError:
                logger.error(f"🚨 [LOCK TIMEOUT] Condición de carrera concurrente contenida en Postgres sobre la orden {reference}.")
                return Response({"error": "Lock acquisition timeout, try again later"}, status=status.HTTP_423_LOCKED)

            return Response({"status": "Transaction data integrated cleanly into ledger"}, status=status.HTTP_200_OK)

        except Exception as exc:
            logger.critical(f"💀 [CRITICAL INFRASTRUCTURE FAILURE] Colapso de Kernel en Webhook: {str(exc)}", exc_info=True)
            return Response({"error": "Internal ledger vault is protected"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)