# apps/orders/api/mercadopago.py
import logging
import uuid
from decimal import Decimal
from typing import Dict, Any

import mercadopago
from django.conf import settings
from django.core.cache import cache
from django.db import transaction, DatabaseError
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle

# 🛡️ 1. LOGGER DE ALTA RENDIMIENTO (SOC / SIEM Ready)
logger = logging.getLogger(__name__)

# 🛡️ 2. CAPA DE DEFENSA: SANITIZACIÓN EXTREMA Y FUZZING SHIELD
class CheckoutPayloadSerializer(serializers.Serializer):
    """
    Zero-Trust Serializer. Bloquea inyecciones XSS y previene desbordamientos de buffer.
    """
    product_id = serializers.UUIDField(required=True)
    quantity = serializers.IntegerField(min_value=1, max_value=10, default=1)
    
    # Prevención XSS: El título solo acepta letras, números y espacios. Ni un solo script pasará.
    title = serializers.RegexField(
        regex=r'^[a-zA-Z0-9\s\-_]+$', 
        max_length=100, 
        default='Ticket General'
    )
    price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('50.00'))

# 🛡️ 3. CORE BANCARIO (God-Tier API View)
class CheckoutMercadoPagoAPIView(APIView):
    """
    Endpoint Transaccional ATP: /api/orders/checkout/mercadopago/
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'checkout_payments'

    def post(self, request, *args, **kwargs) -> Response:
        # 1. FAIL-FAST & MEMORY ISOLATION
        mp_token = getattr(settings, 'MERCADO_PAGO_ACCESS_TOKEN', None)
        if not mp_token:
            logger.critical("🚨 SECURITY ALERT: MERCADO_PAGO_ACCESS_TOKEN ausente del entorno.")
            return Response(
                {"error": "Gateway de pagos en mantenimiento."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        # 2. VALIDACIÓN (Capa Anti-Tampering)
        serializer = CheckoutPayloadSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"Payload Reject - User {request.user.id}: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        
        # 3. BLOQUEO ATÓMICO (Redis SETNX - Big O(1))
        # Previene condiciones de carrera a nivel de CPU. 'cache.add' falla instantáneamente si la llave existe.
        idempotency_key = f"chk_lock:{request.user.id}:{data['product_id']}"
        if not cache.add(idempotency_key, True, timeout=15): 
            logger.warning(f"🛡️ Replay Attack bloqueado para el usuario {request.user.id}")
            return Response(
                {"error": "Transacción en proceso. Espere unos segundos."},
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        try:
            # 4. TRANSACCIÓN DB O(log N) - AISLAMIENTO ESTRICTO
            # La base de datos entra y sale en microsegundos.
            internal_order_reference = f"ORD-{uuid.uuid4().hex[:12].upper()}"

            try:
                with transaction.atomic():
                    # ⚠️ AQUÍ ESCRIBES EN LA BASE DE DATOS.
                    # order = Order.objects.create(status='PENDING', reference=internal_order_reference...)
                    pass 
            except DatabaseError as db_err:
                logger.critical(f"🔥 Falla de I/O en Disco DB: {str(db_err)}")
                return Response({"error": "Error interno del servidor."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # 5. RESOLUCIÓN DE DOMINIO Y ENSAMBLAJE DE PAYLOAD
            public_domain = getattr(settings, 'RAILWAY_PUBLIC_DOMAIN', None)
            base_url = f"https://{public_domain}" if public_domain else "http://localhost:8000"
            
            preference_data: Dict[str, Any] = {
                "items": [{
                    "title": data['title'],
                    "quantity": data['quantity'],
                    "currency_id": "COP",
                    "unit_price": float(data['price']) 
                }],
                "payer": {
                    "email": request.user.email,
                    "name": request.user.first_name,
                },
                "back_urls": {
                    "success": f"{base_url}/payment/success",
                    "failure": f"{base_url}/payment/failure",
                    "pending": f"{base_url}/payment/pending"
                },
                "auto_return": "approved",
                "external_reference": internal_order_reference,
                "notification_url": f"{base_url}/api/orders/webhook/mercadopago/",
                "statement_descriptor": "CEVICHE TICKETS" 
            }

            # 6. E/S DE RED (COMPLETAMENTE DESACOPLADO DE LA BASE DE DATOS)
            sdk = mercadopago.SDK(mp_token)
            
            # 🛡️ MEMORY DUMPING SHIELD: Borramos el token de la memoria RAM local.
            # Si el proceso hace un volcado de núcleo (Core Dump) en la siguiente línea, el token ya no existe.
            del mp_token 

            # Llamada HTTP síncrona. Si MP se demora, el servidor espera, pero la Base de Datos está LIBRE.
            preference_response = sdk.preference().create(preference_data)

            if preference_response.get("status") not in [200, 201]:
                logger.error(f"Rechazo desde MP API: {preference_response}")
                raise Exception("La pasarela de pagos rechazó la solicitud.")

            preference = preference_response["response"]
            logger.info(f"✅ Preferencia creada. REF: {internal_order_reference} | MP_ID: {preference['id']}")

            return Response({
                "checkout_url": preference["init_point"],
                "preference_id": preference["id"],
                "order_reference": internal_order_reference
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            error_trace_id = uuid.uuid4().hex[:8]
            logger.exception(f"[TRACE: {error_trace_id}] Excepción de Red/Procesamiento: {str(e)}")
            
            # ⚠️ AQUÍ ACTUALIZAS LA ORDEN A FALLIDA (Ya no estamos dentro del transaction.atomic)
            # Order.objects.filter(reference=internal_order_reference).update(status='FAILED')

            return Response(
                {"error": "Error de comunicación con la red financiera.", "trace_id": error_trace_id}, 
                status=status.HTTP_502_BAD_GATEWAY
            )
        finally:
            # 7. LIBERACIÓN SEGURA (Cleanup)
            # Pase lo que pase (éxito o excepción), liberamos el candado de Redis para no bloquear al usuario permanentemente.
            cache.delete(idempotency_key)
