from django.utils.text import slugify
from rest_framework import serializers

from .models import CropCategory, Listing
from .permissions import is_ops_admin

FARMER_SETTABLE_STATUSES = {
    Listing.Status.DRAFT,
    Listing.Status.ACTIVE,
    Listing.Status.PAUSED,
    Listing.Status.ARCHIVED,
}


class CropCategorySerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(required=False, max_length=120)

    class Meta:
        model = CropCategory
        fields = ('id', 'name', 'slug', 'description', 'is_active', 'created_at', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        if not self.instance and not attrs.get('slug'):
            attrs['slug'] = slugify(attrs.get('name', ''))
            if not attrs['slug']:
                raise serializers.ValidationError({'name': 'Name must contain letters or digits.'})
        return attrs


class ListingSerializer(serializers.ModelSerializer):
    category = serializers.PrimaryKeyRelatedField(
        queryset=CropCategory.objects.filter(is_active=True)
    )
    seller_name = serializers.SerializerMethodField()
    unit_price_minor = serializers.IntegerField(min_value=1)
    available_quantity = serializers.SerializerMethodField()

    class Meta:
        model = Listing
        fields = (
            'id', 'seller', 'seller_name', 'category', 'name', 'description',
            'unit_code', 'unit_price_minor', 'currency', 'status', 'available_quantity',
            'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'seller', 'currency', 'created_at', 'updated_at')

    def get_available_quantity(self, listing) -> str:
        # Never stored: derived from the stock ledger. Annotated rows (list/detail) avoid
        # per-row queries; objects without annotations (e.g. just created) fall back.
        if hasattr(listing, 'stock_on_hand'):
            available = listing.stock_on_hand - listing.stock_reserved
        else:
            from agrifi.inventory.services import listing_stock
            available = listing_stock(listing)['available']
        return f'{max(available, 0):.3f}'

    def get_seller_name(self, listing) -> str:
        profile = getattr(listing.seller, 'farmer_profile', None)
        return profile.display_name if profile else ''

    def validate_status(self, value):
        user = self.context['request'].user
        if is_ops_admin(user):
            return value
        if value not in FARMER_SETTABLE_STATUSES:
            raise serializers.ValidationError('You cannot set this status.')
        if self.instance is None and value not in (Listing.Status.DRAFT, Listing.Status.ACTIVE):
            raise serializers.ValidationError('New listings must start as draft or active.')
        if self.instance and self.instance.status == Listing.Status.ARCHIVED and value != self.instance.status:
            raise serializers.ValidationError('Archived listings cannot be reopened.')
        return value

    def validate(self, attrs):
        return attrs
