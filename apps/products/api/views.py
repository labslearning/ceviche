from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import viewsets, filters
from rest_framework.permissions import AllowAny
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from apps.products.models import Product
# 👇 CORRECCIÓN CRÍTICA: Aquí importamos ProductSerializer, NO EventSerializer
from .serializers import ProductSerializer

class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Catálogo de productos y combos (Bar/Confitería).
    Nivel ATP: Optimizado con Eager Loading, Caché y Throttling.
    """
    
    # 🧠 OPTIMIZACIÓN DE BASE DE DATOS:
    queryset = Product.objects.filter(is_active=True).prefetch_related(
        'combo_items__product'
    ).order_by('name')

    serializer_class = ProductSerializer
    
    # 🔓 PERMISOS:
    permission_classes = [AllowAny]
    
    # 🛡️ DEFENSA (Throttling):
    throttle_classes = [AnonRateThrottle, UserRateThrottle]
    
    # 🔍 BÚSQUEDA:
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'description']
    
    def get_queryset(self):
        """
        Personalización avanzada del Queryset.
        Permite filtrar por tipo de producto en la URL.
        """
        queryset = super().get_queryset()
        product_type = self.request.query_params.get('type')
        if product_type:
            queryset = queryset.filter(product_type=product_type)
        return queryset

    # 🚀 VELOCIDAD DE LA LUZ (Caché):
    @method_decorator(cache_page(60 * 5))
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @method_decorator(cache_page(60 * 5))
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)