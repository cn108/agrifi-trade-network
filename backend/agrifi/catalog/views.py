import uuid

from django.db import transaction
from django.db.models import Q
from rest_framework import filters, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated

from agrifi.inventory.services import annotate_listing_stock

from .models import CropCategory, Listing
from .permissions import IsFarmer, ReadOnlyOrOperationsAdmin, is_ops_admin
from .serializers import CropCategorySerializer, ListingSerializer


class CropCategoryViewSet(viewsets.ModelViewSet):
    """Crop categories. Any authenticated user can read active categories;
    only operations administrators can create, edit or deactivate. No delete."""

    serializer_class = CropCategorySerializer
    permission_classes = (ReadOnlyOrOperationsAdmin,)
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    filter_backends = (filters.OrderingFilter,)
    ordering_fields = ('name', 'created_at')

    def get_queryset(self):
        queryset = CropCategory.objects.all()
        if not is_ops_admin(self.request.user):
            queryset = queryset.filter(is_active=True)
        return queryset


class ListingWritePermission(BasePermission):
    """Owner (unless suspended) or operations administrator may modify a listing."""

    message = 'You do not have permission to modify this listing.'

    def has_object_permission(self, request, view, obj):
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        if is_ops_admin(request.user):
            return True
        return obj.seller_id == request.user.id and obj.status != Listing.Status.SUSPENDED


class ListingViewSet(viewsets.ModelViewSet):
    """Marketplace listings.

    * Buyers and other users see only active listings (active category and seller).
    * Farmers additionally see all of their own listings.
    * Only farmers can create; the seller is always the authenticated user.
    * Updates are limited to the owner or an operations administrator.
    * Only administrators can suspend; there is no delete (archive instead).
    """

    serializer_class = ListingSerializer
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    filter_backends = (filters.OrderingFilter,)
    ordering_fields = ('created_at', 'unit_price_minor', 'name')

    def get_permissions(self):
        if self.action == 'create':
            return [IsAuthenticated(), IsFarmer()]
        return [IsAuthenticated(), ListingWritePermission()]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):  # schema generation has no user
            return Listing.objects.none()
        user = self.request.user
        queryset = Listing.objects.select_related('category', 'seller', 'seller__farmer_profile')
        if not is_ops_admin(user):
            queryset = queryset.filter(
                Q(seller=user)
                | Q(status=Listing.Status.ACTIVE, category__is_active=True, seller__is_active=True)
            )
        params = self.request.query_params
        if params.get('category'):
            try:
                category_id = uuid.UUID(params['category'])
            except ValueError:
                raise ValidationError({'category': 'Invalid category id.'})
            queryset = queryset.filter(category_id=category_id)
        if params.get('status') in Listing.Status.values:
            queryset = queryset.filter(status=params['status'])
        if params.get('mine') == 'true':
            queryset = queryset.filter(seller=user)
        if params.get('q'):
            queryset = queryset.filter(name__icontains=params['q'])
        # One-query availability for listing pages; the serializer falls back per object elsewhere.
        return annotate_listing_stock(queryset)

    def perform_create(self, serializer):
        serializer.save(seller=self.request.user)

    def perform_update(self, serializer):
        with transaction.atomic():
            locked = Listing.objects.select_for_update().get(pk=serializer.instance.pk)
            if locked.stock_movements.exists():
                for field in ('category', 'unit_code'):
                    if field in serializer.validated_data and (
                        serializer.validated_data[field] != getattr(locked, field)
                    ):
                        raise ValidationError({
                            field: 'Cannot be changed once stock has been allocated to this listing.'
                        })
            serializer.instance = locked
            if 'status' in serializer.validated_data:
                serializer.validated_data['status'] = serializer.validate_status(
                    serializer.validated_data['status']
                )
            serializer.save()
