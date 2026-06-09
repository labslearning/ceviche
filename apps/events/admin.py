from django.contrib import admin
from .models import Venue, ShowFunction, TicketType

# --- 1. ADMINISTRACIÓN DE TEATROS (VENUES) ---

@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    """
    Panel para configurar los teatros y su mapa JSON.
    """
    # Columnas que se ven en la lista
    list_display = ('name', 'city', 'capacity', 'updated_at')
    
    # Filtros laterales
    list_filter = ('city',)
    
    # Barra de búsqueda
    search_fields = ('name', 'city', 'address')
    
    # Organización del formulario de edición
    fieldsets = (
        ('Información General', {
            'fields': ('name', 'city', 'address')
        }),
        ('Motor del Mapa (JSON)', {
            # Colapsamos esto porque ocupa mucho espacio y es código técnico
            'classes': ('collapse',), 
            'fields': ('capacity', 'layout'), 
            'description': 'La capacidad se calcula automáticamente basada en las sillas definidas en el layout.'
        }),
    )
    
    # Hacemos que 'capacity' sea de solo lectura para evitar desincronización con el JSON
    readonly_fields = ('capacity',)


# --- 2. CONFIGURACIÓN DE PRECIOS (INLINE) ---

class TicketTypeInline(admin.TabularInline):
    """
    Permite crear y editar precios (VIP, General, etc.) dentro del mismo Evento.
    """
    model = TicketType
    extra = 1  # Muestra 1 fila vacía lista para llenar
    classes = ('collapse',) # Opcional: para que no ocupe tanto espacio si no se usa
    fields = ('name', 'zone_code', 'price', 'color', 'capacity')


# --- 3. ADMINISTRACIÓN DE FUNCIONES (SHOWS) ---

@admin.register(ShowFunction)
class ShowFunctionAdmin(admin.ModelAdmin):
    """
    Panel para crear funciones (Eventos en fechas específicas).
    """
    # Columnas: Nombre del show, Dónde es, Cuándo y si está activo
    list_display = ('name', 'venue', 'date_time', 'active')
    
    # Filtros laterales para encontrar rápido
    list_filter = ('active', 'venue', 'date_time')
    
    # Buscador
    search_fields = ('name', 'description')
    
    # Edición rápida desde la lista (muy útil para cancelar/activar rápido)
    list_editable = ('active',)
    
    # 👇 AQUÍ CONECTAMOS LOS PRECIOS AL EVENTO
    inlines = [TicketTypeInline]
    
    fieldsets = (
        ('Detalles del Evento', {
            # CORRECCIÓN IMPORTANTE: Usamos 'poster' (el campo de BD) para poder subir imágenes.
            # 'poster_url' es solo una propiedad de lectura.
            'fields': ('name', 'description', 'poster')
        }),
        ('Logística', {
            'fields': ('venue', 'date_time', 'active')
        }),
    )