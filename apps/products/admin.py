import csv
from django.contrib import admin, messages
from django.utils.html import format_html
from django.db import transaction
from django.http import HttpResponse
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

# Importamos componentes de UNFOLD para el máximo nivel visual
from unfold.admin import ModelAdmin, TabularInline
from .models import Product, ComboItem

# =============================================================================
# 📦 INLINE: COMPONENTES DEL COMBO (UX FLUIDA)
# =============================================================================

class ComboItemInline(TabularInline):
    """
    Permite gestionar los productos que componen un combo directamente 
    desde la ficha del producto principal.
    """
    model = ComboItem
    fk_name = 'parent_combo'
    extra = 0
    autocomplete_fields = ['product']
    verbose_name = "📦 Componente del Combo"
    verbose_name_plural = "📦 Componentes del Combo"
    
    # Campos calculados para ayudar al administrador
    fields = ('product', 'quantity', 'get_unit_price', 'get_subtotal')
    readonly_fields = ('get_unit_price', 'get_subtotal')

    def get_unit_price(self, instance):
        if instance.product:
            # Formateamos antes de pasar a format_html para evitar ValueError
            price_str = f"${instance.product.price:,.0f}"
            return price_str
        return "-"
    get_unit_price.short_description = "Precio Ref."

    def get_subtotal(self, instance):
        if instance.product:
            subtotal = instance.product.price * instance.quantity
            sub_str = f"${subtotal:,.0f}"
            return format_html('<b style="color: #6366f1;">{}</b>', sub_str)
        return "-"
    get_subtotal.short_description = "Subtotal"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('product')

# =============================================================================
# 🚀 MODEL ADMIN: PRODUCTOS (EL DASHBOARD DEFINITIVO)
# =============================================================================

