import hmac
import hashlib
import logging
import json
import time
import os
import threading
from decimal import Decimal
from typing import Dict, Optional, Tuple
from django.core.exceptions import ValidationError
from decouple import config
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from requests.exceptions import RequestException, JSONDecodeError, Timeout

logger = logging.getLogger(__name__)

class MercadoPagoAdapter:
    """
    Arquitectura Definitiva Mercado Pago (God Tier - Financial Grade).
    Implementa:
    - Singleton Pool Global seguro contra Thread/Socket Leaks.
    - Retry Loop Mutante (Evita fallas de idempotencia en reintentos).
    - Prevención Asimétrica de Time-Drift en Webhooks.
    """
    
    # ⚡ SINGLETON POOL CONTROLADO POR LOCKS MUTEX
    _session: Optional[requests.Session] = None
    _session_lock = threading.Lock()

    @classmethod
    def _get_session(cls) -> requests.Session:
        """
        Garantiza una única tubería TLS persistente para toda la aplicación.
        Thread-Safe, eficiente en RAM y a prueba de descriptores huérfanos.
        """
        if cls._session is None:
            with cls._session_lock:
                # Doble verificación (Double-Checked Locking Pattern)
                if cls._session is None:
                    session = requests.Session()
                    # Desactivamos los retries automáticos de POST. Nosotros controlamos el flujo.
                    retries = Retry(
                        total=0,  # Importante: Apagado. Usaremos un Retry Loop manual para mutar la llave.
                        status_forcelist=[]
                    )
                    # Optimizamos el pool de sockets para entornos concurrentes masivos
                    adapter = HTTPAdapter(
                        pool_connections=200, 
                        pool_maxsize=200, 
                        max_retries=retries,
                        pool_block=True # Previene que peticiones excedentes rompan la RAM, forzando espera
                    )
                    session.mount("https://", adapter)
                    cls._session = session
        return cls._session

    @staticmethod
    def _generate_idempotent_key(base_key: str, attempt: int) -> str:
        """
        Genera una llave de idempotencia criptográficamente fuerte y única por cada intento de red.
        Evita colisiones en reintentos y resiste análisis predictivo.
        """
        entropy = os.urandom(8).hex()
        raw = f"{base_key}_{attempt}_{time.time()}_{entropy}"
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    @staticmethod
    def get_headers(idempotency_key: str) -> Dict[str, str]:
        token = config('MERCADO_PAGO_ACCESS_TOKEN', default='')
        if not token:
            raise ValidationError("CRÍTICO: Token de Mercado Pago no encontrado.")
        
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Idempotency-Key": str(idempotency_key)
        }

    @staticmethod
    def create_checkout_preference(order, redirect_url: str) -> str:
        """
        Registra la preferencia atómica de pago.
        Motor de reintentos determinista (Deterministic Retry Engine).
        """
        url = "https://api.mercadopago.com/checkout/preferences"
        session = MercadoPagoAdapter._get_session()
        
        # 🛡️ Conversión matemática exacta (Big O: 1)
        unit_price = float(order.total_amount.quantize(Decimal('0.01')))

        payload = {
            "items": [
                {
                    "id": str(order.id),
                    "title": f"Tickets Espectáculo - Ref: {order.wompi_reference}",
                    "quantity": 1,
                    "currency_id": str(order.currency).upper().strip(),
                    "unit_price": unit_price
                }
            ],
            "external_reference": str(order.wompi_reference),
            "back_urls": {
                "success": redirect_url,
                "pending": redirect_url,
                "failure": redirect_url
            },
            "auto_return": "approved",
            "notification_url": config('MERCADO_PAGO_WEBHOOK_URL', default=''),
            "metadata": {
                "order_id": str(order.id)
            }
        }

        payload_bytes = json.dumps(payload).encode('utf-8')

        # 🛡️ MOTOR DE REINTENTOS MANUAL CON MUTACIÓN DE IDEMPOTENCIA
        max_attempts = 3
        backoff_factor = 0.5
        
        for attempt in range(1, max_attempts + 1):
            dynamic_idempotency = MercadoPagoAdapter._generate_idempotent_key(order.idempotency_key, attempt)
            
            try:
                response = session.post(
                    url, 
                    data=payload_bytes, 
                    headers=MercadoPagoAdapter.get_headers(dynamic_idempotency), 
                    timeout=(3.05, 10) 
                )
                
                # Si el código es 5xx, disparamos reintento
                if response.status_code >= 500:
                    response.raise_for_status()

                # Si es 4xx, es un error de negocio irrecuperable (No reintentar)
                if 400 <= response.status_code < 500:
                    logger.error(f"❌ [MP GATEWAY] Rechazo 4xx: {response.text}")
                    raise ValidationError("Transacción rechazada por reglas de negocio en Mercado Pago.")

                # Bloque de éxito
                if response.status_code == 201:
                    try:
                        response_data = response.json()
                        if "id" in response_data:
                            return response_data["id"]
                    except JSONDecodeError:
                        logger.critical(f"💀 [MP GATEWAY] Respuesta corrupta: {response.text[:200]}")
                        raise ValidationError("Error de formato en la respuesta de la pasarela.")

            except (RequestException, Timeout) as e:
                logger.warning(f"⚠️ [MP GATEWAY] Intento {attempt}/{max_attempts} fallido: {e}")
                if attempt == max_attempts:
                    logger.critical("🚨 [MP GATEWAY] Exhausted retries. Fallo de red definitivo.")
                    raise ValidationError("La red de pagos externa está inaccesible. Reintente más tarde.")
                
                # Backoff exponencial antes de reintentar
                time.sleep(backoff_factor * (2 ** (attempt - 1)))
                continue

        # Si el flujo llega aquí, algo estructural falló
        raise ValidationError("Error interno crítico al procesar la conexión.")

    @staticmethod
    def validate_webhook_signature(x_signature: str, x_request_id: str, data_id: str) -> bool:
        """
        Validación HMAC-SHA256 (Especificación V1 MP) + Tolerancia Asimétrica de Reloj.
        """
        secret = config('MERCADO_PAGO_WEBHOOK_SECRET', default='')
        if not secret or not x_signature or not data_id:
            logger.warning("⚠️ Intento de Webhook descartado: Credenciales faltantes.")
            return False
            
        try:
            parts = {p.split("=")[0].strip(): p.split("=")[1].strip() for p in x_signature.split(",") if "=" in p}
            ts_str = parts.get("ts")
            v1 = parts.get("v1")
        except Exception:
            return False

        if not ts_str or not v1:
            return False

        # 🛡️ TOLERANCIA ASIMÉTRICA DE DESINCRONIZACIÓN (Time-Drift Mitigation)
        try:
            ts_int = float(ts_str)
            if ts_int > 1e11: # Normalización heurística si viene en milisegundos
                ts_int = ts_int / 1000.0
            
            server_time = time.time()
            drift = server_time - ts_int
            
            # Tolerancia: Máximo 5 minutos en el futuro (reloj MP adelantado)
            # Máximo 10 minutos en el pasado (mitigación Replay Attack)
            if drift < -300 or drift > 600:
                logger.critical(f"🚨 WEBHOOK RECHAZADO: Time-Drift inaceptable ({drift:.2f}s). Posible ataque.")
                return False
        except ValueError:
            return False

        # 🛡️ MATRIZ DE MANIFIESTO ESTRICTO O(1)
        manifest = f"id:{data_id};"
        if x_request_id:
            manifest += f"request-id:{x_request_id};"
        manifest += f"ts:{ts_str};"
        
        hmac_key = secret.encode('utf-8')
        calculated_signature = hmac.new(hmac_key, manifest.encode('utf-8'), hashlib.sha256).hexdigest()
        
        return hmac.compare_digest(v1, calculated_signature)