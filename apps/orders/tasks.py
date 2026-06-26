import logging
import datetime
from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.core.cache import cache
from django.conf import settings
from django.utils.html import strip_tags
from django.utils import timezone
from django.db import transaction, DatabaseError

# Importaciones de Modelos y Servicios
from apps.orders.models import Order, Ticket
from apps.orders.services import QRService

logger = logging.getLogger(__name__)

# ==============================================================================
# 📨 TAREA 1: DESPACHO CRIPTOGRÁFICO DE CORREOS (ENTREGA ASÍNCRONA RESILIENTE)
# ==============================================================================

@shared_task(
    bind=True,
    # 🛡️ INFINITE RETRY + EXPONENTIAL BACKOFF: Si SMTP falla, reintenta infinitamente 
    # espaciando el tiempo (30s, 1m, 2m, 4m, 8m...) para evitar DDos interno.
    autoretry_for=(Exception,), 
    retry_backoff=30, 
    retry_backoff_max=3600,
    max_retries=None, 
    queue='financial_deliveries'
)
def process_order_tickets_and_email(self, order_id: str):
    """
    WORKER TASK (Grado Fintech).
    Desacoplamiento Absoluto: El fallo en la entrega jamás altera el estado financiero.
    """
    logger.info(f"⚙️ [WORKER RUNNING] Inicializando despacho para Orden ID: {order_id}")
    
    sent_flag_key = f"flag_email_sent_{order_id}"

    # 1. ESCUDO DE IDEMPOTENCIA (O(1) Redis Lock)
    if cache.get(sent_flag_key):
        logger.info(f"✅ [IDEMPOTENCIA] Tickets ya despachados para la orden {order_id}. Abortando duplicado.")
        return "ALREADY_SENT"

    try:
        # 2. BLOQUEO PESIMISTA: Protegemos la orden mientras preparamos los tickets
        with transaction.atomic():
            # 🚀 ANTI-N+1 SHIELD
            order = Order.objects.select_for_update().prefetch_related(
                'tickets__function__venue'
            ).get(pk=order_id)
            
            if order.status != Order.Status.APPROVED:
                logger.warning(f"⚠️ [WORKER ABORT] Orden {order_id} no está aprobada (Actual: {order.status}).")
                return "ABORTED_INVALID_STATUS"

            # 🛡️ MÁQUINA DE ESTADO DESACOPLADA (Dominio Logístico)
            # Asegúrate de tener un campo `delivery_status` en tu modelo Order
            if hasattr(order, 'delivery_status'):
                if order.delivery_status == 'DELIVERED':
                    return "ALREADY_DELIVERED_IN_DB"
                order.delivery_status = 'PENDING_GENERATION'
                order.save(update_fields=['delivery_status'])

        recipient_email = order.user.email if order.user else None
        if not recipient_email and order.payment_metadata:
             recipient_email = order.payment_metadata.get('payer', {}).get('email')
             
        if not recipient_email:
            # Si no hay correo, loggeamos como crítico, pero la orden SIGUE APROBADA.
            logger.critical(f"💀 [DATA LEAK PREVENTED] No hay correo destino en la orden {order_id}")
            return "FAILED_NO_EMAIL"

        attachments = []
        tickets_data = []

        # 3. 🧠 GENERACIÓN DE ACTIVOS DIGITALES (O(1) MEMORY POOLING)
        for ticket in order.tickets.all():
            cache_key_qr = f"qr_cache_{ticket.id.hex}"
            qr_bytes = cache.get(cache_key_qr)

            if not qr_bytes:
                logger.info(f"💡 Cache Miss (Ticket {ticket.id.hex}). Compilando matriz binaria.")
                qr_bytes = QRService.generate_qr_image(ticket.qr_token)
                cache.set(cache_key_qr, qr_bytes, timeout=86400) # Persistencia de 24h

            function_name = ticket.function.name if hasattr(ticket.function, 'name') else "Evento Especial"
            
            tickets_data.append({
                'seat': ticket.seat_label,
                'category': ticket.seat_category,
                'show': function_name,
                'date': ticket.function.date_time.strftime('%Y-%m-%d %H:%M'),
                'venue': getattr(ticket.function.venue, 'name', 'Ubicación General')
            })

            attachments.append((
                f"Ticket_{ticket.seat_label}_{ticket.id.hex[:6]}.png",
                qr_bytes,
                "image/png"
            ))

        # 4. 📄 COMPILACIÓN DEL PAQUETE Y TÚNEL SMTP
        context = {
            'order_reference': order.wompi_reference or str(order.id)[:8].upper(),
            'total_amount': order.total_amount,
            'currency': getattr(order, 'currency', 'COP'),
            'tickets': tickets_data,
            'platform_name': "Ceviche Platform"
        }

        html_content = render_to_string('emails/tickets_delivery.html', context)
        text_content = strip_tags(html_content)

        email = EmailMultiAlternatives(
            subject=f"🎟️ Tus Entradas Están Listas - Ref: {context['order_reference']}",
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient_email]
        )
        email.attach_alternative(html_content, "text/html")

        # Inyección de Binarios Aislados
        for filename, content, mimetype in attachments:
            email.attach(filename, content, mimetype)

        # 🛡️ DESPACHO ATÓMICO SMTP (Bloqueante)
        email.send(fail_silently=False)
        
        # 5. ACTUALIZACIÓN DEL ESTADO LOGÍSTICO Y CIERRE
        if hasattr(order, 'delivery_status'):
            with transaction.atomic():
                order_update = Order.objects.select_for_update().get(pk=order_id)
                order_update.delivery_status = 'DELIVERED'
                order_update.save(update_fields=['delivery_status'])

        # Sello de Idempotencia Inmutable (Persistencia 30 días)
        cache.set(sent_flag_key, "DELIVERED", timeout=2592000) 
        
        logger.info(f"📨 [DESPACHO SUCCESS] Correo emitido a {recipient_email} (Ref: {context['order_reference']})")
        return f"SUCCESS_DELIVERED_TO_{recipient_email}"

    except Order.DoesNotExist:
        logger.error(f"❌ Orden {order_id} no encontrada (Fallo asincrónico DB).")
        raise # Delega al retry
        
    except Exception as exc:
        logger.critical(f"🚨 Falla en túnel SMTP o compilación: {exc}")
        # El decorador @shared_task interceptará esta excepción y aplicará el Exponential Backoff
        raise
        
    finally:
        # Prevención de Memory Dumping / CPU Exhaustion liberando binarios manualmente
        if 'attachments' in locals():
            del attachments
        if 'tickets_data' in locals():
            del tickets_data


