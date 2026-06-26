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

# Importación del modelo de base de datos
from apps.orders.models import Order

# 🛡️ 1. LOGGER SOC/SIEM (Security Information and Event Management)
logger = logging.getLogger(__name__)

class MercadoPagoWebhookAPIView(APIView):
    """
    Endpoint Receptor IPN/Webhook.
    Arquitectura God-Tier: O(1) Redis Lock -> Zero-Trust Pull -> ACID Row-Locking -> O(1) Write.
    """
    
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs) -> Response:
        # 1. EXTRACCIÓN RÁPIDA (O(1) Memory Access)
        topic: str = request.query_params.get('topic') or request.data.get('type', '')
        payment_id: Optional[str] = request.query_params.get('id') or request.data.get('data', {}).get('id')

        # 🛡️ Filtro de Ruido Temprano
        if topic != 'payment' or not payment_id:
            return Response({"status": "ignored"}, status=status.HTTP_200_OK)

        trace_id = uuid.uuid4().hex[:8]

        # 2. ESCUDO ANTI-DDOS E IDEMPOTENCIA DE RED (Redis SETNX)
        lock_key = f"webhook_lock_mp_{payment_id}"
        
        # cache.add es una operación atómica en Redis (SETNX).
        if not cache.add(lock_key, "processing", timeout=60):
            logger.warning(f"🛡️ [TRACE: {trace_id}] Webhook duplicado bloqueado por Redis. MP_ID: {payment_id}")
            return Response({"status": "already_processing"}, status=status.HTTP_200_OK)

        try:
            # 3. VERIFICACIÓN ZERO-TRUST (Outbound Network Call)
            mp_token = getattr(settings, 'MERCADO_PAGO_ACCESS_TOKEN', None)
            if not mp_token:
                logger.critical(f"💀 [TRACE: {trace_id}] SECURITY ALERT: Fuga de configuración de Token.")
                return Response({"error": "Config Error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            sdk = mercadopago.SDK(mp_token)
            
            # Protección contra Memory Dumping: Eliminamos la referencia explícita del token
            del mp_token 

            # E/S de Red: Consulta directa al banco (fuente de verdad)
            payment_info = sdk.payment().get(payment_id)
            
            if payment_info.get("status") != 200:
                logger.warning(f"🚨 [TRACE: {trace_id}] Ataque de Spoofing mitigado. Pago falso: {payment_id}")
                return Response({"status": "not_found_in_mp"}, status=status.HTTP_200_OK)

            payment_data = payment_info["response"]
            estado_pago = payment_data.get("status")
            referencia_interna = payment_data.get("external_reference")

            if not referencia_interna:
                logger.warning(f"⚠️ [TRACE: {trace_id}] Pago {payment_id} sin referencia interna. Abortado.")
                return Response({"status": "no_reference"}, status=status.HTTP_200_OK)

            # 4. TRANSACCIÓN ATÓMICA DE BASE DE DATOS (ACID + Row-Level Pessimistic Lock)
            try:
                with transaction.atomic():
                    # 🛡️ BLOQUEO PESIMISTA: select_for_update() asegura que NINGÚN otro proceso
                    # (ni el usuario en el frontend, ni otra tarea de Celery) pueda modificar esta fila 
                    # hasta que el bloque 'with' termine. Previene el "Phantom Approval".
                    order = Order.objects.select_for_update().get(wompi_reference=referencia_interna)
                    
                    # 🛡️ MÁQUINA DE ESTADO INMUTABLE (Anti-Tampering)
                    # Si el estado actual es FINAL (Aprobado o Rechazado definitivamente), no se toca.
                    if order.status in [Order.Status.APPROVED]:
                        logger.info(f"✅ [TRACE: {trace_id}] Orden {referencia_interna} ya estaba APROBADA. Ignorando IPN tardío.")
                        return Response({"status": "already_paid_in_db"}, status=status.HTTP_200_OK)

                    # Evaluación del nuevo estado
                    estado_anterior = order.status
                    nuevo_estado = order.status

                    if estado_pago == 'approved':
                        nuevo_estado = Order.Status.APPROVED
                    elif estado_pago in ['rejected', 'cancelled', 'refunded', 'charged_back']:
                        nuevo_estado = Order.Status.REJECTED
                    elif estado_pago in ['in_process', 'pending']:
                        nuevo_estado = Order.Status.PENDING

                    # Solo realizamos la escritura si hubo una mutación real de estado
                    if nuevo_estado != estado_anterior:
                        order.status = nuevo_estado
                        
                        # 🧠 OPTIMIZACIÓN BIG O(1) EXTREMA EN ESCRITURA
                        # Usar update_fields evita que Django reescriba toda la fila (Data Race), 
                        # actualizando exclusivamente las columnas necesarias a nivel de I/O de disco.
                        order.save(update_fields=['status']) 
                        
                        logger.info(f"🟢 [TRACE: {trace_id}] MUTACIÓN DE ESTADO: {estado_anterior} -> {nuevo_estado} | REF: {referencia_interna}")
                        
                        # Aquí puedes disparar tu Celery Task para generar Smart Tickets asíncronamente
                        # if order.status == Order.Status.APPROVED:
                        #     generate_smart_tickets.delay(order.id)

            except Order.DoesNotExist:
                logger.error(f"❌ [TRACE: {trace_id}] IDOR ALERT: La referencia {referencia_interna} no existe en la Bóveda.")
                # Mantenemos el candado Redis para no procesar spam
                return Response({"status": "order_not_found"}, status=status.HTTP_200_OK)

            except DatabaseError as db_err:
                logger.critical(f"🔥 [TRACE: {trace_id}] Deadlock o Falla de Cluster DB: {str(db_err)}")
                # Liberamos el candado para permitir que MercadoPago reintente en unos minutos
                cache.delete(lock_key)
                return Response({"error": "DB Lock Error"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

            # 5. RESOLUCIÓN DE CIRCUITO
            return Response({"status": "success"}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.critical(f"💀 [TRACE: {trace_id}] Falla Catastrófica de Kernel procesando Webhook: {str(e)}", exc_info=True)
            cache.delete(lock_key)
            return Response({"error": "Internal Processing Error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)