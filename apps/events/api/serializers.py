from rest_framework import serializers
from apps.events.models import Venue, ShowFunction
# 👇 Importante: Importar Ticket para calcular las estadísticas de ventas
from apps.orders.models import Ticket

# -----------------------------------------------------------------------------
# 1. SERIALIZER DEL TEATRO (VENUE)
# ⚠️ IMPORTANTE: Esta clase DEBE ir PRIMERO, antes que ShowFunctionSerializer,
# porque ShowFunction la utiliza para anidar los datos del teatro.
# -----------------------------------------------------------------------------
class VenueSerializer(serializers.ModelSerializer):
    """
    Maneja la información del Teatro, incluyendo el 'layout' (Mapa JSON).
    """
    class Meta:
        model = Venue
        fields = ['id', 'name', 'address', 'capacity', 'layout']
        # 'layout' es el JSONField donde vive la matriz de sillas.


# -----------------------------------------------------------------------------
# 2. SERIALIZER DE LA FUNCIÓN (SHOWFUNCTION)
# -----------------------------------------------------------------------------
class ShowFunctionSerializer(serializers.ModelSerializer):
    """
    Maneja las funciones (Eventos con fecha y hora).
    """
    # Anidamos el Venue para leer sus datos fácilmente en el frontend
    # Al estar VenueSerializer definido arriba, esto ya no dará error.
    venue = VenueSerializer(read_only=True)
    
    # Campo de escritura para asignar el Venue por ID
    venue_id = serializers.PrimaryKeyRelatedField(
        queryset=Venue.objects.all(), 
        source='venue', 
        write_only=True
    )
    
    # Campos calculados para facilitar la visualización
    venue_name = serializers.CharField(source='venue.name', read_only=True)

    # 📊 ESTADÍSTICAS (Lectura)
    # Estos campos se calculan en la vista (annotate) o se devuelven por defecto
    total_seats = serializers.IntegerField(read_only=True, default=0)
    sold_seats = serializers.IntegerField(read_only=True, default=0)
    available_seats = serializers.IntegerField(read_only=True, default=0)
    
    # 🖼️ IMAGEN (Lectura): Propiedad del modelo que devuelve la URL limpia
    poster_url = serializers.ReadOnlyField()

    # 🚀 TELEMETRÍA (Nuevo campo calculado para el dashboard)
    stats = serializers.SerializerMethodField()

    class Meta:
        model = ShowFunction
        fields = [
            'id', 
            'name', 
            'description',  # ✅ Campo de descripción (texto)
            'date_time', 
            'active', 
            'venue',        # Objeto completo del teatro (Lectura)
            'venue_id',     # Solo ID del teatro (Escritura)
            'venue_name',   # Nombre del teatro (Lectura rápida)
            'poster',       # ✅ Archivo binario de la imagen (Escritura)
            'poster_url',   # ✅ URL pública de la imagen (Lectura)
            'total_seats', 
            'sold_seats', 
            'available_seats',
            'stats'         # ✅ Campo de estadísticas detalladas
        ]

    def get_stats(self, obj):
        """
        Calcula la distribución de sillas (VIP vs GENERAL) en tiempo real
        leyendo el JSON del Venue y cruzándolo con los Tickets vendidos.
        """
        # 1. Inicializar contadores
        distribution = {
            'VIP': {'total': 0, 'sold': 0},
            'GENERAL': {'total': 0, 'sold': 0},
            'PALCO': {'total': 0, 'sold': 0}
        }

        # 2. Leer layout del teatro (JSON)
        # El layout se guarda en el modelo Venue
        layout = obj.venue.layout
        if not layout:
            return distribution

        blocks = layout.get('blocks', [])
        
        # 3. Mapear IDs de sillas a sus tipos (Ej: "A-1" -> "VIP")
        seat_types = {} 
        
        for block in blocks:
            seats = block.get('seats', [])
            for seat in seats:
                sType = seat.get('type', 'GENERAL').upper()
                sId = seat.get('id')
                
                # Asegurar que la categoría exista en el reporte
                if sType not in distribution:
                    distribution[sType] = {'total': 0, 'sold': 0}
                
                distribution[sType]['total'] += 1
                if sId:
                    seat_types[sId] = sType

        # 4. Cruzar con ventas reales (Tickets)
        # Buscamos los tickets válidos (Emitidos, Usados, Adentro) para esta función
        
        # 🚨 CORRECCIÓN CRÍTICA AQUÍ: 
        # El modelo Ticket usa 'state', no 'status'. 
        sold_tickets = Ticket.objects.filter(
            function=obj,  # Nombre correcto de la relación
            state__in=['ISSUED', 'USED', 'INSIDE'] # ✅ 'state' es el nombre real del campo en tu DB
        ).values_list('seat_label', flat=True)

        for seat_label in sold_tickets:
            # Buscamos de qué tipo era esa silla según el mapa
            sType = seat_types.get(seat_label, 'GENERAL')
            if sType in distribution:
                distribution[sType]['sold'] += 1

        return distribution


# -----------------------------------------------------------------------------
# 3. SERIALIZER VIRTUAL DE DISPONIBILIDAD (Para Venta de Boletas)
# -----------------------------------------------------------------------------
class SeatAvailabilitySerializer(serializers.Serializer):
    """
    Este serializer NO está conectado a una base de datos.
    Sirve para estructurar la respuesta JSON que le enviamos al cliente
    cuando pregunta "¿Qué sillas hay disponibles para esta función?".
    """
    id = serializers.CharField()        # Ej: "A-1" (El ID visual de la silla)
    row = serializers.CharField()       # Ej: "A"
    number = serializers.CharField()    # Ej: "1"
    category = serializers.CharField()  # Ej: "VIP", "GENERAL"
    price = serializers.DecimalField(max_digits=10, decimal_places=2) # El precio calculado
    status = serializers.CharField()    # 'available', 'sold', 'reserved'