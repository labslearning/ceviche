import os
from django.core.asgi import get_asgi_application

# 1. Configuración del módulo de settings (Debe ejecutarse ANTES de cualquier importación de Django)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# 2. Inicialización nativa e inmutable de la aplicación HTTP ASGI
django_asgi_app = get_asgi_application()

# 🧠 DEFERRED IMPORTS: Las importaciones de Channels se ejecutan DESPUÉS de instanciar la app HTTP
# para evitar condiciones de carrera en el registro de aplicaciones e hilos del sistema operativo.
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator # 🔥 ESCUDO ANTI-HIJACKING
import apps.dashboard.routing

application = ProtocolTypeRouter({
    # 🌐 Capa de red convencional síncrona (Aislada de forma segura)
    "http": django_asgi_app,
    
    # 🏎️ Capa de red persistente O(1) en tiempo real (Protección Bancaria Perimetral)
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(
                apps.dashboard.routing.websocket_urlpatterns
            )
        )
    ),
})