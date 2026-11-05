import json
import uuid
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import filters, generics, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from agrifi.accounts.models import UserRole
from agrifi.accounts.permissions import role_required
from agrifi.audit import services as audit
from agrifi.catalog.models import Listing
from agrifi.catalog.permissions import IsOperationsAdmin, is_ops_admin
from agrifi.idempotency import services as idempotency
from agrifi.idempotency.models import IdempotencyRecord
from agrifi.openapi import OpenApiTypes, extend_schema

from . import services as stock
from .models import HarvestBatch, StockMovement
from .serializers import (
    AllocationSerializer, HarvestBatchSerializer, RejectSerializer, StockMovementSerializer,
)

IsFarmer = role_required(UserRole.Role.FARMER, allow_superuser=False)
IsFarmerOrOpsAdmin = role_required(UserRole.Role.FARMER, UserRole.Role.OPERATIONS_ADMIN)

CREATE_SCOPE = 'harvest_batch.create'
ALLOCATION_SCOPE = 'listing.allocate'
DEALLOCATION_SCOPE = 'listing.deallocate'
D3 = Decimal('0.001')


class InventoryConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = 'conflict'


class InventoryBadRequest(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = 'invalid'


BAD_REQUEST_CODES = {'invalid_quantity', 'mismatch', 'owner_mismatch'}


def run_stock(function, *args, **kwargs):
    """Call a stock service, translating business-rule errors into API errors."""
    try:
        return function(*args, **kwargs)
    except stock.InventoryError as exc:
        if exc.code == 'forbidden':
            raise PermissionDenied({'code': exc.code, 'detail': exc.message})
        error = InventoryBadRequest if exc.code in BAD_REQUEST_CODES else InventoryConflict
        raise error({'code': exc.code, 'detail': exc.message})


def request_fingerprint(validated):
    """Fingerprint of the validated, canonicalised request; excludes owner and key."""
    payload = {
        'category': str(validated['category'].pk),
        'quantity': idempotency.normalize_decimal(validated['quantity']),
        'unit_code': validated['unit_code'],
        'harvested_on': validated['harvested_on'].isoformat(),
        'notes': validated.get('notes') or '',
    }
    # Only present for corrections, so fingerprints of ordinary requests are unchanged.
    if validated.get('resubmission_of') is not None:
        payload['resubmission_of'] = str(validated['resubmission_of'].pk)
    return idempotency.fingerprint(payload)


def lock_resubmission_target(validated):
    """Inside a transaction: lock the rejected original and refuse a second correction.
    The one-to-one constraint remains the authority; this gives a clean 409 and
    serialises concurrent corrections of the same original."""
    original = validated.get('resubmission_of')
    if original is None:
        return
    locked = HarvestBatch.objects.select_for_update().get(pk=original.pk)
    if locked.status != HarvestBatch.Status.REJECTED:
        raise InventoryConflict('Only rejected batches can be resubmitted.')
    if HarvestBatch.objects.filter(resubmission_of=locked).exists():
        raise InventoryConflict('This rejected batch has already been resubmitted.')


def json_safe(data):
    return json.loads(JSONRenderer().render(data))


class HarvestBatchViewSet(viewsets.ModelViewSet):
    """Harvest batches. Farmers create, read and edit only their own batches.
    Operations administrators have read-only access to all batches. Buyers and
    finance operators are denied. There is no delete.

    Creation with a `client_sync_id` is idempotent per (farmer, scope, key):

    * First request: the batch and an idempotency record are created in one
      transaction; the response is 201.
    * Identical retry: the originally stored response is returned with 200, even
      if the batch was edited or its category deactivated afterwards.
    * Same key with a different request: 409.

    The unique constraint on the idempotency record is authoritative, so concurrent
    requests with one key create at most one batch."""

    serializer_class = HarvestBatchSerializer
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    filter_backends = (filters.OrderingFilter,)
    ordering_fields = ('harvested_on', 'created_at', 'quantity')

    def get_permissions(self):
        if self.action in ('accept', 'reject'):
            return [IsAuthenticated(), IsOperationsAdmin()]
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated(), IsFarmerOrOpsAdmin()]
        return [IsAuthenticated(), IsFarmer()]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):  # schema generation has no user
            return HarvestBatch.objects.none()
        queryset = HarvestBatch.objects.select_related('category', 'correction')
        if not is_ops_admin(self.request.user):
            queryset = queryset.filter(farmer=self.request.user)
        return queryset

    def create(self, request, *args, **kwargs):
        # Phase 1: current-state-independent validation, so a replay can be recognised
        # before state rules (such as "category is active") are applied.
        serializer = self.get_serializer(
            data=request.data, context={**self.get_serializer_context(), 'enforce_current_state': False}
        )
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data
        key = validated.get('client_sync_id')

        if key is None:
            self.enforce_current_state(validated)
            with transaction.atomic():
                lock_resubmission_target(validated)
                serializer.save(farmer=request.user)
                self.audit_submission(request.user, serializer.instance)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        fingerprint = request_fingerprint(validated)
        existing = idempotency.find_record(request.user, CREATE_SCOPE, key)
        if existing is not None:
            return self.replay(existing, fingerprint)

        # Phase 2: current-state rules apply only to genuinely new operations.
        self.enforce_current_state(validated)
        batch_id = uuid.uuid4()
        try:
            with transaction.atomic():
                lock_resubmission_target(validated)
                # Record first: a concurrent loser then fails on the idempotency
                # constraint rather than on the batch's own constraint.
                record = IdempotencyRecord.objects.create(
                    owner=request.user,
                    scope=CREATE_SCOPE,
                    key=str(key),
                    request_fingerprint=fingerprint,
                    resource_type=HarvestBatch._meta.label_lower,
                    resource_id=batch_id,
                    response_status=status.HTTP_201_CREATED,
                )
                serializer.save(farmer=request.user, id=batch_id)
                self.audit_submission(request.user, serializer.instance)
                record.response_body = json_safe(serializer.data)
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
    def audit_submission(farmer, batch):
        audit.record('harvest_batch.submitted', farmer, batch, {
            'quantity': batch.quantity, 'resubmission_of': batch.resubmission_of_id,
        })

    def perform_update(self, serializer):
        # Re-check under a row lock so an edit cannot race with acceptance.
        with transaction.atomic():
            locked = HarvestBatch.objects.select_for_update().get(pk=serializer.instance.pk)
            if locked.status != HarvestBatch.Status.SUBMITTED:
                raise InventoryConflict('Only submitted batches can be edited.')
            serializer.save()

    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        """Accept a submitted batch: posts a RECEIPT stock movement. Operations admin only."""
        batch = get_object_or_404(self.get_queryset(), pk=pk)
        batch = run_stock(stock.accept_batch, batch.pk, request.user)
        return Response(self.get_serializer(batch).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Reject a submitted batch. Operations admin only."""
        batch = get_object_or_404(self.get_queryset(), pk=pk)
        body = RejectSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        batch = run_stock(stock.reject_batch, batch.pk, request.user, body.validated_data.get('reason', ''))
        return Response(self.get_serializer(batch).data)

    @staticmethod
    def enforce_current_state(validated):
        if not validated['category'].is_active:
            raise serializers.ValidationError({'category': ['This category is not active.']})

    @staticmethod
    def replay(record, fingerprint):
        return idempotency.replay_response(record, fingerprint)


def _listing_for(request, pk, *, seller_only):
    queryset = Listing.objects.all()
    if seller_only or not is_ops_admin(request.user):
        queryset = queryset.filter(seller=request.user)
    return get_object_or_404(queryset, pk=pk)


def _quantity_text(value):
    return format(value.quantize(D3), 'f')


class ListingStockView(APIView):
    """GET /listings/{id}/stock/ — on_hand, reserved and available, always computed from
    the stock ledger. Visible to the listing's seller and operations administrators."""

    permission_classes = [IsAuthenticated, IsFarmerOrOpsAdmin]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request, pk):
        listing = _listing_for(request, pk, seller_only=False)
        values = stock.listing_stock(listing)
        return Response({
            'listing': str(listing.pk), 'unit_code': listing.unit_code,
            **{key: _quantity_text(value) for key, value in values.items()},
        })


