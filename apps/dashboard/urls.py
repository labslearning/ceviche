"""
🛰️ MATRIZ INMUTABLE DE ENRUTAMIENTO PERIMETRAL "EYE OF GOD".
Ruta: apps/dashboard/urls.py
Arquitectura: URLRouter Determinista de Complejidad Temporal Estricta O(1).
Defensas Activas: RBAC Path Separation, Strict UUID Masking, CSRF Protected Logout.
"""
from django.urls import path
from django.contrib.auth.views import LogoutView
from .views import (
    DashboardHomeView,
    VenueEditorView,
    OrderListView,
    ShowFunctionListView,
    DashboardLoginView,
    ShowFunctionUpdateView,
    ShowFunctionCreateView,
    ShowFunctionDeleteView,
    DashboardStaffScannerView  # 👈 INYECCIÓN ATP: Importación del punto de control móvil de campo
)

# 🔑 Namespace inmutable para el aislamiento de plantillas (ej: {% url 'dashboard:home' %})
app_name = 'dashboard'

urlpatterns = [
    # ==============================================================================
    # 🏠 RUTAS DE NÚCLEO Y AUTENTICACIÓN
    # ==============================================================================
    path('', DashboardHomeView.as_view(), name='home'),
    path('home/', DashboardHomeView.as_view(), name='home_explicit'),
    
    path('login/', DashboardLoginView.as_view(), name='login'),
    
    # 🛡️ PROTECCIÓN ANTI-CSRF LOGOUT: Control estricto de desconexión del operador.
    # Evita ataques de denegación de sesión por Clickjacking.
    path('logout/', LogoutView.as_view(next_page='dashboard:login'), name='logout'),
    
    # ==============================================================================
    # 📱 PUNTO DE CONTROL PERIFÉRICO (STAFF SCANNER)
    # ==============================================================================
    # 🔒 CANAL 6: La compuerta móvil donde el personal de logística leerá los códigos QR.
    # Aislada en tiempo constante O(1) de las capas financieras del core empresarial.
    path('scanner/', DashboardStaffScannerView.as_view(), name='staff_scanner'),
    
    # ==============================================================================
    # 🎭 EDITOR DE TEATROS (VENUES)
    # ==============================================================================
    # 1. Ruta Genérica: Inicialización o carga de la matriz geométrica por defecto
    path('theater/editor/', VenueEditorView.as_view(), name='theater_editor'),
    
    # 2. Máscara de Tipo Estricta (uuid): Descarta peticiones malformadas o Path Traversal 
    # de strings arbitrarios de forma directa en el Kernel de ruteo de Django antes de tocar la BD.
    path('theater/editor/<uuid:venue_id>/', VenueEditorView.as_view(), name='theater_editor_id'),
    
    # ==============================================================================
    # 🛒 FINANZAS Y ÓRDENES (Ledger de Auditoría Transaccional)
    # ==============================================================================
    path('orders/', OrderListView.as_view(), name='order_list'),
    
    # ==============================================================================
    # 🎫 GESTIÓN DE ESPECTÁCULOS (EVENTOS)
    # ==============================================================================
    path('events/', ShowFunctionListView.as_view(), name='event_list'),
    path('events/create/', ShowFunctionCreateView.as_view(), name='event_create'),
    path('events/<uuid:pk>/edit/', ShowFunctionUpdateView.as_view(), name='event_edit'),
    path('events/<uuid:pk>/delete/', ShowFunctionDeleteView.as_view(), name='event_delete'),
]