import logging
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from django.views.generic import RedirectView, TemplateView

# 👇 IMPORTACIONES TRANSACCIONALES PURAS (Se limpia Wompi obsoleto)
from apps.website.views import (
    order_status_view, 
    HomeView, 
    events_list, 
    event_detail_view,
    CartView,
    MisTicketsView
)

from apps.events.api.views import ShowFunctionViewSet, VenueViewSet, VenueLayoutView 
from apps.products.api.views import ProductViewSet
from apps.orders.api.views import OrderViewSet, TicketViewSet
from apps.orders.webhooks.views import MercadoPagoWebhookView  # 👈 SOLUCIÓN INYECTADA

logger = logging.getLogger(__name__)

# 🔌 Router principal unificado bajo la arquitectura de red API V1
router = DefaultRouter()
router.register(r'venues', VenueViewSet, basename='venues')
router.register(r'functions', ShowFunctionViewSet, basename='functions')
router.register(r'products', ProductViewSet, basename='products')
router.register(r'orders', OrderViewSet, basename='orders')
router.register(r'tickets', TicketViewSet, basename='tickets')

urlpatterns = [
    # 🛡️ PANEL DE DJANGO ADMIN ESTRICTO
    path('admin/', admin.site.urls),
    
    # 🚀 DASHBOARD / LOGÍSTICA MANAGER
    path('dashboard/', include('apps.dashboard.urls')),
    path('manager/', RedirectView.as_view(url='/dashboard/')),

    # 🔌 API V1 INTERNA (Router automático para operaciones integradas)
    path('api/v1/', include(router.urls)),
    
    # 🚨 RUTA CRÍTICA PARA EL MOTOR DE RENDERIZADO DE MAPAS FÍSICOS
    path('api/v1/venues/<uuid:venue_id>/layout/', VenueLayoutView.as_view(), name='api_v1_venue_layout'),
    
    # 🔌 TÚNELES DE APLICACIONES INTERCONECTADAS
    path('api/events/', include('apps.events.api.urls')),
    path('api/logistics/', include('apps.logistics.urls')),
    path('api/orders/', include('apps.orders.api.urls')), 
    
    # 🛰️ BÓVEDA INMUTABLE DE WEBHOOKS (Mercado Pago Gateway)
    path('webhooks/mercadopago/', MercadoPagoWebhookView.as_view(), name='mp_webhook_secure'),
    
    # ==============================================================================
    # 🏠 SITIO PÚBLICO RESPONSIVE (MOBILE-FIRST PRINCIPLE)
    # ==============================================================================
    path('', HomeView.as_view(), name='home'),
    
    # 1. Cartelera de Eventos General
    path('eventos/', events_list, name='public_events'),
    
    # 2. Detalle de Función (Selección de Sillas / Localidades)
    path('eventos/<uuid:event_id>/', event_detail_view, name='event_detail'),
    
    # 3. Pipeline del Carrito de Compras E-Commerce
    path('cart/', CartView.as_view(), name='cart_view'),

    # 🔐 4. LA BÓVEDA DIGITAL DEL ASISTENTE (Consulta Criptográfica Segura)
    path('mis-tickets/', MisTicketsView.as_view(), name='mis_tickets'),
    path('mis-tickets', MisTicketsView.as_view()), # Comodín elástico anti-slash
    
    # ----------------------------------------------------------------------
    # 📂 CAPA DE COMPATIBILIDAD RETROACTIVA (Vistas estáticas legacy retenidas)
    # ----------------------------------------------------------------------
    path('index.html', HomeView.as_view(), name='index_html'),
    path('boleteria-1.html', TemplateView.as_view(template_name="boleteria-1.html"), name='boleteria'),
    path('contact.html', TemplateView.as_view(template_name="contact.html"), name='contact'),
    path('cart.html', TemplateView.as_view(template_name="cart.html"), name='cart'), 
    path('trabaja-con-nosotros.html', TemplateView.as_view(template_name="trabaja-con-nosotros.html"), name='trabajo'),
    path('vuelos-dron.html', TemplateView.as_view(template_name="vuelos-dron.html"), name='vuelos_dron'),
    path('merch-2.html', TemplateView.as_view(template_name="merch-2.html"), name='merch'),
    path('location.html', TemplateView.as_view(template_name="location.html"), name='location'),
    
    # 📦 SEGUIMIENTO LOGÍSTICO Y POLLING DE ÓRDENES
    path('orders/<uuid:order_id>/status/', order_status_view, name='order_status'),
]

# Servido de recursos multimedia en entornos locales de aislamiento
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)