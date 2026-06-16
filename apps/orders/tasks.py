import logging
from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.core.cache import cache
from django.conf import settings
from django.utils.html import strip_tags

from apps.orders.models import Order
from apps.orders.services import QRService

logger = logging.getLogger(__name__)

@shared_task(
    bind=True,
    max_retries=5,
    default_retry_delay=60,
    queue='financial_deliveries'
)
def process_order_tickets_and_email(self, order_id: str):
    """
    WORKER TASK (Grado Fintech).
    1. Recupera la orden optimizando queries (prefetch_related).
    2. Extrae u obtiene los QRs binarios desde la caché RAM O(1).
    3. Construye el HTML financiero de alta fidelidad.
    4. Despacha el correo de forma atómica.
    """
    logger.info(f"⚙️ [WORKER RUNNING] Procesando despacho de correo para Orden ID: {order_id}")
    
    try:
        # Optimizamos la consulta para traer los tickets y la función de un solo golpe (Anti-N+1 Problem)
        order = Order.objects.prefetch_related('tickets__function__venue').get(pk=order_id)
        
        if order.status != Order.Status.APPROVED:
            logger.warning(f"⚠️ [WORKER ABORT] Intento de procesar orden no aprobada: {order_id}")
            return "ABORTED_INVALID_STATUS"

        # Capturamos el correo del usuario (Soporta flujo de invitados usando un campo alterno si aplica)
        recipient_email = order.user.email if order.user else order.payment_metadata.get('payer', {}).get('email')
        
        if not recipient_email:
            logger.critical(f"💀 [WORKER FATAL] No se encontró correo de destino para la orden: {order.wompi_reference}")
            return "FAILED_NO_EMAIL"

        attachments = []
        tickets_data = []

        # 🧠 EXTRACCIÓN DE GRÁFICOS COMPLEJIDAD O(1) DESDE CACHÉ DE RAM
        for ticket in order.tickets.all():
            cache_key = f"qr_cache_{ticket.id.hex}"
            qr_bytes = cache.get(cache_key)

            if not qr_bytes:
                # Si por alguna razón expiró de la memoria intermedia, lo recalculamos al vuelo de forma segura
                logger.warning(f"💡 Cache Miss para ticket {ticket.id.hex}. Regenerando matriz de bytes.")
                qr_bytes = QRService.generate_qr_image(ticket.qr_token)
                cache.set(cache_key, qr_bytes, timeout=86400)

            # Estructuramos la información para la plantilla HTML
            tickets_data.append({
                'seat': ticket.seat_label,
                'category': ticket.seat_category,
                'show': ticket.function.show.name if hasattr(ticket.function, 'show') else "Espectáculo",
                'date': ticket.function.date_time.strftime('%Y-%m-%d %H:%M'),
                'venue': ticket.function.venue.name
            })

            # Añadimos el binario directamente a la matriz de adjuntos del correo (Sin escribir archivos en disco)
            attachments.append((
                f"Ticket_{ticket.seat_label}_{ticket.id.hex[:6]}.png",
                qr_bytes,
                "image/png"
            ))

        # 📄 CONSTRUCCIÓN DEL CONTEXTO DEL CORREO FINANCIERO
        context = {
            'order_reference': order.wompi_reference,
            'total_amount': order.total_amount,
            'currency': order.currency,
            'tickets': tickets_data,
            'platform_name': "Ceviche Platform"
        }

        # Renderizamos la plantilla HTML sofisticada
        html_content = render_to_string('emails/tickets_delivery.html', context)
        text_content = strip_tags(html_content) # Fallback para lectores de correo antiguos

        # Configuración del Mensaje Segura contra Email Injections
        email = EmailMultiAlternatives(
            subject=f"🎟️ Tus Entradas Están Listas - Ref: {order.wompi_reference}",
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient_email]
        )
        email.attach_alternative(html_content, "text/html")

        # Inyectamos los adjuntos binarios desde la RAM
        for filename, content, mimetype in attachments:
            email.attach(filename, content, mimetype)

        # 🛡️ Despacho Atómico a la red SMTP externa
        email.send(fail_silently=False)
        
        # Registramos el éxito en la bitácora inmutable
        logger.info(f"📨 [DESPACHO SUCCESS] Correo enviado exitosamente a {recipient_email} para la orden {order.wompi_reference}")
        return f"SUCCESS_DELIVERED_TO_{recipient_email}"

    except Order.DoesNotExist:
        logger.error(f"❌ Orden {order_id} no encontrada en la base de datos. Reintentando tarea...")
        raise self.retry(exc=Order.DoesNotExist)
        
    except Exception as exc:
        logger.critical(f"🚨 Error crítico en el Worker de envíos: {exc}", exc_info=True)
        # Reintento exponencial ante fallas del servidor SMTP (Network Timeouts)
        raise self.retry(exc=exc)
