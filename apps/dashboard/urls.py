from django.urls import path
from django.contrib.auth.views import LogoutView
from .views import (
    DashboardHomeView,
    VenueEditorView,
    OrderListView,
    ShowFunctionListView,
    DashboardLoginView,
    ShowFunctionUpdateView
)

# 🔑 Namespace para las URLs (ej: {% url 'dashboard:home' %})
app_name = 'dashboard'

urlpatterns = [
    # 🏠 RUTA RAÍZ: /dashboard/
    path('', DashboardHomeView.as_view(), name='home'),

    # 🚨 RUTA EXPLÍCITA (Para evitar el error 404 si alguien escribe /home/)
    path('home/', DashboardHomeView.as_view(), name='home_explicit'),
    
    # 🔑 Autenticación
    path('login/', DashboardLoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(next_page='dashboard:login'), name='logout'),
    
    # 🎭 EDITOR DE TEATROS (VENUES)
    
    # 1. Ruta GENÉRICA (Sin ID): Para crear o cargar por defecto
    # URL: /dashboard/theater/editor/
    path('theater/editor/', VenueEditorView.as_view(), name='theater_editor'),
    
    # 2. Ruta ESPECÍFICA (Con ID UUID): Para editar un teatro puntual
    # URL: /dashboard/theater/editor/da21a06a-9eda.../
    # CAMBIOS: 
    # - 'venue' -> 'theater' (Para coincidir con el navegador)
    # - <int:venue_id> -> <uuid:venue_id> (Para coincidir con tu modelo)
    # - Orden cambiado a 'editor/<id>/' para coincidir con tu Javascript
    path('theater/editor/<uuid:venue_id>/', VenueEditorView.as_view(), name='theater_editor_id'),
    
    # 🛒 Finanzas y Órdenes
    path('orders/', OrderListView.as_view(), name='order_list'),
    
    # 🎫 Lista de Funciones (Eventos)
    path('events/', ShowFunctionListView.as_view(), name='event_list'),

    path('events/<uuid:pk>/edit/', ShowFunctionUpdateView.as_view(), name='event_edit'),
    path('events/<uuid:pk>/edit/', ShowFunctionUpdateView.as_view(), name='event_edit'),
]