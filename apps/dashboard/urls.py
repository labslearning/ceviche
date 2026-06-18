# apps/dashboard/urls.py
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
    ShowFunctionDeleteView  # 👈 Añadido: Importación del motor de purga (DELETE)
)

# 🔑 Namespace para las URLs (ej: {% url 'dashboard:home' %})
app_name = 'dashboard'

urlpatterns = [
    # ==========================================
    # 🏠 RUTAS DE NÚCLEO Y AUTENTICACIÓN
    # ==========================================
    path('', DashboardHomeView.as_view(), name='home'),
    path('home/', DashboardHomeView.as_view(), name='home_explicit'),
    
    path('login/', DashboardLoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(next_page='dashboard:login'), name='logout'),
    
    # ==========================================
    # 🎭 EDITOR DE TEATROS (VENUES)
    # ==========================================
    # 1. Ruta GENÉRICA: Para crear o cargar el mapa por defecto
    path('theater/editor/', VenueEditorView.as_view(), name='theater_editor'),
    
    # 2. Ruta ESPECÍFICA: Para editar un teatro puntual según su UUID
    path('theater/editor/<uuid:venue_id>/', VenueEditorView.as_view(), name='theater_editor_id'),
    
    # ==========================================
    # 🛒 FINANZAS Y ÓRDENES
    # ==========================================
    path('orders/', OrderListView.as_view(), name='order_list'),
    
    # ==========================================
    # 🎫 GESTIÓN DE ESPECTÁCULOS (EVENTOS)
    # ==========================================
    # 1. Listado principal
    path('events/', ShowFunctionListView.as_view(), name='event_list'),
    
    # 2. MOTOR DE CREACIÓN (El eslabón que faltaba)
    path('events/create/', ShowFunctionCreateView.as_view(), name='event_create'),
    
    # 3. MOTOR DE EDICIÓN Y PRECIOS 
    path('events/<uuid:pk>/edit/', ShowFunctionUpdateView.as_view(), name='event_edit'),
    
    # 🚨 4. MOTOR DE ERRADICACIÓN (Nueva ruta para el botón de borrar)
    path('events/<uuid:pk>/delete/', ShowFunctionDeleteView.as_view(), name='event_delete'),
]