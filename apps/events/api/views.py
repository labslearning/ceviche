from rest_framework import viewsets, permissions, status
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.db.models import Count

# 👇 MODELOS (Arquitectura Limpia)
# ✅ AGREGADO: TicketType para poder consultar los precios
from apps.events.models import Venue, ShowFunction, TicketType
from apps.orders.models import Ticket

# 👇 SERIALIZERS
from apps.events.api.serializers import (
    VenueSerializer, 
    ShowFunctionSerializer, 
    SeatAvailabilitySerializer
)

# ==========================================
#  SECCIÓN 1: GESTIÓN DE TEATROS (ADMIN & DASHBOARD)
# ==========================================

class VenueViewSet(viewsets.ModelViewSet):
    """
    CRUD completo para crear/editar Teatros (Venues).
    Soporta: GET (Lista), POST (Crear), PUT/PATCH (Editar info), DELETE.
    """
    queryset = Venue.objects.all().order_by('-created_at')
    serializer_class = VenueSerializer
    permission_classes = [permissions.IsAdminUser]

    @action(detail=True, methods=['get'])
    def calendar(self, request, pk=None):
        """
        NUEVO ENDPOINT: Devuelve la agenda de eventos para este teatro.
        URL: /api/v1/venues/{id}/calendar/
        """
        venue = self.get_object()
        
        # Obtenemos las funciones asociadas a este Venue
        functions = ShowFunction.objects.filter(venue=venue).order_by('date_time')
        
        # Construimos una respuesta ligera para el panel lateral del Dashboard
        data = []
        for func in functions:
            # Determinamos estado visual basado en si ya pasó o está activa
            status_label = "CONFIRMED" if func.active else "PENDING"
            
            # Nombre del evento
            event_name = func.name 

            data.append({
                "id": str(func.id),
                "name": event_name,
                "date": func.date_time.strftime("%Y-%m-%d"),
                "time": func.date_time.strftime("%H:%M"),
                "staff": 0,  
                "status": status_label,
                "active": func.active
            })
            
        return Response(data)


class VenueLayoutView(APIView):
    """
    API ESPECÍFICA PARA EL EDITOR GRÁFICO DE TEATROS.
    Maneja el JSON gigante de coordenadas y sillas.
    """
    permission_classes = [permissions.IsAdminUser]

    def get(self, request, venue_id):
        # Obtener el teatro
        venue = get_object_or_404(Venue, id=venue_id)
        # Devolver el layout (o una estructura vacía base si es nuevo)
        return Response({
            "id": venue.id,
            "name": venue.name,
            "city": venue.city,
            "address": venue.address,
            "layout": venue.layout or {"blocks": []} 
        })

    def post(self, request, venue_id):
        """
        Guarda el diseño dibujado en el frontend y recalcula capacidad automáticamente.
        """
        venue = get_object_or_404(Venue, id=venue_id)
        new_layout = request.data.get('layout')
        
        if not new_layout:
            return Response({"error": "Falta el campo 'layout'"}, status=400)
            
        venue.layout = new_layout
        
        # 🧠 CÁLCULO AUTOMÁTICO DE CAPACIDAD (ACTUALIZADO PARA BLOQUES)
        total_seats = 0
        
        # Lógica Nueva (Bloques)
        if 'blocks' in new_layout:
            for block in new_layout['blocks']:
                if 'seats' in block:
                    total_seats += len(block['seats'])
                    
        # Lógica Antigua (Filas - Retrocompatibilidad)
        elif 'rows' in new_layout:
            for row in new_layout['rows']:
                total_seats += len(row.get('seats', []))
        
        venue.capacity = total_seats
        venue.save()
        
        return Response({
            "success": True, 
            "message": f"Diseño guardado. Nueva capacidad calculada: {total_seats} sillas."
        })


# ==========================================
#  SECCIÓN 2: FUNCIONES Y VENTA (PÚBLICO)
# ==========================================

