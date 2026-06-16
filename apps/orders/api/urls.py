from django.urls import path, include
from rest_framework.routers import DefaultRouter

# Importamos ambos controladores de nuestra bóveda transaccional
from .views import OrderViewSet, TicketViewSet

# ==========================================
# 🛣️ ENRUTADOR PRINCIPAL (API GATEWAY)
# ==========================================
router = DefaultRouter()
router.register(r'orders', OrderViewSet, basename='orders')
router.register(r'tickets', TicketViewSet, basename='tickets')

urlpatterns = [
    # 🛡️ ENDPOINT CRÍTICO FINANCIERO (Prioridad 1)
    # Lo declaramos de forma explícita antes del router para garantizar 
    # que Mercado Pago siempre alcance esta ruta sin colisiones.
    path(
        'orders/webhook/mercadopago/', 
        OrderViewSet.as_view({'post': 'webhook_mercadopago'}), 
        name='mp-webhook'
    ),
    
    # ==========================================
    # 🔄 RUTAS AUTOMÁTICAS (REST Framework)
    # ==========================================
    # Incluye:
    # GET  /orders/                 -> Listar órdenes
    # POST /orders/                 -> Crear orden (Checkout)
    # GET  /orders/{id}/payment_info/ -> Regenerar pago anti-IDOR
    # GET  /tickets/                -> Listar mis boletas
    # GET  /tickets/{id}/qr_image/  -> Generador O(1) de QR en RAM
    path('', include(router.urls)),
]