class ListingAllocationView(APIView):
    """POST /listings/{id}/allocate/ and /deallocate/ — move quantity between an accepted
    batch and the seller's own listing. Seller (farmer) only."""

    permission_classes = [IsAuthenticated, IsFarmer]
    operation = None

    @extend_schema(request=AllocationSerializer, responses={200: StockMovementSerializer, 201: StockMovementSerializer})
    def post(self, request, pk):
        listing = _listing_for(request, pk, seller_only=True)
        body = AllocationSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        validated = body.validated_data
        scope = ALLOCATION_SCOPE if self.operation is stock.allocate else DEALLOCATION_SCOPE
        key = validated['client_request_id']
        fingerprint = idempotency.fingerprint({
            'listing': str(listing.pk),
            'batch': str(validated['batch']),
            'quantity': idempotency.normalize_decimal(validated['quantity']),
        })
        existing = idempotency.find_record(request.user, scope, key)
        if existing is not None:
            return self.replay_movement(existing, fingerprint)

        movement_id = uuid.uuid4()
        try:
            with transaction.atomic():
                record = IdempotencyRecord.objects.create(
                    owner=request.user,
                    scope=scope,
                    key=str(key),
                    request_fingerprint=fingerprint,
                    resource_type=StockMovement._meta.label_lower,
                    resource_id=movement_id,
                    response_status=status.HTTP_201_CREATED,
                )
                batch = get_object_or_404(
                    HarvestBatch, pk=validated['batch'], farmer=request.user,
                )
                movement = run_stock(
                    self.operation, listing.pk, batch.pk, validated['quantity'], request.user,
                )
                record.resource_id = movement.pk
                record.response_body = json_safe(StockMovementSerializer(movement).data)
                record.save(update_fields=['resource_id', 'response_body'])
        except IntegrityError as exc:
            if not idempotency.is_idempotency_violation(exc):
                raise
            existing = idempotency.find_record(request.user, scope, key)
            if existing is None:
                raise
            return self.replay_movement(existing, fingerprint)
        return Response(record.response_body, status=status.HTTP_201_CREATED)

    @staticmethod
    def replay_movement(record, fingerprint):
        return idempotency.replay_response(record, fingerprint)


class AllocateView(ListingAllocationView):
    operation = staticmethod(stock.allocate)


class DeallocateView(ListingAllocationView):
    operation = staticmethod(stock.deallocate)


class StockMovementListView(generics.ListAPIView):
    """GET /stock-movements/ — read-only ledger. Farmers see movements of their own
    batches; operations administrators see all."""

    serializer_class = StockMovementSerializer
    permission_classes = [IsAuthenticated, IsFarmerOrOpsAdmin]

    def get_queryset(self):
        queryset = StockMovement.objects.all()
        if not is_ops_admin(self.request.user):
            queryset = queryset.filter(batch__farmer=self.request.user)
        return queryset
