import uuid
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.conf import settings

class Venue(models.Model):
    """
    Representa el Teatro, Auditorio o Estadio.
    Contiene la 'Matriz Maestra' (JSON) con el diseño de las sillas.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    name = models.CharField(
        max_length=200, 
        verbose_name=_("Nombre del Lugar")
    )
    
    address = models.CharField(
        max_length=300, 
        verbose_name=_("Dirección"), 
        blank=True
    )
    
    city = models.CharField(
        max_length=100, 
        verbose_name=_("Ciudad"), 
        blank=True, 
        null=True
    )
    
    # Capacidad (Se calcula automáticamente sumando las sillas del JSON)
    capacity = models.PositiveIntegerField(
        default=0, 
        verbose_name=_("Capacidad Máxima")
    )
    
    # 🧠 EL CEREBRO: Mapa de Sillas en JSON
    # Estructura: { "blocks": [{ "name": "Plate A", "seats": [...] }] }
    layout = models.JSONField(
        default=dict, 
        blank=True, 
        verbose_name=_("Diseño de Sillas (JSON)")
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Teatro / Venue")
        verbose_name_plural = _("Teatros / Venues")
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.city})" if self.city else self.name


class ShowFunction(models.Model):
    """
    La Función o Evento específico a la venta.
    Ejemplo: "Concierto Rock - 12 Octubre 8pm".
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Relación con el lugar donde ocurre
    venue = models.ForeignKey(
        Venue, 
        on_delete=models.PROTECT, 
        related_name='functions', 
        verbose_name=_("Lugar")
    )
    
    # Detalles del Show
    name = models.CharField(
        max_length=200, 
        verbose_name=_("Nombre del Show")
    )
    
    description = models.TextField(
        verbose_name=_("Descripción / Sinopsis"), 
        blank=True, 
        null=True
    )
    
    # ✅ CAMPO DE IMAGEN REAL (Necesita Pillow instalado)
    poster = models.ImageField(
        upload_to='events/posters/', 
        verbose_name=_("Poster del Evento"), 
        blank=True, 
        null=True,
        help_text="Formatos recomendados: JPG, PNG. Resolución óptima: 800x1200px."
    )
    
    # Fecha y Hora exacta
    date_time = models.DateTimeField(
        verbose_name=_("Fecha y Hora"), 
        db_index=True
    )
    
    # Control de Venta
    active = models.BooleanField(
        default=True, 
        verbose_name=_("¿A la venta?")
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Función / Evento")
        verbose_name_plural = _("Funciones / Eventos")
        ordering = ['date_time']

    # ✅ PROPIEDAD PUENTE CRÍTICA
    # Permite acceder a {{ event.poster_url }} en el HTML sin errores si no hay foto.
    @property
    def poster_url(self):
        if self.poster and hasattr(self.poster, 'url'):
            return self.poster.url
        # Puedes retornar una imagen por defecto aquí si quieres
        return None

    def __str__(self):
        return f"{self.name} - {self.date_time.strftime('%Y-%m-%d %H:%M')}"



# ... (Mantén todo el código anterior de Venue y ShowFunction igual)

class TicketType(models.Model):
    """
    Define los tipos de boletas y precios para una función específica.
    Ejemplo: 
    - VIP (Zona 'A'): $150.000
    - General (Zona 'B'): $80.000
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Relación: Estos precios pertenecen a UNA función específica
    function = models.ForeignKey(
        ShowFunction, 
        on_delete=models.CASCADE, 
        related_name='ticket_types',
        verbose_name=_("Función")
    )
    
    name = models.CharField(
        max_length=100, 
        verbose_name=_("Nombre de la Categoría"),
        help_text="Ej: VIP, General, Platinum, Early Bird"
    )
    
    # 🔗 EL ESLABÓN PERDIDO: Este código debe coincidir con el JSON del Venue
    zone_code = models.CharField(
        max_length=50,
        verbose_name=_("Código de Zona en Mapa"),
        help_text="Debe coincidir con la etiqueta 'zone' o 'category' en el diseño de sillas. Ej: 'vip', 'platea_a'."
    )
    
    price = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        verbose_name=_("Precio de Venta")
    )
    
    color = models.CharField(
        max_length=7, 
        default="#3388ff",
        verbose_name=_("Color en el Mapa"),
        help_text="Código Hexadecimal para pintar las sillas. Ej: #FFD700 (Dorado)"
    )

    # Opcional: Cupo total para zonas sin sillas numeradas (Admisión General)
    capacity = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Capacidad (Opcional)"),
        help_text="Solo si la zona NO tiene sillas numeradas (Admisión General)."
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Tipo de Boleta / Precio")
        verbose_name_plural = _("Lista de Precios")
        # Restricción: No crear dos precios para la misma zona en la misma función
        unique_together = ('function', 'zone_code')

    def __str__(self):
        return f"{self.name} - ${self.price:,.0f}"