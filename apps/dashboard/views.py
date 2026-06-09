from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import TemplateView, ListView, View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import LoginView
from django.http import JsonResponse
from django.db.models import Sum, Q
from django.utils import timezone
import datetime
import json
from apps.events.models import ShowFunction, TicketType #


from apps.events.models import ShowFunction # Asegúrate de tener este import

# 👇 IMPORTACIÓN DE MODELOS
from apps.orders.models import Order
from apps.users.models import User
from apps.events.models import Venue, ShowFunction

# --- MIXIN DE SEGURIDAD ---
class SuperUserRequiredMixin(UserPassesTestMixin):
    """
    Solo permite entrar a Superusuarios (Admins).
    """
    def test_func(self):
        # En desarrollo a veces es útil permitir is_staff también
        return self.request.user.is_superuser or self.request.user.is_staff
    
    def handle_no_permission(self):
        return redirect('dashboard:login')

# --- VISTAS DEL DASHBOARD ---

class DashboardHomeView(LoginRequiredMixin, SuperUserRequiredMixin, TemplateView):
    template_name = "dashboard/home.html"
    login_url = '/dashboard/login/'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        
        # 1. KPIs Generales
        try:
            approved_orders = Order.objects.filter(status=Order.Status.APPROVED)
        except AttributeError:
            approved_orders = Order.objects.filter(status='APPROVED')

        total_sales = approved_orders.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        total_tickets = approved_orders.count()

        # 2. Crecimiento Mensual
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0)
        last_month_end = current_month_start - datetime.timedelta(seconds=1)
        last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0)
        
        sales_this_month = approved_orders.filter(created_at__gte=current_month_start).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        sales_last_month = approved_orders.filter(created_at__range=(last_month_start, last_month_end)).aggregate(Sum('total_amount'))['total_amount__sum'] or 0

        growth = 0
        if sales_last_month > 0:
            growth = ((sales_this_month - sales_last_month) / sales_last_month) * 100
        elif sales_this_month > 0:
            growth = 100

        # 3. Datos para la Gráfica (Últimos 7 días)
        chart_labels = []
        chart_data = []
        for i in range(6, -1, -1):
            day = now - datetime.timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0)
            day_end = day.replace(hour=23, minute=59, second=59)
            daily_sales = approved_orders.filter(created_at__range=(day_start, day_end)).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
            chart_labels.append(day.strftime('%a'))
            chart_data.append(float(daily_sales))

        context.update({
            "total_sales": total_sales,
            "total_tickets": total_tickets,
            "growth_percentage": round(growth, 1),
            "is_growth_positive": growth >= 0,
            "chart_labels": json.dumps(chart_labels),
            "chart_data": json.dumps(chart_data),
        })
        return context

# ceviche_platform/backend/apps/dashboard/views.py

