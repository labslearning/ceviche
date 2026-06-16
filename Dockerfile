# ==============================================================================
# 🛠️ STAGE 1: THE BUILDER (Compilación Pesada y Criptográfica)
# ==============================================================================
FROM python:3.10-slim as builder

# Optimizaciones de Python en memoria
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Instalamos compiladores de C y librerías de PostgreSQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Creamos y activamos entorno virtual interno (Aislamiento total)
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .

# 🚀 GOD TIER TWEAK: Instalamos optimizadores, gunicorn (WSGI) y whitenoise
RUN pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt && \
    pip install gunicorn whitenoise

# ==============================================================================
# 🛡️ STAGE 2: PRODUCTION RUNTIME (Imagen Final Blindada)
# ==============================================================================
FROM python:3.10-slim

# Variables de entorno críticas
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Dependencias estrictamente necesarias para tiempo de ejecución
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 🛡️ HARDENING: Creación de usuario restringido (Evita escalada de privilegios)
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

WORKDIR /app

# Inyección limpia de binarios compilados desde el Stage 1
COPY --from=builder /opt/venv /opt/venv

# Copiamos el código fuente de tu proyecto
COPY . .

# 🛡️ PERMISOS ABSOLUTOS: Garantizar ejecución ANTES de cambiar de usuario
RUN chmod +x entrypoint.sh && chown -R appuser:appgroup /app

# Cerramos la bóveda: de aquí en adelante, el contenedor no tiene permisos root
USER appuser

# 🌐 CLOUD NATIVE: Exponemos el puerto dinámicamente (Railway inyecta la variable $PORT)
EXPOSE $PORT

# 🚀 IGNICIÓN AUTOMÁTICA: El contenedor arranca por sí solo (Bypass de docker-compose)
ENTRYPOINT ["/bin/bash", "/app/entrypoint.sh"]
