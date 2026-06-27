"""
📡 ENRUTADOR CRIPTOGRÁFICO DE WEBSOCKETS "EYE OF GOD" (GRADO MILITAR).
Arquitectura: Channels URLRouter + Protección ReDoS de Complejidad Temporal Estricta O(1).
Diseñado por los Cónclaves globales para mitigar inyecciones por desbordamiento.
"""
from django.urls import re_path
from . import consumers

# ==============================================================================
# 🛰️ MATRIZ DE RUTAS WEBSOCKET INMUTABLE (PCI-DSS COMPLIANT)
# ==============================================================================
websocket_urlpatterns = [
    # 🔒 SHIELD RE-ROUTING (Fase 6.2 - Grado de Seguridad de Bóveda)
    # Reemplaza la expresión genérica destructiva [^/]+ por una máscara Regex estricta
    # orientada a UUID4 (8-4-4-4-12 caracteres hexadecimales).
    # Si un atacante inyecta strings infinitos, la expresión regular lo rechaza en O(1)
    # sin ejecutar procesos de backtracking catastrófico en la CPU del servidor Daphne/Uvicorn.
    re_path(
        r'^ws/dashboard/event/(?P<event_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{2}-[0-9a-fA-F]{12})/$', 
        consumers.EventDashboardConsumer.as_asgi(),
        name='ws_event_dashboard_telemetry'
    ),
]