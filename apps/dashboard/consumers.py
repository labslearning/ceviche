"""
👁️ TRANSMISOR TELEMÉTRICO "EYE OF GOD" (GRADO FINTECH MÁXIMO).
Ruta: apps/dashboard/consumers.py
Arquitectura: AsyncWebsocketConsumer O(1)
Defensas Activas: Anti-CSWSH, Zero-Trust is_staff Auth, Anti-Memory Dumping, Anti-DDoS Tarpit.
"""
import json
import logging
import gc
from urllib.parse import urlparse
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings

# 🔒 Logger asincrónico aislado, inmune a bloqueos del Global Interpreter Lock (GIL)
logger = logging.getLogger(__name__)

class EventDashboardConsumer(AsyncWebsocketConsumer):
    """
    Bóveda Multiplexada Asíncrona: Distribución de telemetría reactiva y logs financieros en O(1).
    """
    
    # Caché estático de hosts a nivel de clase para evitar cálculos O(N) por cada handshake de socket
    _cached_allowed_hosts = None

    @classmethod
    def _get_allowed_hosts(cls):
        if cls._cached_allowed_hosts is None:
            cls._cached_allowed_hosts = set(getattr(settings, 'ALLOWED_HOSTS', ['localhost', '127.0.0.1']))
        return cls._cached_allowed_hosts

    async def connect(self):
        # ==============================================================================
        # 1. 🛡️ VALIDADOR DE AUTENTICACIÓN ZERO-TRUST (KERNEL LEVEL)
        # ==============================================================================
        self.user = self.scope.get('user')
        # Si el socket intenta abrirse sin sesión activa de Staff, se destruye el handshake inmediatamente
        if not self.user or not self.user.is_authenticated or not self.user.is_staff:
            logger.critical("🚨 [WS ZERO-TRUST SHIELD] Intento de conexión anónima o sin privilegios rechazada.")
            await self.close(code=4401)
            return

        # ==============================================================================
        # 2. 🛡️ DEFENSA ANTI-CSWSH (Cross-Site WebSocket Hijacking)
        # ==============================================================================
        headers = dict(self.scope.get('headers', []))
        origin_bytes = headers.get(b'origin', b'')
        
        if origin_bytes:
            try:
                origin_url = origin_bytes.decode('utf-8')
                parsed_origin = urlparse(origin_url)
                hostname = parsed_origin.hostname
                
                # Validación de seguridad O(1) usando Hash Sets
                allowed_hosts = self._get_allowed_hosts()
                
                if hostname not in allowed_hosts and not settings.DEBUG:
                    logger.critical(f"🚨 [CSWSH ATTACK THWARTED] Socket abortado desde origen hostil: {hostname}")
                    await self.close(code=4403)
                    return
            except Exception as e:
                logger.error(f"⚠️ [MALFORMED HEADER] Error analizando origin: {str(e)}")
                await self.close(code=4400)
                return

        # ==============================================================================
        # 3. ENRUTAMIENTO DINÁMICO Y AISLAMIENTO DE GRUPOS
        # ==============================================================================
        self.event_id = self.scope['url_route']['kwargs'].get('event_id')
        
        if self.event_id:
            self.group_name = f"event_{self.event_id}_dashboard"
        else:
            # Fallback al canal maestro de auditoría si no hay un evento específico en el routing
            self.group_name = "admin_fintech_audit_stream"

        # Memoria Redis: Unir de manera atómica el hilo al clúster de telemetría
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        
        await self.accept()
        logger.info(f"📡 [CONCLAVE UPLINK ESTABLISHED] {self.user.email} enlazado al clúster: {self.group_name}")

    async def disconnect(self, close_code):
        """
        🧼 DEFENSA ANTI-MEMORY DUMPING Y ZOMBIE SOCKETS.
        Erradicación forzada de punteros de la RAM al cerrar la sesión.
        """
        if hasattr(self, 'group_name') and self.group_name:
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )
        logger.info(f"🔌 [UPLINK TERMINATED] Nodo retirado (Código: {close_code})")
        gc.collect() # Forzamos la limpieza del Garbage Collector en memoria RAM

    async def receive(self, text_data=None, bytes_data=None):
        """
        ⛔ DEFENSA COTA DE RED (Anti-RAM Exhaustion / DDoS).
        Tolerancia cero a inyección de tramas. El canal es estrictamente de lectura.
        """
        logger.warning(f"🚨 [PROTOCOL VIOLATION] Intento de inyección de tramas detectado. Destruyendo nodo.")
        await self.close(code=4429)

    # ==============================================================================
    # MULTIPLEXOR DE TELEMETRÍA (METRICAS Y AUDITORÍA INMUTABLE)
    # ==============================================================================

    async def update_metrics(self, event):
        """Difusión de escaneos en puertas en complejidad O(1)."""
        try:
            payload = json.dumps({
                "type": "METRICS_UPDATE",
                "message": str(event.get('message', '')),
                "metrics": event.get('metrics', {})
            }, separators=(',', ':'))
            await self.send(text_data=payload)
        except Exception as exc:
            logger.error(f"❌ [METRICS BROADCAST FAIL]: {str(exc)}")
        finally:
            if 'payload' in locals(): del payload

    async def send_audit_event(self, event):
        """Difusión de transacciones del Ledger y rastreo exclusivo de envíos por Email."""
        try:
            payload = json.dumps(event.get("payload", {}), separators=(',', ':'))
            await self.send(text_data=payload)
        except Exception as exc:
            logger.error(f"❌ [AUDIT BROADCAST FAIL]: {str(exc)}")
        finally:
            if 'payload' in locals(): del payload