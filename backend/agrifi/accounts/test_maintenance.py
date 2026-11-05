from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from datetime import timedelta

from .management.commands import run_maintenance
from .models import RevokedRefreshToken, User


class RunMaintenanceTests(SimpleTestCase):
    def test_runs_all_jobs_in_order(self):
        with mock.patch.object(run_maintenance, 'call_command') as cc:
            call_command('run_maintenance', stdout=StringIO())
        self.assertEqual(
            [c.args[0] for c in cc.call_args_list],
            [
                'expire_reservations',
                'cancel_expired_orders',
                'purge_expired_refresh_tokens',
                'purge_old_idempotency_records',
            ],
        )

    def test_one_failure_does_not_stop_the_others_and_exits_nonzero(self):
        def fake(job, **kwargs):
            if job == 'expire_reservations':
                raise RuntimeError('boom')

        with mock.patch.object(run_maintenance, 'call_command', side_effect=fake) as cc:
            with self.assertLogs('agrifi.maintenance', level='ERROR'):
                with self.assertRaisesMessage(CommandError, 'expire_reservations'):
                    call_command('run_maintenance', stdout=StringIO())
        self.assertEqual(cc.call_count, len(run_maintenance.JOBS))

    def test_negative_interval_rejected(self):
        with self.assertRaises(CommandError):
            call_command('run_maintenance', interval=-1, stdout=StringIO())

    def test_interval_loops_until_interrupted(self):
        with mock.patch.object(run_maintenance, 'call_command'), \
                mock.patch.object(run_maintenance.time, 'sleep', side_effect=[None, KeyboardInterrupt]) as sleep:
            with self.assertRaises(KeyboardInterrupt):
                call_command('run_maintenance', interval=5, stdout=StringIO())
        sleep.assert_called_with(5)
        self.assertEqual(sleep.call_count, 2)


class RunMaintenanceIntegrationTests(TestCase):
    def test_real_run_purges_expired_revocations(self):
        user = User.objects.create_user(email='maint@example.com', password='pw-test-2026-strong')
        RevokedRefreshToken.objects.create(
            jti='old', user=user, expires_at=timezone.now() - timedelta(days=1),
        )
        out = StringIO()
        call_command('run_maintenance', stdout=out)
        self.assertFalse(RevokedRefreshToken.objects.filter(jti='old').exists())
        self.assertIn('Expired 0 reservation(s)', out.getvalue())
