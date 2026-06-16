from django.apps import AppConfig

class OrdersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.orders'

    def ready(self):
        # 🛡️ Carga explícita de señales para evitar descriptores huérfanos
        import apps.orders.signals