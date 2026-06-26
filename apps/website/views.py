import logging
import json
import copy
from django.conf import settings
from django.shortcuts import render, get_object_or_404
from django.views.generic import TemplateView
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.core.serializers.json import DjangoJSONEncoder
from django.contrib.auth.mixins import LoginRequiredMixin

# Importaciones de modelos
from apps.orders.models import Order
from apps.events.models import ShowFunction, Venue

logger = logging.getLogger(__name__)

# ==========================================
# 🏠 VISTAS PÚBLICAS
# ==========================================

@method_decorator(cache_page(60 * 5), name='dispatch')
class HomeView(TemplateView):
    template_name = "index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['upcoming_shows'] = ShowFunction.objects.filter(
            active=True,
            date_time__gte=timezone.now()
        ).select_related('venue').order_by('date_time')[:3]
        return context


def events_list(request):
    """
    Vista pública optimizada. 
    Filtra eventos activos desde el inicio del día actual (00:00:00) 
    para asegurar que los eventos de 'hoy' siempre aparezcan.
    """
    # Obtenemos la fecha de hoy, ajustada a las 00:00:00 locales
    today_start = timezone.localtime(timezone.now()).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    
    # Filtramos desde el inicio del día. 
    # Esto garantiza que el evento del 9 de junio (o cualquiera de hoy) aparezca.
    events = ShowFunction.objects.filter(
        active=True, 
        date_time__gte=today_start
    ).select_related('venue').order_by('date_time')

    return render(request, 'website/events_public_list.html', {
        'events': events
    })


class BoleteriaView(TemplateView):
    template_name = "boleteria-1.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['shows'] = ShowFunction.objects.filter(
            active=True,
            date_time__gte=timezone.now()
        ).select_related('venue').order_by('date_time')
        return context


class CartView(TemplateView):
    template_name = "cart.html"


# ==========================================
# 🎟️ PROCESO DE COMPRA (DETECTIVE DE PRECIOS)
# ==========================================

def event_detail_view(request, event_id):
    """
    Vista de Detalle de Función.
    VERSION DETECTIVE: Muestra por consola por qué falla la VIP.
    """
    function = get_object_or_404(
        ShowFunction.objects.select_related('venue'), 
        id=event_id, 
        active=True
    )
    
    venue = function.venue
    
    # 1. OBTENER PRECIOS
    ticket_types = function.ticket_types.all()
    price_map = {}
    default_price = 0
    
    print(f"\n=======================================================")
    print(f"🕵️‍♂️ INICIANDO RASTREO DE PRECIOS PARA: {function.name}")
    print(f"-------------------------------------------------------")
    print(f"1. TABLA DE PRECIOS (Lo que definiste en el Admin):")
    for tt in ticket_types:
        clean_code = str(tt.zone_code).strip().lower()
        price_map[clean_code] = tt.price
        print(f"   ✅ Tienes precio para: '{clean_code}' -> ${tt.price}")
        
        # Guardamos 'general' como salvavidas
        if 'general' in clean_code:
            default_price = tt.price

    # 2. PREPARAR MAPA
    raw_layout = venue.layout if (venue and venue.layout) else {}
    layout_data = copy.deepcopy(raw_layout)

    # Contadores
    seats_vip_ok = 0
    seats_rescued = 0
    unmatched_zones = set() # Para no repetir el error en consola 100 veces

    # 3. RECORRIDO E INYECCIÓN
    print(f"-------------------------------------------------------")
    print(f"2. ANALIZANDO EL MAPA (Silla por Silla):")
    
    if isinstance(layout_data, dict) and 'blocks' in layout_data:
        for block in layout_data['blocks']:
            # Zona global del bloque
            raw_block_zone = block.get('zone') or block.get('category')
            
            if 'seats' in block:
                for seat in block['seats']:
                    # Buscamos la etiqueta en TODOS lados posibles
                    raw_seat_zone = (
                        seat.get('zone') or 
                        seat.get('category') or 
                        seat.get('type') or   # A veces el editor lo guarda aqui
                        raw_block_zone
                    )
                    
                    price_assigned = 0
                    
                    # CASO A: La silla TIENE etiqueta
                    if raw_seat_zone:
                        clean_seat_zone = str(raw_seat_zone).strip().lower()
                        
                        if clean_seat_zone in price_map:
                            # ¡EXITO! Coincidencia exacta
                            price_assigned = price_map[clean_seat_zone]
                            seats_vip_ok += 1
                        else:
                            # FALLO: Tiene nombre, pero no precio.
                            # Guardamos el nombre para reportarlo al usuario
                            unmatched_zones.add(clean_seat_zone)
                    
                    # CASO B: Salvavidas (Si falló lo de arriba o no tenía nombre)
                    if price_assigned == 0 and default_price > 0:
                        price_assigned = default_price
                        # Si tenía un nombre raro (ej: 'vip_gold'), NO lo sobreescribimos visualmente
                        # Solo le ponemos 'General' si no tenía nada de nada.
                        if not seat.get('category') and not raw_seat_zone:
                            seat['category'] = 'General'
                        seats_rescued += 1

                    seat['price'] = price_assigned

    # 4. REPORTE FINAL (LO QUE NECESITAS LEER)
    if unmatched_zones:
        print(f"\n🚨🚨🚨 ALERTA ROJA: PRECIOS NO COINCIDEN 🚨🚨🚨")
        print(f"El mapa tiene sillas con estos nombres, pero NO creaste precio para ellos:")
        for z in unmatched_zones:
            print(f"   ❌ Nombre en Mapa: '{z}'")
            print(f"      (Ve al Admin -> Funciones -> Precios y crea uno con el código: {z})")
    else:
        print(f"\n✅ Todo parece correcto. Se encontraron coincidencias.")

    print(f"-------------------------------------------------------")
    print(f"📊 Resumen:")
    print(f"   - Sillas con precio exacto (VIP/Etc): {seats_vip_ok}")
    print(f"   - Sillas rescatadas con precio General: {seats_rescued}")
    print(f"=======================================================\n")

    # 5. RETORNO
    venue_layout_json = json.dumps(layout_data, cls=DjangoJSONEncoder)

    context = {
        'function': function,
        'venue': venue,
        'venue_layout_json': venue_layout_json,
        'event_name': getattr(function, 'name', 'Evento Ceviche'),
    }
    
    return render(request, 'event_detail.html', context)


def order_status_view(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    
    is_approved = False
    status_str = str(order.status).upper()

    if hasattr(Order.Status, 'APPROVED'):
        is_approved = (order.status == Order.Status.APPROVED)
    else:
        is_approved = (status_str == 'APPROVED')

    context = {
        'order': order,
        'tickets': order.tickets.all() if is_approved else [],
        'wompi_public_key': getattr(settings, 'WOMPI_PUBLIC_KEY', 'pub_test_XXXXXX')
    }
    
    return render(request, 'order_status.html', context)

class MisTicketsView(LoginRequiredMixin, TemplateView):
    """
    Portal God-Tier de Inventario Personal.
    Aísla las órdenes aprobadas del usuario autenticado.
    """
    template_name = "order_status.html" # Puedes cambiar esto por "mis_tickets.html" cuando crees el diseño final
    login_url = '/' # Redirección silenciosa si un invitado intenta acceder
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # O(1) Query optimizada usando prefetch_related para evitar el N+1 problem al cargar los tickets
        context['my_orders'] = Order.objects.filter(
            user=self.request.user, 
            status='APPROVED'
        ).prefetch_related('tickets').order_by('-created_at')
        return context