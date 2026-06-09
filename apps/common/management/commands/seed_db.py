import random
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from datetime import timedelta

# 1. IMPORTACIONES DE MODELOS
from backend.apps.events.models import Theater, SeatCategory, Seat, Event, ShowFunction, Price
from backend.apps.products.models import Product, ComboItem

class Command(BaseCommand):
    help = 'Puebla la base de datos con un escenario de prueba profesional (ATP Level)'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.WARNING('🌱 Iniciando protocolo de siembra de datos...'))

        try:
            with transaction.atomic():
                # ============================================================
                # FASE 1: INFRAESTRUCTURA (TEATRO Y SILLAS)
                # ============================================================
                
                # 1. Crear Teatro
                theater, created = Theater.objects.get_or_create(
                    name="Teatro Principal Chía",
                    defaults={
                        'address': "Centro Chía - Local 305",
                        'capacity': 100,
                        'seating_map_url': "https://example.com/mapa.svg"
                    }
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f'✅ Teatro creado: {theater.name}'))

                # 2. Crear Categorías (Zonas)
                cat_vip, _ = SeatCategory.objects.get_or_create(
                    theater=theater, name="VIP", 
                    defaults={'color_code': "#FFD700"} # Dorado
                )
                cat_gen, _ = SeatCategory.objects.get_or_create(
                    theater=theater, name="General", 
                    defaults={'color_code': "#CCCCCC"} # Gris Plata
                )

                # 3. Crear Sillas
                seats_created_count = 0
                
                # Fila A (VIP) - 8 Sillas
                for i in range(1, 9):
                    row, number = "A", str(i)
                    svg_id = f"{row}-{number}"
                    
                    # CORRECCIÓN: Usamos category para buscar, NO theater directamente
                    seat, s_created = Seat.objects.get_or_create(
                        category=cat_vip, 
                        svg_id=svg_id,
                        defaults={
                            'row': row, 
                            'number': number
                        }
                    )
                    if s_created: seats_created_count += 1

                # Fila B (General) - 8 Sillas
                for i in range(1, 9):
                    row, number = "B", str(i)
                    svg_id = f"{row}-{number}"
                    
                    seat, s_created = Seat.objects.get_or_create(
                        category=cat_gen,
                        svg_id=svg_id,
                        defaults={
                            'row': row, 
                            'number': number
                        }
                    )
                    if s_created: seats_created_count += 1
                
                # Filas Extra (C y D)
                for row in ['C', 'D']:
                    for i in range(1, 9):
                        svg_id = f"{row}-{i}"
                        Seat.objects.get_or_create(
                            category=cat_gen,
                            svg_id=svg_id,
                            defaults={'row': row, 'number': str(i)}
                        )

                self.stdout.write(self.style.SUCCESS(f'🪑 Sillas sincronizadas.'))

                # ============================================================
                # FASE 2: SHOW BUSINESS (EVENTOS)
                # ============================================================

                # 4. Crear Evento
                event, e_created = Event.objects.get_or_create(
                    title="Gran Stand Up Comedy",
                    defaults={
                        'description': "Una noche llena de risas con los mejores comediantes.",
                        'is_active': True,
                        'poster_url': "https://images.unsplash.com/photo-1585699324551-f6c309eedeca?auto=format&fit=crop&w=800&q=80"
                    }
                )

                # 5. Crear Función (Para mañana a las 8:00 PM)
                tomorrow_8pm = timezone.now() + timedelta(days=1)
                tomorrow_8pm = tomorrow_8pm.replace(hour=20, minute=0, second=0, microsecond=0)

                # 🛠️ CORRECCIÓN AQUÍ: Eliminamos 'is_active' de defaults
                function, f_created = ShowFunction.objects.get_or_create(
                    event=event,
                    theater=theater,
                    date_time=tomorrow_8pm
                )

                # 6. Precios
                Price.objects.get_or_create(function=function, category=cat_vip, defaults={'amount': 80000})
                Price.objects.get_or_create(function=function, category=cat_gen, defaults={'amount': 50000})

                self.stdout.write(self.style.SUCCESS(f'📅 Evento y Función programados: {event.title}'))

                # ============================================================
                # FASE 3: E-COMMERCE (PRODUCTOS)
                # ============================================================

                prod_soda, _ = Product.objects.get_or_create(
                    name="Coca-Cola 400ml", 
                    defaults={
                        'price': 5000, 
                        'stock': 200,
                        'product_type': Product.Type.SINGLE,
                        'description': "Refrescante y fría.",
                        'image_url': "https://via.placeholder.com/150?text=Soda"
                    }
                )
                
                prod_popcorn, _ = Product.objects.get_or_create(
                    name="Crispetas Saladas", 
                    defaults={
                        'price': 10000, 
                        'stock': 100,
                        'product_type': Product.Type.SINGLE,
                        'description': "Recién hechas.",
                        'image_url': "https://via.placeholder.com/150?text=Popcorn"
                    }
                )

                combo_pareja, c_created = Product.objects.get_or_create(
                    name="Combo Pareja Ideal",
                    defaults={
                        'description': "2 Gaseosas + 1 Crispetas. Ahorras $2.000",
                        'price': 18000,
                        'is_active': True,
                        'stock': 50,
                        'product_type': Product.Type.COMBO,
                        'image_url': "https://via.placeholder.com/150?text=Combo"
                    }
                )

                if c_created:
                    ComboItem.objects.create(parent_combo=combo_pareja, product=prod_soda, quantity=2)
                    ComboItem.objects.create(parent_combo=combo_pareja, product=prod_popcorn, quantity=1)

                self.stdout.write(self.style.SUCCESS('🚀 DB SEED COMPLETADO: Sistema listo.'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Error crítico: {str(e)}'))