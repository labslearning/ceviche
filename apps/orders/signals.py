"""
🚀 SISTEMA NERVIOSO CENTRAL DE EVENTOS (GRADO FINTECH).
Ruta: apps/orders/signals.py
Arquitectura: Despachador de Tareas Celery Anti-Double-Dispatch + Transmisor de Telemetría O(1).
"""
import logging
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from apps.orders.models import Order, AdminPaymentLedger, AdminCommunicationLog
from apps.orders.tasks import process_order_tickets_and_email

# 🔒 Logger aislado para monitoreo forense de señales
logger = logging.getLogger(__name__)

# ==============================================================================
# 1. MOTOR TELEMÉTRICO (WEBSOCKET BROADCASTER)
# ==============================================================================
def broadcast_to_admins(payload_data: dict) -> None:
    """
    Inyecta eventos financieros de manera atómica al clúster de Redis Channel Layer.
    Aislamiento de hilo O(1) con manejo estricto de excepciones para evitar bloqueos del GIL.
    """
    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                "admin_fintech_audit_stream",
                {
                    "type": "send_audit_event",
                    "payload": payload_data
                }
            )
    except Exception as e:
        logger.error(f"🚨 [BROADCAST CRITICAL ERROR] Falla al comunicar con el túnel de auditoría: {str(e)}")


# ==============================================================================
# 2. DISPARADOR DEL PIPELINE CRIPTOGRÁFICO Y CORREOS (CONCLAVE SHIELD)
# ==============================================================================
@receiver(post_save, sender=Order)
def order_approved_signal_handler(sender, instance, created, update_fields, **kwargs):
    """
    Escucha atómica de la Bóveda Financiera con mitigación activa de Race Conditions.
    Despacha la tarea de Celery ÚNICAMENTE si la orden está pagada y NO ha sido despachada.
    """
    if created:
        return

    # 🛡️ Blindaje de memoria: Abortar si los campos mutados no nos interesan
    if update_fields and not any(field in update_fields for field in ['status', 'tickets_dispatched']):
        return

    # 🛡️ IDEMPOTENCY CHECK (Anti Double-Dispatching)
    # Evita el envío masivo de correos si un Webhook duplicado intenta re-aprobar la orden
    if instance.status == Order.Status.APPROVED and not instance.tickets_dispatched:
        
        logger.info(f"⚡ [DISPATCH SECURE PIPELINE] Orden {instance.wompi_reference} consolidada. Encolando emisión criptográfica...")
        
        # 🚀 Regla de Hiper-Escala: Despachar a Celery SÓLO tras el COMMIT de PostgreSQL
        transaction.on_commit(
            lambda: process_order_tickets_and_email.delay(str(instance.id))
        )


# ==============================================================================
# 3. SENSORES DE AUDITORÍA PARA EL DASHBOARD (TIEMPO REAL)
# ==============================================================================
@receiver(post_save, sender=AdminPaymentLedger)
def stream_payment_ledger_realtime(sender, instance, created, **kwargs):
    """Intercepta registros financieros crudos y los inyecta en el monitor del administrador."""
    if created:
        payload = {
            "event_type": "PAYMENT_LEDGER",
            "order_id": str(instance.order_id),
            "reference": str(instance.gateway_reference),
            "gateway": str(instance.gateway),
            "amount": str(instance.order.total_amount),
            "timestamp": instance.processed_at.strftime('%Y-%m-%d %H:%M:%S')
        }
        # Esperar confirmación atómica en BD para evitar la propagación de datos "fantasma"
        transaction.on_commit(lambda: broadcast_to_admins(payload))


@receiver(post_save, sender=AdminCommunicationLog)
def stream_communication_log_realtime(sender, instance, created, **kwargs):
    """Transmite telemétricamente el éxito o fallo del envío del código QR al correo del usuario."""
    if created:
        payload = {
            "event_type": "COMMUNICATION_LOG",
            "order_id": str(instance.order_id),
            "email": str(instance.recipient_email),
            "subject": str(instance.subject),
            "status": str(instance.delivery_status),
            "timestamp": instance.sent_at.strftime('%Y-%m-%d %H:%M:%S')
        }
        transaction.on_commit(lambda: broadcast_to_admins(payload))