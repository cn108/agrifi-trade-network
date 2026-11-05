import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import UserManager


class User(AbstractUser):
    username = None

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()

    def save(self, *args, **kwargs):
        if self.email:
            self.email = UserManager.normalize_email_address(self.email)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email


class UserRole(models.Model):
    class Role(models.TextChoices):
        FARMER = 'farmer', 'Farmer'
        BUYER = 'buyer', 'Buyer'
        OPERATIONS_ADMIN = 'operations_admin', 'Operations administrator'
        FINANCE_OPERATOR = 'finance_operator', 'Finance operator'
        SYSTEM = 'system', 'System'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='roles')
    role = models.CharField(max_length=32, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('user', 'role'), name='unique_user_role'),
        ]
        indexes = [
            models.Index(fields=('role', 'user'), name='accounts_role_user_idx'),
        ]

    def __str__(self):
        return f'{self.user.email}: {self.get_role_display()}'


class RevokedRefreshToken(models.Model):
    jti = models.CharField(max_length=255, unique=True)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='revoked_refresh_tokens',
    )
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=('expires_at',), name='accounts_revoked_exp_idx'),
        ]

    def __str__(self):
        return f'Revoked refresh token {self.jti}'


class VerificationStatus(models.TextChoices):
    UNVERIFIED = 'unverified', 'Unverified'
    PENDING = 'pending', 'Pending review'
    VERIFIED = 'verified', 'Verified'
    REJECTED = 'rejected', 'Rejected'


class FarmerProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='farmer_profile')
    display_name = models.CharField(max_length=150)
    region = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=200, blank=True)
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.UNVERIFIED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.display_name


class BuyerProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='buyer_profile')
    business_name = models.CharField(max_length=200)
    region = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=200, blank=True)
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.UNVERIFIED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.business_name
