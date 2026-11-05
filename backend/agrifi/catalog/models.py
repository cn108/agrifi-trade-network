import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class UnitCode(models.TextChoices):
    KILOGRAM = 'kg', 'Kilogram'
    TONNE = 'tonne', 'Tonne'
    BAG = 'bag', 'Bag'
    CRATE = 'crate', 'Crate'
    PIECE = 'piece', 'Piece'


class CropCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('name',)
        verbose_name_plural = 'crop categories'

    def __str__(self):
        return self.name


class Listing(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        ACTIVE = 'active', 'Active'
        PAUSED = 'paused', 'Paused'
        SUSPENDED = 'suspended', 'Suspended by administrator'
        ARCHIVED = 'archived', 'Archived'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='listings'
    )
    category = models.ForeignKey(
        CropCategory, on_delete=models.PROTECT, related_name='listings'
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    unit_code = models.CharField(max_length=10, choices=UnitCode.choices)
    # Integer minor units (kobo) per the spec; never floats.
    unit_price_minor = models.BigIntegerField()
    currency = models.CharField(max_length=3, default='NGN', editable=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['status', 'category'], name='listing_status_category_idx'),
            models.Index(fields=['seller', 'status'], name='listing_seller_status_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(unit_price_minor__gt=0), name='listing_unit_price_positive'
            ),
        ]

    def __str__(self):
        return self.name
