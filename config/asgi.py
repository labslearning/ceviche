import os
import django
from django.core.asgi import get_asgi_application

# 🔒 Inicialización temprana del core de Django requerida para hilos asíncronos
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import apps.dashboard.routing  # 👈 Inyección del búnker de enrutamiento Regex de la Fase 6.2

application = ProtocolTypeRouter({
    # Capa de red convencional síncrona
    "http": get_asgi_application(),
    
    # Capa de red persistente en tiempo real (Redis Channel Layer)
    "websocket": AuthMiddlewareStack(
        URLRouter(
            apps.dashboard.routing.websocket_urlpatterns
        )
    ),
})