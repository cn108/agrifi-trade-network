from decimal import Decimal

from rest_framework import serializers

from agrifi.catalog.models import CropCategory

from .models import HarvestBatch, StockMovement


class StockMovementSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockMovement
        fields = ('id', 'batch', 'listing', 'movement_type', 'quantity', 'reference', 'created_at')
        read_only_fields = fields


class AllocationSerializer(serializers.Serializer):
    batch = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal('0.001'))
    client_request_id = serializers.UUIDField()


class RejectSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class HarvestBatchSerializer(serializers.ModelSerializer):
    # Syntactic validation only; whether the category is currently active is a
    # current-state rule applied by validate_category so that replays of an
    # already-successful request can be recognised first (see the view).
    category = serializers.PrimaryKeyRelatedField(queryset=CropCategory.objects.all())
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal('0.001'))
    resubmission_of = serializers.PrimaryKeyRelatedField(
        queryset=HarvestBatch.objects.all(), required=False, allow_null=True,
    )
    correction_id = serializers.SerializerMethodField()

    class Meta:
        model = HarvestBatch
        fields = (
            'id', 'farmer', 'status', 'reviewed_at', 'rejection_reason', 'category', 'quantity',
            'unit_code', 'harvested_on', 'client_sync_id', 'resubmission_of', 'correction_id',
            'notes', 'created_at', 'updated_at',
        )
        read_only_fields = (
            'id', 'farmer', 'status', 'reviewed_at', 'rejection_reason', 'created_at', 'updated_at',
        )

    def get_correction_id(self, batch) -> str | None:
        correction = getattr(batch, 'correction', None)
        return str(correction.pk) if correction else None

    def validate_resubmission_of(self, value):
        if value is None:
            return value
        if self.instance is not None:
            raise serializers.ValidationError('resubmission_of cannot be changed after creation.')
        request = self.context['request']
        # Same message for "not yours" and "does not exist" so ids cannot be probed.
        if value.farmer_id != request.user.pk or value.status != HarvestBatch.Status.REJECTED:
            raise serializers.ValidationError('Only your own rejected batches can be resubmitted.')
        return value

    def validate_category(self, value):
        if self.context.get('enforce_current_state', True) and not value.is_active:
            raise serializers.ValidationError('This category is not active.')
        return value

    def validate_client_sync_id(self, value):
        if self.instance and value != self.instance.client_sync_id:
            raise serializers.ValidationError('client_sync_id cannot be changed.')
        return value
