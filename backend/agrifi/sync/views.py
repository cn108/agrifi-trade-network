"""Generic sync-operation API for the offline clients.

A thin envelope over the existing idempotent workflows. There is deliberately no second
table: a receipt is derived from the `IdempotencyRecord` written by the business
operation in the same transaction, so the receipt cannot disagree with the data.

Only operations that were applied have receipts. A rejected operation (validation error or
conflict) is answered with the standard error envelope and may be corrected and re-sent
under a new operation id."""
from types import SimpleNamespace
import uuid

from rest_framework import serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from agrifi.idempotency import services as idempotency
from agrifi.openapi import OpenApiTypes, extend_schema
from agrifi.inventory.views import CREATE_SCOPE, HarvestBatchViewSet, IsFarmer

SCHEMA_VERSION = 1
HARVEST_CREATE = 'harvest_batch.create'
# operation_type -> idempotency scope. Only harvest capture is an offline operation.
OPERATION_SCOPES = {HARVEST_CREATE: CREATE_SCOPE}


class SyncOperationSerializer(serializers.Serializer):
    operation_id = serializers.UUIDField()
    operation_type = serializers.ChoiceField(choices=sorted(OPERATION_SCOPES))
    schema_version = serializers.IntegerField()
    payload = serializers.DictField()

    def validate_schema_version(self, value):
        if value != SCHEMA_VERSION:
            raise serializers.ValidationError(f'Unsupported schema_version; expected {SCHEMA_VERSION}.')
        return value


def _receipt(operation_id, operation_type, record, replayed):
    return {
        'operation_id': str(operation_id),
        'operation_type': operation_type,
        'schema_version': SCHEMA_VERSION,
        'status': 'applied',
        'replayed': replayed,
        'resource_id': str(record.resource_id),
        'processed_at': record.created_at.isoformat(),
        'result': record.response_body,
    }


class SyncOperationCollectionView(APIView):
    """POST /sync/operations/ — apply an operation exactly once.

    201 first application, 200 identical replay (stored result, no new effects). The same
    operation id with a different payload is 409. Other failures use the error envelope."""

    permission_classes = [IsAuthenticated, IsFarmer]

    @extend_schema(request=SyncOperationSerializer, responses={200: OpenApiTypes.OBJECT, 201: OpenApiTypes.OBJECT})
    def post(self, request):
        envelope = SyncOperationSerializer(data=request.data)
        envelope.is_valid(raise_exception=True)
        data = envelope.validated_data
        operation_id = data['operation_id']
        payload = dict(data['payload'])
        # Compare as UUIDs so letter case in a client's GUID formatting cannot split one
        # operation into two idempotency keys.
        try:
            same_id = uuid.UUID(str(payload.get('client_sync_id', operation_id))) == operation_id
        except ValueError:
            same_id = False
        if not same_id:
            raise serializers.ValidationError(
                {'payload': {'client_sync_id': ['Must equal operation_id when supplied.']}}
            )
        payload['client_sync_id'] = str(operation_id)

        # Delegates to the harvest-batch workflow so validation, locking, audit events and
        # idempotency are shared with the REST endpoint rather than duplicated.
        view = HarvestBatchViewSet(action='create', format_kwarg=None, kwargs={})
        view.request = SimpleNamespace(data=payload, user=request.user)
        response = view.create(view.request)
        if response.status_code not in (status.HTTP_200_OK, status.HTTP_201_CREATED):
            return response
        record = idempotency.find_record(request.user, CREATE_SCOPE, operation_id)
        return Response(
            _receipt(operation_id, data['operation_type'], record, replayed=response.status_code == 200),
            status=response.status_code,
        )


class SyncOperationDetailView(APIView):
    """GET /sync/operations/{operation_id}/ — the receipt of an applied operation.

    Lets a client that lost a response (ambiguous timeout) learn the outcome without
    resending. 404 means the operation has not been applied. Scoped to the caller."""

    permission_classes = [IsAuthenticated, IsFarmer]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request, operation_id):
        record = idempotency.find_record(request.user, CREATE_SCOPE, operation_id)
        if record is None:
            raise NotFound('No applied operation with this id.')
        return Response(_receipt(operation_id, HARVEST_CREATE, record, replayed=False))
