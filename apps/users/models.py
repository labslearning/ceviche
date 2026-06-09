import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    """
    Usuario personalizado para Ceviche Platform.
    Reemplaza al usuario por defecto de Django para mayor control y seguridad.
    """
    
    # Roles definidos según requerimientos [cite: 6]
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrador"
        CLIENT = "CLIENT", "Cliente"
        LOGISTICS = "LOGISTICS", "Logística (Portero)"

    # ID seguro: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    role = models.CharField(
        max_length=50, 
        choices=Role.choices, 
        default=Role.CLIENT,
        verbose_name="Rol en el sistema"
    )
    
    phone_number = models.CharField(max_length=20, blank=True, verbose_name="Celular")
    
    # Campos de auditoría
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
