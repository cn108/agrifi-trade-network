from rest_framework.routers import SimpleRouter

from .views import DisputeViewSet, OrderViewSet

router = SimpleRouter()
router.register('orders', OrderViewSet, basename='order')
router.register('disputes', DisputeViewSet, basename='dispute')

urlpatterns = router.urls
