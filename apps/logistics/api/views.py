from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.utils import timezone
from django.shortcuts import get_object_or_404

# Importamos el Ticket y sus estados
from apps.orders.models import Ticket

class ValidateQRView(APIView):
    """
    API PARA PORTEROS (LOGÍSTICA)
    Maneja el control de acceso usando la Máquina de Estados.
    Requiere autenticación de Staff (Admin o Portero).
    """
    permission_classes = [permissions.IsAdminUser] 

    def post(self, request):
        # 1. Recibir datos del escáner (QR + Acción)
        qr_token = request.data.get('qr_token')
        action = request.data.get('action') # Valores esperados: 'ENTRY' o 'EXIT'

        if not qr_token or not action:
            return Response(
                {"error": "Faltan datos. Se requiere 'qr_token' y 'action'."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # 2. Buscar el Ticket en la BD (Blindado contra SQL Injection por el ORM)
        # Usamos filter().first() para manejar el error manualmente si no existe
        ticket = Ticket.objects.filter(qr_token=qr_token).first()
        
        if not ticket:
            return Response(
                {"error": "⛔ TICKET NO ENCONTRADO. QR Inválido o Falso."},
                status=status.HTTP_404_NOT_FOUND
            )

        # 3. Validar Fecha de la Función (Opcional pero recomendado)
        # Aquí podrías bloquear si intentan entrar un día antes.
        # Por ahora lo dejamos pasar para facilitar tus pruebas.

        # 4. 🧠 CEREBRO DE ESTADOS (Lógica Anti-Fraude)
        now = timezone.now()
        response_msg = ""
        new_state = None

        if action == 'ENTRY':
            # CASO 1: Primer ingreso
            if ticket.state == Ticket.State.ISSUED:
                new_state = Ticket.State.INSIDE
                ticket.last_entry_at = now
                response_msg = f"✅ BIENVENIDO: {ticket.seat_label} - {ticket.seat_category}"
            
            # CASO 2: Re-ingreso (Baño/Fumar)
            elif ticket.state == Ticket.State.TEMP_EXIT:
                new_state = Ticket.State.INSIDE
                ticket.last_entry_at = now
                response_msg = f"🔄 RE-INGRESO AUTORIZADO: {ticket.seat_label}"
            
            # CASO 3: Intento de Fraude (Ticket clonado o ya adentro)
            elif ticket.state == Ticket.State.INSIDE:
                return Response(
                    {
                        "error": "🚨 ALERTA DE SEGURIDAD",
                        "detail": "Este ticket YA figura ADENTRO del evento. Posible copia o error."
                    },
                    status=status.HTTP_409_CONFLICT
                )
            
            # CASO 4: Ticket Quemado o Cancelado
            else:
                return Response(
                    {"error": f"⛔ ACCESO DENEGADO. Estado del ticket: {ticket.get_state_display()}"},
                    status=status.HTTP_403_FORBIDDEN
                )

        elif action == 'EXIT':
            # Solo puedes salir si estás adentro
            if ticket.state == Ticket.State.INSIDE:
                new_state = Ticket.State.TEMP_EXIT
                ticket.last_exit_at = now
                response_msg = "👋 SALIDA TEMPORAL REGISTRADA. (Puede volver a entrar)"
            else:
                 return Response(
                    {"error": f"No se puede dar salida. El ticket no está adentro (Estado: {ticket.state})."},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        else:
            return Response({"error": "Acción desconocida. Use 'ENTRY' o 'EXIT'."}, status=400)

        # 5. Guardar cambios en la Base de Datos
        if new_state:
            ticket.state = new_state
            ticket.save()

        # 6. Respuesta Exitosa al Portero
        return Response({
            "success": True,
            "message": response_msg,
            "data": {
                "seat": ticket.seat_label,
                "category": ticket.seat_category,
                "owner": ticket.order.user.email if ticket.order.user else "Invitado",
                "new_state": ticket.state,
                "timestamp": now.strftime("%H:%M:%S")
            }
        })
