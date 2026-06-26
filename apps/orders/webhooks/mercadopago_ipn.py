# apps/orders/webhooks/mercadopago_ipn.py
import logging
import uuid
from typing import Optional

import mercadopago
from django.conf import settings
from django.core.cache import cache
from django.db import transaction, DatabaseError
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny

from apps.orders.models import Order

logger = logging.getLogger(__name__)

class MercadoPagoWebhookAPIView(APIView):
    """
    Endpoint Receptor IPN/Webhook.
    Arquitectura God-Tier: O(1) Redis Lock -> Zero-Trust Pull -> ACID Row-Locking -> O(1) Write.
    """
    
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs) -> Response:
        topic: str = request.query_params.get('topic') or request.data.get('type', '')
        payment_id: Optional[str] = request.query_params.get('id') or request.data.get('data', {}).get('id')

        if topic != 'payment' or not payment_id:
            return Response({"status": "ignored"}, status=status.HTTP_200_OK)

        trace_id = uuid.uuid4().hex[:8]
        lock_key = f"webhook_lock_mp_{payment_id}"
        
        if not cache.add(lock_key, "processing", timeout=60):
            logger.warning(f"🛡️ [TRACE: {trace_id}] Webhook duplicado bloqueado por Redis. MP_ID: {payment_id}")
            return Response({"status": "already_processing"}, status=status.HTTP_200_OK)

        try:
            mp_token = getattr(settings, 'MERCADO_PAGO_ACCESS_TOKEN', None)
            if not mp_token:
                logger.critical(f"💀 [TRACE: {trace_id}] SECURITY ALERT: Fuga de configuración de Token.")
                cache.delete(lock_key)
                return Response({"error": "Config Error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            sdk = mercadopago.SDK(mp_token)
            del mp_token 

            payment_info = sdk.payment().get(payment_id)
            
            if payment_info.get("status") != 200:
                logger.warning(f"🚨 [TRACE: {trace_id}] Ataque de Spoofing mitigado. Pago falso: {payment_id}")
                cache.delete(lock_key)
                return Response({"status": "not_found_in_mp"}, status=status.HTTP_200_OK)

            payment_data = payment_info["response"]
            estado_pago = payment_data.get("status")
            referencia_interna = payment_data.get("external_reference")

            if not referencia_interna:
                logger.warning(f"⚠️ [TRACE: {trace_id}] Pago {payment_id} sin referencia interna. Abortado.")
                cache.delete(lock_key)
                return Response({"status": "no_reference"}, status=status.HTTP_200_OK)

            try:
                with transaction.atomic():
                    order = Order.objects.select_for_update().get(id=referencia_interna)
                    
                    if order.status in [Order.Status.APPROVED]:
                        logger.info(f"✅ [TRACE: {trace_id}] Orden {referencia_interna} ya estaba APROBADA. Ignorando IPN tardío.")
                        return Response({"status": "already_paid_in_db"}, status=status.HTTP_200_OK)

                    estado_anterior = order.status
                    nuevo_estado = order.status

                    if estado_pago == 'approved':
                        nuevo_estado = Order.Status.APPROVED
                    elif estado_pago in ['rejected', 'cancelled', 'refunded', 'charged_back']:
                        nuevo_estado = Order.Status.REJECTED
                    elif estado_pago in ['in_process', 'pending']:
                        nuevo_estado = Order.Status.PENDING

                    if nuevo_estado != estado_anterior:
                        order.status = nuevo_estado
                        order.mp_transaction_id = payment_id
                        
                        order.save(update_fields=['status', 'mp_transaction_id']) 
                        
                        logger.info(f"🟢 [TRACE: {trace_id}] MUTACIÓN DE ESTADO: {estado_anterior} -> {nuevo_estado} | REF: {referencia_interna}")

            except Order.DoesNotExist:
                logger.error(f"❌ [TRACE: {trace_id}] IDOR ALERT: La referencia {referencia_interna} no existe en la Bóveda.")
                return Response({"status": "order_not_found"}, status=status.HTTP_200_OK)

            except DatabaseError as db_err:
                logger.critical(f"🔥 [TRACE: {trace_id}] Deadlock o Falla de Cluster DB: {str(db_err)}")
                cache.delete(lock_key)
                return Response({"error": "DB Lock Error"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

            return Response({"status": "success"}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.critical(f"💀 [TRACE: {trace_id}] Falla Catastrófica de Kernel procesando Webhook: {str(e)}", exc_info=True)
            cache.delete(lock_key)
            return Response({"error": "Internal Processing Error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)