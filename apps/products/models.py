import uuid
from django.db import models

class Product(models.Model):
    """
    Representa tanto productos individuales (Gaseosa) como Combos.
    """
    class Type(models.TextChoices):
        SINGLE = 'SINGLE', 'Producto Individual'
        COMBO = 'COMBO', 'Combo / Paquete'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, verbose_name="Nombre del Producto")
    description = models.TextField(blank=True, verbose_name="Descripción")
    
    # Precios
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Precio de Venta")
    
    # Inventario
    stock = models.PositiveIntegerField(default=0, verbose_name="Unidades en Stock")
    is_active = models.BooleanField(default=True, verbose_name="¿Está a la venta?")
    
    # Configuración de Tipo
    product_type = models.CharField(
        max_length=20, 
        choices=Type.choices, 
        default=Type.SINGLE
    )
    
    # Imagen (Usaremos URL por ahora para facilitar despliegue en Railway sin S3)
    image_url = models.URLField(blank=True, null=True, help_text="URL de la imagen del producto")

    # Auditoría
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} (${self.price:,.0f})"

class ComboItem(models.Model):
    """
    Define qué productos componen un combo.
    Ej: El "Combo Pareja" (parent) tiene 2 unidades de "Gaseosa" (product).
    """
    parent_combo = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE, 
        related_name='combo_items',
        limit_choices_to={'product_type': Product.Type.COMBO}
    )
    product = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE, 
        related_name='included_in_combos',
        limit_choices_to={'product_type': Product.Type.SINGLE}
    )
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "Ítem de Combo"
        verbose_name_plural = "Contenido de Combos"

    def __str__(self):
        return f"{self.quantity}x {self.product.name} en {self.parent_combo.name}"