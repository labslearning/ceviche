from django.urls import path
from .views import (
    HomeView, 
    BoleteriaView, 
    CartView, 
    event_detail_view, 
    order_status_view
)

urlpatterns = [
    # 🏠 Landing Page (Raíz)
    path('', HomeView.as_view(), name='home'),
    
    # 🎟️ Cartelera / Boletería
    path('boleteria/', BoleteriaView.as_view(), name='boleteria'),
    
    # 🛒 Carrito de Compras
    path('cart/', CartView.as_view(), name='cart'),
    
    # 🎫 Detalle del Evento (Selección de sillas)
    # Usamos <uuid:event_id> asumiendo que tus IDs son UUIDs (como en Orders)
    path('events/<uuid:event_id>/', event_detail_view, name='event_detail'),
    
    # ✅ Estado de la Orden (Post-Pago)
    path('orders/<uuid:order_id>/status/', order_status_view, name='order_status'),
]
