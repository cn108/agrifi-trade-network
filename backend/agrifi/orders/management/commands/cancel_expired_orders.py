from django.core.management.base import BaseCommand

from agrifi.orders.services import cancel_expired_orders


class Command(BaseCommand):
    help = 'Cancel pending orders whose stock reservation has lapsed (run periodically).'

    def handle(self, *args, **options):
        self.stdout.write(f'Cancelled {cancel_expired_orders()} order(s).')
