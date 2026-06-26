from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from django.views.generic import RedirectView, TemplateView

# 👇 IMPORTACIONES (Limpias y sin duplicados)
from apps.website.views import (
    order_status_view, 
    HomeView, 
    events_list, 
    event_detail_view,
    CartView,
    MisTicketsView # 🚀 1. IMPORTAMOS LA NUEVA VISTA
)

from apps.events.api.views import ShowFunctionViewSet, VenueViewSet, VenueLayoutView 
from apps.products.api.views import ProductViewSet
from apps.orders.api.views import OrderViewSet, TicketViewSet
from apps.orders.webhooks.views import WompiWebhookView

# 🔌 Router para la API unificada (API V1)
router = DefaultRouter()
router.register(r'venues', VenueViewSet, basename='venues')
router.register(r'functions', ShowFunctionViewSet, basename='functions')
router.register(r'products', ProductViewSet, basename='products')
router.register(r'orders', OrderViewSet, basename='orders')
router.register(r'tickets', TicketViewSet, basename='tickets')

urlpatterns = [
    # 🛡️ Panel de Django Admin
    path('admin/', admin.site.urls),
    
    # 🚀 DASHBOARD / MANAGER
    path('dashboard/', include('apps.dashboard.urls')),
    path('manager/', RedirectView.as_view(url='/dashboard/')),

    # 🔌 API V1 (Router automático para CRUDs)
    path('api/v1/', include(router.urls)),
    
    # 🚨 RUTA MANUAL CRÍTICA PARA EL EDITOR DE TEATROS
    path('api/v1/venues/<uuid:venue_id>/layout/', VenueLayoutView.as_view(), name='api_v1_venue_layout'),
    
    # 🔌 APIS ESPECÍFICAS (Para que funcione el botón COMPRAR y otros)
    path('api/events/', include('apps.events.api.urls')),
    path('api/logistics/', include('apps.logistics.urls')),
    path('api/orders/', include('apps.orders.api.urls')), # 👈 VITAL para el checkout
    
    # 🎣 WEBHOOKS (Pagos)
    path('webhooks/wompi/', WompiWebhookView.as_view(), name='wompi_webhook'),
    
    # ==========================================
    # 🏠 SITIO PÚBLICO
    # ==========================================
    path('', HomeView.as_view(), name='home'),
    
    # 1. Cartelera General
    path('eventos/', events_list, name='public_events'),
    
    # 2. Detalle del evento (Selección de sillas)
    path('eventos/<uuid:event_id>/', event_detail_view, name='event_detail'),
    
    # 3. Carrito de Compras
    path('cart/', CartView.as_view(), name='cart_view'),

    # 🚀 4. LA BÓVEDA DEL USUARIO (Soluciona el 404 de Mercado Pago)
    path('mis-tickets/', MisTicketsView.as_view(), name='mis_tickets'),
    path('mis-tickets', MisTicketsView.as_view()), # Comodín Anti-Slash
    
    # -----------------------------------------------------------
    # 📂 TUS RUTAS ESTÁTICAS ORIGINALES (No hemos borrado nada)
    # -----------------------------------------------------------
    path('index.html', HomeView.as_view(), name='index_html'),
    path('boleteria-1.html', TemplateView.as_view(template_name="boleteria-1.html"), name='boleteria'),
    path('contact.html', TemplateView.as_view(template_name="contact.html"), name='contact'),
    path('cart.html', TemplateView.as_view(template_name="cart.html"), name='cart'), 
    path('trabaja-con-nosotros.html', TemplateView.as_view(template_name="trabaja-con-nosotros.html"), name='trabajo'),
    path('vuelos-dron.html', TemplateView.as_view(template_name="vuelos-dron.html"), name='vuelos_dron'),
    path('merch-2.html', TemplateView.as_view(template_name="merch-2.html"), name='merch'),
    path('location.html', TemplateView.as_view(template_name="location.html"), name='location'),
    
    # 📦 ESTADO DE ÓRDENES
    path('orders/<uuid:order_id>/status/', order_status_view, name='order_status'),
]

# Servir archivos estáticos y media en modo DEBUG
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)