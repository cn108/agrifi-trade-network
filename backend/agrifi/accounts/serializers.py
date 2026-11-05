from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.serializers import TokenRefreshSerializer

from .managers import UserManager
from .models import BuyerProfile, FarmerProfile, User, UserRole
from .tokens import RevocableRefreshToken


class AuthenticatedUserSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'email', 'first_name', 'last_name', 'roles')

    def get_roles(self, user) -> list[str]:
        return list(user.roles.order_by('role').values_list('role', flat=True))


class RegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    password_confirm = serializers.CharField(write_only=True, trim_whitespace=False)
    role = serializers.ChoiceField(
        choices=(UserRole.Role.FARMER, UserRole.Role.BUYER),
        default=UserRole.Role.BUYER,
        write_only=True,
    )
    roles = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = (
            'id',
            'email',
            'password',
            'password_confirm',
            'first_name',
            'last_name',
            'role',
            'display_name',
            'business_name',
            'region',
            'roles',
        )
        read_only_fields = ('id',)
        # The model's unique validator would reveal existing emails; RegisterView handles them.
        extra_kwargs = {'email': {'validators': []}}

    display_name = serializers.CharField(max_length=150, required=False, write_only=True)
    business_name = serializers.CharField(max_length=200, required=False, write_only=True)
    region = serializers.CharField(
        max_length=100, required=False, allow_blank=True, write_only=True
    )

    def validate_email(self, value):
        try:
            return UserManager.normalize_email_address(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate(self, attrs):
        password = attrs.get('password')
        if password != attrs.get('password_confirm'):
            raise serializers.ValidationError({'password_confirm': 'Passwords do not match.'})
        role = attrs.get('role', UserRole.Role.BUYER)
        if role == UserRole.Role.FARMER and not attrs.get('display_name'):
            raise serializers.ValidationError({'display_name': 'This field is required for farmers.'})
        if role == UserRole.Role.BUYER and not attrs.get('business_name'):
            raise serializers.ValidationError({'business_name': 'This field is required for buyers.'})
        candidate = User(email=attrs.get('email', ''))
        try:
            validate_password(password, user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'password': list(exc.messages)}) from exc
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        role = validated_data.pop('role')
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        display_name = validated_data.pop('display_name', '')
        business_name = validated_data.pop('business_name', '')
        region = validated_data.pop('region', '')
        user = User.objects.create_user(password=password, **validated_data)
        UserRole.objects.create(user=user, role=role)
        if role == UserRole.Role.FARMER:
            FarmerProfile.objects.create(user=user, display_name=display_name, region=region)
        else:
            BuyerProfile.objects.create(user=user, business_name=business_name, region=region)
        return user

    def get_roles(self, user) -> list[str]:
        return list(user.roles.order_by('role').values_list('role', flat=True))


class UserProfileSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = ('id', 'email', 'first_name', 'last_name', 'roles', 'created_at', 'updated_at')
        read_only_fields = ('id', 'email', 'roles', 'created_at', 'updated_at')

    def get_roles(self, user) -> list[str]:
        return list(user.roles.order_by('role').values_list('role', flat=True))


class LoginSerializer(TokenObtainPairSerializer):
    token_class = RevocableRefreshToken

    def validate(self, attrs):
        data = super().validate(attrs)
        data['user'] = AuthenticatedUserSerializer(self.user).data
        return data


class RefreshSerializer(TokenRefreshSerializer):
    token_class = RevocableRefreshToken


class FarmerProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = FarmerProfile
        fields = (
            'id', 'display_name', 'region', 'location',
            'verification_status', 'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'verification_status', 'created_at', 'updated_at')


class BuyerProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = BuyerProfile
        fields = (
            'id', 'business_name', 'region', 'location',
            'verification_status', 'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'verification_status', 'created_at', 'updated_at')