# ==============================================================================
# 🧹 TAREA 2: SEGADOR DE MEMORIA (GLOBAL GARBAGE COLLECTOR)
# ==============================================================================

@shared_task(name="orders.purge_orphaned_reservations")
def purge_orphaned_reservations():
    """
    🛡️ SWEEPER DE NIVEL BANCARIO (Anti-Deadlock Mechanism)
    Libera inventario sin colisionar con los Webhooks entrantes.
    """
    logger.info("📡 [SWEEPER INICIADO] Escaneando anomalías en la bóveda de inventario...")
    
    expiration_time = timezone.now() - datetime.timedelta(minutes=15)

    try:
        with transaction.atomic():
            # 🛡️ GOD-TIER FIX: select_for_update(skip_locked=True)
            # CRÍTICO: Si el webhook de MP está actualizando una orden en este exacto milisegundo, 
            # el Sweeper la ignorará (skip_locked) en lugar de causar un bloqueo (Deadlock).
            expired_orders = Order.objects.select_for_update(skip_locked=True).filter(
                status=Order.Status.PENDING, 
                created_at__lt=expiration_time
            )

            # Para evitar cargar todo en memoria, extraemos solo los IDs a purgar
            expired_order_ids = list(expired_orders.values_list('id', flat=True))

            if not expired_order_ids:
                logger.info("✅ [SWEEPER] Clúster limpio. No se encontraron bloqueos huérfanos accesibles.")
                return "CLEAN_CLUSTER"

            # 💥 DESTRUCCIÓN ATÓMICA Y SILENCIOSA
            tickets_released = Ticket.objects.filter(
                order_id__in=expired_order_ids
            ).update(state='VOIDED') 

            orders_cancelled = Order.objects.filter(
                id__in=expired_order_ids
            ).update(status=Order.Status.REJECTED)

        logger.info(
            f"🔥 [SWEEPER EJECUTADO] Matriz purgada exitosamente. "
            f"Sillas liberadas: {tickets_released} | Bóvedas destruidas: {orders_cancelled}"
        )
        
        return f"Purged {orders_cancelled} orders and freed {tickets_released} seats."

    except DatabaseError as e:
        logger.error(f"⚠️ [SWEEPER ALERT] Falla transaccional limpiando bóvedas: {e}")
        return "SWEEPER_ERROR_DB_LOCK"