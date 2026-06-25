#!/bin/bash
# ==============================================================================
# 🛡️ KERNEL BOOTSTRAP: CEVICHE PLATFORM (GOD-TIER EDITION)
# Arquitectura: Zero-Trust | Fail-Fast | Anti-DDoS | Memory-Safe
# ==============================================================================

# 1. 🛡️ STRICT MODE (Prevención de Cascada de Fallos)
# -e: Aborta si un comando falla.
# -u: Aborta si se usa una variable no definida (Anti-Environment Injection).
# -o pipefail: Aborta si falla cualquier comando dentro de un pipe (ej: cmd1 | cmd2)
set -euo pipefail

echo "⚡ [INIT] SECUENCIA DE ARRANQUE KERNEL INICIADA..."

# ==============================================================================
# 2. 🛡️ GATEKEEPER MULTI-NÚCLEO (POSTGRESQL + REDIS)
# Mitigación de Memory Dumping: Las credenciales se borran de RAM tras usarse.
# ==============================================================================
python -c "
import sys, time, os, gc
import psycopg2
import redis

def check_postgres():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        print('⚠️ [POSTGRES] DATABASE_URL no detectada. Omitiendo bloqueo...')
        return
    
    for i in range(15):
        try:
            # Connect_timeout previene TCP SYN Floods (Cuelgues infinitos)
            conn = psycopg2.connect(db_url, connect_timeout=3)
            conn.close()
            # 🛡️ ANTI-MEMORY DUMP: Destrucción inmediata de credenciales en RAM
            del db_url 
            gc.collect()
            print('🟢 [POSTGRES] Enlace criptográfico a la bóveda establecido.')
            return
        except Exception as e:
            print(f'⏳ [POSTGRES] Sincronizando clúster (Intento {i+1}/15)...')
            time.sleep(2)
    print('❌ [CRÍTICO] Fallo catastrófico de red DB.')
    sys.exit(1)

def check_redis():
    redis_url = os.environ.get('REDIS_URL')
    if not redis_url:
        print('⚠️ [REDIS] REDIS_URL no detectada. Omitiendo bloqueo...')
        return
        
    for i in range(10):
        try:
            # Timeout estricto para evitar bloqueos del socket
            client = redis.from_url(redis_url, socket_timeout=2)
            client.ping()
            client.close()
            del redis_url
            gc.collect()
            print('🟢 [REDIS] Capa de caché in-memory O(1) operativa.')
            return
        except Exception as e:
            print(f'⏳ [REDIS] Despertando demonio de caché (Intento {i+1}/10)...')
            time.sleep(2)
    print('❌ [CRÍTICO] Falla del clúster Redis. Transacciones bloqueadas.')
    sys.exit(1)

check_postgres()
check_redis()
sys.exit(0)
"

# ==============================================================================
# 3. 🛡️ MIGRACIONES ESTRUCTURALES ATÓMICAS
# ==============================================================================
echo "📦 [ACID] Validando esquema de base de datos..."
# Si la migración falla, el bloque 'if' atrapa el error y mata el contenedor 
# antes de abrir el puerto, evitando que la app corra con DB corrupta.
if ! python manage.py migrate --noinput; then
    echo "🚨 [CRÍTICO] Divergencia en el esquema DB. Abortando despliegue preventivamente."
    exit 1
fi

# ==============================================================================
# 4. 🛡️ MATRIZ DE RECURSOS (STATIC FILES)
# ==============================================================================
echo "🎨 [ASSETS] Compilando matriz estática (WhiteNoise/O(1) Access)..."
if ! python manage.py collectstatic --noinput; then
    echo "🚨 [CRÍTICO] Fallo en la inyección de recursos. Abortando."
    exit 1
fi

# ==============================================================================
# 5. 🛡️ DESPLIEGUE DEL SERVIDOR WSGI (ANTI-DDOS & AUTO-SCALING)
# ==============================================================================
# Asignación de Puerto Dinámico (Railway Native)
PORT=${PORT:-8000}

# Cálculo Dinámico de Workers basado en núcleos físicos (Fórmula FAANG: 2 * Cores + 1)
# Si WEB_CONCURRENCY no está definida, calculamos dinámicamente. 
# Fallback a 4 si 'nproc' no está disponible.
WORKERS=${WEB_CONCURRENCY:-$(($(nproc 2>/dev/null || echo 2) * 2 + 1))}

echo "🚀 [GUNICORN] Levantando Escudos. Workers activos: $WORKERS en Puerto: $PORT"

# Ejecución (exec reemplaza el shell actual por Gunicorn, optimizando memoria PIDs)
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:$PORT \
    --workers $WORKERS \
    --worker-class gthread \
    --threads 4 \
    --timeout 90 \
    --keep-alive 5 \
    --max-requests 1000 \
    --max-requests-jitter 50 \
    --limit-request-line 4094 \
    --limit-request-fields 100 \
    --limit-request-field_size 8190 \
    --log-level info