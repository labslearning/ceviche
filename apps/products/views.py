from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import viewsets, filters
from rest_framework.permissions import AllowAny
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from backend.apps.products.models import Product
from .serializers import ProductSerializer

class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Catálogo de productos y combos (Bar/Confitería).
    Nivel ATP: Optimizado con Eager Loading, Caché y Throttling.
    """
    
    # 🧠 OPTIMIZACIÓN DE BASE DE DATOS (High Performance):
    # Si alguien pide el menú, traemos los productos.
    # PERO si hay COMBOS, usamos 'prefetch_related' para traer también 
    # los ítems que lo componen (ej: las 2 gaseosas) en la misma consulta.
    # 'combo_items__product' sigue la relación definida en el modelo.
    queryset = Product.objects.filter(is_active=True).prefetch_related(
        'combo_items__product'
    ).order_by('name')

    serializer_class = ProductSerializer
    
    # 🔓 PERMISOS:
    # El menú es público. Cualquier usuario (incluso sin loguearse) puede verlo.
    permission_classes = [AllowAny]
    
    # 🛡️ DEFENSA (Throttling):
    # Protegemos contra ataques DoS.
    throttle_classes = [AnonRateThrottle, UserRateThrottle]
    
    # 🔍 MOTORES DE BÚSQUEDA Y FILTRADO:
    # Búsqueda textual: ?search=crispetas
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'description']
    
    def get_queryset(self):
        """
        Personalización avanzada del Queryset.
        Permite filtrar por tipo de producto en la URL.
        Ejemplo: /api/v1/products/?type=COMBO
        """
        queryset = super().get_queryset()
        
        # Capturamos el parámetro 'type' de la URL
        product_type = self.request.query_params.get('type')
        
        if product_type:
            # Validamos que sea un tipo seguro antes de filtrar
            queryset = queryset.filter(product_type=product_type)
            
        return queryset

    # 🚀 VELOCIDAD DE LA LUZ (Caché):
    # Guardamos el menú en memoria RAM por 5 minutos (60 * 5).
    # El Frontend recibirá la respuesta en milisegundos sin tocar la BD.
    @method_decorator(cache_page(60 * 5))
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @method_decorator(cache_page(60 * 5))
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)
