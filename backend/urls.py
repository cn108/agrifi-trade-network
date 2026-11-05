from django.contrib import admin
from django.urls import path, include
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi


schema_view = get_schema_view(
   openapi.Info(
      title="AgriFi Trade Network API",
      default_version='v1',
      description="API documentation for the AgriFi Trade Network web application",
      terms_of_service="https://www.google.com/policies/terms/",
      contact=openapi.Contact(email="contact@agrifi.local"),
      license=openapi.License(name="MIT License"),
   ),
   public=True,
   permission_classes=(permissions.AllowAny,),
)


urlpatterns = [
    path('admin/', admin.site.urls),
    
    # API endpoints
    path('api/users/register/', include('backend.agrifi.views').register_user_urlpatterns),
    path('api/users/profile/', include('backend.agrifi.views').profile_urlpatterns),
    path('api/transactions/', include('backend.agrifi.views').transaction_urlpatterns),
    path('api/analytics/', include('backend.agrifi.views').analytics_urlpatterns),
    
    # API docs
    path('docs/', schema_view.with_ui('swagger', cache_timeout=0)),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0)),
]
