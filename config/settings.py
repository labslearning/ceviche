"""
⚙️ Configuración Maestra - Ceviche Platform
Seguridad: Grado Alto (ATP).
Arquitectura: Django + Railway + PostgreSQL + Redis
"""
from pathlib import Path
from decouple import config, Csv
import dj_database_url
import os

# Rutas base
# BASE_DIR apunta a la carpeta 'backend'
BASE_DIR = Path(__file__).resolve().parent.parent

# 🔐 SEGURIDAD: Leer secretos desde variables de entorno (.env)
SECRET_KEY = config('SECRET_KEY', default='django-insecure-development-key-change-me')

# En producción (Railway), DEBUG debe ser False.
DEBUG = config('DEBUG', default=True, cast=bool)

# Hosts permitidos
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='127.0.0.1,localhost', cast=Csv())

# Confianza CSRF (Vital para Railway y formularios seguros)
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='http://127.0.0.1,http://localhost', cast=Csv())

# 📦 APLICACIONES INSTALADAS
INSTALLED_APPS = [
    #'jazzmin',
    "unfold",
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third party apps
    'rest_framework', # API Profesional
    'corsheaders',    # Conexión Frontend-Backend
    # 'django_celery_results', # (Opcional)

    # 🏠 Mis Apps (Módulos de Negocio)
    # 👇 CORRECCIÓN CRÍTICA: Eliminamos 'backend.'
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
    'django.contrib.humanize', 
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware', # 🚀 Archivos estáticos rápidos
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',      # CORS antes de Common
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# 👇 CORRECCIÓN CRÍTICA: Eliminamos 'backend.'
ROOT_URLCONF = 'config.urls'

# 🎨 CONFIGURACIÓN DE PLANTILLAS (HTML)
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

# 👇 CORRECCIÓN CRÍTICA: Eliminamos 'backend.'
WSGI_APPLICATION = 'config.wsgi.application'

# 🗄️ BASE DE DATOS
DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600
    )
}

# 🔐 VALIDACIÓN DE CONTRASEÑAS
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# 🌍 IDIOMA Y ZONA HORARIA
LANGUAGE_CODE = 'es-co' # Colombia
TIME_ZONE = 'America/Bogota'
USE_I18N = True
USE_TZ = True

# 📂 ARCHIVOS ESTÁTICOS (CSS, JS, IMAGES)
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

# Compresión y caché para alto rendimiento en producción
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# 👤 USUARIO PERSONALIZADO
# IMPORTANTE: Asegúrate de que tu modelo User esté en apps.users
AUTH_USER_MODEL = 'users.User' 

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 🛡️ CORS (Seguridad de API)
CORS_ALLOW_ALL_ORIGINS = True 

# ⚡ CONFIGURACIÓN DRF (DJANGO REST FRAMEWORK)
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

# 🐇 CELERY & REDIS
CELERY_BROKER_URL = config('REDIS_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = config('REDIS_URL', default='redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'

# 📜 LOGGING PROFESIONAL
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

JAZZMIN_SETTINGS = {
    "site_title": "Ceviche Studios Admin",
    "site_header": "Ceviche Studios",
    "site_brand": "Ceviche Admin",
    "welcome_sign": "Bienvenido al Panel de Control de Ceviche Studios",
    "copyright": "Ceviche Studios Ltd",
    "search_model": ["users.User", "products.Product"], # Ajustado a 'users'
    "topmenu_links": [
        {"name": "Inicio", "url": "admin:index", "permissions": ["auth.view_user"]},
        {"name": "Ver Sitio Web", "url": "/", "new_window": True},
    ],
    "show_sidebar": True,
    "navigation_expanded": True,
    "icons": {
        "auth": "fas fa-users-cog",
        "users.User": "fas fa-user", # Ajustado a 'users'
        "products.Product": "fas fa-hamburger",
        "events.Event": "fas fa-ticket-alt",
        "orders.Order": "fas fa-shopping-cart",
    },
}


# --- CONFIGURACIÓN DE AUTH (LOGIN/LOGOUT) ---
LOGIN_URL = '/manager/login/'           
LOGIN_REDIRECT_URL = '/manager/'        
LOGOUT_REDIRECT_URL = '/manager/login/'


# ... configuración de STATIC_URL ...

# 👇 AGREGA ESTAS DOS LÍNEAS PARA EVITAR EL ERROR 404 "CATCH-ALL"
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

