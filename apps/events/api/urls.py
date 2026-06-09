from django.urls import path
from .views import VenueLayoutView

# 🧹 LIMPIEZA: Quitamos el router de aquí porque ya está en config/urls.py
# Dejamos SOLO las rutas manuales especiales.

urlpatterns = [
    # Esta ruta es vital para el Editor de Teatros (Guardar/Cargar Sillas)
    path('venue/<uuid:venue_id>/layout/', VenueLayoutView.as_view(), name='venue_layout'),
]