import logging
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.utils import timezone

from apps.orders.models import Order
from apps.orders.adapters.wompi import WompiAdapter
# from apps.orders.tasks import generar_tickets_async  # Importa tu tarea de Celery/background

# 1. ELIMINAMOS PRINT: Usamos un logger profesional (No bloqueante)
logger = logging.getLogger(__name__)

class WompiWebhookView(APIView):
    """
    Bóveda Transaccional de Wompi - Conclave God Tier
    """
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            # 1. EXTRACCIÓN SEGURA (O(1) memory lookup)
            payload = request.data
            transaction_data = payload.get('data', {}).get('transaction', {})
            signature_received = payload.get('signature', {}).get('checksum')
            timestamp = payload.get('timestamp')

            if not all([transaction_data, signature_received, timestamp]):
                logger.warning("Payload incompleto recibido en webhook.")
                return Response({"error": "Bad Request"}, status=status.HTTP_400_BAD_REQUEST)

            # 2. VALIDACIÓN CRIPTOGRÁFICA (Zero-Trust Security)
            is_valid = WompiAdapter.validate_webhook_signature(
                transaction_data, timestamp, signature_received
            )
            
            if not is_valid:
                logger.critical(
                    f"Firma criptográfica inválida. Posible ataque de spoofing. IP: {request.META.get('REMOTE_ADDR')}"
                )
                return Response({"error": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED)

            reference = transaction_data.get('reference')
            wompi_status = transaction_data.get('status')
            wompi_trx_id = transaction_data.get('id')

            # 3. ZONA DE AISLAMIENTO TRANSACCIONAL (Pessimistic Locking)
            # Todo el proceso de lectura, evaluación y escritura ocurre en un túnel atómico.
            with transaction.atomic():
                try:
                    # select_for_update() bloquea la fila a nivel de motor SQL. 
                    # Ningún otro proceso puede leer ni tocar esta orden hasta que terminemos.
                    order = Order.objects.select_for_update().get(wompi_reference=reference)
                except Order.DoesNotExist:
                    logger.error(f"Orden no encontrada en base de datos. Referencia: {reference}")
                    return Response({"error": "Order Not Found"}, status=status.HTTP_404_NOT_FOUND)

                # 4. MÁQUINA DE ESTADOS ESTRICTA (Idempotencia)
                if order.status == Order.Status.APPROVED:
                    logger.info(f"Webhook repetido ignorado: La orden {reference} ya estaba aprobada.")
                    return Response({"status": "Already approved"}, status=status.HTTP_200_OK)

                # Si la orden ya fue rechazada y llega otro intento de rechazo, ignorar.
                if order.status == Order.Status.REJECTED and wompi_status in ['VOIDED', 'DECLINED', 'ERROR']:
                    return Response({"status": "Already rejected"}, status=status.HTTP_200_OK)

                # 5. MUTACIÓN DE ESTADO QUIRÚRGICA
                if wompi_status == 'APPROVED':
                    order.status = Order.Status.APPROVED
                    order.wompi_transaction_id = wompi_trx_id
                    
                    # save(update_fields) evita colisiones de memoria (Memory Dumping prevention)
                    order.save(update_fields=['status', 'wompi_transaction_id'])
                    
                    logger.info(f"💰 DINERO EN CAJA: Orden {reference} APROBADA exitosamente.")

                    # 6. DELEGACIÓN ASÍNCRONA SEGURA
                    # on_commit garantiza que la tarea de correos SOLO se dispare 
                    # si la base de datos hizo el commit exitosamente. No hay QRs fantasma.
                    # transaction.on_commit(lambda: generar_tickets_async.delay(order.id))

                elif wompi_status in ['VOIDED', 'DECLINED', 'ERROR']:
                    order.status = Order.Status.REJECTED
                    order.save(update_fields=['status'])
                    logger.info(f"❌ PAGO RECHAZADO: Orden {reference} actualizada a rechazada.")

            # Responder a Wompi en O(1) tan pronto se libera el lock de la DB
            return Response({"status": "Procesado"}, status=status.HTTP_200_OK)

        except Exception as e:
            # Captura de Memory Dumps o fallos no controlados
            logger.error(f"Falla crítica en Motor de Pagos: {str(e)}", exc_info=True)
            return Response({"error": "Internal Error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)