import logging
from django.db import models, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from apps.orders.models import Order
from apps.orders.tasks import process_order_tickets_and_email

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Order)
def order_approved_signal_handler(sender, instance, created, update_fields, **kwargs):
    """
    Escucha atómica de la Bóveda Financiera.
    Solo inyecta la tarea en Celery si la orden pasó a estado APPROVED.
    Mitiga Race Conditions esperando el COMMIT de la base de datos.
    """
    # Si la orden se acaba de crear, nace en PENDING, por ende no procesamos correo aún
    if created:
        return

    # 🛡️ Blindaje contra Signal Loops: Si el cambio no es el estatus, abortamos ejecución
    if update_fields and 'status' not in update_fields:
        return

    if instance.status == Order.Status.APPROVED:
        logger.info(f"📡 [SIGNAL DETECTED] Orden ORD-{instance.wompi_reference} aprobada. Preparando despacho asíncrono...")
        
        # 🚀 REGLA DE ORO DE HI PER-ESCALA: Detener el disparo hasta que el SQL haga COMMIT real
        transaction.on_commit(
            lambda: process_order_tickets_and_email.delay(str(instance.id))
        )
