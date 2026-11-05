import hashlib
import json
from decimal import Decimal

from django.db.models import ProtectedError
from django.db.models.signals import pre_delete
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response

from .models import IdempotencyRecord

CONSTRAINT_NAME = 'idempotency_owner_scope_key_unique'


class IdempotencyKeyConflict(APIException):
    """409 in the standard error envelope: the key was already used with a different request."""

    status_code = status.HTTP_409_CONFLICT
    default_code = 'idempotency_conflict'


def replay_response(record, fingerprint_value):
    """Stored response (200) for an identical retry; 409 envelope when the request differs."""
    if record.request_fingerprint != fingerprint_value:
        raise IdempotencyKeyConflict({
            'code': 'idempotency_conflict',
            'detail': 'This key was already used with a different request.',
        })
    return Response(record.response_body, status=status.HTTP_200_OK)


def normalize_decimal(value):
    """Canonical string for a decimal so 120.5 and 120.500 fingerprint identically."""
    return format(Decimal(value).normalize(), 'f')


def fingerprint(payload):
    """SHA-256 of the canonical JSON form of an already validated, normalised payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def find_record(owner, scope, key):
    """Always scoped to the owner, so one user's stored response is never visible to another."""
    return IdempotencyRecord.objects.filter(owner=owner, scope=scope, key=str(key)).first()


def is_idempotency_violation(exc):
    """True only when an IntegrityError came from the (owner, scope, key) unique constraint."""
    diag = getattr(exc.__cause__, 'diag', None)
    constraint = getattr(diag, 'constraint_name', None)
    if constraint:
        return constraint == CONSTRAINT_NAME
    message = str(exc)
    if CONSTRAINT_NAME in message:
        return True
    # SQLite names the columns instead of the constraint.
    table = IdempotencyRecord._meta.db_table
    return (
        'UNIQUE constraint failed' in message
        and all(f'{table}.{column}' in message for column in ('owner_id', 'scope', 'key'))
    )


def protect_referenced_records(model):
    """Refuse to delete rows of `model` that an idempotency record refers to."""

    def guard(sender, instance, **kwargs):
        referenced = IdempotencyRecord.objects.filter(
            resource_type=sender._meta.label_lower, resource_id=instance.pk
        ).exists()
        if referenced:
            raise ProtectedError(
                f'{sender._meta.label} is referenced by an idempotency record and cannot be deleted.',
                [instance],
            )

    pre_delete.connect(
        guard,
        sender=model,
        weak=False,
        dispatch_uid=f'idempotency-guard-{model._meta.label_lower}',
    )
