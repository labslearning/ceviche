from rest_framework import serializers
from apps.products.models import Product, ComboItem

class ProductSimpleSerializer(serializers.ModelSerializer):
    """Para mostrar productos dentro de un combo"""
    class Meta:
        model = Product
        fields = ['id', 'name']

class ComboItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name')
    
    class Meta:
        model = ComboItem
        fields = ['product_name', 'quantity']

class ProductSerializer(serializers.ModelSerializer):
    # Campo calculado: Si es combo, mostramos qué trae
    combo_content = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'description', 'price', 
            'stock', 'image_url', 'product_type', 'combo_content'
        ]

    def get_combo_content(self, obj):
        if obj.product_type == Product.Type.COMBO:
            items = obj.combo_items.all()
            return ComboItemSerializer(items, many=True).data
        return None
