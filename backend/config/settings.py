"""
Django settings for agrifi-trade-network project.
"""

import os
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


DEBUG = env_bool('DJANGO_DEBUG')
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false.')
    SECRET_KEY = 'development-only-insecure-secret-key'

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
    if host.strip()
]

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third party apps
    'rest_framework',
    'corsheaders',
    'agrifi.accounts.apps.AccountsConfig',
    'agrifi.catalog.apps.CatalogConfig',
    'agrifi.idempotency.apps.IdempotencyConfig',
    'agrifi.inventory.apps.InventoryConfig',
    'agrifi.orders.apps.OrdersConfig',
    'agrifi.finance.apps.FinanceConfig',
    'agrifi.audit.apps.AuditConfig',
]

# OpenAPI generation is a build/dev tool; the app runs without it when it is not installed.
try:
    import drf_spectacular  # noqa: F401
    HAS_SPECTACULAR = True
except ImportError:
    HAS_SPECTACULAR = False
if HAS_SPECTACULAR:
    INSTALLED_APPS.append('drf_spectacular')

MIDDLEWARE = [
    'agrifi.request_context.RequestIdMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
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

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# Database
if env_bool('AGRIFI_USE_SQLITE'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.environ.get('AGRIFI_SQLITE_PATH') or BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'agrifi'),
            'USER': os.environ.get('DB_USER', 'agrifi'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', 'localhost'),
            'PORT': os.environ.get('DB_PORT', '5432'),
            'CONN_MAX_AGE': int(os.environ.get('DB_CONN_MAX_AGE', '60')),
            'OPTIONS': {'connect_timeout': 5},
        }
    }

# Custom user model must be selected before the first migration.
AUTH_USER_MODEL = 'accounts.User'

# CORS settings for the Angular development server.
default_cors_origins = 'http://localhost:4200' if DEBUG else ''
CORS_ALLOWED_ORIGINS = []
for configured_origin in os.environ.get(
    'DJANGO_CORS_ALLOWED_ORIGINS',
    default_cors_origins,
).split(','):
    origin = configured_origin.strip()
    if not origin:
        continue
    parsed_origin = urlsplit(origin)
    if (
        '*' in origin
        or parsed_origin.scheme not in {'http', 'https'}
        or not parsed_origin.netloc
        or parsed_origin.path
        or parsed_origin.query
        or parsed_origin.fragment
        or parsed_origin.username
        or parsed_origin.password
    ):
        raise ImproperlyConfigured(
            'DJANGO_CORS_ALLOWED_ORIGINS must contain exact origins without paths or wildcards.'
        )
    if not DEBUG and parsed_origin.scheme != 'https':
        raise ImproperlyConfigured(
            'DJANGO_CORS_ALLOWED_ORIGINS must use HTTPS when DJANGO_DEBUG is false.'
        )
    CORS_ALLOWED_ORIGINS.append(origin)
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'agrifi.pagination.StandardPagination',
    'PAGE_SIZE': 25,
    'EXCEPTION_HANDLER': 'agrifi.api_errors.exception_handler',
    # 0 = ignore X-Forwarded-For and throttle on the socket address. Behind N trusted proxies
    # set DJANGO_NUM_PROXIES=N; otherwise a client could dodge the per-address limit by
    # varying that header.
    'NUM_PROXIES': int(os.environ.get('DJANGO_NUM_PROXIES', '0')),
}
if HAS_SPECTACULAR:
    REST_FRAMEWORK['DEFAULT_SCHEMA_CLASS'] = 'drf_spectacular.openapi.AutoSchema'
    SPECTACULAR_SETTINGS = {
        'TITLE': 'AgriFi Trade Network API',
        'DESCRIPTION': (
            'Nigerian-first B2B agricultural marketplace. Payments, refunds, settlements and '
            'the ledger are SIMULATED: no real money moves. Money is integer kobo.'
        ),
        'VERSION': '1.0.0',
        'SERVE_INCLUDE_SCHEMA': False,
        'COMPONENT_SPLIT_REQUEST': True,
        'SCHEMA_PATH_PREFIX': r'/api/v1',
    }

# Throttle counters live in the Django cache. The default per-process memory cache is only
# adequate for one worker; set DJANGO_CACHE_DB_TABLE (then run `manage.py createcachetable`)
# so every worker shares the counters.
if os.environ.get('DJANGO_CACHE_DB_TABLE'):
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
            'LOCATION': os.environ['DJANGO_CACHE_DB_TABLE'],
        }
    }

# Rates use DRF notation ("10/min"); an empty value disables that throttle. The automated
# test run disables them so unrelated tests are not rate limited; throttle tests set their own.
RUNNING_TESTS = len(sys.argv) > 1 and sys.argv[1] == 'test'
AGRIFI_THROTTLE_RATES = {
    'auth_ip': '' if RUNNING_TESTS else os.environ.get('THROTTLE_AUTH_IP', '30/min'),
    'login_email': '' if RUNNING_TESTS else os.environ.get('THROTTLE_LOGIN_EMAIL', '10/min'),
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=5),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

JWT_REFRESH_COOKIE_NAME = os.environ.get('JWT_REFRESH_COOKIE_NAME', 'agrifi_refresh')
JWT_REFRESH_COOKIE_PATH = '/api/v1/auth/'
JWT_REFRESH_COOKIE_SECURE = env_bool('JWT_REFRESH_COOKIE_SECURE', not DEBUG)
JWT_REFRESH_COOKIE_SAMESITE = os.environ.get('JWT_REFRESH_COOKIE_SAMESITE', 'Lax')
JWT_REFRESH_COOKIE_MAX_AGE = int(os.environ.get('JWT_REFRESH_COOKIE_MAX_AGE', '604800'))
if not DEBUG and not JWT_REFRESH_COOKIE_SECURE:
    raise ImproperlyConfigured('JWT_REFRESH_COOKIE_SECURE must be true when DJANGO_DEBUG is false.')
if JWT_REFRESH_COOKIE_SAMESITE not in {'Lax', 'Strict', 'None'}:
    raise ImproperlyConfigured('JWT_REFRESH_COOKIE_SAMESITE must be Lax, Strict, or None.')
if JWT_REFRESH_COOKIE_SAMESITE == 'None' and not JWT_REFRESH_COOKIE_SECURE:
    raise ImproperlyConfigured('SameSite=None refresh cookies require JWT_REFRESH_COOKIE_SECURE=true.')

CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG

# Transport hardening is opt-in because HSTS is hard to undo and redirects depend on the proxy.
# Behind a TLS-terminating proxy set DJANGO_SECURE_PROXY_SSL_HEADER=true (the proxy must strip
# any client-supplied X-Forwarded-Proto), then DJANGO_SECURE_SSL_REDIRECT and DJANGO_HSTS_SECONDS.
if env_bool('DJANGO_SECURE_PROXY_SSL_HEADER'):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = env_bool('DJANGO_SECURE_SSL_REDIRECT')
SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('DJANGO_HSTS_INCLUDE_SUBDOMAINS')

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Static files
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
# How long checkout holds stock while waiting for the seller to confirm.
ORDER_RESERVATION_TTL_HOURS = int(os.environ.get('ORDER_RESERVATION_TTL_HOURS', '48'))

# Structured (JSON) logs to stdout. Request bodies, headers and credentials are never logged.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'json': {'()': 'config.logging.JsonFormatter'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'json'}},
    'root': {'handlers': ['console'], 'level': os.environ.get('DJANGO_LOG_LEVEL', 'INFO')},
}
