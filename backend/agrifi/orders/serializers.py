from decimal import Decimal

from rest_framework import serializers

from .models import Dispute, Order, OrderItem, OrderStatusHistory


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = (
            'id', 'listing', 'listing_name', 'category_name', 'seller_name', 'unit_code',
            'unit_price_minor', 'quantity', 'line_total_minor',
        )
        read_only_fields = fields


class OrderHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderStatusHistory
        fields = ('from_status', 'to_status', 'actor', 'reason', 'created_at')
        read_only_fields = fields


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    history = OrderHistorySerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = (
            'id', 'buyer', 'seller', 'status', 'currency', 'total_minor', 'delivery_address',
            'notes', 'items', 'history', 'created_at', 'updated_at',
        )
        read_only_fields = fields


class OrderItemInputSerializer(serializers.Serializer):
    listing = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal('0.001'))


class CreateOrderSerializer(serializers.Serializer):
    """Client input for checkout. No prices, totals, seller or buyer are accepted."""

    client_request_id = serializers.UUIDField()
    items = OrderItemInputSerializer(many=True, allow_empty=False, max_length=50)
    delivery_address = serializers.CharField(max_length=1000)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=1000, default='')


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000, default='')


class DisputeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dispute
        fields = (
            'id', 'order', 'opened_by', 'reason', 'previous_order_status', 'status', 'outcome',
            'resolution_notes', 'resolved_by', 'created_at', 'resolved_at',
        )
        read_only_fields = fields


class OpenDisputeSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=2000)


class ResolveDisputeSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=Dispute.Outcome.choices)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000, default='')
