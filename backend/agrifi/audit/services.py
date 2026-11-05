"""The one way to write an audit event.

Call `record()` inside the same `transaction.atomic()` block as the change it describes, so
the event commits with the change and vanishes with it on rollback."""
import hashlib
import hmac
from decimal import Decimal

from django.conf import settings

from agrifi.request_context import get_request_id

from .models import AuditEvent

# Metadata keys are an allow-list so credentials, tokens or request bodies cannot be logged
# by accident. Adding a key is a deliberate, reviewed change.
ALLOWED_METADATA_KEYS = frozenset({
    'amount_minor', 'batch_id', 'currency', 'email_hash', 'from_status', 'item_count',
    'journal_id', 'listing_id', 'order_id', 'outcome', 'payment_id', 'quantity', 'reason',
    'reservation_id', 'resubmission_of', 'role', 'system', 'to_status', 'total_minor',
})
MAX_TEXT = 500


class AuditError(ValueError):
    pass


def _clean(key, value):
    if key not in ALLOWED_METADATA_KEYS:
        raise AuditError(f'Audit metadata key "{key}" is not allowed.')
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, (str, Decimal)) or hasattr(value, 'hex'):  # UUIDs
        return str(value)[:MAX_TEXT]
    raise AuditError(f'Audit metadata "{key}" must be a scalar value.')


def hash_identifier(value):
    """Keyed hash so failed-login events can be correlated without storing the email."""
    key = settings.SECRET_KEY.encode()
    return hmac.new(key, str(value).strip().lower().encode(), hashlib.sha256).hexdigest()[:16]


def record(action, actor=None, obj=None, metadata=None, object_type='', object_id=''):
    """Append one audit event. `obj` is any model instance; its class and pk are stored."""
    if obj is not None:
        object_type = obj._meta.label_lower
        object_id = str(obj.pk)
    if actor is not None and not getattr(actor, 'is_authenticated', False):
        actor = None
    return AuditEvent.objects.create(
        action=action,
        actor=actor,
        object_type=object_type,
        object_id=str(object_id),
        request_id=get_request_id() or '',
        metadata={key: _clean(key, value) for key, value in (metadata or {}).items()},
    )
