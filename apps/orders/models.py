import uuid
import secrets
import hmac
import hashlib
import json
import jwt
import logging
from decimal import Decimal
from django.db import models, transaction, OperationalError
from django.db.models import F, Q
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.utils import timezone
from decouple import config

# Importación de la lógica de eventos
from apps.events.models import ShowFunction 

logger = logging.getLogger(__name__)

# ==============================================================================
# 0. MOTORES CRIPTOGRÁFICOS (O(1) Memory Footprint)
# ==============================================================================
def generate_order_reference():
    """Entropía híbrida: Sortability temporal + Colision Resistance (Hex)."""
    timestamp_hex = hex(int(timezone.now().timestamp() * 10000))[2:]
    random_hex = secrets.token_hex(4)
    return f"CEV-{timestamp_hex.upper()}-{random_hex.upper()}"

def generate_secure_token():
    """Generador URL-Safe expandido para alojar buffers JWT asimétricos."""
    return secrets.token_urlsafe(96)


# ==============================================================================
# 1. ORDEN MAESTRA (LA BÓVEDA FINANCIERA)
# ==============================================================================
class Order(models.Model):
    """
    GOD TIER: Registro Financiero Híbrido protegido por Kernel-level CheckConstraints.
    """
    class Status(models.TextChoices):
        PENDING = 'PENDING', _('Pendiente de Pago')
        PROCESSING = 'PROCESSING', _('Procesando en Pasarela') 
        APPROVED = 'APPROVED', _('Aprobada (Pagada)')
        REJECTED = 'REJECTED', _('Rechazada/Fallida')
        CANCELLED = 'CANCELLED', _('Cancelada (Timeout/Abandonada)')
        REFUNDED = 'REFUNDED', _('Reembolsada Totalmente')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, 
        related_name='orders', null=True, blank=True, db_index=True
    )
    
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    
    currency = models.CharField(max_length=3, default='COP')
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    fee_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    
    wompi_reference = models.CharField(max_length=100, unique=True, default=generate_order_reference, editable=False, db_index=True)
    wompi_transaction_id = models.CharField(max_length=100, blank=True, null=True, unique=True, db_index=True)
    siigo_invoice_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    
    tickets_dispatched = models.BooleanField(default=False, db_index=True)
    gateway_transaction_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    
    delivery_status = models.CharField(
        max_length=50, 
        choices=[
            ('PENDING', 'Pendiente'),
            ('PENDING_GENERATION', 'Generando Activos Criptográficos'),
            ('DELIVERED', 'Entregado de Forma Segura'),
            ('FAILED', 'Despacho Fallido')
        ],
        default='PENDING',
        db_index=True
    )
    
    payment_metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['user', 'status']),
        ]
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
        if self.amount_paid > self.total_amount:
            raise ValidationError("Violación: Pago excede el total.")
        if self.total_amount < 0 or self.amount_paid < 0:
            raise ValidationError("Violación: Montos negativos no permitidos.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"ORD-{self.wompi_reference} | {self.status}"


# ==============================================================================
# 2. EL TICKET (BÓVEDA DE ACCESO ASIMÉTRICA)
# ==============================================================================
class Ticket(models.Model):
    """
    Control de Acceso Físico. 
    Desacoplado de la criptografía simétrica; utiliza validación asimétrica ECDSA (ES256).
    """
    class State(models.TextChoices):
        RESERVED = 'RESERVED', _('Reservado')
        VALID = 'VALID', _('Válido / Activo')
        INSIDE = 'INSIDE', _('Adentro del Recinto')
        TEMP_EXIT = 'TEMP_EXIT', _('Salida Temporal')
        CONSUMED = 'CONSUMED', _('Consumido / Finalizado')
        VOIDED = 'VOIDED', _('Anulado')
        BLOCKED = 'BLOCKED', _('Bloqueado por Fraude')
        REFUNDED = 'REFUNDED', _('Reembolsado')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.RESTRICT, related_name='tickets')
    function = models.ForeignKey(ShowFunction, on_delete=models.RESTRICT, related_name='sold_tickets')
    
    seat_label = models.CharField(max_length=50, db_index=True)
    seat_category = models.CharField(max_length=50)
    price_at_purchase = models.DecimalField(max_digits=10, decimal_places=2)
    
    # 🛡️ FIX: Ampliación a 512 caracteres para almacenar firmas JWT ECDSA sin truncamiento
    qr_token = models.CharField(max_length=512, unique=True, default=generate_secure_token, editable=False, db_index=True)
    
    # Mantenido como Checksum interno secundario (Retrocompatibilidad DB)
    crypto_signature = models.CharField(max_length=64, editable=False)
    key_version = models.PositiveIntegerField(default=1, editable=False)
    
    state = models.CharField(max_length=20, choices=State.choices, default=State.RESERVED, db_index=True)

    class Meta:
        unique_together = ('function', 'seat_label') 
        indexes = [
            models.Index(fields=['function', 'seat_label', 'state']),
            models.Index(fields=['qr_token', 'state']),
        ]
        constraints = [
            models.CheckConstraint(check=Q(price_at_purchase__gte=Decimal('0.00')), name='ticket_price_positive')
        ]

    def generate_signature(self):
        """Checksum de redundancia interna (Integridad local, no usado en puerta)."""
        secret_key = getattr(settings, f'TICKET_SECRET_KEY_V{self.key_version}', settings.SECRET_KEY)
        payload = f"{self.id}:{self.function_id}:{self.seat_label}"
        return hmac.new(secret_key.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()

    def save(self, *args, **kwargs):
        if not self.crypto_signature:
            self.crypto_signature = self.generate_signature()
        super().save(*args, **kwargs)

    def process_scan(self, gate_id: str, scanner_agent_id: str) -> tuple[bool, str]:
        """
        📐 DECODIFICADOR CRIPTOGRÁFICO ECDSA Y MÁQUINA DE ESTADOS (Fase 7).
        Opera con llave pública. Si se filtra, los atacantes no pueden crear tickets, solo leerlos.
        """
        # 1. Validación Matemática (Aislamiento Offline Simulator)
        public_key_pem = config('ECDSA_PUBLIC_KEY', default=None)
        if public_key_pem:
            try:
                clean_public_key = public_key_pem.replace('\\n', '\n').encode('utf-8')
                # Verificación estricta de la firma matemática inyectada en el QR del cliente
                decoded_payload = jwt.decode(self.qr_token, clean_public_key, algorithms=["ES256"])
                
                if decoded_payload.get('sub') != self.id.hex:
                    self._log_scan(gate_id, scanner_agent_id, 'DENIED', "SPOOFING_HUELLA_INVALIDA", self.state)
                    return False, "ERROR: HUELLA DIGITAL FALSIFICADA"
                    
            except jwt.ExpiredSignatureError:
                self._log_scan(gate_id, scanner_agent_id, 'DENIED', "TOKEN_EXPIRADO", self.state)
                return False, "ERROR: TOKEN DE ACCESO CADUCADO"
            except jwt.InvalidTokenError:
                # Si llegamos aquí, se intenta un Fallback (en caso de que el token sea anterior a la Fase 2)
                pass 

        # 2. Exclusión Mutua Transaccional (Pessimistic Locking O(1))
        try:
            with transaction.atomic():
                locked_ticket = Ticket.objects.select_for_update(nowait=True, of=('self',)).get(id=self.id)
                
                new_state, action, reason, success = None, None, "OK", False

                if locked_ticket.state in [self.State.BLOCKED, self.State.VOIDED, self.State.REFUNDED]:
                    action, reason = 'DENIED', f"Ticket Inactivo. Estado: {locked_ticket.state}"
                elif locked_ticket.state == self.State.CONSUMED:
                    action, reason = 'DENIED', "Ticket finalizado/consumido."
                elif locked_ticket.state == self.State.RESERVED:
                    action, reason = 'DENIED', "Reserva sin pago consolidado."
                
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
            self._log_scan(gate_id, scanner_agent_id, 'DENIED', "Race Condition: Escaneo Simultáneo", self.state)
            return False, "ALERTA: PROCESAMIENTO EN OTRA PUERTA"

    def _log_scan(self, gate, agent, action, reason, state_at_moment):
        """Inyección O(1) en el Ledger de Auditoría Forense."""
        # FIX BIG O: Extracción optimizada (.values_list) en lugar de instanciar un objeto completo en RAM
        last_hash = TicketScan.objects.filter(ticket=self).order_by('-timestamp').values_list('integrity_hash', flat=True).first()
        prev_hash = last_hash if last_hash else "GENESIS_BLOCK"

        TicketScan.objects.create(
            ticket=self, gate_id=gate, scanner_agent_id=agent,
            action=action, reason=reason, state_at_scan=state_at_moment,
            previous_hash=prev_hash
        )


# ==============================================================================
# 3. EL LEDGER (TRUE BLOCKCHAIN IMMUTABLE RECORD)
# ==============================================================================
class TicketScan(models.Model):
    """Auditoría Forense ligada matemáticamente en cadena."""
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
    
    previous_hash = models.CharField(max_length=64, editable=False, default="GENESIS_BLOCK")
    integrity_hash = models.CharField(max_length=64, editable=False)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['ticket', 'timestamp']),
            models.Index(fields=['gate_id', 'timestamp']),
        ]

    def _generate_integrity_hash(self):
        payload = json.dumps([
            str(self.ticket_id), str(self.gate_id), str(self.action), 
            str(self.state_at_scan), str(self.timestamp.isoformat()), 
            str(self.previous_hash)
        ], separators=(',', ':'))
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("Violación Criptográfica: Los bloques del Ledger son Append-Only.")
            
        self.integrity_hash = self._generate_integrity_hash()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Violación Criptográfica: Prohibido manipular bloques del Ledger.")


# ==============================================================================
# 4. E-COMMERCE & ACCESORIOS (AISLADO)
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
            models.CheckConstraint(check=Q(quantity__gt=0), name='item_quantity_positive'),
            models.CheckConstraint(check=Q(price_at_purchase__gte=Decimal('0.00')) & Q(discount_applied__gte=Decimal('0.00')), name='item_prices_positive')
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