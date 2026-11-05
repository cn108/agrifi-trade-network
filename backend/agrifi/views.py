from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Sum, Count, Avg, Q
from django.shortcuts import get_object_or_404

from .models import User, Product, Order, Payment, Review, AnalyticsData, Notification
from .serializers import (
    UserSerializer, ProductSerializer, OrderSerializer, PaymentSerializer,
    ReviewSerializer, AnalyticsDataSerializer, NotificationSerializer,
    ProductCreateSerializer, OrderCreateSerializer
)


class ProductViewSet(viewsets.ModelViewSet):
    """API endpoint for product listings and management."""
    
    queryset = Product.objects.filter(is_available=True).order_by('-created_at')
    serializer_class = ProductSerializer
    permission_classes = ()  # Add proper authentication later
    
    def get_permissions(self):
        if self.action == 'list':
            return [AllowAny()]
        elif self.action in ['create', 'retrieve']:
            return [AllowAny()]
        return []
    
    @action(detail=True, methods=['get'])
    def orders(self, request, pk=None):
        """Get all orders for this product."""
        product = self.get_object()
        orders = Order.objects.filter(product=product).select_related('buyer').prefetch_related(
            'payments__order'
        )
        serializer = OrderSerializer(orders, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def by_category(self, request):
        """Get products filtered by category."""
        category = request.query_params.get('category', None)
        if not category:
            return Response({'error': 'Category parameter required'}, status=status.HTTP_400_BAD_REQUEST)
        
        products = Product.objects.filter(
            is_available=True,
            category=category
        ).order_by('-created_at')
        serializer = ProductSerializer(products, many=True)
        return Response(serializer.data)


class OrderViewSet(viewsets.ModelViewSet):
    """API endpoint for orders."""
    
    queryset = Order.objects.select_related('buyer', 'product').prefetch_related(
        'payments'
    ).order_by('-created_at')
    serializer_class = OrderSerializer
    permission_classes = ()
    
    def get_permissions(self):
        if self.action == 'list':
            return [AllowAny()]
        elif self.action in ['create', 'retrieve']:
            return [AllowAny()]
        return []
    
    @action(detail=True, methods=['get'])
    def payments(self, request, pk=None):
        """Get all payments for this order."""
        order = self.get_object()
        payments = Payment.objects.filter(order=order)
        serializer = PaymentSerializer(payments, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def create_order(self, request):
        """Create a new order."""
        serializer = OrderCreateSerializer(data=request.data)
        if serializer.is_valid():
            order = serializer.save()
            # Auto-create payment record
            Payment.objects.create(
                order=order,
                amount=order.quantity_ordered * order.unit_price,
                payment_method='wallet',
                transaction_id=f"ORD{order.id}PAY",
                status='completed',
                payment_date=order.estimated_delivery
            )
            return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PaymentViewSet(viewsets.ModelViewSet):
    """API endpoint for payments."""
    
    queryset = Payment.objects.select_related('order').order_by('-payment_date')
    serializer_class = PaymentSerializer
    permission_classes = ()
    
    def get_permissions(self):
        if self.action == 'list':
            return [AllowAny()]
        elif self.action in ['create', 'retrieve']:
            return [AllowAny()]
        return []


class ReviewViewSet(viewsets.ModelViewSet):
    """API endpoint for product reviews."""
    
    queryset = Review.objects.select_related('order__product').order_by('-created_at')
    serializer_class = ReviewSerializer
    permission_classes = ()
    
    def get_permissions(self):
        if self.action == 'list':
            return [AllowAny()]
        elif self.action in ['create', 'retrieve']:
            return [AllowAny()]
        return []


class AnalyticsViewSet(viewsets.ViewSet):
    """API endpoint for analytics data."""
    
    permission_classes = ()
    
    @action(detail=False, methods=['get'])
    def daily(self, request):
        """Get daily analytics."""
        days = request.query_params.get('days', '7')
        try:
            days = int(days)
        except ValueError:
            return Response({'error': 'Invalid days parameter'}, status=status.HTTP_400_BAD_REQUEST)
        
        end_date = AnalyticsData.objects.latest('date').date if AnalyticsData.objects.exists() else None
        start_date = (end_date - __import__('datetime').timedelta(days=days)).date() if end_date else None
        
        analytics = AnalyticsData.objects.filter(date__range=[start_date, end_date])\
            .order_by('date')\
            .annotate(
                total_revenue=Sum('revenue'),
                avg_rating=Avg('rating')
            )
        
        serializer = AnalyticsDataSerializer(analytics, many=True)
        return Response(serializer.data)


class NotificationViewSet(viewsets.ModelViewSet):
    """API endpoint for user notifications."""
    
    queryset = Notification.objects.all().order_by('-created_at')
    serializer_class = NotificationSerializer
    permission_classes = ()