@admin.register(Product)
class ProductAdmin(ModelAdmin):
    """
    Panel de control empresarial de Ceviche Studios. 
    Optimizado para alta densidad de datos, seguridad financiera y estética moderna.
    """
    
    # --- 📋 INTERFAZ DE LISTA (DATAGRID) ---
    list_display = (
        'display_thumbnail', 
        'name_styled', 
        'product_type_badge', 
        'price_tag', 
        'profit_margin', 
        'stock_status', 
        'is_active', 
        'quick_actions'
    )
    list_display_links = ('display_thumbnail', 'name_styled')
    list_editable = ('is_active',)
    list_filter = ('product_type', 'is_active', 'created_at')
    search_fields = ('name', 'description')
    list_per_page = 15

    # --- 🎨 COMPONENTES VISUALES (FIXED FORMATTING) ---

    def display_thumbnail(self, obj):
        url = obj.image_url if obj.image_url else "https://via.placeholder.com/150"
        return format_html(
            '<div style="width: 50px; height: 50px; border-radius: 10px; overflow: hidden; '
            'box-shadow: 0 4px 6px rgba(0,0,0,0.1); border: 2px solid #fff;">'
            '<img src="{}" style="width: 100%; height: 100%; object-fit: cover;" />'
            '</div>', url
        )
    display_thumbnail.short_description = "Img"

    def name_styled(self, obj):
        return format_html(
            '<div><div style="font-weight: 700; color: #1e293b; font-size: 0.9rem;">{}</div>'
            '<div style="font-size: 10px; color: #94a3b8; font-family: monospace;">ID: {}</div></div>',
            obj.name, str(obj.id)[:8].upper()
        )
    name_styled.short_description = "Producto"

    def product_type_badge(self, obj):
        bg = "#e0e7ff" if obj.product_type == 'SINGLE' else "#f3e8ff"
        color = "#4338ca" if obj.product_type == 'SINGLE' else "#7e22ce"
        return format_html(
            '<span style="background: {}; color: {}; padding: 2px 10px; '
            'border-radius: 6px; font-weight: 800; font-size: 10px; letter-spacing: 0.5px;">{}</span>',
            bg, color, obj.product_type
        )
    product_type_badge.short_description = "Tipo"

    def profit_margin(self, obj):
        """Inteligencia de Negocio: Calcula rentabilidad real de los combos"""
        if obj.product_type == 'COMBO':
            total_cost = sum(item.product.price * item.quantity for item in obj.combo_items.all())
            if total_cost > 0:
                profit = obj.price - total_cost
                margin_pc = (profit / obj.price) * 100 if obj.price > 0 else 0
                color = "#10b981" if margin_pc > 15 else "#ef4444"
                # Formateamos el string del porcentaje antes de format_html
                margin_str = f"{margin_pc:.1f}%"
                return format_html('<span style="color: {}; font-weight: 800;">{}</span>', color, margin_str)
        return format_html('<span style="color: #cbd5e1; font-size: 0.8rem;">Individual</span>')
    profit_margin.short_description = "Rentabilidad"

    def price_tag(self, obj):
        # Formateamos el precio antes de pasarlo al template de format_html
        price_str = f"${obj.price:,.0f}"
        return format_html(
            '<span style="background: #f8fafc; color: #0f172a; padding: 4px 10px; '
            'border-radius: 8px; font-weight: 900; font-family: monospace; border: 1px solid #e2e8f0;">'
            '{}</span>', price_str
        )
    price_tag.short_description = "P. Venta"

    def stock_status(self, obj):
        if obj.stock <= 0:
            label, color = "AGOTADO", "#ef4444"
        elif obj.stock <= 5:
            label, color = f"BAJO: {obj.stock}", "#f59e0b"
        else:
            label, color = f"{obj.stock} u.", "#10b981"
        
        return format_html(
            '<div style="display: flex; align-items: center; gap: 6px;">'
            '<div style="width: 8px; height: 8px; border-radius: 50%; background: {}; shadow: 0 0 5px {};"></div>'
            '<span style="font-weight: 700; color: #334155; font-size: 0.8rem;">{}</span></div>', 
            color, color, label
        )
    stock_status.short_description = "Inventario"

    def quick_actions(self, obj):
        return format_html(
            '<a href="/index.html" target="_blank" style="display: inline-flex; align-items: center; '
            'background: #f1f5f9; padding: 4px 8px; border-radius: 6px; color: #475569; '
            'text-decoration: none; font-size: 11px; font-weight: 600; transition: all 0.2s;">'
            '<i class="fas fa-eye" style="margin-right: 4px;"></i> Ver Web</a>'
        )
    quick_actions.short_description = "Acciones"

    # --- 📂 ORGANIZACIÓN DEL FORMULARIO (FIELDSETS) ---
    fieldsets = (
        ("💎 Identidad del Producto", {
            'fields': (('name', 'product_type'), 'description'),
            'classes': ('unfold-fieldset-blue',),
        }),
        ("💰 Control Financiero e Inventario", {
            'fields': (('price', 'stock'), ('is_active', 'image_url')),
            'description': "Configure los valores comerciales y la disponibilidad en tiempo real."
        }),
    )

    inlines = [ComboItemInline]

    # --- 🛡️ LÓGICA DE NEGOCIO Y PROTECCIÓN TOTAL ---

    def save_related(self, request, form, formsets, change):
        """
        Ejecuta validaciones críticas de integridad antes de confirmar cambios.
        """
        super().save_related(request, form, formsets, change)
        obj = form.instance
        
        if obj.product_type == 'COMBO':
            # 1. Alerta de Márgenes Negativos
            cost = sum(i.product.price * i.quantity for i in obj.combo_items.all())
            if obj.price < cost:
                messages.error(
                    request, 
                    f"🛑 RIESGO FINANCIERO: El combo '{obj.name}' se está vendiendo por "
                    f"${obj.price:,.0f} pero sus partes cuestan ${cost:,.0f}."
                )
            
            # 2. Protección de Bucle Infinito (Un combo no puede contenerse a sí mismo)
            if any(item.product.id == obj.id for item in obj.combo_items.all()):
                with transaction.atomic():
                    obj.combo_items.filter(product=obj).delete()
                    messages.set_level(request, messages.ERROR)
                    messages.error(
                        request, 
                        "🛑 ERROR DE SEGURIDAD: Se eliminó el producto del combo porque "
                        "no puede ser un ingrediente de sí mismo."
                    )

    def get_queryset(self, request):
        """Optimización SQL: Carga todos los datos relacionados en 1 sola consulta"""
        return super().get_queryset(request).prefetch_related('combo_items__product')

    # --- ⚡ ACCIONES EMPRESARIALES ---
    actions = ['export_to_csv', 'duplicate_items', 'mark_active', 'mark_inactive']

    @admin.action(description="📥 Exportar Inventario para Contabilidad (CSV)")
    def export_to_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="inventario_ceviche_studios.csv"'
        writer = csv.writer(response)
        writer.writerow(['UUID', 'Nombre', 'Tipo', 'Precio Público', 'Stock', 'Estado'])
        for p in queryset:
            writer.writerow([
                p.id, p.name, p.product_type, p.price, p.stock, 
                "ACTIVO" if p.is_active else "INACTIVO"
            ])
        return response

    @admin.action(description="👯 Clonar productos (Modo Borrador)")
    def duplicate_items(self, request, queryset):
        for obj in queryset:
            obj.pk = None
            obj.name = f"{obj.name} (CLON)"
            obj.is_active = False
            obj.save()
        self.message_user(request, f"Se han duplicado {queryset.count()} productos como borradores.")

    @admin.action(description="✅ Activar seleccionados")
    def mark_active(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description="❌ Desactivar seleccionados")
    def mark_inactive(self, request, queryset):
        queryset.update(is_active=False)       