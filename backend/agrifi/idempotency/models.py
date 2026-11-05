import uuid

from django.conf import settings
from django.db import models


class IdempotencyRecord(models.Model):
    """Record of a successfully processed idempotent operation.

    The unique constraint on (owner, scope, key) is the authority that prevents an
    operation from being processed twice. A record is written in the same database
    transaction as the business record it refers to, so both commit or neither does.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+'
    )
    scope = models.CharField(max_length=64)
    key = models.CharField(max_length=128)
    request_fingerprint = models.CharField(max_length=64)
    # Reference to the business record as "app_label.model" plus its UUID primary key.
    # Deletion is guarded by agrifi.idempotency.services.protect_referenced_records.
    resource_type = models.CharField(max_length=100)
    resource_id = models.UUIDField()
    response_status = models.PositiveSmallIntegerField()
    response_body = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'scope', 'key'], name='idempotency_owner_scope_key_unique'
            ),
        ]
        indexes = [
            models.Index(fields=['resource_type', 'resource_id'], name='idempotency_resource_idx'),
            models.Index(fields=['created_at'], name='idempotency_created_idx'),
        ]

    def __str__(self):
        return f'{self.scope}:{self.key}'
