"""
⚙️ Configuración Maestra - Ceviche Platform (GOD-TIER CLOUD EDITION)
Seguridad: Grado Bancario (PCI-DSS) - Zero Trust Architecture.
Infraestructura: Django + Railway + PostgreSQL + Redis + Celery + MercadoPago
"""
import os
from pathlib import Path
from decouple import config, Csv
import dj_database_url

# ==============================================================================
# 🏗️ RUTAS BASE
# ==============================================================================
# BASE_DIR apunta a la carpeta 'backend'
BASE_DIR = Path(__file__).resolve().parent.parent

# ==============================================================================
# 🔐 SEGURIDAD CORE Y CRIPTOGRAFÍA
# ==============================================================================
SECRET_KEY = config('SECRET_KEY', default='django-insecure-development-key-change-me')

# En producción (Railway), DEBUG debe ser explícitamente False.
DEBUG = config('DEBUG', default=True, cast=bool)

# ==============================================================================
# 🌐 FIREWALL DE DOMINIOS, CORS Y SITE_URL (CLOUD NATIVE)
# ==============================================================================
# 1. Hosts base locales y de túneles (Ngrok)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='127.0.0.1,localhost,.ngrok-free.dev', cast=Csv())
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='http://127.0.0.1,http://localhost,https://*.ngrok-free.dev', cast=Csv())

# 2. 🚀 INYECCIÓN DINÁMICA RAILWAY (Auto-Scaling & Webhooks MP)
RAILWAY_DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN')

if RAILWAY_DOMAIN:
    ALLOWED_HOSTS.append(RAILWAY_DOMAIN)
    ALLOWED_HOSTS.append('.up.railway.app')
    CSRF_TRUSTED_ORIGINS.append(f'https://{RAILWAY_DOMAIN}')
    CSRF_TRUSTED_ORIGINS.append('https://*.up.railway.app')
    # Dominio Absoluto para callbacks de Mercado Pago (Success, Failure, Webhooks)
    SITE_URL = f"https://{RAILWAY_DOMAIN}"
else:
    SITE_URL = config('SITE_URL', default='http://localhost:8000')

# 3. 🛡️ REGLAS DE PRODUCCIÓN ESTRICTAS (Nivel Bancario - PCI-DSS)
if not DEBUG:
    # Fuerza HTTPS detrás del proxy de Railway
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    
    # Blindaje de Cookies (Anti Memory Dumping & Session Hijacking)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True # Evita lectura desde JS
    SESSION_COOKIE_SAMESITE = 'Strict' # Anti CSRF cruzado
    
    # HSTS: Obliga a los navegadores a usar solo HTTPS (Anti Man-in-the-Middle)
    SECURE_HSTS_SECONDS = 31536000  # 1 año
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    
    # Previene inyección de MIME types (Sniffing) y Clickjacking
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    
    # CORS Restringido: Solo nuestro dominio puede consumir las APIs de pago
    CORS_ALLOW_ALL_ORIGINS = False
    CORS_ALLOWED_ORIGINS = [
        f"https://{RAILWAY_DOMAIN}" if RAILWAY_DOMAIN else "https://tu-dominio-produccion.com",
    ]
else:
    # En desarrollo permitimos todo para facilitar el debugging
    CORS_ALLOW_ALL_ORIGINS = True

# ==============================================================================
# 📦 APLICACIONES Y MIDDLEWARES
# ==============================================================================
INSTALLED_APPS = [
    # Interfaz Admin Moderna
    "unfold",
    
    # Core Django
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize', 
    
    # Third party apps
    'rest_framework', # API Profesional
    'corsheaders',    # Conexión Frontend-Backend

    # 🏠 Mis Apps (Módulos de Negocio)
    'apps.common',
    'apps.users',
    'apps.events',
    'apps.orders',
    'apps.billing',
    'apps.logistics',
    'apps.support',
    'apps.products',
    'apps.website', 
    'apps.dashboard',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware', # 🚀 Estáticos O(1)
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',      # CORS debe ir antes de Common
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'

# ==============================================================================
# 🎨 PLANTILLAS HTML
# ==============================================================================
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'], 
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# ==============================================================================
# 🗄️ BASES DE DATOS (AUTO-PROVISIONING CLOUD)
# ==============================================================================
DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# ==============================================================================
# 🔐 VALIDACIÓN DE USUARIOS Y CONTRASEÑAS
# ==============================================================================
AUTH_USER_MODEL = 'users.User' 
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# --- CONFIGURACIÓN DE AUTH (LOGIN/LOGOUT) ---
LOGIN_URL = '/manager/login/'           
LOGIN_REDIRECT_URL = '/manager/'        
LOGOUT_REDIRECT_URL = '/manager/login/'

# ==============================================================================
# 🌍 LOCALIZACIÓN
# ==============================================================================
LANGUAGE_CODE = 'es-co' # Colombia
TIME_ZONE = 'America/Bogota'
USE_I18N = True
USE_TZ = True

# ==============================================================================
# 📂 ARCHIVOS ESTÁTICOS Y MEDIA (WHITENOISE OPTIMIZED)
# ==============================================================================
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [BASE_DIR / 'static']

# Modo Permisivo: Ignora referencias rotas en CSS sin crashear el servidor
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# ==============================================================================
# ⚡ DJANGO REST FRAMEWORK (API)
# ==============================================================================
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 10,
    
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/day',  
        'user': '1000/day', 
        '20/min': '20/min', 
    }
}

# ==============================================================================
# 🚀 CELERY & REDIS: COLAS DE ALTO RENDIMIENTO (CORREGIDO PARA CLOUD)
# ==============================================================================
# Toma la URL inyectada por Railway, o usa localhost como fallback seguro.
CELERY_BROKER_URL = config('REDIS_URL', default='redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = config('REDIS_URL', default='redis://127.0.0.1:6379/0')

CELERY_ACCEPT_CONTENT = ['application/json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 1800 # 30 Minutos de seguridad
CELERY_WORKER_CONCURRENCY = 4

# ==============================================================================
# 📜 LOGGING PROFESIONAL
# ==============================================================================
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO', 
    },
}

# ==============================================================================
# 💄 CONFIGURACIÓN ADMIN (JAZZMIN/UNFOLD FALLBACK)
# ==============================================================================
JAZZMIN_SETTINGS = {
    "site_title": "Ceviche Studios Admin",
    "site_header": "Ceviche Studios",
    "site_brand": "Ceviche Admin",
    "welcome_sign": "Bienvenido al Panel de Control de Ceviche Studios",
    "copyright": "Ceviche Studios Ltd",
    "search_model": ["users.User", "products.Product"], 
    "topmenu_links": [
        {"name": "Inicio", "url": "admin:index", "permissions": ["auth.view_user"]},
        {"name": "Ver Sitio Web", "url": "/", "new_window": True},
    ],
    "show_sidebar": True,
    "navigation_expanded": True,
    "icons": {
        "auth": "fas fa-users-cog",
        "users.User": "fas fa-user", 
        "products.Product": "fas fa-hamburger",
        "events.Event": "fas fa-ticket-alt",
        "orders.Order": "fas fa-shopping-cart",
    },
}

# ==============================================================================
# 💳 MERCADO PAGO INTEGRATION (FINTECH CORE)
# ==============================================================================
# IMPORTANTE: En el panel de variables de Railway debes declarar estas llaves EXACTAMENTE ASÍ
MERCADOPAGO_ACCESS_TOKEN = config('MERCADOPAGO_ACCESS_TOKEN', default='')
MERCADOPAGO_PUBLIC_KEY = config('MERCADOPAGO_PUBLIC_KEY', default='')