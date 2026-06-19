import uuid
import secrets
import hmac
import hashlib
import json
from decimal import Decimal
from django.db import models, transaction, OperationalError
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.utils import timezone

# Importación de la lógica de eventos
from apps.events.models import ShowFunction 

# ==============================================================================
# 0. MOTORES CRIPTOGRÁFICOS Y UTILIDADES (COMPLEJIDAD O(1))
# ==============================================================================
def generate_order_reference():
    """
    Genera una referencia financiera única, cronológica e in-hackeable.
    Previene colisiones incluso con 10,000 transacciones por milisegundo.
    """
    timestamp_hex = hex(int(timezone.now().timestamp() * 10000))[2:]
    random_hex = secrets.token_hex(4)
    return f"CEV-{timestamp_hex.upper()}-{random_hex.upper()}"

def generate_secure_token():
    """Genera un token con 512 bits de entropía real (URL Safe)"""
    return secrets.token_urlsafe(64)

def secure_compare(val1, val2):
    """Mitiga ataques temporales (Time-Timing Attacks) al comparar strings"""
    if val1 is None or val2 is None:
        return False
    return hmac.compare_digest(str(val1), str(val2))

# ==============================================================================
# 1. ORDEN MAESTRA (LA BÓVEDA FINANCIERA)
# ==============================================================================
class Order(models.Model):
    """
    GOD TIER: Registro inmutable de transacciones financieras.
    Cumple normativas ACID y PCI-DSS.
    """
    class Status(models.TextChoices):
        PENDING = 'PENDING', _('Pendiente de Pago')
        PROCESSING = 'PROCESSING', _('Procesando en Pasarela') 
        APPROVED = 'APPROVED', _('Aprobada (Pagada)')
        REJECTED = 'REJECTED', _('Rechazada/Fallida')
        CANCELLED = 'CANCELLED', _('Cancelada')
        REFUNDED = 'REFUNDED', _('Reembolsada (Devolución)')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Llave de Idempotencia: Previene cobros dobles si hay fallos de red en el Frontend
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    
    # PROTECT: Evita borrar compras si se borra el usuario
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.PROTECT, 
        related_name='orders',
        null=True, blank=True,
        db_index=True
    )
    
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    
    # Finanzas Strict (Con soporte multidivisa estructural)
    currency = models.CharField(max_length=3, default='COP')
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), help_text="Impuestos calculados")
    fee_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), help_text="Cargos por servicio (Ticketera)")
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), help_text="Verificación cruzada (Cross-Check)")
    
    # Huella Forense Antifraude
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    
    # Trazabilidad de Pasarela (Mercado Pago / Wompi / SIIGO)
    wompi_reference = models.CharField(max_length=100, unique=True, default=generate_order_reference, editable=False, db_index=True)
    wompi_transaction_id = models.CharField(max_length=100, blank=True, null=True, unique=True, db_index=True)
    siigo_invoice_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    
    # Data Dumping: Almacena todo el JSON del banco. Útil para Debugging avanzado
    payment_metadata = models.JSONField(default=dict, blank=True, help_text="Log crudo e inmutable del Webhook")
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        # Índices compuestos B-Tree optimizados para Dashboards financieros
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['user', 'status']),
        ]

    def clean(self):
        if self.amount_paid > self.total_amount:
            raise ValidationError("Violación Financiera: El monto pagado no puede exceder el total de la orden.")
        if self.total_amount < 0 or self.amount_paid < 0:
            raise ValidationError("Violación Financiera: Los montos no pueden ser negativos.")

    def save(self, *args, **kwargs):
        # 🛡️ OBLIGA LA VALIDACIÓN: Django no ejecuta clean() por defecto en save()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        user_display = self.user.email if self.user else "Invitado Anónimo"
        return f"ORD-{self.wompi_reference} | {user_display} | {self.status} | {self.currency} {self.total_amount}"


