import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'dev-secret')
DEBUG = True

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'django.contrib.admin',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'drf_yasg',
    'wa_templates',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'wa_templates.middleware.InjectOrgMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]

ROOT_URLCONF = 'whatsapp_template_service.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [str(BASE_DIR / 'templates')],
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

WSGI_APPLICATION = 'whatsapp_template_service.wsgi.application'

# Allow using SQLite for fast local development by setting USE_SQLITE=1
USE_SQLITE = str(os.environ.get('USE_SQLITE', '')).lower() in ('1', 'true', 'yes')

if USE_SQLITE:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': str(BASE_DIR / 'db.sqlite3'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('POSTGRES_DB', 'whatsapp_template_db'),
            'USER': os.environ.get('POSTGRES_USER', 'postgres'),
            'PASSWORD': os.environ.get('POSTGRES_PASSWORD', 'postgres'),
            'HOST': os.environ.get('POSTGRES_HOST', 'localhost'),
            'PORT': os.environ.get('POSTGRES_PORT', '5432'),
        }
    }

REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'wa_templates.auth.JWTAuthentication',
    ),
}

STATIC_URL = '/static/'

# JWT public key for verifying tokens
JWT_PUBLIC_KEY = os.environ.get('JWT_PUBLIC_KEY', '')

# JWT claim names configurable to support different identity providers
JWT_TENANT_CLAIM = os.environ.get('JWT_TENANT_CLAIM', 'tenant')
JWT_USER_CLAIM = os.environ.get('JWT_USER_CLAIM', 'sub')
JWT_ALGORITHM = os.environ.get('JWT_ALGORITHM', 'RS256')

# Celery
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL

# Gupshup placeholders
GUPSHUP_API_KEY = os.environ.get('GUPSHUP_API_KEY', '')
GUPSHUP_APP_ID = os.environ.get('GUPSHUP_APP_ID', '')
