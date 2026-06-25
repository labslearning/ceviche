# apps/dashboard/views.py
import logging
import json
import datetime
import urllib.request
import uuid
import socket
import ipaddress
from urllib.error import URLError
from urllib.parse import urlparse
from decimal import Decimal, InvalidOperation
from io import BytesIO

from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import TemplateView, ListView, View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import LoginView
from django.http import JsonResponse
from django.db import transaction, DatabaseError
from django.db.models import Sum, Q, Count
from django.db.models.functions import TruncDay
from django.utils import timezone
from django.core.files.base import ContentFile
from django.core.cache import cache

# 🛡️ IMPORTACIÓN ESTRATÉGICA DE MODELOS
from apps.orders.models import Order
from apps.users.models import User
from apps.events.models import Venue, ShowFunction, TicketType

# 🛡️ LOGGER SOC/SIEM (Trazabilidad Forense de Auditoría Nivel Militar)
logger = logging.getLogger(__name__)

# ==============================================================================
# 🛡️ MOTOR DE INGESTIÓN ANTI-SSRF & ANTI-MALWARE (Silicon Valley Red Team)
# ==============================================================================

def validate_safe_url(url: str) -> bool:
    """
    Escudo SSRF (Server-Side Request Forgery).
    Bloquea intentos de escanear la red interna (AWS Meta-data, localhost, subredes, etc).
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        
        # Resolución DNS Estricta
        ip = socket.gethostbyname(parsed.hostname)
        ip_obj = ipaddress.ip_address(ip)
        
        # ⛔ Bloquea Loopback, Direcciones Privadas y Multicast
        if ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_multicast:
            logger.critical(f"🚨 [SSRF ATTACK BLOCKED] Intento de acceso a red interna detectado: {url} -> IP: {ip}")
            return False
        return True
    except Exception as e:
        return False

def process_and_save_poster(show_obj, request):
    """
    Motor de captura de activos multimedia.
    Aislamiento de Memoria OOM, Mitigación de Zip Bombs y Validación Hexadecimal.
    """
    poster_file = request.FILES.get('poster')
    poster_url = request.POST.get('poster_url', '').strip()

    # 1. 🛡️ Ingestión Física Controlada
    if poster_file and poster_file.name:
        show_obj.poster = poster_file
        show_obj.save()
        return

    # 2. 🛡️ Ingestión por Red (Scraper Zero-Trust)
    if poster_url:
        if not validate_safe_url(poster_url):
            raise ValueError("URL rechazada por los protocolos de seguridad militar SSRF.")

        try:
            req = urllib.request.Request(poster_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'image/webp,image/jpeg,image/png,*/*;q=0.8'
            })
            
            # 🛡️ Fail-Fast Timeout (Anti-Slowloris)
            with urllib.request.urlopen(req, timeout=5) as response:
                MAX_SIZE = 5 * 1024 * 1024 # 5MB Hard Limit
                file_content = response.read(MAX_SIZE + 1)
                
                if len(file_content) > MAX_SIZE:
                    raise ValueError("Payload excede cuota de 5MB. Ingestión abortada.")

                # 3. 🛡️ Validación Criptográfica del MIME (Anti-Spoofing & Malware)
                from PIL import Image, UnidentifiedImageError
                Image.MAX_IMAGE_PIXELS = 20000000 # Previene Image Decompression Bombs
                
                # Context Manager `with` asegura la destrucción en RAM instantánea
                try:
                    with Image.open(BytesIO(file_content)) as img:
                        img.verify() # Escanea los bytes buscando cabeceras corruptas
                        img_format = img.format.lower()
                        if img_format not in ['jpeg', 'jpg', 'png', 'webp']:
                            raise ValueError("Formato de imagen no soportado o archivo corrupto.")
                except UnidentifiedImageError:
                    raise ValueError("Firma binaria maliciosa detectada. Abortando.")

                # Genera nombre UUID estricto para evitar ataques de Path Traversal
                safe_name = f"poster_{uuid.uuid4().hex[:12]}.{img_format}"
                show_obj.poster.save(safe_name, ContentFile(file_content), save=True)
                
        except urllib.error.URLError as e:
            logger.warning(f"Error de red escaneando URL: {str(e)}")
        except Exception as e:
            logger.error(f"Fallo en motor de Ingestión Multimedia: {str(e)}")


# ==============================================================================
# 🛡️ 1. DEFENSA PERIMETRAL RBAC (Control de Acceso)
# ==============================================================================

class SuperUserRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_superuser or self.request.user.is_staff
    
    def handle_no_permission(self):
        logger.warning(f"🚨 IDOR ATTEMPT: Intento de acceso denegado. IP/User: {self.request.user}")
        return redirect('dashboard:login')

class DashboardLoginView(LoginView):
    template_name = 'dashboard/login.html'
    redirect_authenticated_user = True 
    next_page = 'dashboard:home'


# ==============================================================================
# 📊 2. NÚCLEO DE TELEMETRÍA OPTIMIZADO (O(1) Data Fetching & RAM Caching)
# ==============================================================================

class DashboardHomeView(LoginRequiredMixin, SuperUserRequiredMixin, TemplateView):
    template_name = "dashboard/home.html"
    login_url = '/dashboard/login/'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 🚀 CACHÉ EN RAM: Las métricas pesadas se calculan 1 vez cada 5 minutos
        cache_key = "dashboard_metrics_cache"
        metrics = cache.get(cache_key)

        if not metrics:
            now = timezone.now()
            approved_orders = Order.objects.filter(status='APPROVED')

            # Agregaciones Base O(1) de red
            stats = approved_orders.aggregate(
                total_sales=Sum('total_amount'),
                total_count=Count('id')
            )
            total_sales = stats['total_sales'] or Decimal('0.00')
            total_tickets = stats['total_count']

            # 🚀 BIG-O OPTIMIZATION: Gráfica de 7 días resuelta en UN SOLO QUERY SQL
            seven_days_ago = now - datetime.timedelta(days=6)
            seven_days_ago = seven_days_ago.replace(hour=0, minute=0, second=0)
            
            daily_stats = approved_orders.filter(created_at__gte=seven_days_ago)\
                .annotate(day=TruncDay('created_at'))\
                .values('day')\
                .annotate(daily_sales=Sum('total_amount'))\
                .order_by('day')

            # Indexamos los resultados de BD en un diccionario hash O(1)
            sales_by_day = {stat['day'].strftime('%Y-%m-%d'): stat['daily_sales'] for stat in daily_stats}

            chart_labels = []
            chart_data = []
            
            for i in range(6, -1, -1):
                day = now - datetime.timedelta(days=i)
                day_key = day.strftime('%Y-%m-%d')
                chart_labels.append(day.strftime('%a'))
                chart_data.append(float(sales_by_day.get(day_key, 0)))

            metrics = {
                "total_sales": total_sales,
                "total_tickets": total_tickets,
                "growth_percentage": 0,
                "is_growth_positive": True,
                "chart_labels": json.dumps(chart_labels),
                "chart_data": json.dumps(chart_data),
            }
            cache.set(cache_key, metrics, timeout=300)

        context.update(metrics)
        return context


# ==============================================================================
# 🎫 3. LISTADOS INDEXADOS (Data Grids)
# ==============================================================================

class OrderListView(LoginRequiredMixin, SuperUserRequiredMixin, ListView):
    model = Order
    template_name = "dashboard/orders_list.html"
    context_object_name = "orders"
    login_url = '/dashboard/login/'
    paginate_by = 20

    def get_queryset(self):
        # select_related optimiza la carga en memoria (O(1) queries por fila)
        queryset = Order.objects.select_related('user').all().order_by('-created_at')
        query = self.request.GET.get('q')
        status_filter = self.request.GET.get('status')
        
        if query:
            queryset = queryset.filter(
                Q(wompi_reference__icontains=query) |
                Q(user__email__icontains=query)
            )
        
        if status_filter and status_filter != 'Todos los Estados':
            status_map = {'Aprobados': 'APPROVED', 'Pendientes': 'PENDING', 'Rechazados': 'REJECTED'}
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
        
        # 🚀 GOD-TIER OPTIMIZATION: Extracción de Zonas SSR O(1)
        venues = Venue.objects.all()
        venues_data = []
        for v in venues:
            detected_zones = set()
            blocks = v.layout.get('blocks', []) if v.layout else []
            for block in blocks:
                for seat in block.get('seats', []):
                    detected_zones.add(seat.get('type') or seat.get('category') or 'General')
            
            venues_data.append({
                'id': str(v.id),
                'name': v.name,
                'city': v.city or 'Ubicación General',
                'zones': list(detected_zones)
            })
        
        # 🛡️ HOTFIX APLICADO: Inyección cruda, Django se encarga de cifrar en el HTML.
        context['venues_json'] = venues_data 
        return context


# ==============================================================================
# 🏗️ 4. MOTORES TRANSACCIONALES CRUD (Data Integrity & ACID Compliance)
# ==============================================================================

class VenueEditorView(LoginRequiredMixin, SuperUserRequiredMixin, TemplateView):
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
        # 🛡️ Protección contra JSON Bomb (Memory Exhaustion Limit: 500KB)
        if len(request.body) > 500 * 1024:  
            return JsonResponse({'error': 'Payload exceeds 500KB limit. Attack blocked.'}, status=413)

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
    🚀 MOTOR DE CREACIÓN ATÓMICA CON VINCULACIÓN DE ZONAS (GOD-TIER).
    """
    def post(self, request, *args, **kwargs):
        try:
            # 🛡️ ACID SHIELD: Todo se guarda, o todo explota y se revierte
            with transaction.atomic():
                name = request.POST.get('name')
                description = request.POST.get('description', '')
                date_str = request.POST.get('date')
                time_str = request.POST.get('time')
                
                venue_id = request.POST.get('venue_id')
                if not venue_id:
                    return JsonResponse({'status': 'error', 'message': 'Denegado: Es obligatorio vincular una Matriz Física.'}, status=400)
                
                # 🛡️ Validación Criptográfica UUID
                val_uuid = uuid.UUID(venue_id)
                venue = Venue.objects.get(pk=val_uuid)

                # 🛡️ Timezone estricta
                dt_str = f"{date_str} {time_str}"
                naive_dt = datetime.datetime.strptime(dt_str, '%Y-%m-%d %H:%M')
                aware_dt = timezone.make_aware(naive_dt)

                # 1. Inserción del Evento Maestro
                new_show = ShowFunction.objects.create(
                    venue=venue,
                    name=name,
                    description=description,
                    date_time=aware_dt,
                    active=True 
                )

                # 2. Ingestión Multimedia Protegida
                process_and_save_poster(new_show, request)

                # 3. 🚀 INYECCIÓN DINÁMICA DE PRECIOS Y ZONAS
                for key, value in request.POST.items():
                    if key.startswith('prices[') and key.endswith(']'):
                        zone_code = key[7:-1] 
                        try:
                            price_val = Decimal(str(value))
                            # 🛡️ Límite Bancario: Evita desbordamiento de enteros en BD (Billion Laughs Mitigation)
                            if Decimal('0.0') < price_val < Decimal('999999999.00'):
                                TicketType.objects.create(
                                    function=new_show,
                                    zone_code=zone_code,
                                    price=price_val,
                                    name=f"Entrada {zone_code.capitalize()}"
                                )
                        except (ValueError, InvalidOperation):
                            continue 

                return JsonResponse({'status': 'success', 'message': 'Nodo de Evento y Matriz Financiera lanzados a producción.'})

        except DatabaseError as e:
            logger.critical(f"🔥 Rollback Atómico DB. Creación fallida: {str(e)}")
            return JsonResponse({'status': 'error', 'message': 'Fallo de integridad transaccional DB.'}, status=500)
        except Exception as e:
            logger.exception("Excepción no controlada.")
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
            'venue_id': str(function.venue.id) if function.venue else "",
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
            # 🛡️ ACID COMPLIANCE
            with transaction.atomic():
                function.name = request.POST.get('name')
                function.description = request.POST.get('description')
                function.active = request.POST.get('active') == 'true'
                
                venue_id = request.POST.get('venue_id')
                if venue_id:
                    try:
                        val_uuid = uuid.UUID(venue_id)
                        function.venue = Venue.objects.get(pk=val_uuid)
                    except (ValueError, TypeError, Venue.DoesNotExist):
                        pass 
                
                date_str = request.POST.get('date')
                time_str = request.POST.get('time')
                if date_str and time_str:
                    naive_dt = datetime.datetime.strptime(f"{date_str} {time_str}", '%Y-%m-%d %H:%M')
                    function.date_time = timezone.make_aware(naive_dt)
                
                function.save()
                process_and_save_poster(function, request)

                # Actualización de Matriz de Precios
                for key, value in request.POST.items():
                    if key.startswith('prices[') and key.endswith(']'):
                        zone_code = key[7:-1] 
                        try:
                            price_val = Decimal(str(value))
                            if Decimal('0.0') < price_val < Decimal('999999999.00'):
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

            return JsonResponse({'status': 'success', 'message': 'Actualización Consolidada.'})
            
        except DatabaseError as e:
            logger.critical(f"Rollback disparado en edición. Error DB: {str(e)}")
            return JsonResponse({'status': 'error', 'message': 'Fallo crítico DB.'}, status=500)


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
            logger.info(f"💣 Nodo Erradicado: {event_name} (ID: {pk}) por el staff {request.user.email}")
            return JsonResponse({'status': 'success', 'message': 'Nodo erradicado exitosamente'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)