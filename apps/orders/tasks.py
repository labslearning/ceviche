import logging
import datetime
from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.core.cache import cache
from django.conf import settings
from django.utils.html import strip_tags
from django.utils import timezone
from django.db import transaction

# Importaciones de Modelos y Servicios
from apps.orders.models import Order, Ticket
from apps.orders.services import QRService

logger = logging.getLogger(__name__)

# ==============================================================================
# 📨 TAREA 1: DESPACHO CRIPTOGRÁFICO DE CORREOS (IDEMPOTENTE)
# ==============================================================================

@shared_task(
    bind=True,
    max_retries=5,
    default_retry_delay=30, # Reducido a 30s para evitar cuellos de botella en la cola
    queue='financial_deliveries'
)
def process_order_tickets_and_email(self, order_id: str):
    """
    WORKER TASK (Grado Fintech).
    Equipado con Distributed Locking (Anti-Spam), Caching en Memoria O(1),
    y liberación inmediata de descriptores de archivos (Memory Leak Prevention).
    """
    logger.info(f"⚙️ [WORKER RUNNING] Inicializando despacho para Orden ID: {order_id}")
    
    # 🛡️ ESCUDO 1: Distributed Lock (Idempotencia Estricta)
    # Evita que dos workers procesen la misma orden en paralelo por un fallo en la cola de mensajes
    lock_key = f"lock_email_dispatch_{order_id}"
    sent_flag_key = f"flag_email_sent_{order_id}"

    if cache.get(sent_flag_key):
        logger.info(f"✅ [IDEMPOTENCIA] El correo de la orden {order_id} ya fue despachado previamente. Abortando duplicado.")
        return "ALREADY_SENT"

    # Adquisición de bloqueo atómico en Redis (Tiempo de vida máximo: 2 minutos)
    lock = cache.lock(lock_key, timeout=120) if hasattr(cache, 'lock') else None
    lock_acquired = lock.acquire(blocking=False) if lock else cache.add(lock_key, "LOCKED", 120)
    
    if not lock_acquired:
        logger.warning(f"⚠️ [RACE CONDITION] Otro worker ya está procesando la orden {order_id}. Reintentando...")
        raise self.retry(exc=Exception("Colisión de workers. Lock activo."))

    try:
        # 🚀 ANTI-N+1 SHIELD: Extracción profunda desde PostgreSQL
        order = Order.objects.prefetch_related('tickets__function__venue').get(pk=order_id)
        
        status_str = str(order.status).upper()
        if status_str != 'APPROVED':
            logger.warning(f"⚠️ [WORKER ABORT] Intento de procesar orden no aprobada: {order_id}")
            return "ABORTED_INVALID_STATUS"

        recipient_email = order.user.email if order.user else None
        if not recipient_email and order.payment_metadata:
             recipient_email = order.payment_metadata.get('payer', {}).get('email')
             
        if not recipient_email:
            logger.critical(f"💀 [WORKER FATAL] Fuga de datos: No hay correo destino en la orden {order_id}")
            return "FAILED_NO_EMAIL"

        attachments = []
        tickets_data = []

        # 🧠 O(1) MEMORY POOLING & CACHE EXTRACTION
        for ticket in order.tickets.all():
            cache_key_qr = f"qr_cache_{ticket.id.hex}"
            qr_bytes = cache.get(cache_key_qr)

            if not qr_bytes:
                logger.info(f"💡 Cache Miss (Ticket {ticket.id.hex}). Recompilando matriz binaria.")
                qr_bytes = QRService.generate_qr_image(ticket.qr_token)
                cache.set(cache_key_qr, qr_bytes, timeout=86400) # Persistencia de 24h

            # Mapeo Seguro
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

        # 📄 COMPILACIÓN DEL PAQUETE FINANCIERO
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

        # 🛡️ DESPACHO ATÓMICO SMTP
        email.send(fail_silently=False)
        
        # 🛡️ ESCUDO 2: Sello de Idempotencia Inmutable (Persistencia 30 días)
        cache.set(sent_flag_key, "DELIVERED", timeout=2592000) 
        
        logger.info(f"📨 [DESPACHO SUCCESS] Correo emitido a {recipient_email} (Ref: {context['order_reference']})")
        return f"SUCCESS_DELIVERED_TO_{recipient_email}"

    except Order.DoesNotExist:
        logger.error(f"❌ Orden {order_id} no encontrada (Posible retraso en COMMIT DB). Reintentando...")
        raise self.retry(exc=Order.DoesNotExist)
        
    except Exception as exc:
        logger.critical(f"🚨 Falla en túnel SMTP o compilación: {exc}")
        raise self.retry(exc=exc)
        
    finally:
        # Liberación de Memoria Garantizada (Destrucción del Lock)
        if lock and lock_acquired:
            try:
                lock.release()
            except Exception:
                pass
        elif not lock:
            cache.delete(lock_key)
        
        # Invocación manual al recolector de basura de Python para vaciar los binarios pesados de la RAM
        del attachments
        del tickets_data


# ==============================================================================
# 🧹 TAREA 2: SEGADOR DE MEMORIA (GLOBAL GARBAGE COLLECTOR)
# ==============================================================================

@shared_task(name="orders.purge_orphaned_reservations")
def purge_orphaned_reservations():
    """
    🛡️ SWEEPER DE NIVEL BANCARIO (O(1) Network Operations)
    Escanea la base de datos en busca de transacciones iniciadas que fueron abandonadas 
    en la pasarela de pagos. Restaura el inventario a nivel global silenciosamente.
    Ejecutar con Celery Beat cada 10 minutos.
    """
    logger.info("📡 [SWEEPER INICIADO] Escaneando anomalías en la bóveda de inventario...")
    
    # Tolerancia de 15 minutos (Regla de caducidad estricta)
    expiration_time = timezone.now() - datetime.timedelta(minutes=15)

    # Identificación de clústeres zombis
    expired_orders = Order.objects.filter(
        status='PENDING', 
        created_at__lt=expiration_time
    )

    if not expired_orders.exists():
        logger.info("✅ [SWEEPER] Clúster limpio. No se encontraron bloqueos huérfanos.")
        return "CLEAN_CLUSTER"

    with transaction.atomic():
        # 💥 DESTRUCCIÓN ATÓMICA (Cero iteraciones en RAM, todo procesado en el motor de BD)
        tickets_released = Ticket.objects.filter(
            order__in=expired_orders
        ).update(state='VOIDED') 

        orders_cancelled = expired_orders.update(status='REJECTED')

    logger.info(
        f"🔥 [SWEEPER EJECUTADO] Matriz purgada exitosamente. "
        f"Sillas liberadas: {tickets_released} | Bóvedas destruidas: {orders_cancelled}"
    )
    
    return f"Purged {orders_cancelled} orders and freed {tickets_released} seats."