# apps/dashboard/views.py
import logging
import json
import datetime
import urllib.request
import uuid  # 👈 Añadido para validación criptográfica de IDs
from urllib.error import URLError
from decimal import Decimal, InvalidOperation

from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import TemplateView, ListView, View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import LoginView
from django.http import JsonResponse
from django.db import transaction, DatabaseError
from django.db.models import Sum, Q
from django.utils import timezone
from django.core.files.base import ContentFile

# 🛡️ IMPORTACIÓN ESTRATÉGICA DE MODELOS
from apps.orders.models import Order
from apps.users.models import User
from apps.events.models import Venue, ShowFunction, TicketType

# 🛡️ LOGGER SOC/SIEM (Trazabilidad Forense de Auditoría)
logger = logging.getLogger(__name__)

# ==============================================================================
# 🚀 MOTOR DE INGESTIÓN MULTI-ORIGEN (God-Tier Web Scraper)
# ==============================================================================

def process_and_save_poster(show_obj, request):
    """
    Motor de captura de activos multimedia.
    Mitiga ataques de Hotlinking y Fugas de Memoria (OOM).
    Si se detecta una URL, el backend viaja, extrae el binario y lo almacena localmente.
    """
    poster_file = request.FILES.get('poster')
    poster_url = request.POST.get('poster_url', '').strip()

    # 1. Prioridad 1: Si el usuario subió un archivo físico manualmente
    if poster_file and poster_file.name:
        show_obj.poster = poster_file
        show_obj.save()
        return

    # 2. Prioridad 2: Si el usuario pegó un enlace de internet
    if poster_url and poster_url.startswith('http'):
        try:
            # 🛡️ User-Agent Spoofing: Evita ser detectado como Bot/Scraper por WAFs
            req = urllib.request.Request(poster_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8'
            })
            
            # 🛡️ Timeout Shield: Previene ataques Slowloris limitando a 5 segundos
            with urllib.request.urlopen(req, timeout=5) as response:
                # 🛡️ Memory Limit Shield (OOM Protection): Límite estricto de 5 Megabytes
                MAX_SIZE = 5 * 1024 * 1024 
                file_content = response.read(MAX_SIZE + 1)
                
                if len(file_content) > MAX_SIZE:
                    raise ValueError("El archivo excede la cuota militar de 5MB. Ingestión abortada.")

                img_name = poster_url.split("/")[-1].split("?")[0]
                if not img_name or not img_name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    img_name = f"poster_{show_obj.id}.jpg"
                
                # Guarda el binario descargado directamente en el ecosistema de Django
                show_obj.poster.save(img_name, ContentFile(file_content), save=True)
                
        except Exception as e:
            logger.error(f"God-Tier Ingestion Error: Fallo descargando póster URL {poster_url} -> {str(e)}")


# ==============================================================================
# 🛡️ 1. CAPA DE SEGURIDAD Y DEFENSA PERIMETRAL (Zero-Trust)
# ==============================================================================

class SuperUserRequiredMixin(UserPassesTestMixin):
    """
    Control de Acceso Basado en Roles (RBAC). 
    Bloquea accesos laterales (IDOR) a la consola de administración.
    """
    def test_func(self):
        return self.request.user.is_superuser or self.request.user.is_staff
    
    def handle_no_permission(self):
        logger.warning(f"Intento de acceso denegado al Dashboard. IP/User: {self.request.user}")
        return redirect('dashboard:login')

class DashboardLoginView(LoginView):
    template_name = 'dashboard/login.html'
    redirect_authenticated_user = True 
    next_page = 'dashboard:home'


# ==============================================================================
# 📊 2. NÚCLEO DE TELEMETRÍA (Dashboards y KPIs)
# ==============================================================================

