from rest_framework.routers import SimpleRouter

from .views import CropCategoryViewSet, ListingViewSet

router = SimpleRouter()
router.register('categories', CropCategoryViewSet, basename='category')
router.register('listings', ListingViewSet, basename='listing')

urlpatterns = router.urls
