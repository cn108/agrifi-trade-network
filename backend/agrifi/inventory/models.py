import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from agrifi.catalog.models import CropCategory, UnitCode


class HarvestBatch(models.Model):
    """A farmer's claim of physical supply. Stock only exists once an administrator
    accepts the batch (a RECEIPT StockMovement); see docs/ARCHITECTURE.md."""

    class Status(models.TextChoices):
        SUBMITTED = 'submitted', 'Submitted'
        ACCEPTED = 'accepted', 'Accepted'
        REJECTED = 'rejected', 'Rejected'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    farmer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='harvest_batches'
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUBMITTED)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='reviewed_harvest_batches',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    category = models.ForeignKey(
        CropCategory, on_delete=models.PROTECT, related_name='harvest_batches'
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_code = models.CharField(max_length=10, choices=UnitCode.choices)
    harvested_on = models.DateField()
    # Idempotency key for offline-first mobile sync, unique per farmer.
    client_sync_id = models.UUIDField(null=True, blank=True)
    # Link to the rejected submission this batch corrects. The rejected batch is never
    # mutated; the one-to-one makes "corrected at most once" a database guarantee.
    resubmission_of = models.OneToOneField(
        'self', null=True, blank=True, on_delete=models.PROTECT, related_name='correction',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-harvested_on', '-created_at')
        indexes = [models.Index(fields=['farmer', 'harvested_on'], name='batch_farmer_date_idx')]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name='batch_quantity_positive'),
            models.UniqueConstraint(
                fields=['farmer', 'client_sync_id'],
                condition=Q(client_sync_id__isnull=False),
                name='batch_farmer_sync_id_unique',
            ),
        ]

    def __str__(self):
        return f'{self.quantity} {self.unit_code} of {self.category} ({self.harvested_on})'


class ImmutableRecordError(Exception):
    pass


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ImmutableRecordError('Stock movements are immutable.')

    def delete(self):
        raise ImmutableRecordError('Stock movements are immutable.')

    def bulk_update(self, *args, **kwargs):
        raise ImmutableRecordError('Stock movements are immutable.')


class StockMovement(models.Model):
    """Append-only inventory ledger; the single source of truth for stock.
    Quantity is always positive; the movement type gives it direction."""

    class Type(models.TextChoices):
        RECEIPT = 'receipt', 'Receipt (batch accepted)'
        ALLOCATION = 'allocation', 'Allocation to listing'
        DEALLOCATION = 'deallocation', 'Return from listing'
        SALE = 'sale', 'Sale (reservation consumed)'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(HarvestBatch, on_delete=models.PROTECT, related_name='movements')
    listing = models.ForeignKey(
        'catalog.Listing', null=True, blank=True, on_delete=models.PROTECT,
        related_name='stock_movements',
    )
    movement_type = models.CharField(max_length=20, choices=Type.choices)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    reference = models.CharField(max_length=100, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        ordering = ('created_at', 'id')
        indexes = [
            models.Index(fields=['batch', 'movement_type'], name='move_batch_type_idx'),
            models.Index(fields=['listing', 'movement_type'], name='move_listing_type_idx'),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name='move_quantity_positive'),
            models.CheckConstraint(
                condition=(Q(movement_type='receipt', listing__isnull=True)
                           | (~Q(movement_type='receipt') & Q(listing__isnull=False))),
                name='move_listing_matches_type',
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError('Stock movements are immutable.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError('Stock movements are immutable.')


class Reservation(models.Model):
    """Temporary hold for pending orders; confirmed orders commit it by clearing its
    expiry. Active holds count against availability until release or consumption."""

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        RELEASED = 'released', 'Released'
        CONSUMED = 'consumed', 'Consumed'
        EXPIRED = 'expired', 'Expired'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    listing = models.ForeignKey(
        'catalog.Listing', on_delete=models.PROTECT, related_name='reservations'
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    expires_at = models.DateTimeField(null=True, blank=True)
    # Opaque pointer to the owning order (added in Phase 3).
    reference = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['listing', 'status', 'expires_at'], name='resv_listing_status_idx'),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name='resv_quantity_positive'),
        ]