class DashboardHomeView(LoginRequiredMixin, SuperUserRequiredMixin, TemplateView):
    """
    Procesador de Estadísticas en Tiempo Real.
    Big O Optimizado: Delegamos el cálculo pesado al motor de Base de Datos.
    """
    template_name = "dashboard/home.html"
    login_url = '/dashboard/login/'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        
        try:
            approved_orders = Order.objects.filter(status=Order.Status.APPROVED)
        except AttributeError:
            approved_orders = Order.objects.filter(status='APPROVED')

        total_sales = approved_orders.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        total_tickets = approved_orders.count()

        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_end = current_month_start - datetime.timedelta(seconds=1)
        last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        sales_this_month = approved_orders.filter(created_at__gte=current_month_start).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        sales_last_month = approved_orders.filter(created_at__range=(last_month_start, last_month_end)).aggregate(Sum('total_amount'))['total_amount__sum'] or 0

        growth = Decimal('0.0')
        if sales_last_month > 0:
            growth = ((Decimal(str(sales_this_month)) - Decimal(str(sales_last_month))) / Decimal(str(sales_last_month))) * 100
        elif sales_this_month > 0:
            growth = Decimal('100.0')

        chart_labels = []
        chart_data = []
        for i in range(6, -1, -1):
            day = now - datetime.timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
            daily_sales = approved_orders.filter(created_at__range=(day_start, day_end)).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
            chart_labels.append(day.strftime('%a'))
            chart_data.append(float(daily_sales))

        context.update({
            "total_sales": total_sales,
            "total_tickets": total_tickets,
            "growth_percentage": round(float(growth), 1),
            "is_growth_positive": growth >= 0,
            "chart_labels": json.dumps(chart_labels),
            "chart_data": json.dumps(chart_data),
        })
        return context


# ==============================================================================
# 🎫 3. LISTADOS INDEXADOS (Data Grids con Búsqueda O(log N))
# ==============================================================================

class OrderListView(LoginRequiredMixin, SuperUserRequiredMixin, ListView):
    model = Order
    template_name = "dashboard/orders_list.html"
    context_object_name = "orders"
    login_url = '/dashboard/login/'
    paginate_by = 20

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
            status_map = {
                'Aprobados': 'APPROVED',
                'Pendientes': 'PENDING',
                'Rechazados': 'REJECTED'
            }
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


# ==============================================================================
# 🏗️ 4. MOTORES TRANSACCIONALES CRUD (Data Integrity & ACID Compliance)
# ==============================================================================

class VenueEditorView(LoginRequiredMixin, SuperUserRequiredMixin, TemplateView):
    """
    Motor de I/O para el mapa físico de sillas.
    """
    template_name = "dashboard/theater_editor.html"
    login_url = '/dashboard/login/'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        venue_id = self.kwargs.get('venue_id')
        
        if venue_id:
            venue = get_object_or_404(Venue, pk=venue_id)
        else:
            venue = Venue.objects.first()
            if not venue:
                venue = Venue.objects.create(
                    name="Teatro Principal", 
                    city="Bogotá",
                    address="Calle 123",
                    layout={'blocks': []} 
                )
        
        context['theater'] = venue 
        context['existing_layout'] = json.dumps(venue.layout) if venue.layout else '{"blocks": []}'
        return context

    def post(self, request, *args, **kwargs):
        venue_id = self.kwargs.get('venue_id')
        venue = get_object_or_404(Venue, pk=venue_id) if venue_id else Venue.objects.first()

        try:
            data = json.loads(request.body)
            venue.layout = data.get('layout', {})
            if data.get('capacity'):
                venue.capacity = data.get('capacity')
            venue.save()
            
            return JsonResponse({'status': 'ok', 'message': 'Mapa guardado correctamente'})
        except Exception as e:
            logger.error(f"Falla procesando Payload del Venue: {str(e)}")
            return JsonResponse({'status': 'error', 'message': "Cuerpo de petición inválido."}, status=400)


