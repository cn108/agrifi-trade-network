from types import SimpleNamespace
from datetime import timedelta
from io import StringIO

from django.db import IntegrityError
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from agrifi.accounts.models import User
from .models import IdempotencyRecord
from . import services


class FingerprintTests(SimpleTestCase):
    def test_independent_of_key_order(self):
        self.assertEqual(
            services.fingerprint({'a': 1, 'b': 'x'}),
            services.fingerprint({'b': 'x', 'a': 1}),
        )

    def test_changes_when_any_value_changes(self):
        base = {'a': 1, 'b': 'x'}
        self.assertNotEqual(services.fingerprint(base), services.fingerprint({**base, 'a': 2}))
        self.assertNotEqual(services.fingerprint(base), services.fingerprint({**base, 'c': ''}))

    def test_is_sha256_hex(self):
        self.assertRegex(services.fingerprint({'a': 1}), r'^[0-9a-f]{64}$')

    def test_decimal_normalisation(self):
        for equivalent in ('120.5', '120.500', '0120.50', '1.205E+2'):
            self.assertEqual(services.normalize_decimal(equivalent), '120.5')
        self.assertEqual(services.normalize_decimal('100'), '100')
        self.assertEqual(services.normalize_decimal('1E+2'), '100')
        self.assertNotEqual(services.normalize_decimal('120.501'), services.normalize_decimal('120.5'))


class ViolationDetectionTests(SimpleTestCase):
    def error_with_constraint(self, name):
        class DriverError(Exception):
            diag = SimpleNamespace(constraint_name=name)

        exc = IntegrityError('duplicate key')
        exc.__cause__ = DriverError()
        return exc

    def test_postgresql_constraint_name_is_matched_exactly(self):
        self.assertTrue(services.is_idempotency_violation(
            self.error_with_constraint('idempotency_owner_scope_key_unique')
        ))
        self.assertFalse(services.is_idempotency_violation(
            self.error_with_constraint('batch_farmer_sync_id_unique')
        ))

    def test_sqlite_message_requires_the_record_table_columns(self):
        table = services.IdempotencyRecord._meta.db_table
        match = IntegrityError(
            f'UNIQUE constraint failed: {table}.owner_id, {table}.scope, {table}.key'
        )
        other_table = IntegrityError(
            'UNIQUE constraint failed: inventory_harvestbatch.farmer_id, inventory_harvestbatch.client_sync_id'
        )
        self.assertTrue(services.is_idempotency_violation(match))
        self.assertFalse(services.is_idempotency_violation(other_table))
        self.assertFalse(services.is_idempotency_violation(IntegrityError('CHECK constraint failed: x')))


class IdempotencyRetentionTests(TestCase):
    def test_purge_removes_only_records_older_than_one_year(self):
        owner = User.objects.create_user(email='retention@example.com', password='safe-test-password')
        expired = IdempotencyRecord.objects.create(
            owner=owner,
            scope='order.create',
            key='old-key',
            request_fingerprint='a' * 64,
            resource_type='orders.order',
            resource_id='0b2f6b23-d90a-498b-9f11-dfd419684f07',
            response_status=201,
            response_body={},
        )
        recent = IdempotencyRecord.objects.create(
            owner=owner,
            scope='order.create',
            key='recent-key',
            request_fingerprint='b' * 64,
            resource_type='orders.order',
            resource_id='1c184c1c-ef31-49ce-a7c7-78386cd4c077',
            response_status=201,
            response_body={},
        )
        IdempotencyRecord.objects.filter(pk=expired.pk).update(
            created_at=timezone.now() - timedelta(days=366),
        )

        output = StringIO()
        call_command('purge_old_idempotency_records', stdout=output)

        self.assertFalse(IdempotencyRecord.objects.filter(pk=expired.pk).exists())
        self.assertTrue(IdempotencyRecord.objects.filter(pk=recent.pk).exists())
        self.assertIn('Deleted 1 idempotency record(s)', output.getvalue())
