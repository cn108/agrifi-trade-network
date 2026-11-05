from django.db import models
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Extended user model with role-based permissions."""
    is_admin = models.BooleanField(default=False)
    
    def __str__(self):
        return self.username


class Product(models.Model):
    """Product listing for farmers and buyers."""
    category = models.CharField(max_length=100, choices=[
        ('fruits', 'Fruits'),
        ('vegetables', 'Vegetables'),
        ('grains', 'Grains'),
        ('livestock', 'Livestock'),
        ('other', 'Other')
    ])
    
    product_name = models.CharField(max_length=200)
    description = models.TextField()
    
    # Farmer info
    farmer_name = models.CharField(max_length=100)
    farmer_location = models.CharField(max_length=200)
    farmer_contact = models.CharField(max_length=20)
    
    # Product details
    price_per_unit = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=50)  # kg, lbs, pieces, etc.
    quantity_available = models.PositiveIntegerField()
    
    # Quality & specifications
    quality_grade = models.CharField(max_length=50, default='A')
    harvest_date = models.DateField()
    expiry_date = models.DateField()
    
    # Images
    image_url = models.URLField(blank=True)
    
    # Status
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.product_name


class Order(models.Model):
    """Order for product purchases."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('processing', 'Processing'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled')
    ]
    
    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    
    quantity_ordered = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    order_date = models.DateTimeField(auto_now_add=True)
    delivery_address = models.TextField()
    estimated_delivery = models.DateField()
    
    def __str__(self):
        return f"Order #{self.id} - {self.product.product_name}"


class Payment(models.Model):
    """Payment transaction records."""
    PAYMENT_METHOD_CHOICES = [
        ('card', 'Credit/Debit Card'),
        ('upi', 'UPI'),
        ('bank_transfer', 'Bank Transfer'),
        ('wallet', 'Digital Wallet')
    ]
    
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='payments')
    
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    transaction_id = models.CharField(max_length=100, unique=True)
    
    status = models.CharField(max_length=20, default='pending')  # pending, completed, failed
    
    payment_date = models.DateTimeField()
    
    def __str__(self):
        return f"Payment #{self.id} - {self.transaction_id}"


class Review(models.Model):
    """Product reviews and ratings."""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='reviews')
    rating = models.PositiveSmallIntegerField()  # 1-5 stars
    
    review_text = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Review #{self.id} - {self.rating} stars"


class AnalyticsData(models.Model):
    """Analytics and insights data."""
    date = models.DateField()
    
    total_products = models.PositiveIntegerField()
    total_orders = models.PositiveIntegerField(default=0)
    revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Category breakdown
    category_breakdown = models.JSONField(blank=True)  # {'fruits': 50, 'vegetables': 30, ...}
    
    created_at = models.DateTimeField(auto_now_add=True)


class Notification(models.Model):
    """User notifications."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    type = models.CharField(max_length=50, choices=[
        ('order_status', 'Order Status'),
        ('payment_received', 'Payment Received'),
        ('new_product', 'New Product'),
        ('message', 'Message')
    ])
    
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Notification for {self.user.username}"
