"""
🛣️ ENRUTADOR MAESTRO DE ÓRDENES Y PAGOS
Arquitectura: REST Framework Router + Endpoints Financieros Aislados
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

# 1. Importamos las vistas clásicas (CRUD, QRs, Consultas de Pago)
from .views import OrderViewSet, TicketViewSet

# 2. Importamos la nueva Bóveda Transaccional God-Tier (Mercado Pago)
from .api.mercadopago import CheckoutMercadoPagoAPIView
from .webhooks.mercadopago_ipn import MercadoPagoWebhookAPIView

# ==========================================
# 🔄 ENRUTADOR AUTOMÁTICO (API GATEWAY LOCAL)
# ==========================================
router = DefaultRouter()
router.register(r'orders', OrderViewSet, basename='orders')
router.register(r'tickets', TicketViewSet, basename='tickets')

urlpatterns = [
    # ==========================================================
    # 🛡️ ENDPOINTS CRÍTICOS FINANCIEROS (Prioridad Máxima)
    # Deben ir antes del router para evitar colisiones de Regex
    # ==========================================================
    
    # 📡 1. EL RADAR (Webhook IPN)
    # Ruta real: /api/orders/webhook/mercadopago/
    path(
        'webhook/mercadopago/', 
        MercadoPagoWebhookAPIView.as_view(), 
        name='mp-webhook'
    ),
    
    # 💳 2. EL MOTOR DE PAGOS (Checkout)
    # Ruta real: /api/orders/checkout/mercadopago/
    path(
        'checkout/mercadopago/', 
        CheckoutMercadoPagoAPIView.as_view(), 
        name='mp-checkout'
    ),

    # ==========================================================
    # 🔄 RUTAS DINÁMICAS (ViewSets)
    # ==========================================================
    # Incluye:
    # GET  /api/orders/                 -> Listar órdenes
    # GET  /api/orders/{id}/payment_info/ -> Regenerar pago anti-IDOR
    # GET  /api/tickets/                -> Listar mis boletas
    # GET  /api/tickets/{id}/qr_image/  -> Generador O(1) de QR en RAM
    path('', include(router.urls)),
]