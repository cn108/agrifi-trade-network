import logging
import uuid

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.middleware.csrf import CsrfViewMiddleware, get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import generics, serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from agrifi.audit import services as audit
from agrifi.openapi import OpenApiTypes, extend_schema
from agrifi.request_context import get_request_id
from agrifi.throttles import AnonymousAuthThrottle, LoginEmailThrottle

from .models import BuyerProfile, FarmerProfile, User, UserRole
from .permissions import role_required
from .serializers import (
    BuyerProfileSerializer,
    FarmerProfileSerializer,
    LoginSerializer,
    RefreshSerializer,
    RegistrationSerializer,
    UserProfileSerializer,
)
from .tokens import RevocableRefreshToken


COOKIE_TRANSPORT_VALUE = 'cookie'
logger = logging.getLogger('agrifi.accounts')


def _is_cookie_transport(request):
    return request.data.get('token_transport') == COOKIE_TRANSPORT_VALUE


def _csrf_failure(request):
    http_request = getattr(request, '_request', request)
    middleware = CsrfViewMiddleware(lambda req: None)
    response = middleware.process_view(http_request, lambda req: None, (), {})
    if response is not None:
        return JsonResponse({'detail': 'CSRF validation failed.'}, status=status.HTTP_403_FORBIDDEN)
    return None


def _set_refresh_cookie(response, refresh_token):
    response.set_cookie(
        settings.JWT_REFRESH_COOKIE_NAME,
        str(refresh_token),
        max_age=settings.JWT_REFRESH_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.JWT_REFRESH_COOKIE_SECURE,
        samesite=settings.JWT_REFRESH_COOKIE_SAMESITE,
        path=settings.JWT_REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response):
    response.delete_cookie(
        settings.JWT_REFRESH_COOKIE_NAME,
        path=settings.JWT_REFRESH_COOKIE_PATH,
        samesite=settings.JWT_REFRESH_COOKIE_SAMESITE,
    )


@ensure_csrf_cookie
def csrf_cookie(request):
    return JsonResponse({'csrfToken': get_token(request)})


class RegisterView(generics.CreateAPIView):
    """Registration answers identically whether or not the email is already registered, so
    the endpoint cannot be used to discover which emails have accounts. No account is
    created for an existing email and the existing account is never modified."""

    serializer_class = RegistrationSerializer
    permission_classes = (AllowAny,)
    throttle_classes = (AnonymousAuthThrottle,)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        if User.objects.filter(email__iexact=email).exists():
            return self._existing_account_response(serializer, request)
        try:
            with transaction.atomic():
                user = serializer.save()
                audit.record('auth.registered', user, user, {'role': serializer.validated_data.get('role')})
        except IntegrityError:
            # A concurrent registration for the same email won the unique constraint.
            return self._existing_account_response(serializer, request)
        return Response(self.get_serializer(user).data, status=status.HTTP_201_CREATED)

    def _existing_account_response(self, serializer, request):
        # Spend the same hashing time as a real registration.
        make_password(serializer.validated_data['password'])
        logger.info('registration for an existing email ignored', extra={'request_id': get_request_id()})
        return Response(
            {
                'id': str(uuid.uuid4()),
                'email': serializer.validated_data['email'],
                'first_name': serializer.validated_data.get('first_name', ''),
                'last_name': serializer.validated_data.get('last_name', ''),
                'roles': [serializer.validated_data.get('role', UserRole.Role.BUYER)],
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    throttle_classes = (AnonymousAuthThrottle, LoginEmailThrottle)

    def post(self, request, *args, **kwargs):
        cookie_transport = _is_cookie_transport(request)
        if cookie_transport:
            csrf_response = _csrf_failure(request)
            if csrf_response is not None:
                return csrf_response

        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except AuthenticationFailed:
            audit.record('auth.login_failed', metadata={
                'email_hash': audit.hash_identifier(request.data.get('email', '')),
            })
            raise
        audit.record('auth.login_succeeded', serializer.user, serializer.user)
        token_data = dict(serializer.validated_data)
        response = Response(token_data, status=status.HTTP_200_OK)
        if cookie_transport:
            refresh = token_data.pop('refresh')
            response.data = token_data
            _set_refresh_cookie(response, refresh)
        return response


class RefreshView(TokenRefreshView):
    serializer_class = RefreshSerializer
    throttle_classes = (AnonymousAuthThrottle,)

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        cookie_transport = _is_cookie_transport(request)
        if cookie_transport:
            csrf_response = _csrf_failure(request)
            if csrf_response is not None:
                return csrf_response
            refresh = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)
            if not refresh:
                raise serializers.ValidationError({'refresh': 'Refresh cookie is missing.'})
            data = {'refresh': refresh}
        else:
            data = request.data

        serializer = self.get_serializer(data=data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            raise InvalidToken(exc.args[0]) from exc
        token_data = dict(serializer.validated_data)
        response = Response(token_data, status=status.HTTP_200_OK)
        if cookie_transport:
            refresh = token_data.pop('refresh', None)
            response.data = token_data
            if refresh:
                _set_refresh_cookie(response, refresh)
        return response


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()

    def validate_refresh(self, value):
        try:
            return RevocableRefreshToken(value)
        except TokenError as exc:
            raise serializers.ValidationError('Invalid or revoked refresh token.') from exc


class LogoutView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(request=LogoutSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        cookie_transport = _is_cookie_transport(request)
        if cookie_transport:
            csrf_response = _csrf_failure(request)
            if csrf_response is not None:
                return csrf_response
            refresh = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)
            if not refresh:
                raise serializers.ValidationError({'refresh': 'Refresh cookie is missing.'})
            data = {'refresh': refresh}
        else:
            data = request.data

        serializer = LogoutSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        refresh_token = serializer.validated_data['refresh']
        if str(refresh_token.get('user_id')) != str(request.user.pk):
            return Response(
                {'detail': 'The refresh token does not belong to the authenticated user.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        refresh_token.blacklist()
        audit.record('auth.logout', request.user, request.user)
        response = Response({'detail': 'Refresh token revoked.'}, status=status.HTTP_200_OK)
        if cookie_transport:
            _clear_refresh_cookie(response)
        return response


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserProfileSerializer
    permission_classes = (IsAuthenticated,)

    def get_object(self):
        return self.request.user


class FarmerProfileMeView(generics.RetrieveUpdateAPIView):
    """Caller's own farmer profile. Verification status is read-only."""

    serializer_class = FarmerProfileSerializer
    permission_classes = (IsAuthenticated, role_required(UserRole.Role.FARMER, allow_superuser=False))
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_object(self):
        return generics.get_object_or_404(FarmerProfile, user=self.request.user)


class BuyerProfileMeView(generics.RetrieveUpdateAPIView):
    """Caller's own buyer profile. Verification status is read-only."""

    serializer_class = BuyerProfileSerializer
    permission_classes = (IsAuthenticated, role_required(UserRole.Role.BUYER, allow_superuser=False))
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_object(self):
        return generics.get_object_or_404(BuyerProfile, user=self.request.user)
