import uuid
import secrets
import time
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _

# 👇 Importamos ShowFunction (Seat ya no existe, usamos lógica de etiquetas)
from apps.events.models import ShowFunction 

class Order(models.Model):
    """
    Representa una transacción de compra (Carrito de compras convertido en pedido).
    Agrupa Tickets (entradas) y OrderItems (productos de bar/merch).
    """
    class Status(models.TextChoices):
        PENDING = 'PENDING', _('Pendiente de Pago')
        APPROVED = 'APPROVED', _('Aprobada (Pagada)')
        REJECTED = 'REJECTED', _('Rechazada/Fallida')
        CANCELLED = 'CANCELLED', _('Cancelada por Usuario')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='orders')
    
    # Control de Estado
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    
    # Datos financieros
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name=_("Total a Pagar"))
    
    # Integración WOMPI
    wompi_transaction_id = models.CharField(max_length=100, blank=True, null=True, unique=True)
    wompi_reference = models.CharField(max_length=100, unique=True, blank=True, help_text="Referencia única para pasarela")
    
    # Integración SIIGO (Facturación Electrónica)
    siigo_invoice_id = models.CharField(max_length=100, blank=True, null=True)
    
    # Auditoría
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _("Orden de Compra")
        verbose_name_plural = _("Órdenes de Compra")

    def __str__(self):
        return f"Orden #{str(self.id)[:8]} - {self.user.email} [{self.status}]"

    def save(self, *args, **kwargs):
        # Generar referencia única para Wompi si no existe
        if not self.wompi_reference:
            # Usamos time.time() para asegurar unicidad temporal + token aleatorio
            ts = int(time.time())
            random_part = secrets.token_hex(4).upper()
            self.wompi_reference = f"ORD-{random_part}-{ts}"
        super().save(*args, **kwargs)

class Ticket(models.Model):
    """
    La Boleta final. Implementamos MÁQUINA DE ESTADOS para seguridad anti-fraude.
    Permite controlar re-ingresos (baño, fumar) sin "quemar" el ticket definitivamente hasta el final.
    """
    class State(models.TextChoices):
        ISSUED = 'ISSUED', _('Emitido / Valido')           # Listo para usar
        INSIDE = 'INSIDE', _('Adentro del Evento')         # Cliente ingresó
        TEMP_EXIT = 'TEMP_EXIT', _('Salida Temporal')      # Salió al baño/fumar (QR válido para entrar de nuevo)
        CONSUMED = 'CONSUMED', _('Finalizado / Quemado')   # Evento terminó o ticket invalidado
        CANCELLED = 'CANCELLED', _('Anulado por Fraude')   # Reembolso o fraude detectado

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='tickets')
    
    # Datos del evento
    function = models.ForeignKey(ShowFunction, on_delete=models.PROTECT, related_name='sold_tickets')
    
    # --- DATOS DE LA SILLA ---
    seat_label = models.CharField(max_length=50, verbose_name=_("Ubicación")) # Ej: "Fila A - 12"
    seat_category = models.CharField(max_length=50, verbose_name=_("Categoría")) # Ej: "VIP"
    
    # Precio Snapshot
    price_at_purchase = models.DecimalField(max_digits=10, decimal_places=2, verbose_name=_("Precio Pagado"))
    
    # 🔒 SEGURIDAD DEL QR
    # Este token es lo que lee el portero. NO es el ID de la base de datos (para que nadie adivine IDs)
    qr_token = models.CharField(max_length=64, unique=True, editable=False, db_index=True)
    
    # MÁQUINA DE ESTADOS (Reemplaza al simple is_used)
    state = models.CharField(
        max_length=20, 
        choices=State.choices, 
        default=State.ISSUED, 
        db_index=True
    )
    
    # Auditoría de accesos (Bitácora)
    last_entry_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Última Entrada"))
    last_exit_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Última Salida"))

    class Meta:
        verbose_name = _("Ticket / Boleta")
        verbose_name_plural = _("Tickets / Boletas")
        # Restricción: No vender la misma silla dos veces en la misma función
        unique_together = ('function', 'seat_label')

    def save(self, *args, **kwargs):
        if not self.qr_token:
            # Token criptográficamente seguro para la URL del QR
            self.qr_token = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"[{self.state}] {self.seat_label} ({self.function})"

class OrderItem(models.Model):
    """
    Productos adicionales en la orden (Merch, Comida, Bebida).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    
    # Referencia lazy para evitar ciclos
    product = models.ForeignKey('products.Product', on_delete=models.PROTECT, related_name='order_items')
    
    quantity = models.PositiveIntegerField(default=1, verbose_name=_("Cantidad"))
    
    # Precio Snapshot
    price_at_purchase = models.DecimalField(max_digits=10, decimal_places=2, verbose_name=_("Precio Unitario"))
    
    class Meta:
        verbose_name = _("Item de Producto")
        verbose_name_plural = _("Items de Productos")

    def __str__(self):
        return f"{self.quantity}x {self.product.name}"
    
    @property
    def total_line(self):
        return self.quantity * self.price_at_purchase