import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# 🛡️ RELOJ ATÓMICO: Programación del Segador de Memoria
app.conf.beat_schedule = {
    'purge_orphaned_reservations_every_5_mins': {
        'task': 'orders.purge_orphaned_reservations',
        'schedule': crontab(minute='*/5'), # Ejecuta cada 5 minutos
    },
}

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')