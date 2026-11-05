from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    AllocateView, DeallocateView, HarvestBatchViewSet, ListingStockView, StockMovementListView,
)

router = SimpleRouter()
router.register('harvest-batches', HarvestBatchViewSet, basename='harvest-batch')

urlpatterns = [
    path('listings/<uuid:pk>/stock/', ListingStockView.as_view(), name='listing-stock'),
    path('listings/<uuid:pk>/allocate/', AllocateView.as_view(), name='listing-allocate'),
    path('listings/<uuid:pk>/deallocate/', DeallocateView.as_view(), name='listing-deallocate'),
    path('stock-movements/', StockMovementListView.as_view(), name='stock-movement-list'),
    *router.urls,
]