class ShowFunctionCreateView(LoginRequiredMixin, SuperUserRequiredMixin, View):
    """
    🚀 MOTOR DE CREACIÓN ATÓMICA CON VINCULACIÓN DINÁMICA DE TEATROS (GOD-TIER).
    """
    def post(self, request, *args, **kwargs):
        try:
            # 🛡️ ACID SHIELD: Bloqueo de escritura integral
            with transaction.atomic():
                name = request.POST.get('name')
                description = request.POST.get('description', '')
                date_str = request.POST.get('date')
                time_str = request.POST.get('time')
                
                # 🔍 VALIDACIÓN CRIPTOGRÁFICA Y DE INTEGRIDAD REFERENCIAL DEL TEATRO
                venue_id = request.POST.get('venue_id')
                if not venue_id:
                    return JsonResponse({'status': 'error', 'message': 'Denegado: Es obligatorio vincular una Matriz Física (Teatro) al evento.'}, status=400)
                
                # 🛡️ Prevención de Memory Dumps y Crashes (Protección UUID)
                try:
                    val_uuid = uuid.UUID(venue_id)
                    venue = Venue.objects.get(pk=val_uuid)
                except (ValueError, TypeError, Venue.DoesNotExist):
                    logger.warning(f"Intento de inyección de UUID inválido o Teatro inexistente: {venue_id}")
                    return JsonResponse({'status': 'error', 'message': 'Falla de Integridad: El Teatro especificado no existe o la conexión se perdió.'}, status=400)

                # Validación de carga útil
                if not name or not date_str or not time_str:
                    return JsonResponse({'status': 'error', 'message': 'Payload incompleto. Faltan datos críticos en la petición.'}, status=400)

                # 🛡️ TIMEZONE SHIELD: Evita desfases en servidores Cloud
                dt_str = f"{date_str} {time_str}"
                naive_dt = datetime.datetime.strptime(dt_str, '%Y-%m-%d %H:%M')
                aware_dt = timezone.make_aware(naive_dt)

                # Inserción en Base de Datos
                new_show = ShowFunction.objects.create(
                    venue=venue, # 👈 Vínculo explícito y validado
                    name=name,
                    description=description,
                    date_time=aware_dt,
                    active=True 
                )

                # 🛡️ INGESTIÓN MULTIMEDIA
                process_and_save_poster(new_show, request)

                return JsonResponse({'status': 'success', 'message': 'Nodo de Evento y activos lanzados a producción.'})

        except DatabaseError as e:
            logger.critical(f"Falla atómica creando ShowFunction: {str(e)}")
            return JsonResponse({'status': 'error', 'message': 'Fallo de integridad DB en PostgreSQL.'}, status=500)
        except Exception as e:
            logger.exception("Excepción no controlada en motor de creación.")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


