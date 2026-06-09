from django.urls import path
from .views import TheaterLayoutSaveView

urlpatterns = [
    # Endpoint: /api/events/theater/<uuid>/save_layout/
    path('theater/<uuid:theater_id>/save_layout/', TheaterLayoutSaveView.as_view(), name='theater_save_layout'),
]
