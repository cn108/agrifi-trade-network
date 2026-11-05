import json
import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from agrifi.accounts.models import UserRole
from agrifi.accounts.permissions import role_required, user_has_role
from agrifi.catalog.permissions import is_ops_admin
from agrifi.idempotency import services as idempotency
from agrifi.idempotency.models import IdempotencyRecord
from agrifi.openapi import OpenApiParameter, OpenApiTypes, extend_schema

from . import services
from .models import Journal, LedgerAccount, Refund, Settlement, SimulatedPayment
from .serializers import (
    CreatePaymentSerializer, CreateRefundSerializer, CreateSettlementSerializer,
    JournalSerializer, LedgerAccountSerializer, RefundSerializer, SettlementSerializer,
    SimulatedPaymentSerializer,
)

IsBuyer = role_required(UserRole.Role.BUYER, allow_superuser=False)
IsFinance = role_required(UserRole.Role.FINANCE_OPERATOR, UserRole.Role.OPERATIONS_ADMIN)


class FinanceApiError(APIException):
    def __init__(self, detail, http_status, code):
        self.status_code = http_status
        self.default_code = code
        super().__init__(detail, code=code)


class IsFinanceOrBuyer(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated
            and (
                is_ops_admin(user)
                or user_has_role(user, UserRole.Role.FINANCE_OPERATOR)
                or user_has_role(user, UserRole.Role.BUYER)
            )
        )


def _call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except services.FinanceError as exc:
        raise FinanceApiError(
            {'code': exc.code, 'detail': exc.message}, exc.status, exc.code,
        )


def _json_safe(data):
    return json.loads(JSONRenderer().render(data))


def _replay(record, fingerprint):
    return idempotency.replay_response(record, fingerprint)


def _idempotent_create(owner, scope, key, fingerprint, model, callback, serializer_class):
    existing = idempotency.find_record(owner, scope, key)
    if existing is not None:
        return _replay(existing, fingerprint)
    resource_id = uuid.uuid4()
    try:
        with transaction.atomic():
            record = IdempotencyRecord.objects.create(
                owner=owner, scope=scope, key=str(key), request_fingerprint=fingerprint,
                resource_type=model._meta.label_lower, resource_id=resource_id,
                response_status=status.HTTP_201_CREATED,
            )
            result = callback(resource_id)
            record.response_body = _json_safe(serializer_class(result).data)
            record.save(update_fields=['response_body'])
    except IntegrityError as exc:
        if not idempotency.is_idempotency_violation(exc):
            raise
        existing = idempotency.find_record(owner, scope, key)
        if existing is None:
            raise
        return _replay(existing, fingerprint)
    return Response(record.response_body, status=status.HTTP_201_CREATED)


class SimulatedPaymentViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Simulated only. No card/bank details are accepted; no money moves."""

    serializer_class = SimulatedPaymentSerializer
    http_method_names = ['get', 'post', 'head', 'options']

    def get_permissions(self):
        if self.action == 'create':
            return [IsAuthenticated(), IsBuyer()]
        return [IsAuthenticated(), IsFinanceOrBuyer()]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):  # schema generation has no user
            return SimulatedPayment.objects.none()
        queryset = SimulatedPayment.objects.select_related('order', 'buyer')
        if not (
            is_ops_admin(self.request.user)
            or user_has_role(self.request.user, UserRole.Role.FINANCE_OPERATOR)
        ):
            queryset = queryset.filter(buyer=self.request.user)
        return queryset

    def create(self, request, *args, **kwargs):
        body = CreatePaymentSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        fingerprint = idempotency.fingerprint({'order': str(data['order'])})
        return _idempotent_create(
            request.user, 'finance.payment.create', data['client_request_id'], fingerprint,
            SimulatedPayment,
            lambda payment_id: _call(
                services.create_simulated_payment, data['order'], request.user, payment_id,
            ),
            SimulatedPaymentSerializer,
        )


class SimulatedRefundViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Operations-approved refund record. It is not a payment-provider operation."""

    serializer_class = RefundSerializer
    permission_classes = [IsAuthenticated, IsFinance]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        return Refund.objects.select_related('payment', 'created_by', 'payment__order')

    def create(self, request, *args, **kwargs):
        body = CreateRefundSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        fingerprint = idempotency.fingerprint({
            'payment': str(data['payment']),
            'amount_minor': data['amount_minor'],
            'reason': data['reason'],
        })
        return _idempotent_create(
            request.user, 'finance.refund.create', data['client_request_id'], fingerprint,
            Refund,
            lambda refund_id: _call(
                services.create_simulated_refund, data['payment'], data['amount_minor'],
                data['reason'], request.user, refund_id,
            ),
            RefundSerializer,
        )


class SimulatedSettlementViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Simulated internal settlement record. Never initiates a bank transfer."""

    serializer_class = SettlementSerializer
    permission_classes = [IsAuthenticated, IsFinance]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        return Settlement.objects.select_related('payment', 'seller', 'payment__order')

    def create(self, request, *args, **kwargs):
        body = CreateSettlementSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        fingerprint = idempotency.fingerprint({'order': str(data['order'])})
        return _idempotent_create(
            request.user, 'finance.settlement.create', data['client_request_id'], fingerprint,
            Settlement,
            lambda settlement_id: _call(
                services.create_simulated_settlement, data['order'], request.user, settlement_id,
            ),
            SettlementSerializer,
        )


class JournalViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Read-only posted simulated journals and their balanced lines."""

    serializer_class = JournalSerializer
    permission_classes = [IsAuthenticated, IsFinance]
    http_method_names = ['get', 'head', 'options']

    def get_queryset(self):
        return Journal.objects.prefetch_related('lines__account')


class LedgerAccountViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Read-only chart of accounts with derived (never stored) balances."""

    serializer_class = LedgerAccountSerializer
    permission_classes = [IsAuthenticated, IsFinance]
    http_method_names = ['get', 'head', 'options']

    def get_queryset(self):
        return LedgerAccount.objects.all()


class FinanceReportView(APIView):
    """Read-only simulated finance report derived from the immutable journal.

    Optional `start` (inclusive) and `end` (exclusive) ISO-8601 datetimes."""

    permission_classes = [IsAuthenticated, IsFinance]

    @extend_schema(
        parameters=[
            OpenApiParameter('start', OpenApiTypes.DATETIME, description='Inclusive ISO 8601 start (with offset).'),
            OpenApiParameter('end', OpenApiTypes.DATETIME, description='Exclusive ISO 8601 end (with offset).'),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        bounds = {}
        for name in ('start', 'end'):
            raw = request.query_params.get(name)
            if raw is None:
                bounds[name] = None
                continue
            value = parse_datetime(raw)
            if value is None:
                raise ValidationError({name: 'Enter a valid ISO 8601 datetime.'})
            if timezone.is_naive(value):
                raise ValidationError({name: 'Include a timezone offset.'})
            bounds[name] = value
        if bounds['start'] and bounds['end'] and bounds['start'] >= bounds['end']:
            raise ValidationError({'end': 'end must be after start.'})
        return Response(services.build_report(bounds['start'], bounds['end']))
