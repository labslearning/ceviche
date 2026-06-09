import hashlib
from decouple import config

class WompiAdapter:
    """
    Clase utilitaria para manejar la criptografía y comunicación con Wompi.
    Seguridad: Grado Militar (Validación de Tipos, Keys y SHA-256).
    """
    
    @staticmethod
    def get_integrity_signature(reference: str, amount_in_cents: int, currency: str = "COP") -> str:
        """
        Genera la firma SHA-256 requerida por el Widget de Wompi.
        Args:
            reference (str): Referencia única de la orden.
            amount_in_cents (int): Monto en centavos (Ej: 2000000 para $20.000).
            currency (str): Moneda (Por defecto 'COP').
        """
        secret = config('WOMPI_INTEGRITY_SECRET', default=None)
        
        # 🛡️ FAIL-FAST: Si no hay secreto, detenemos todo.
        if not secret:
            raise ValueError("FATAL: WOMPI_INTEGRITY_SECRET no está configurado en el .env")

        # 🧹 SANEAMIENTO DE DATOS (NIVEL ATP):
        # Aseguramos que el monto sea una cadena de solo números, sin puntos decimales.
        # Si llega 25000.0, esto lo convierte a "25000". Vital para que coincida con el hash.
        clean_amount = str(int(amount_in_cents))
        clean_currency = str(currency).upper().strip() # Aseguramos 'COP', no 'cop '
        
        # Cadena de concatenación estricta
        raw_string = f"{reference}{clean_amount}{clean_currency}{secret}"
        
        # Generar Hash
        m = hashlib.sha256()
        m.update(raw_string.encode('utf-8'))
        signature = m.hexdigest()
        
        return signature

    @staticmethod
    def get_public_key() -> str:
        key = config('WOMPI_PUB_KEY', default=None)
        if not key:
             raise ValueError("FATAL: WOMPI_PUB_KEY no está configurado.")
        return key
        
    @staticmethod
    def get_redirect_url() -> str:
        # 🛡️ SEGURIDAD DE DESPLIEGUE:
        # Quitamos el default 'localhost'. Si olvidas configurar esto en Prod,
        # el sistema debe avisarte (Crash) en lugar de enviar usuarios a la nada.
        url = config('WOMPI_REDIRECT_URL', default=None)
        if not url:
            raise ValueError("FATAL: WOMPI_REDIRECT_URL no está configurada.")
        return url
# ... (métodos anteriores: get_integrity_signature, get_public_key, get_redirect_url) ...

    @staticmethod
    def validate_webhook_signature(transaction_data: dict, timestamp: str, signature_received: str) -> bool:
        """
        Valida que la notificación venga realmente de Wompi y no de un hacker.
        Fórmula Wompi: SHA256(TransactionID + Status + AmountInCents + Timestamp + Secret)
        """
        secret = config('WOMPI_INTEGRITY_SECRET')
        
        # Extraemos los datos críticos del paquete JSON de Wompi
        t_id = transaction_data.get('id')
        status = transaction_data.get('status')
        amount_in_cents = int(transaction_data.get('amount_in_cents')) # Convertir a entero por seguridad
        
        # Construimos la cadena de verificación
        raw_string = f"{t_id}{status}{amount_in_cents}{timestamp}{secret}"
        
        # Generamos el hash localmente
        m = hashlib.sha256()
        m.update(raw_string.encode('utf-8'))
        calculated_signature = m.hexdigest()
        
        # Comparamos: Si son idénticos, es legítimo.
        return calculated_signature == signature_received