class VenueEditorView(LoginRequiredMixin, SuperUserRequiredMixin, TemplateView):
    """
    Editor Visual de Teatros (Venues).
    Maneja tanto la visualización (GET) como el guardado (POST).
    """
    template_name = "dashboard/theater_editor.html"
    login_url = '/dashboard/login/'
    
    def get_context_data(self, **kwargs):
        """Prepara los datos para mostrar el editor"""
        context = super().get_context_data(**kwargs)
        venue_id = self.kwargs.get('venue_id')
        
        if venue_id:
            venue = get_object_or_404(Venue, pk=venue_id)
        else:
            # Load the first venue or create a default one
            venue = Venue.objects.first()
            if not venue:
                venue = Venue.objects.create(
                    name="Teatro Principal", 
                    city="Bogotá",
                    address="Calle 123",
                    layout={'blocks': []} 
                )
        
        # Convert layout to JSON string for JS
        existing_layout = json.dumps(venue.layout) if venue.layout else '{"blocks": []}'

        # --- FIX IS HERE ---
        # We change key from 'venue' to 'theater' to match the HTML template variables
        context['theater'] = venue 
        context['existing_layout'] = existing_layout
        return context

    def post(self, request, *args, **kwargs):
        """Maneja el guardado del mapa cuando le das click al botón Guardar"""
        venue_id = self.kwargs.get('venue_id')
        
        # Logic to handle 'default' venue if no ID is passed in URL,
        # though ideally the editor should always have an ID in the URL.
        if venue_id:
             venue = get_object_or_404(Venue, pk=venue_id)
        else:
             # Fallback just in case
             venue = Venue.objects.first()

        try:
            # Read data sent by Javascript
            data = json.loads(request.body)
            layout = data.get('layout')
            capacity = data.get('capacity')
            
            # Save to DB
            venue.layout = layout
            if capacity:
                venue.capacity = capacity
            venue.save()
            
            return JsonResponse({'status': 'ok', 'message': 'Mapa guardado correctamente'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

class OrderListView(LoginRequiredMixin, SuperUserRequiredMixin, ListView):
    model = Order
    template_name = "dashboard/orders_list.html"
    context_object_name = "orders"
    login_url = '/dashboard/login/'
    paginate_by = 20
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = Order.objects.select_related('user').all().order_by('-created_at')
        query = self.request.GET.get('q')
        status_filter = self.request.GET.get('status')
        
        if query:
            queryset = queryset.filter(
                Q(id__icontains=query) | 
                Q(user__email__icontains=query) | 
                Q(user__username__icontains=query)
            )
        
        if status_filter and status_filter != 'Todos los Estados':
            # Mapeo simple de strings a valores del modelo
            status_map = {
                'Aprobados': 'APPROVED',
                'Pendientes': 'PENDING',
                'Rechazados': 'REJECTED'
            }
            # Intentamos usar el mapa o el valor directo
            db_status = status_map.get(status_filter, status_filter)
            queryset = queryset.filter(status=db_status)
                
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('q', '')
        context['current_status'] = self.request.GET.get('status', 'Todos los Estados')
        return context

class ShowFunctionListView(LoginRequiredMixin, SuperUserRequiredMixin, ListView):
    model = ShowFunction
    template_name = "dashboard/events_list.html"
    context_object_name = "events" 
    paginate_by = 10
    login_url = '/dashboard/login/'

    def get_queryset(self):
        queryset = ShowFunction.objects.select_related('venue').all().order_by('-date_time')
        
        query = self.request.GET.get('q')
        if query:
            queryset = queryset.filter(name__icontains=query)
            
        status = self.request.GET.get('status')
        if status == 'active':
            queryset = queryset.filter(active=True)
        elif status == 'inactive':
            queryset = queryset.filter(active=False)
            
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('q', '')
        context['current_status'] = self.request.GET.get('status', 'all')
        
        context['total_count'] = ShowFunction.objects.count()
        context['active_count'] = ShowFunction.objects.filter(active=True).count()
        context['featured_count'] = 0 
        
        return context

class DashboardLoginView(LoginView):
    template_name = 'dashboard/login.html'
    redirect_authenticated_user = True 
    next_page = 'dashboard:home'



class ShowFunctionUpdateView(LoginRequiredMixin, SuperUserRequiredMixin, View):
    """
    Gestiona la edición del evento Y sus precios (TicketTypes).
    """
    def get(self, request, pk):
        function = get_object_or_404(ShowFunction, pk=pk)
        
        # 1. Estadísticas (Tu código actual)
        total_seats = 0
        layout = function.venue.layout if function.venue else {}
        blocks = layout.get('blocks', []) or []
        
        # --- NUEVO: DETECCIÓN DE ZONAS EN EL MAPA ---
        # Escaneamos el JSON para encontrar todas las categorías únicas (VIP, GENERAL, etc.)
        detected_zones = set()
        for block in blocks:
            for seat in block.get('seats', []):
                # Asumimos que el editor guarda el tipo en 'type' o 'category'
                z_code = seat.get('type') or seat.get('category') or 'General'
                detected_zones.add(z_code)
        
        # Calcular estadísticas
        for block in blocks:
            total_seats += len(block.get('seats', []))
        
        sold_seats = getattr(function, 'sold_seats', 0)
        available_seats = total_seats - sold_seats
        occupancy_rate = round((sold_seats / total_seats * 100), 1) if total_seats > 0 else 0

        # --- NUEVO: RECUPERAR PRECIOS ACTUALES ---
        # Buscamos los TicketTypes que ya existen para este evento
        existing_prices = {
            tt.zone_code: tt.price 
            for tt in TicketType.objects.filter(function=function)
        }

        # Construimos la lista de precios para el Frontend
        price_list = []
        for zone in detected_zones:
            price_list.append({
                'zone_code': zone,
                'zone_name': zone.upper(), # Nombre bonito para mostrar
                'current_price': existing_prices.get(zone, 0) # 0 si no se ha configurado
            })

        data = {
            'id': function.id,
            'name': function.name,
            'date': function.date_time.strftime('%Y-%m-%d'),
            'time': function.date_time.strftime('%H:%M'),
            'description': function.description or "",
            'active': function.active,
            'poster_url': function.poster.url if function.poster else None,
            'stats': {
                'total': total_seats,
                'sold': sold_seats,
                'available': available_seats,
                'occupancy': occupancy_rate
            },
            # 👇 Enviamos la matriz de precios al modal
            'pricing': price_list 
        }
        return JsonResponse(data)

    def post(self, request, pk):
        function = get_object_or_404(ShowFunction, pk=pk)
        
        try:
            # 1. Actualizar Datos Básicos
            function.name = request.POST.get('name')
            function.description = request.POST.get('description')
            function.active = request.POST.get('active') == 'true'
            
            date_str = request.POST.get('date')
            time_str = request.POST.get('time')
            if date_str and time_str:
                dt_str = f"{date_str} {time_str}"
                function.date_time = datetime.datetime.strptime(dt_str, '%Y-%m-%d %H:%M')
            
            if 'poster' in request.FILES:
                function.poster = request.FILES['poster']
            
            function.save()

            # 2. --- NUEVO: GUARDAR PRECIOS ---
            # Esperamos datos como: prices[VIP]=50000, prices[GENERAL]=20000
            # Iteramos sobre todos los campos del POST buscando este patrón
            for key, value in request.POST.items():
                if key.startswith('prices[') and key.endswith(']'):
                    # Extraer el código de zona: "prices[VIP]" -> "VIP"
                    zone_code = key[7:-1] 
                    try:
                        price_val = float(value)
                        if price_val > 0:
                            # Update or Create (Upsert)
                            TicketType.objects.update_or_create(
                                function=function,
                                zone_code=zone_code,
                                defaults={
                                    'price': price_val,
                                    'name': f"Entrada {zone_code.capitalize()}" # Nombre por defecto
                                }
                            )
                    except ValueError:
                        continue # Ignorar si el precio no es un número

            return JsonResponse({'status': 'success', 'message': 'Evento y precios actualizados'})
            
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)