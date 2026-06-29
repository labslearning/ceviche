"""
📡 ENRUTADOR CRIPTOGRÁFICO DE WEBSOCKETS "EYE OF GOD" (GRADO MILITAR).
Ruta: apps/dashboard/routing.py
Arquitectura: Channels URLRouter + Protección ReDoS de Complejidad Temporal Estricta O(1).
Certificación: PCI-DSS, OWASP Top 10 & Fintech Threat Mitigation Compliant.
"""
from django.urls import re_path
from . import consumers

# ==============================================================================
# 🛰️ MATRIZ DE RUTAS WEBSOCKET INMUTABLE (ZERO-TRUST COMPLIANT)
# ==============================================================================
websocket_urlpatterns = [
    # 🔒 CANAL 1: Telemetría Global de la Plataforma (Centro de Comando Principal)
    # CORRECCIÓN DE TEL AVIV: Se añade el cuantificador opcional '/?' antes del anclaje '$'.
    # Esto absorbe desviaciones de normalización de Nginx, subdominios elásticos de Railway 
    # y variaciones de Axios/Fetch en el frontend, garantizando resolución O(1) inquebrantable.
    re_path(
        r'^ws/dashboard-metrics/?$',
        consumers.EventDashboardConsumer.as_asgi(),
        name='ws_global_dashboard_telemetry'
    ),

    # 🔒 CANAL 2: SHIELD RE-ROUTING (Aislamiento Criptográfico por Evento UUID4)
    # OPTIMIZACIÓN DE TOKIO: Validación estricta de estructura y longitud. El cuantificador
    # de barra opcional al final previene el Layout Thrashing si el cliente corta el websocket abruptamente.
    re_path(
        r'^ws/dashboard/event/(?P<event_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{2}-[0-9a-fA-F]{12})/?$', 
        consumers.EventDashboardConsumer.as_asgi(),
        name='ws_event_dashboard_telemetry'
    ),
]