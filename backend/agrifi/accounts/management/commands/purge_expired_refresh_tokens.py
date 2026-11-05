from django.core.management.base import BaseCommand
from django.utils import timezone

from agrifi.accounts.models import RevokedRefreshToken


class Command(BaseCommand):
    help = 'Delete refresh-token revocation records whose tokens have expired.'

    def handle(self, *args, **options):
        deleted, _ = RevokedRefreshToken.objects.filter(
            expires_at__lte=timezone.now(),
        ).delete()
        self.stdout.write(f'Deleted {deleted} expired refresh-token revocation record(s).')
