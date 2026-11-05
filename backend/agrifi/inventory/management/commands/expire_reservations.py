from django.core.management.base import BaseCommand

from agrifi.inventory.services import expire_reservations


class Command(BaseCommand):
    help = 'Mark overdue active stock reservations as expired (run periodically).'

    def handle(self, *args, **options):
        self.stdout.write(f'Expired {expire_reservations()} reservation(s).')
