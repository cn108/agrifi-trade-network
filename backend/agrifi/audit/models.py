import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditImmutableError(Exception):
    pass


class AuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AuditImmutableError('Audit events are append-only.')

    def delete(self):
        raise AuditImmutableError('Audit events are append-only.')

    def bulk_update(self, *args, **kwargs):
        raise AuditImmutableError('Audit events are append-only.')


class AuditEvent(models.Model):
    """Who did what to which record, and when. Append-only: the ORM refuses updates and
    deletes, and PostgreSQL triggers (audit/0002) refuse them for any other client.
    Metadata holds only allow-listed, non-secret values (see audit.services)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='audit_events',
    )
    action = models.CharField(max_length=64)
    object_type = models.CharField(max_length=64, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = AuditQuerySet.as_manager()

    class Meta:
        ordering = ('-created_at', '-id')
        indexes = [
            models.Index(fields=['created_at'], name='audit_created_idx'),
            models.Index(fields=['action', 'created_at'], name='audit_action_idx'),
            models.Index(fields=['object_type', 'object_id'], name='audit_object_idx'),
            models.Index(fields=['actor', 'created_at'], name='audit_actor_idx'),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AuditImmutableError('Audit events are append-only.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AuditImmutableError('Audit events are append-only.')
