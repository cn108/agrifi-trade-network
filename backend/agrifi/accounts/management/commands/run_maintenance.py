import logging
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger('agrifi.maintenance')

# Order matters: reservations expire first so orders whose hold lapsed are then cancelled.
JOBS = (
    'expire_reservations',
    'cancel_expired_orders',
    'purge_expired_refresh_tokens',
    'purge_old_idempotency_records',
)


def run_jobs(stdout):
    failed = []
    for job in JOBS:
        try:
            call_command(job, stdout=stdout)
        except Exception:
            logger.exception('maintenance job failed', extra={'job': job})
            failed.append(job)
    return failed


class Command(BaseCommand):
    help = (
        'Run all periodic maintenance jobs once (for cron / Task Scheduler), '
        'or continuously with --interval SECONDS (for the compose scheduler service).'
    )

    def add_arguments(self, parser):
        parser.add_argument('--interval', type=int, default=0, help='Repeat every N seconds; 0 runs once.')

    def handle(self, *args, **options):
        interval = options['interval']
        if interval < 0:
            raise CommandError('--interval must be >= 0.')
        while True:
            failed = run_jobs(self.stdout)
            if failed and not interval:
                raise CommandError(f'Maintenance job(s) failed: {", ".join(failed)}')
            if not interval:
                return
            time.sleep(interval)
