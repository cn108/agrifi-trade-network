"""
URL configuration for agrifi-trade-network project.
"""

from django.conf import settings
from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path


def health_check(request):
    """Liveness: the process is up. Does not touch dependencies."""
    return JsonResponse({'status': 'ok'})


def readiness_check(request):
    """Readiness: the database answers. Failure details are logged, never returned."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception:
        import logging
        logging.getLogger('agrifi.health').exception('readiness check failed')
        return JsonResponse({'status': 'unavailable'}, status=503)
    return JsonResponse({'status': 'ready'})


handler500 = 'agrifi.api_errors.server_error'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('healthz/', health_check, name='health-check'),
    path('readyz/', readiness_check, name='readiness-check'),
    path('api/v1/auth/', include('agrifi.accounts.urls')),
    path('api/v1/', include('agrifi.catalog.urls')),
    path('api/v1/', include('agrifi.inventory.urls')),
    path('api/v1/', include('agrifi.orders.urls')),
    path('api/v1/', include('agrifi.finance.urls')),
    path('api/v1/', include('agrifi.audit.urls')),
    path('api/v1/', include('agrifi.sync.urls')),
]

if settings.HAS_SPECTACULAR:
    from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
    from rest_framework.permissions import AllowAny

    from agrifi.catalog.permissions import IsOperationsAdmin

    # The contract is open in development; in production it is limited to operations admins.
    _docs_permissions = [AllowAny] if settings.DEBUG else [IsOperationsAdmin]
    urlpatterns += [
        path('api/v1/schema/', SpectacularAPIView.as_view(permission_classes=_docs_permissions), name='schema'),
        path(
            'api/v1/docs/',
            SpectacularSwaggerView.as_view(url_name='schema', permission_classes=_docs_permissions),
            name='api-docs',
        ),
    ]