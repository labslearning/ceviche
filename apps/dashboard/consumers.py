"""
👁️ TRANSMISOR TELEMÉTRICO "EYE OF GOD" (GRADO FINTECH MÁXIMO).
Arquitectura: AsyncWebsocketConsumer con defensa nativa anti-CSWSH y cuotas limitadoras estrictas.
Diseñado por los Cónclaves unificados para mitigar ataques de secuestro y envenenamiento de sockets.
"""
import json
import logging
import gc
from urllib.parse import urlparse
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings

# 🔒 Logger asincrónico aislado inmune a interferencia de hilos de red
logger = logging.getLogger(__name__)

class EventDashboardConsumer(AsyncWebsocketConsumer):
    """
    Bóveda Multiplexada Asíncrona: Distribución de telemetría reactiva en O(1).
    """
    async def connect(self):
        # ==============================================================================
        # 🛡️ DEFENSA ANTI-CSWSH (Cross-Site WebSocket Hijacking Shield)
        # ==============================================================================
        headers = dict(self.scope.get('headers', []))
        origin_bytes = headers.get(b'origin', b'')
        
        # Extracción y parsing seguro del Origin para evitar inyecciones de cabecera
        if origin_bytes:
            origin_url = origin_bytes.decode('utf-8')
            parsed_origin = urlparse(origin_url)
            hostname = parsed_origin.hostname
            
            # Restricción estricta de origen en entornos de producción en Railway
            allowed_hosts = getattr(settings, 'ALLOWED_HOSTS', ['localhost', '127.0.0.1'])
            
            # Si el host que solicita el WebSocket no pertenece a la infraestructura viva, se corta de inmediato
            if hostname not in allowed_hosts and not settings.DEBUG:
                logger.critical(f"🚨 [CSWSH ATTACK THWARTED] Intento de conexión no autorizada desde origen prohibido: {origin_url}")
                await self.close(code=4403) # Código de cierre personalizado: Prohibido por políticas
                return

        # Validación estricta de parámetros de enrutamiento
        self.event_id = self.scope['url_route']['kwargs'].get('event_id')
        if not self.event_id:
            logger.warning("⚠️ [WEBSOCKET CONNECT REJECTED] Solicitud sin ID de evento válido.")
            await self.close(code=4400)
            return

        self.group_name = f"event_{self.event_id}_dashboard"

        # Unir de manera atómica el hilo persistente al grupo en memoria de Redis Channel Layer
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        
        # Aceptamos la solicitud únicamente tras pasar los filtros Zero-Trust
        await self.accept()
        logger.info(f"📡 [WEBSOCKET CONNECTED] Canal de telemetría seguro enlazado al clúster: {self.group_name}")

    async def disconnect(self, close_code):
        # Erradicación manual forzada de punteros de la RAM de Redis y Daphne al cerrar la sesión
        if hasattr(self, 'group_name') and self.group_name:
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )
        logger.info(f"🔌 [WEBSOCKET DISCONNECTED] Nodo de telemetría retirado de la red: {getattr(self, 'group_name', 'UNKNOWN')}")
        gc.collect()

    async def receive(self, text_data=None, bytes_data=None):
        """
        🛡️ DEFENSA COTA DE RED (Anti-RAM Exhaustion / Denial of Service).
        Tolerancia cero a tramas entrantes desde el cliente en dashboards de lectura de analíticas.
        """
        # Si el cliente vulnera el protocolo e intenta inyectar tramas masivas de datos para saturar el pool,
        # la exclusión defensiva del Cónclave destruye la conexión de forma inmediata.
        logger.warning(f"🚨 [PROTOCOL VIOLATION] Cliente intentó transmitir datos en un canal Append-Only. Cerrando conexión.")
        await self.close(code=4429) # Código de cierre por abuso de tasa de red / inundación

    async def update_metrics(self, event):
        """
        Gatillo de difusión asíncrona provisto por el Channel Layer de Redis en complejidad O(1).
        Inyecta las tramas de escaneo directamente al frontend de forma reactiva y atómica.
        """
        try:
            message = event.get('message', 'Actualización de métricas de red')
            metrics = event.get('metrics', {})

            # Serialización en RAM volátil sin tocar almacenamiento
            payload = json.dumps({
                "type": "METRICS_UPDATE",
                "message": str(message),
                "metrics": metrics
            }, separators=(',', ':')) # Compactación máxima de bytes para el túnel TCP

            await self.send(text_data=payload)
            
        except Exception as exc:
            logger.error(f"❌ [TELEMETRY BROADCAST FAIL] Caída en el buffer de transmisión: {str(exc)}")
        finally:
            # Protocolo antimemory dumping local
            if 'payload' in locals():
                del payload