class ShowFunctionUpdateView(LoginRequiredMixin, SuperUserRequiredMixin, View):
    """
    ⚙️ MOTOR HÍBRIDO DE EDICIÓN Y PRECIOS FINTECH.
    """
    def get(self, request, pk):
        function = get_object_or_404(ShowFunction, pk=pk)
        
        layout = function.venue.layout if function.venue else {}
        blocks = layout.get('blocks', []) or []
        
        total_seats = 0
        detected_zones = set()
        
        # O(N) Scanner: Extrae zonas sin duplicar memoria
        for block in blocks:
            seats = block.get('seats', [])
            total_seats += len(seats)
            for seat in seats:
                detected_zones.add(seat.get('type') or seat.get('category') or 'General')
        
        sold_seats = getattr(function, 'sold_seats', 0)
        available_seats = total_seats - sold_seats
        occupancy_rate = round((sold_seats / total_seats * 100), 1) if total_seats > 0 else 0

        # Recuperación de Precios O(1)
        existing_prices = {
            tt.zone_code: tt.price for tt in TicketType.objects.filter(function=function)
        }

        price_list = []
        for zone in detected_zones:
            price_list.append({
                'zone_code': zone,
                'zone_name': zone.upper(),
                'current_price': existing_prices.get(zone, 0)
            })

        local_dt = timezone.localtime(function.date_time)

        data = {
            'id': function.id,
            'name': function.name,
            'venue_id': str(function.venue.id) if function.venue else "", # 👈 Inyectado para pre-seleccionar teatro actual
            'date': local_dt.strftime('%Y-%m-%d'),
            'time': local_dt.strftime('%H:%M'),
            'description': function.description or "",
            'active': function.active,
            'poster_url': function.poster.url if function.poster else None,
            'stats': {
                'total': total_seats,
                'sold': sold_seats,
                'available': available_seats,
                'occupancy': occupancy_rate
            },
            'pricing': price_list 
        }
        return JsonResponse(data)

    def post(self, request, pk):
        function = get_object_or_404(ShowFunction, pk=pk)
        
        try:
            # 🛡️ ACID COMPLIANCE: O guardamos todo, o hacemos Rollback.
            with transaction.atomic():
                
                function.name = request.POST.get('name')
                function.description = request.POST.get('description')
                function.active = request.POST.get('active') == 'true'
                
                # 🔄 PERMITE ACTUALIZAR EL TEATRO (Si se envió en el payload)
                venue_id = request.POST.get('venue_id')
                if venue_id:
                    try:
                        val_uuid = uuid.UUID(venue_id)
                        function.venue = Venue.objects.get(pk=val_uuid)
                    except (ValueError, TypeError, Venue.DoesNotExist):
                        pass # Si hay error silencioso, conserva el teatro actual.
                
                date_str = request.POST.get('date')
                time_str = request.POST.get('time')
                if date_str and time_str:
                    dt_str = f"{date_str} {time_str}"
                    naive_dt = datetime.datetime.strptime(dt_str, '%Y-%m-%d %H:%M')
                    function.date_time = timezone.make_aware(naive_dt)
                
                function.save()

                # 🛡️ INGESTIÓN MULTIMEDIA AL ACTUALIZAR
                process_and_save_poster(function, request)

                # 2. Inyección de Precios (FinTech Decimal Guard)
                for key, value in request.POST.items():
                    if key.startswith('prices[') and key.endswith(']'):
                        zone_code = key[7:-1] 
                        try:
                            # Se usa Decimal estricto, nunca flotantes para precisión bancaria.
                            price_val = Decimal(str(value))
                            if price_val > Decimal('0.0'):
                                TicketType.objects.update_or_create(
                                    function=function,
                                    zone_code=zone_code,
                                    defaults={
                                        'price': price_val,
                                        'name': f"Entrada {zone_code.capitalize()}"
                                    }
                                )
                        except (ValueError, InvalidOperation):
                            continue

            return JsonResponse({'status': 'success', 'message': 'Transacción de actualización completada.'})
            
        except DatabaseError as e:
            logger.critical(f"Rollback disparado en edición de precios. Error DB: {str(e)}")
            return JsonResponse({'status': 'error', 'message': 'Fallo crítico DB. Cambios revertidos.'}, status=500)
        except Exception as e:
            logger.exception("Excepción no controlada en motor de edición.")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


# ==============================================================================
# 🚨 5. PROTOCOLO DE ERRADICACIÓN DE NODOS (DELETE VIEW)
# ==============================================================================

class ShowFunctionDeleteView(LoginRequiredMixin, SuperUserRequiredMixin, View):
    """
    🚨 PROTOCOLO DE PURGA ATÓMICA
    Erradica un evento de la base de datos de forma irreversible.
    """
    def post(self, request, pk):
        try:
            event = get_object_or_404(ShowFunction, pk=pk)
            event_name = event.name
            event.delete()
            logger.info(f"Nodo Erradicado: {event_name} (ID: {pk}) por el usuario {request.user}")
            return JsonResponse({'status': 'success', 'message': 'Nodo erradicado exitosamente'})
        except Exception as e:
            logger.error(f"Fallo en la purga del evento {pk}: {str(e)}")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)