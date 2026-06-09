from django.urls import path
from apps.logistics.api.views import ValidateQRView

urlpatterns = [
    # Endpoint: /api/logistics/validate/
    path('validate/', ValidateQRView.as_view(), name='validate_qr'),
]
