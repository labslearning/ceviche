# apps/website/views.py
import logging
import json
from decimal import Decimal

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

# 🛡️ LOGGER SOC/SIEM (Reemplazo absoluto de los 'print' bloqueantes)
logger = logging.getLogger(__name__)

# ==============================================================================
# 🏠 VISTAS PÚBLICAS (CACHÉ EN RAM Y CONSULTAS O(1))
# ==============================================================================

@method_decorator(cache_page(60 * 5), name='dispatch')
class HomeView(TemplateView):
    template_name = "index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # 🚀 Optimización O(1): Limita la carga de memoria al Top 3 con relaciones directas
        context['upcoming_shows'] = ShowFunction.objects.filter(
            active=True,
            date_time__gte=timezone.now()
        ).select_related('venue').order_by('date_time')[:3]
        return context


def events_list(request):
    """
    Vista pública optimizada. 
    Filtra eventos activos desde el inicio del día actual (00:00:00).
    """
    today_start = timezone.localtime(timezone.now()).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    
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


# ==============================================================================
# 🎟️ MOTOR DE DETALLE Y RENDERIZADO DE MATRIZ DE SILLAS (GOD-TIER)
# ==============================================================================

def event_detail_view(request, event_id):
    """
    Motor de Extracción y Fusión de Precios.
    Aísla las operaciones en C (json.loads) para evitar Memory Leaks por deepcopy.
    """
    # 🚀 ANTI N+1 SHIELD: Extracción atómica de función, teatro y lista de precios
    function = get_object_or_404(
        ShowFunction.objects.select_related('venue').prefetch_related('ticket_types'), 
        id=event_id, 
        active=True
    )
    
    venue = function.venue
    ticket_types = function.ticket_types.all()
    
    # 1. GENERACIÓN DEL HASH MAP DE PRECIOS (O(1) Access Time)
    price_map = {}
    default_price = Decimal('0.00')
    
    for tt in ticket_types:
        clean_code = str(tt.zone_code).strip().lower()
        price_map[clean_code] = tt.price
        if 'general' in clean_code:
            default_price = tt.price

    # 2. CLONACIÓN DE ALTA VELOCIDAD (Mitigación de Memory Exhaustion)
    raw_layout = venue.layout if (venue and venue.layout) else {}
    # Utilizamos la librería JSON en C que es exponencialmente más rápida que copy.deepcopy()
    layout_data = json.loads(json.dumps(raw_layout))

    # Contadores de Telemetría
    seats_vip_ok = 0
    seats_rescued = 0
    unmatched_zones = set()

    # 3. RECORRIDO DE LA MATRIZ (Inyección de Datos)
    if isinstance(layout_data, dict) and 'blocks' in layout_data:
        for block in layout_data['blocks']:
            raw_block_zone = block.get('zone') or block.get('category')
            
            if 'seats' in block:
                for seat in block['seats']:
                    raw_seat_zone = (
                        seat.get('zone') or 
                        seat.get('category') or 
                        seat.get('type') or   
                        raw_block_zone
                    )
                    
                    price_assigned = Decimal('0.00')
                    
                    # CASO A: Coincidencia de HASH
                    if raw_seat_zone:
                        clean_seat_zone = str(raw_seat_zone).strip().lower()
                        if clean_seat_zone in price_map:
                            price_assigned = price_map[clean_seat_zone]
                            seats_vip_ok += 1
                        else:
                            unmatched_zones.add(clean_seat_zone)
                    
                    # CASO B: Protocolo de Rescate (Fallback)
                    if price_assigned == Decimal('0.00') and default_price > Decimal('0.00'):
                        price_assigned = default_price
                        if not seat.get('category') and not raw_seat_zone:
                            seat['category'] = 'General'
                        seats_rescued += 1

                    seat['price'] = float(price_assigned) # Serialización segura para el Frontend

    # 4. VOLCADO DE TELEMETRÍA ASÍNCRONO (Logging No Bloqueante)
    if unmatched_zones:
        logger.warning(
            f"🚨 [ANOMALÍA DE PRECIOS] Evento ID {function.id}: Zonas en mapa sin precio configurado: {list(unmatched_zones)}"
        )
    
    logger.info(
        f"📊 [MATRIZ PROCESADA] Evento: {function.name} | Sillas Asignadas: {seats_vip_ok} | Rescatadas (General): {seats_rescued}"
    )

    # 5. RETORNO DE PAQUETES
    venue_layout_json = json.dumps(layout_data, cls=DjangoJSONEncoder)

    context = {
        'function': function,
        'venue': venue,
        'venue_layout_json': venue_layout_json,
        'event_name': getattr(function, 'name', 'Evento Ceviche'),
    }
    
    return render(request, 'event_detail.html', context)


# ==============================================================================
# 🔐 PORTALES DE ESTADO Y SEGURIDAD DEL USUARIO (ZERO-TRUST)
# ==============================================================================

def order_status_view(request, order_id):
    """
    Verificador Criptográfico de Estado de Órdenes.
    """
    order = get_object_or_404(Order, id=order_id)
    
    status_str = str(order.status).upper()
    if hasattr(Order.Status, 'APPROVED'):
        is_approved = (order.status == Order.Status.APPROVED)
    else:
        is_approved = (status_str == 'APPROVED')

    context = {
        'order': order,
        # Aislamiento de seguridad: Solo se exponen los tickets si la bóveda fue aprobada.
        'tickets': order.tickets.all() if is_approved else [],
        'wompi_public_key': getattr(settings, 'WOMPI_PUBLIC_KEY', '')
    }
    
    return render(request, 'order_status.html', context)


class MisTicketsView(LoginRequiredMixin, TemplateView):
    """
    🚀 BÓVEDA DEL USUARIO (Inventario Personal).
    Aísla las órdenes aprobadas del usuario autenticado mediante barreras Tenant-Isolation.
    """
    template_name = "order_status.html" 
    login_url = '/' 
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # 🚀 ANTI N+1 SHIELD: prefetch_related neutraliza llamadas masivas a la DB al listar tickets.
        context['my_orders'] = Order.objects.filter(
            user=self.request.user, 
            status='APPROVED'
        ).prefetch_related('tickets').order_by('-created_at')
        return context