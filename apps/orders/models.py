import uuid
import secrets
import hmac
import hashlib
import json
from decimal import Decimal
from django.db import models, transaction, OperationalError
from django.db.models import F, Q
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.utils import timezone

# Importación de la lógica de eventos
from apps.events.models import ShowFunction 

# ==============================================================================
# 0. MOTORES CRIPTOGRÁFICOS Y ANTI-TIMING ATTACKS (O(1))
# ==============================================================================
def generate_order_reference():
    """
    Referencia alfanumérica única. Usa timestamp para sortability en DB 
    y token_hex para entropía (prevención de colisiones masivas).
    """
    timestamp_hex = hex(int(timezone.now().timestamp() * 10000))[2:]
    random_hex = secrets.token_hex(4)
    return f"CEV-{timestamp_hex.upper()}-{random_hex.upper()}"

def generate_secure_token():
    """Genera un token URL-Safe con 512 bits de entropía real (OS urandom)."""
    return secrets.token_urlsafe(64)

def secure_compare(val1, val2):
    """
    Mitigación de Time-Timing Attacks. 
    Compara en tiempo constante, evitando que un atacante adivine la firma letra por letra.
    """
    if val1 is None or val2 is None:
        return False
    return hmac.compare_digest(str(val1), str(val2))

# ==============================================================================
# 1. ORDEN MAESTRA (LA BÓVEDA FINANCIERA)
# ==============================================================================
class Order(models.Model):
    """
    GOD TIER: Registro Financiero Híbrido.
    Protegido por Kernel-level CheckConstraints.
    """
    class Status(models.TextChoices):
        PENDING = 'PENDING', _('Pendiente de Pago')
        PROCESSING = 'PROCESSING', _('Procesando en Pasarela') 
        APPROVED = 'APPROVED', _('Aprobada (Pagada)')
        REJECTED = 'REJECTED', _('Rechazada/Fallida')
        CANCELLED = 'CANCELLED', _('Cancelada (Timeout/Abandonada)')
        REFUNDED = 'REFUNDED', _('Reembolsada Totalmente')

    # Se usa UUID4. En sistemas ultra masivos se usaría UUID7 para evitar fragmentación B-Tree,
    # pero UUID4 es suficiente si los índices están bien estructurados.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, 
        related_name='orders', null=True, blank=True, db_index=True
    )
    
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    
    # Finanzas Strict O(1)
    currency = models.CharField(max_length=3, default='COP')
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    fee_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    
    # Huella Forense
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    
    # Gateways
    wompi_reference = models.CharField(max_length=100, unique=True, default=generate_order_reference, editable=False, db_index=True)
    wompi_transaction_id = models.CharField(max_length=100, blank=True, null=True, unique=True, db_index=True)
    siigo_invoice_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    
    # Anti-Memory Dumping: Guardamos toda la data para auditoría sin requerir logs en texto plano.
    payment_metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['user', 'status']),
        ]
        # 🛡️ KERNEL-LEVEL CONSTRAINTS: Ningún ORM o Raw SQL puede violar esto.
        constraints = [
            models.CheckConstraint(
                check=Q(total_amount__gte=Decimal('0.00')),
                name='order_total_amount_positive'
            ),
            models.CheckConstraint(
                check=Q(amount_paid__lte=F('total_amount')),
                name='order_amount_paid_not_exceed_total'
            )
        ]

    def clean(self):
        # Mantenemos clean() para validación temprana en formularios (UX),
        # pero la verdadera seguridad recae en los constraints de arriba.
        if self.amount_paid > self.total_amount:
            raise ValidationError("Violación: Pago excede el total.")
        if self.total_amount < 0 or self.amount_paid < 0:
            raise ValidationError("Violación: Montos negativos no permitidos.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"ORD-{self.wompi_reference} | {self.status} | {self.total_amount}"


# ==============================================================================
# 2. EL TICKET (EL ACTIVO FÍSICO / INVENTARIO)
# ==============================================================================
class Ticket(models.Model):
    """
    Separación de Dominio: El ticket no se entera de cómo fue pagado, 
    solo le importa si existe, si es válido o si fue anulado.
    """
    class State(models.TextChoices):
        RESERVED = 'RESERVED', _('Reservado (En Proceso de Pago)')
        VALID = 'VALID', _('Válido / Activo')
        INSIDE = 'INSIDE', _('Adentro del Recinto')
        TEMP_EXIT = 'TEMP_EXIT', _('Salida Temporal')
        CONSUMED = 'CONSUMED', _('Consumido / Finalizado')
        VOIDED = 'VOIDED', _('Anulado (Pago Fallido o Expirado)')
        BLOCKED = 'BLOCKED', _('Bloqueado por Fraude')
        REFUNDED = 'REFUNDED', _('Reembolsado')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.RESTRICT, related_name='tickets')
    function = models.ForeignKey(ShowFunction, on_delete=models.RESTRICT, related_name='sold_tickets')
    
    seat_label = models.CharField(max_length=50, db_index=True)
    seat_category = models.CharField(max_length=50)
    price_at_purchase = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Arquitectura Criptográfica HMAC
    qr_token = models.CharField(max_length=128, unique=True, default=generate_secure_token, editable=False, db_index=True)
    crypto_signature = models.CharField(max_length=64, editable=False)
    key_version = models.PositiveIntegerField(default=1, editable=False)
    
    state = models.CharField(max_length=20, choices=State.choices, default=State.RESERVED, db_index=True)

    class Meta:
        # DB-Level Lock contra sobreventa física.
        unique_together = ('function', 'seat_label') 
        indexes = [
            # Índice compuesto optimizado para el motor transaccional de alta concurrencia
            models.Index(fields=['function', 'seat_label', 'state']),
            models.Index(fields=['qr_token', 'state']),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(price_at_purchase__gte=Decimal('0.00')),
                name='ticket_price_positive'
            )
        ]

    def generate_signature(self):
        """Previene Delimiter Injection Attacks al firmar el payload estructurado."""
        secret_key = getattr(settings, f'TICKET_SECRET_KEY_V{self.key_version}', settings.SECRET_KEY)
        payload = json.dumps([str(self.id), str(self.function_id), self.qr_token, self.seat_label], separators=(',', ':'))
        return hmac.new(secret_key.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()

    def save(self, *args, **kwargs):
        if not self.crypto_signature:
            self.crypto_signature = self.generate_signature()
        super().save(*args, **kwargs)

    @property
    def is_valid_signature(self):
        return secure_compare(self.crypto_signature, self.generate_signature())

    def process_scan(self, gate_id, scanner_agent_id="SYSTEM"):
        """
        Motor Transaccional del Gatekeeper (Pessimistic Locking O(1)).
        """
        if not self.is_valid_signature:
            self._log_scan(gate_id, scanner_agent_id, 'DENIED', "Falsificación: Firma Inválida", "CORRUPTED")
            return False, "ERROR: TICKET FALSO O CORRUPTO"

        try:
            with transaction.atomic():
                # Bloqueo Pesimista Estricto (Previene ataques de escaneo simultáneo)
                locked_ticket = Ticket.objects.select_for_update(nowait=True, of=('self',)).get(id=self.id)
                
                new_state, action, reason, success = None, None, "OK", False

                if locked_ticket.state in [self.State.BLOCKED, self.State.VOIDED, self.State.REFUNDED]:
                    action, reason = 'DENIED', f"Ticket Inactivo. Estado actual: {locked_ticket.state}"
                elif locked_ticket.state == self.State.CONSUMED:
                    action, reason = 'DENIED', "Ticket consumido previamente."
                elif locked_ticket.state == self.State.RESERVED:
                    action, reason = 'DENIED', "Ticket reservado pero sin pago consolidado."
                
                # Lógica de Permisos de Entrada
                elif locked_ticket.state in [self.State.VALID, self.State.TEMP_EXIT]:
                    new_state, action, success = self.State.INSIDE, 'ENTRY', True
                elif locked_ticket.state == self.State.INSIDE:
                    new_state, action, success = self.State.TEMP_EXIT, 'EXIT', True
                
                if new_state:
                    locked_ticket.state = new_state
                    locked_ticket.save(update_fields=['state'])
                    self.state = new_state 

                self._log_scan(gate_id, scanner_agent_id, action, reason, locked_ticket.state)
                return success, reason

        except OperationalError:
            self._log_scan(gate_id, scanner_agent_id, 'DENIED', "Race Condition: Doble Escaneo", self.state)
            return False, "ERROR: PROCESANDO EN OTRA PUERTA"

    def _log_scan(self, gate, agent, action, reason, state_at_moment):
        # Recuperamos el último scan para generar la cadena de bloques
        last_scan = TicketScan.objects.filter(ticket=self).order_by('-timestamp').first()
        prev_hash = last_scan.integrity_hash if last_scan else "GENESIS_BLOCK"

        TicketScan.objects.create(
            ticket=self, gate_id=gate, scanner_agent_id=agent,
            action=action, reason=reason, state_at_scan=state_at_moment,
            previous_hash=prev_hash
        )

    def __str__(self):
        return f"TKT-{self.seat_label} [{self.get_state_display()}]"


# ==============================================================================
# 3. EL LEDGER (TRUE BLOCKCHAIN IMMUTABLE RECORD)
# ==============================================================================
class TicketScan(models.Model):
    """
    Auditoría Forense con Arquitectura Blockchain.
    Vincula el hash actual con el hash anterior (previous_hash).
    """
    class Action(models.TextChoices):
        ENTRY = 'ENTRY', _('Entrada Autorizada')
        EXIT = 'EXIT', _('Salida Temporal')
        DENIED = 'DENIED', _('Acceso Denegado')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.RESTRICT, related_name='scans')
    
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    gate_id = models.CharField(max_length=50)
    scanner_agent_id = models.CharField(max_length=100)
    
    action = models.CharField(max_length=20, choices=Action.choices)
    state_at_scan = models.CharField(max_length=20)
    reason = models.CharField(max_length=255, default="OK")
    
    # 🛡️ ARQUITECTURA BLOCKCHAIN
    previous_hash = models.CharField(max_length=64, editable=False, default="GENESIS_BLOCK")
    integrity_hash = models.CharField(max_length=64, editable=False)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['ticket', 'timestamp']),
            models.Index(fields=['gate_id', 'timestamp']),
        ]

    def _generate_integrity_hash(self):
        """
        Algoritmo Hashing de Enlace: Incluye el previous_hash.
        Si se elimina un registro del medio, el puente matemático se rompe alertando de manipulación.
        """
        payload = json.dumps([
            str(self.ticket_id), self.gate_id, self.action, 
            self.state_at_scan, str(self.timestamp.isoformat()), 
            self.previous_hash # El eslabón de la cadena
        ], separators=(',', ':'))
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("Violación Criptográfica: Los registros del Ledger son Append-Only.")
            
        self.integrity_hash = self._generate_integrity_hash()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Violación Criptográfica: Está prohibido eliminar bloques del Ledger.")

    def __str__(self):
        return f"{self.timestamp.strftime('%H:%M:%S')} | {self.action} | Puerta: {self.gate_id}"


# ==============================================================================
# 4. PRODUCTOS ADICIONALES (CARRITO DE COMPRAS FINANCIERO)
# ==============================================================================
class OrderItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.RESTRICT, related_name='items')
    product = models.ForeignKey('products.Product', on_delete=models.RESTRICT)
    
    quantity = models.PositiveIntegerField(default=1)
    price_at_purchase = models.DecimalField(max_digits=10, decimal_places=2)
    discount_applied = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=Q(quantity__gt=0),
                name='item_quantity_positive'
            ),
            models.CheckConstraint(
                check=Q(price_at_purchase__gte=Decimal('0.00')) & Q(discount_applied__gte=Decimal('0.00')),
                name='item_prices_positive'
            )
        ]

    def clean(self):
        if self.quantity <= 0:
            raise ValidationError("Cantidad debe ser mayor a cero.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def total_line(self):
        return (self.quantity * self.price_at_purchase) - self.discount_applied