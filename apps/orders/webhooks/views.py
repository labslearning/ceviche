from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.orders.models import Order
from apps.orders.adapters.wompi import WompiAdapter

class WompiWebhookView(APIView):
    """
    Endpoint público que escucha notificaciones de Wompi.
    URL: https://tudominio.com/api/webhooks/wompi/
    """
    # 🔓 ABIERTO AL MUNDO: Wompi necesita entrar sin loguearse.
    # La seguridad la da la FIRMA CRIPTOGRÁFICA, no el usuario/contraseña.
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            # 1. Extraer datos del evento Wompi
            event = request.data.get('data', {})
            transaction_data = event.get('transaction', {})
            signature_received = request.data.get('signature', {}).get('checksum')
            timestamp = request.data.get('timestamp') # Wompi envía timestamp global

            # Validaciones básicas de estructura
            if not transaction_data or not signature_received or not timestamp:
                return Response({"error": "Payload inválido"}, status=status.HTTP_400_BAD_REQUEST)

            # 2. 🛡️ VERIFICAR FIRMA (Seguridad Anti-Hacker)
            is_valid = WompiAdapter.validate_webhook_signature(
                transaction_data, timestamp, signature_received
            )
            
            if not is_valid:
                print(f"🚨 ALERTA: Intento de webhook falso. IP: {request.META.get('REMOTE_ADDR')}")
                return Response({"error": "Firma inválida"}, status=status.HTTP_401_UNAUTHORIZED)

            # 3. Procesar el Estado
            wompi_status = transaction_data.get('status')
            reference = transaction_data.get('reference')
            
            # Buscamos la orden por la referencia única
            order = get_object_or_404(Order, wompi_reference=reference)

            # Si ya fue procesada, respondemos OK para que Wompi deje de insistir
            if order.status == Order.Status.APPROVED:
                return Response({"status": "Already approved"}, status=status.HTTP_200_OK)

            if wompi_status == 'APPROVED':
                # 🏆 EL PAGO FUE EXITOSO
                self.approve_order(order, transaction_data)
            elif wompi_status == 'VOIDED' or wompi_status == 'DECLINED':
                # El pago falló
                order.status = Order.Status.REJECTED
                order.save()

            return Response({"status": "Recibido"}, status=status.HTTP_200_OK)

        except Exception as e:
            print(f"❌ ERROR WEBHOOK: {str(e)}")
            return Response({"error": "Internal Error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @transaction.atomic
    def approve_order(self, order, transaction_data):
        """
        Lógica de negocio cuando entra el dinero.
        """
        order.status = Order.Status.APPROVED
        order.wompi_transaction_id = transaction_data.get('id')
        order.save()
        
        # Aquí dispararemos el envío de correos con QRs en el futuro
        print(f"✅ ORDEN {order.wompi_reference} APROBADA. ¡DINERO EN CAJA!")
