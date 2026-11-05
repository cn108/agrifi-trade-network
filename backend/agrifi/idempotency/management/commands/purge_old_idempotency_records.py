from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from agrifi.idempotency.models import IdempotencyRecord


RETENTION_DAYS = 365


class Command(BaseCommand):
    help = 'Delete idempotency replay records older than the one-year retention window.'

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=RETENTION_DAYS)
        deleted, _ = IdempotencyRecord.objects.filter(created_at__lt=cutoff).delete()
        self.stdout.write(
            f'Deleted {deleted} idempotency record(s) older than {RETENTION_DAYS} days.'
        )
