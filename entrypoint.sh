#!/bin/bash
set -e

echo "🛡️ INICIANDO SECUENCIA DE ARRANQUE CLOUD (RAILWAY)..."

# 🛡️ MOTOR DE BLOQUEO EN PYTHON (Adaptado para bases de datos Cloud)
python -c "
import sys, time, psycopg2, os

db_url = os.environ.get('DATABASE_URL')
if not db_url:
    print('⚠️ No se detectó DATABASE_URL. Asumiendo entorno sin DB o inyección pendiente...')
    sys.exit(0)

for i in range(15):
    try:
        conn = psycopg2.connect(db_url)
        conn.close()
        print('🟢 [RAILWAY DB ONLINE] Conexión física con Postgres lograda.')
        sys.exit(0)
    except Exception as e:
        print(f'😴 Esperando a la base de datos administrada (Intento {i+1}/15)...')
        time.sleep(2)

print('❌ Error Crítico: Timeout de red. La base de datos no responde.')
sys.exit(1)
"

echo "📦 Aplicando migraciones estructurales..."
python manage.py migrate --noinput

echo "🎨 Compilando matriz de estáticos para WhiteNoise..."
python manage.py collectstatic --noinput

# 🛡️ RAILWAY DYNAMIC PORT BINDING (La magia de la nube)
# Si Railway nos da un puerto, lo usamos. Si no (ej. en tu laptop), usamos el 8000
PORT=${PORT:-8000}

echo "🚀 Desplegando Gunicorn WSGI en el puerto $PORT..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:$PORT \
    --workers 4 \
    --worker-class gthread \
    --threads 4 \
    --timeout 60 \
    --log-level info
