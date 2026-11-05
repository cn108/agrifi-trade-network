from rest_framework import serializers
from .models import User, Product, Order, Payment, Review, AnalyticsData, Notification


class UserSerializer(serializers.ModelSerializer):
    """Extended user serializer with role info."""
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'is_admin']
        read_only_fields = ['is_admin']


class ProductSerializer(serializers.ModelSerializer):
    """Product listing serializer."""
    
    class Meta:
        model = Product
        fields = [
            'id', 'category', 'product_name', 'description',
            'farmer_name', 'farmer_location', 'farmer_contact',
            'price_per_unit', 'unit', 'quantity_available',
            'quality_grade', 'harvest_date', 'expiry_date',
            'image_url', 'is_available', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class OrderSerializer(serializers.ModelSerializer):
    """Order serializer with related product info."""
    
    product_name = serializers.CharField(source='product.product_name', read_only=True)
    product_category = serializers.CharField(source='product.category', read_only=True)
    farmer_name = serializers.CharField(source='product.farmer_name', read_only=True)
    
    class Meta:
        model = Order
        fields = [
            'id', 'buyer', 'product', 'product_name', 'product_category',
            'farmer_name', 'quantity_ordered', 'unit_price', 'status',
            'order_date', 'delivery_address', 'estimated_delivery'
        ]
        read_only_fields = ['id']


class PaymentSerializer(serializers.ModelSerializer):
    """Payment transaction serializer."""
    
    order_id = serializers.IntegerField(source='order.id', read_only=True)
    
    class Meta:
        model = Payment
        fields = [
            'id', 'order', 'order_id', 'amount', 'payment_method',
            'transaction_id', 'status', 'payment_date'
        ]
        read_only_fields = ['id']


class ReviewSerializer(serializers.ModelSerializer):
    """Product review serializer."""
    
    order_id = serializers.IntegerField(source='order.id', read_only=True)
    product_name = serializers.CharField(source='order.product.product_name', read_only=True)
    
    class Meta:
        model = Review
        fields = ['id', 'order', 'order_id', 'product_name', 'rating', 'review_text', 'created_at']
        read_only_fields = ['id', 'created_at']


class AnalyticsDataSerializer(serializers.ModelSerializer):
    """Analytics data serializer."""
    
    class Meta:
        model = AnalyticsData
        fields = [
            'date', 'total_products', 'total_orders', 'revenue',
            'category_breakdown', 'created_at'
        ]
        read_only_fields = ['created_at']


class NotificationSerializer(serializers.ModelSerializer):
    """User notification serializer."""
    
    class Meta:
        model = Notification
        fields = [
            'id', 'user', 'message', 'type', 'is_read', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class ProductCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating products."""
    
    class Meta:
        model = Product
        fields = [
            'category', 'product_name', 'description',
            'farmer_name', 'farmer_location', 'farmer_contact',
            'price_per_unit', 'unit', 'quantity_available',
            'quality_grade', 'harvest_date', 'expiry_date',
            'image_url'
        ]


class OrderCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating orders."""
    
    class Meta:
        model = Order
        fields = [
            'product', 'quantity_ordered', 'delivery_address', 'estimated_delivery'
        ]