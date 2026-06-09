from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import OrderViewSet

router = DefaultRouter()
router.register(r'orders', OrderViewSet, basename='orders')

urlpatterns = [
    # Rutas automáticas:
    # GET /api/orders/orders/ -> Listar mis órdenes
    # POST /api/orders/orders/ -> Crear orden (Checkout)
    path('', include(router.urls)),
]