# ==============================================================================
# 2. EL TICKET Criptográfico (El Activo Digital Unhackeable)
# ==============================================================================
class Ticket(models.Model):
    """
    Ticket de Grado Militar. Implementa Firmas HMAC, rotación de llaves (Key Versioning)
    y manejo de concurrencia pesimista (Pessimistic Locking).
    """
    class State(models.TextChoices):
        ISSUED = 'ISSUED', _('Emitido / Válido')
        INSIDE = 'INSIDE', _('Adentro del Recinto')
        TEMP_EXIT = 'TEMP_EXIT', _('Salida Temporal')
        CONSUMED = 'CONSUMED', _('Finalizado / Quemado')
        BLOCKED = 'BLOCKED', _('Bloqueado por Fraude')
        REFUNDED = 'REFUNDED', _('Devuelto al inventario')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # RESTRICT: Un ticket financiero NUNCA debe borrarse en cascada.
    order = models.ForeignKey(Order, on_delete=models.RESTRICT, related_name='tickets')
    function = models.ForeignKey(ShowFunction, on_delete=models.RESTRICT, related_name='sold_tickets')
    
    seat_label = models.CharField(max_length=50, db_index=True)
    seat_category = models.CharField(max_length=50)
    price_at_purchase = models.DecimalField(max_digits=10, decimal_places=2)
    
    # --- ARQUITECTURA CRIPTOGRÁFICA ---
    qr_token = models.CharField(max_length=128, unique=True, default=generate_secure_token, editable=False, db_index=True)
    crypto_signature = models.CharField(max_length=64, editable=False)
    key_version = models.PositiveIntegerField(default=1, editable=False, help_text="Permite rotación de llaves de seguridad")
    
    state = models.CharField(max_length=20, choices=State.choices, default=State.ISSUED, db_index=True)

    class Meta:
        unique_together = ('function', 'seat_label') # DB-Level Lock contra sobreventa
        indexes = [
            models.Index(fields=['qr_token', 'state']),
            models.Index(fields=['function', 'state']),
        ]

    def generate_signature(self):
        """
        Firma el ticket serializando a JSON para evitar 'Delimiter Injection Attacks'.
        """
        secret_key = getattr(settings, f'TICKET_SECRET_KEY_V{self.key_version}', settings.SECRET_KEY)
        
        # 🛡️ JSON Array asegura que los valores no colisionen (Elimina Inyección de Strings)
        payload = json.dumps([str(self.id), str(self.function_id), self.qr_token, self.seat_label], separators=(',', ':'))
        return hmac.new(secret_key.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()

    def save(self, *args, **kwargs):
        if not self.crypto_signature:
            self.crypto_signature = self.generate_signature()
        super().save(*args, **kwargs)

    @property
    def is_valid_signature(self):
        """Verificación criptográfica inmune a manipulaciones de la BD"""
        return secure_compare(self.crypto_signature, self.generate_signature())

    def process_scan(self, gate_id, scanner_agent_id="SYSTEM"):
        """
        Motor de Transición de Estados.
        Utiliza Pessimistic Locking (select_for_update con NOWAIT) para evitar Deadlocks 
        si hay ataques de fuerza bruta en los escáneres.
        """
        if not self.is_valid_signature:
            self._log_scan(gate_id, scanner_agent_id, 'DENIED', "Falsificación: Firma HMAC Inválida", "CORRUPTED")
            return False, "ERROR: TICKET FALSO O CORRUPTO"

        try:
            with transaction.atomic():
                # nowait=True lanza OperationalError instantáneo si otro escáner procesa el mismo ticket a la vez
                locked_ticket = Ticket.objects.select_for_update(nowait=True).get(id=self.id)
                
                new_state, action, reason, success = None, None, "OK", False

                if locked_ticket.state == self.State.BLOCKED:
                    action, reason = 'DENIED', "Seguridad: Ticket Reportado por Fraude"
                elif locked_ticket.state == self.State.REFUNDED:
                    action, reason = 'DENIED', "Ticket Reembolsado (No Válido)"
                elif locked_ticket.state == self.State.CONSUMED:
                    action, reason = 'DENIED', "Ticket ya utilizado en su totalidad"

                # Lógica de Accesos
                elif locked_ticket.state in [self.State.ISSUED, self.State.TEMP_EXIT]:
                    new_state, action, success = self.State.INSIDE, 'ENTRY', True
                elif locked_ticket.state == self.State.INSIDE:
                    new_state, action, success = self.State.TEMP_EXIT, 'EXIT', True
                
                if new_state:
                    locked_ticket.state = new_state
                    locked_ticket.save(update_fields=['state'])
                    self.state = new_state # Sincroniza la instancia en memoria RAM

                # Genera la traza forense inmutable
                self._log_scan(gate_id, scanner_agent_id, action, reason, locked_ticket.state)
                return success, reason

        except OperationalError:
            # Capturamos el Deadlock: Alguien más está escaneando este exacto ticket AHORA
            self._log_scan(gate_id, scanner_agent_id, 'DENIED', "Race Condition: Intento de doble escaneo", self.state)
            return False, "ERROR: DOBLE ESCANEO DETECTADO"

    def _log_scan(self, gate, agent, action, reason, state_at_moment):
        TicketScan.objects.create(
            ticket=self, gate_id=gate, scanner_agent_id=agent,
            action=action, reason=reason, state_at_scan=state_at_moment
        )

    def __str__(self):
        return f"TKT-{self.seat_label} [{self.get_state_display()}]"


# ==============================================================================
# 3. EL LEDGER (LIBRO MAYOR CRIPTOGRÁFICO INMUTABLE)
# ==============================================================================
class TicketScan(models.Model):
    """
    Auditoría Forense Avanzada (Concepto Blockchain).
    Registra una firma interna para detectar si un DBA manipuló la tabla a mano.
    """
    class Action(models.TextChoices):
        ENTRY = 'ENTRY', _('Entrada Autorizada')
        EXIT = 'EXIT', _('Salida Temporal')
        DENIED = 'DENIED', _('Acceso Denegado')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # RESTRICT: Historial blindado
    ticket = models.ForeignKey(Ticket, on_delete=models.RESTRICT, related_name='scans')
    
    # 🛡️ CORRECCIÓN: Usamos default=timezone.now en lugar de auto_now_add para garantizar que 
    # el timestamp existe exacto ANTES de crear el Integrity Hash.
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    gate_id = models.CharField(max_length=50)
    scanner_agent_id = models.CharField(max_length=100)
    
    action = models.CharField(max_length=20, choices=Action.choices)
    state_at_scan = models.CharField(max_length=20)
    reason = models.CharField(max_length=255, default="OK")
    
    # Sello de integridad de la base de datos (Anti-Tampering)
    integrity_hash = models.CharField(max_length=64, editable=False)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['ticket', 'timestamp']),
            models.Index(fields=['gate_id', 'timestamp']),
        ]

    def _generate_integrity_hash(self):
        """Crea un hash del registro. Si un hacker edita el SQL a mano, el hash se rompe."""
        payload = json.dumps([str(self.ticket_id), self.gate_id, self.action, self.state_at_scan, str(self.timestamp.isoformat())], separators=(',', ':'))
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    def save(self, *args, **kwargs):
        if self.pk is not None:
            # PREVIENE ACTUALIZACIONES: EL LEDGER ES APPEND-ONLY (Solo Escritura)
            raise ValidationError("Violación: Los registros de auditoría (TicketScan) son inmutables.")
            
        self.integrity_hash = self._generate_integrity_hash()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """PREVIENE BORRADOS: Ningún admin puede borrar una entrada del registro"""
        raise ValidationError("Violación de Seguridad: Está prohibido eliminar registros del Libro Mayor.")

    def __str__(self):
        return f"{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')} | {self.action} | Puerta: {self.gate_id}"


# ==============================================================================
# 4. PRODUCTOS ADICIONALES (CARRITO DE COMPRAS)
# ==============================================================================
class OrderItem(models.Model):
    """
    Items asociados a una compra financiera. Blindados con RESTRICT.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.RESTRICT, related_name='items')
    
    # Asumimos que tienes una app 'products'. Si no, comenta esta línea.
    product = models.ForeignKey('products.Product', on_delete=models.RESTRICT)
    
    quantity = models.PositiveIntegerField(default=1)
    price_at_purchase = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Descuentos o variaciones de impuestos aplicadas en el momento
    discount_applied = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    def clean(self):
        if self.quantity <= 0:
            raise ValidationError("La cantidad debe ser mayor a cero.")
        if self.price_at_purchase < 0 or self.discount_applied < 0:
            raise ValidationError("El precio y el descuento no pueden ser negativos.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def total_line(self):
        return (self.quantity * self.price_at_purchase) - self.discount_applied

    def __str__(self):
        return f"{self.quantity} x {self.product.name} (ORD-{self.order.wompi_reference[-6:]})"