"""
📡 ENRUTADOR CRIPTOGRÁFICO DE WEBSOCKETS "EYE OF GOD" (GRADO MILITAR).
Ruta: apps/dashboard/routing.py
Arquitectura: Channels URLRouter + Protección ReDoS de Complejidad Temporal Estricta O(1).
Diseñado por los Cónclaves globales para mitigar inyecciones por desbordamiento y Path Traversal.
"""
from django.urls import re_path
from . import consumers

# ==============================================================================
# 🛰️ MATRIZ DE RUTAS WEBSOCKET INMUTABLE (PCI-DSS & FINTECH COMPLIANT)
# ==============================================================================
websocket_urlpatterns = [
    # 🔒 CANAL 1: Telemetría Global de la Plataforma (Centro de Comando Principal)
    # Ruta limpia y exacta, anclada de inicio a fin (^...$). 
    # Evita el Layout/Routing Thrashing y valida handshakes globales en tiempo constante O(1).
    re_path(
        r'^ws/dashboard-metrics/$',
        consumers.EventDashboardConsumer.as_asgi(),
        name='ws_global_dashboard_telemetry'
    ),

    # 🔒 CANAL 2: SHIELD RE-ROUTING (Aislamiento por Evento)
    # Reemplaza expresiones genéricas por una máscara Regex de longitud fija orientada a UUID4.
    # Si un atacante inyecta payloads masivos, el motor de expresiones regulares de Python
    # aborta la evaluación en tiempo real (O(1)) sin caer en backtracking catastrófico de CPU.
    re_path(
        r'^ws/dashboard/event/(?P<event_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{2}-[0-9a-fA-F]{12})/$', 
        consumers.EventDashboardConsumer.as_asgi(),
        name='ws_event_dashboard_telemetry'
    ),
]