class ShowFunctionViewSet(viewsets.ModelViewSet):
    """
    API Pública para listar funciones y Privada para crear (Booking).
    """
    serializer_class = ShowFunctionSerializer
    
    # 🔐 PERMISOS DINÁMICOS:
    # Cualquiera puede ver (GET), pero solo Admins pueden crear/editar (POST/PUT)
    def get_permissions(self):
        if self.action in ['list', 'retrieve', 'seats']:
            return [permissions.AllowAny()]
        return [permissions.IsAdminUser()]

    def get_queryset(self):
        # Optimizamos consultas trayendo el Venue relacionado
        return ShowFunction.objects.select_related('venue').filter(active=True).order_by('date_time')

    # Endpoint: /api/events/functions/{id}/seats/
    @action(detail=True, methods=['get'])
    def seats(self, request, pk=None):
        """
        Genera el mapa de sillas en tiempo real para la venta (Widget de Compra).
        Cruza el diseño del Venue con los Tickets vendidos y LOS PRECIOS REALES.
        """
        function = self.get_object()
        venue = function.venue
        
        if not venue or not venue.layout:
            return Response([], status=200)

        # 1. TRAER PRECIOS REALES DE LA BD (TicketType)
        # Creamos un diccionario rápido: {'VIP': 150000, 'GENERAL': 80000}
        # Si no existe precio para una zona, devolveremos 0.
        prices_map = {
            tt.zone_code: tt.price 
            for tt in TicketType.objects.filter(function=function)
        }

        # 2. Consultar sillas vendidas (CACHEABLE idealmente)
        sold_labels = set(
            Ticket.objects.filter(
                function=function
            ).exclude(
                state=Ticket.State.CANCELLED
            ).values_list('seat_label', flat=True)
        )

        # 3. Construir respuesta plana para el frontend de venta
        available_seats = []
        layout = venue.layout

        # A. SOPORTE PARA ESTRUCTURA DE BLOQUES (NUEVO EDITOR)
        if 'blocks' in layout:
            for block in layout['blocks']:
                block_name = block.get('name', 'General')
                for seat in block.get('seats', []):
                    # Datos del JSON
                    seat_type = seat.get('type', 'GENERAL') # Ej: "VIP" o "PLATEA_A"
                    row_char = seat.get('row', '')
                    seat_num = seat.get('num', '')
                    
                    # Generamos ID lógico: Ej "A-1"
                    seat_id = f"{row_char}-{seat_num}" 
                    
                    # Determinar precio y estado
                    # ✅ BUSCAMOS EL PRECIO REAL EN LA BD USANDO EL TIPO
                    real_price = prices_map.get(seat_type, 0)
                    
                    status = 'SOLD' if seat_id in sold_labels else 'AVAILABLE'
                    
                    # Si el precio es 0 (no configurado), bloqueamos la silla para evitar ventas gratis
                    if real_price == 0 and status == 'AVAILABLE':
                        status = 'BLOCKED'

                    available_seats.append({
                        'id': seat_id,
                        'row': row_char,
                        'number': seat_num,
                        'section': block_name,
                        'category': seat_type,
                        'price': real_price, # ✅ PRECIO REAL (NO HARDCODED)
                        'status': status
                    })

        # B. SOPORTE LEGACY (SI AÚN TIENES DATOS VIEJOS)
        elif 'rows' in layout:
            for row in layout['rows']:
                for seat in row.get('seats', []):
                    seat_id = seat.get('id')
                    seat_type = seat.get('type', 'GENERAL')
                    
                    # Legacy también intenta buscar precio real
                    real_price = prices_map.get(seat_type, 0)
                    status = 'SOLD' if seat_id in sold_labels else 'AVAILABLE'
                    
                    # Bloqueo de seguridad si no hay precio
                    if real_price == 0 and status == 'AVAILABLE':
                        status = 'BLOCKED'
                    
                    available_seats.append({
                        'id': seat_id,
                        'row': row.get('name'),
                        'category': seat_type,
                        'price': real_price,
                        'status': status
                    })

        # 4. Serializar
        return Response(available_seats)