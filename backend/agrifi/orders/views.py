import json
import uuid

from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from agrifi.accounts.models import UserRole
from agrifi.accounts.permissions import role_required
from agrifi.catalog.permissions import is_ops_admin
from agrifi.idempotency import services as idempotency
from agrifi.idempotency.models import IdempotencyRecord
from agrifi.inventory import services as stock

from . import services
from .models import Dispute, Order
from .serializers import (
    CreateOrderSerializer, DisputeSerializer, OpenDisputeSerializer, OrderSerializer,
    ReasonSerializer, ResolveDisputeSerializer,
)

IsBuyer = role_required(UserRole.Role.BUYER, allow_superuser=False)
IsOrderParticipant = role_required(
    UserRole.Role.BUYER, UserRole.Role.FARMER, UserRole.Role.OPERATIONS_ADMIN
)
CREATE_SCOPE = 'order.create'
S = Order.Status


class ApiConflict(APIException):
    status_code = status.HTTP_409_CONFLICT


class ApiBadRequest(APIException):
    status_code = status.HTTP_400_BAD_REQUEST


class ApiForbidden(APIException):
    status_code = status.HTTP_403_FORBIDDEN


def run(function, *args, **kwargs):
    """Call a service, translating business-rule errors into API errors."""
    try:
        return function(*args, **kwargs)
    except (services.OrderError, stock.InventoryError) as exc:
        http = getattr(exc, 'status', None)
        if http is None:  # InventoryError
            http = 400 if exc.code in ('invalid_quantity', 'mismatch', 'owner_mismatch') else 409
        error = {400: ApiBadRequest, 403: ApiForbidden}.get(http, ApiConflict)
        raise error({'code': exc.code, 'detail': exc.message})


def request_fingerprint(data):
    return idempotency.fingerprint({
        'items': sorted(
            (str(item['listing']), idempotency.normalize_decimal(item['quantity']))
            for item in data['items']
        ),
        'delivery_address': data['delivery_address'],
        'notes': data.get('notes') or '',
    })


def json_safe(data):
    return json.loads(JSONRenderer().render(data))


class OrderViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                   viewsets.GenericViewSet):
    """Orders (single seller, server-priced).

    * `POST /orders/` (buyers): body `client_request_id`, `items[{listing, quantity}]`,
      `delivery_address`, `notes`. Prices and totals are computed on the server; stock is
      reserved atomically. Idempotent on `client_request_id`: the first call returns 201,
      an identical retry returns the stored response with 200, a different payload 409.
    * `GET /orders/`, `GET /orders/{id}/`: buyer and seller see their own orders,
      operations administrators see all; everyone else gets 404 (or 403 by role).
    * Actions: `confirm`, `ship`, `deliver` (seller), `complete` (buyer), `cancel`
      (pending only; buyer, seller or operations administrator), `dispute` (buyer).
    Transitions are explicit; see `agrifi.orders.services.TRANSITIONS`."""

    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated, IsOrderParticipant]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_permissions(self):
        if self.action == 'create':
            return [IsAuthenticated(), IsBuyer()]
        return [IsAuthenticated(), IsOrderParticipant()]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):  # schema generation has no user
            return Order.objects.none()
        queryset = Order.objects.prefetch_related('items', 'history')
        user = self.request.user
        if not is_ops_admin(user):
            queryset = queryset.filter(Q(buyer=user) | Q(seller=user))
        return queryset

    def create(self, request, *args, **kwargs):
        body = CreateOrderSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        key = data['client_request_id']
        fingerprint = request_fingerprint(data)

        existing = idempotency.find_record(request.user, CREATE_SCOPE, key)
        if existing is not None:
            return self.replay(existing, fingerprint)

        order_id = uuid.uuid4()
        items = [{'listing': i['listing'], 'quantity': i['quantity']} for i in data['items']]
        try:
            with transaction.atomic():
                # Record first so a concurrent loser fails on the idempotency constraint.
                record = IdempotencyRecord.objects.create(
                    owner=request.user, scope=CREATE_SCOPE, key=str(key),
                    request_fingerprint=fingerprint, resource_type=Order._meta.label_lower,
                    resource_id=order_id, response_status=status.HTTP_201_CREATED,
                )
                order = run(
                    services.create_order, request.user, items, data['delivery_address'],
                    data['notes'], order_id=order_id,
                )
                order = self.get_queryset().get(pk=order.pk)
                record.response_body = json_safe(OrderSerializer(order).data)
                record.save(update_fields=['response_body'])
        except IntegrityError as exc:
            if not idempotency.is_idempotency_violation(exc):
                raise
            existing = idempotency.find_record(request.user, CREATE_SCOPE, key)
            if existing is None:
                raise
            return self.replay(existing, fingerprint)
        return Response(record.response_body, status=status.HTTP_201_CREATED)

    @staticmethod
    def replay(record, fingerprint):
        return idempotency.replay_response(record, fingerprint)

    def _transition(self, request, pk, to_status, with_reason=False):
        order = self.get_object()
        reason = ''
        if with_reason:
            body = ReasonSerializer(data=request.data)
            body.is_valid(raise_exception=True)
            reason = body.validated_data['reason']
        run(services.transition, order.pk, to_status, request.user, reason)
        return Response(OrderSerializer(self.get_queryset().get(pk=order.pk)).data)

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """Seller accepts the order; reserved stock becomes sold (SALE movements)."""
        return self._transition(request, pk, S.CONFIRMED)

    @action(detail=True, methods=['post'])
    def ship(self, request, pk=None):
        return self._transition(request, pk, S.SHIPPED)

    @action(detail=True, methods=['post'])
    def deliver(self, request, pk=None):
        return self._transition(request, pk, S.DELIVERED)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        """Buyer acknowledges delivery."""
        return self._transition(request, pk, S.COMPLETED)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel a pending order and release its stock reservations."""
        return self._transition(request, pk, S.CANCELLED, with_reason=True)

    @action(detail=True, methods=['post'])
    def dispute(self, request, pk=None):
        """Buyer opens a dispute on a confirmed, shipped or delivered order."""
        order = self.get_object()
        body = OpenDisputeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        dispute = run(services.open_dispute, order.pk, request.user, body.validated_data['reason'])
        return Response(DisputeSerializer(dispute).data, status=status.HTTP_201_CREATED)


class DisputeViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Disputes. Visible to the order's buyer and seller and to operations administrators;
    only operations administrators resolve them."""

    serializer_class = DisputeSerializer
    permission_classes = [IsAuthenticated, IsOrderParticipant]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):  # schema generation has no user
            return Dispute.objects.none()
        queryset = Dispute.objects.all()
        user = self.request.user
        if not is_ops_admin(user):
            queryset = queryset.filter(Q(order__buyer=user) | Q(order__seller=user))
        return queryset

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        dispute = self.get_object()
        body = ResolveDisputeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        dispute = run(
            services.resolve_dispute, dispute.pk, request.user,
            body.validated_data['outcome'], body.validated_data['notes'],
        )
        return Response(DisputeSerializer(dispute).data)
