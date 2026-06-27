"""
🛣️ ENRUTADOR MAESTRO DE ÓRDENES, PAGOS Y AUTO-RESCATE (GRADO BANCARIO).
Arquitectura: REST Framework Router + Endpoints Financieros Aislados en RAM.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

# 1. Importación de Controladores Base (CRUD, Visor Vectorial de Tickets)
from apps.orders.api.views import (
    OrderViewSet, 
    TicketViewSet, 
    OrderRescueAPIView  # 👈 INYECTADO: Resuelve el NameError de raíz
)

# 2. Importación del Webhook Central Transaccional de Mercado Pago (Fase 3)
from apps.orders.webhooks.views import MercadoPagoWebhookView

# ==========================================================
# 🔄 ENRUTADOR AUTOMÁTICO (API GATEWAY LOCAL)
# ==========================================================
router = DefaultRouter()
router.register(r'orders', OrderViewSet, basename='orders')
router.register(r'tickets', TicketViewSet, basename='tickets')

urlpatterns = [
    # ==========================================================
    # 🛡️ ENDPOINTS CRÍTICOS FINANCIEROS (Prioridad Máxima de Red)
    # Ubicados antes del router para anular colisiones de Regex
    # ==========================================================
    
    # 🛟 1. PORTAL DE AUTO-RESCATE CRIPTOGRÁFICO (Fase 5)
    # Permite la re-dirección única de pases vectoriales utilizando el ID de Mercado Pago
    path(
        'rescue/', 
        OrderRescueAPIView.as_view(), 
        name='order_rescue_api'
    ),
    
    # 🛰️ 2. EL RADAR (Webhook Central Unificado - Fase 3)
    # Captura las notificaciones de acreditación de dinero real libres de loops DoS
    path(
        'webhook/mercadopago/', 
        MercadoPagoWebhookView.as_view(), 
        name='mp_webhook_secure'
    ),

    # ==========================================================
    # 🔄 RUTAS DINÁMICAS INDEXADAS (ViewSets)
    # ==========================================================
    # Incluye nativamente bajo O(log n):
    # GET  /api/orders/orders/                 -> Listar historial del usuario (Anti-IDOR)
    # GET  /api/orders/orders/{id}/check_status/ -> Polling asíncrono para el Frontend
    # GET  /api/orders/tickets/                -> Consultar pases aprobados
    # GET  /api/orders/tickets/{id}/qr_image/  -> Renderizador Vectorial RAM-Only del PDF
    path('', include(router.urls)),
]