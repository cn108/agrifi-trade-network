import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class ImmutableRowError(Exception):
    pass


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ImmutableRowError('These records are immutable.')

    def delete(self):
        raise ImmutableRowError('These records are immutable.')

    def bulk_update(self, *args, **kwargs):
        raise ImmutableRowError('These records are immutable.')


class ImmutableModel(models.Model):
    """Append-only rows. Also enforced in PostgreSQL by triggers (orders/0002)."""

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRowError('These records are immutable.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRowError('These records are immutable.')


class Order(models.Model):
    """A single-seller order. Status changes only through orders.services.transition."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending seller confirmation'
        CONFIRMED = 'confirmed', 'Confirmed'
        SHIPPED = 'shipped', 'Shipped'
        DELIVERED = 'delivered', 'Delivered'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'
        DISPUTED = 'disputed', 'Disputed'
        DISPUTE_RESOLVED = 'dispute_resolved', 'Dispute resolved'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='orders_as_buyer'
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='orders_as_seller'
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    currency = models.CharField(max_length=3, default='NGN', editable=False)
    # Integer kobo, always computed on the server from the item snapshots.
    total_minor = models.BigIntegerField()
    delivery_address = models.TextField()
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['buyer', 'status'], name='order_buyer_status_idx'),
            models.Index(fields=['seller', 'status'], name='order_seller_status_idx'),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(total_minor__gt=0), name='order_total_positive'),
            models.CheckConstraint(condition=~Q(buyer=F('seller')), name='order_buyer_not_seller'),
        ]

    def __str__(self):
        return f'Order {self.id}'


class OrderItem(ImmutableModel):
    """Immutable snapshot of what was bought, at what price, from whom."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name='items')
    listing = models.ForeignKey(
        'catalog.Listing', on_delete=models.PROTECT, related_name='order_items'
    )
    reservation = models.OneToOneField(
        'inventory.Reservation', on_delete=models.PROTECT, related_name='order_item'
    )
    # Snapshots: later listing edits must never change historical orders.
    listing_name = models.CharField(max_length=150)
    category_name = models.CharField(max_length=100)
    seller_name = models.CharField(max_length=150, blank=True)
    unit_code = models.CharField(max_length=10)
    unit_price_minor = models.BigIntegerField()
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    line_total_minor = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('created_at', 'id')
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name='orderitem_quantity_positive'),
            models.CheckConstraint(
                condition=Q(unit_price_minor__gt=0), name='orderitem_price_positive'
            ),
            models.CheckConstraint(
                condition=Q(line_total_minor__gt=0), name='orderitem_line_total_positive'
            ),
        ]


class OrderStatusHistory(ImmutableModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name='history')
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+'
    )
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('created_at', 'id')
        verbose_name_plural = 'order status history'


class Dispute(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        RESOLVED = 'resolved', 'Resolved'

    class Outcome(models.TextChoices):
        BUYER_FAVOURED = 'buyer_favoured', 'Buyer favoured'
        SELLER_FAVOURED = 'seller_favoured', 'Seller favoured'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name='disputes')
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='disputes_opened'
    )
    reason = models.TextField()
    previous_order_status = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    outcome = models.CharField(max_length=20, choices=Outcome.choices, blank=True)
    resolution_notes = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='disputes_resolved',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            # At most one open dispute per order.
            models.UniqueConstraint(
                fields=['order'], condition=Q(status='open'), name='dispute_one_open_per_order'
            ),
        ]
