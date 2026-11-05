from django.urls import path

from .views import SyncOperationCollectionView, SyncOperationDetailView

urlpatterns = [
    path('sync/operations/', SyncOperationCollectionView.as_view(), name='sync-operations'),
    path('sync/operations/<uuid:operation_id>/', SyncOperationDetailView.as_view(), name='sync-operation'),
]
