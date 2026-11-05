from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import mock, skipUnless

from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models import ProtectedError
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from agrifi.accounts.models import UserRole
from agrifi.catalog.models import CropCategory
from agrifi.catalog.tests import make_user
from agrifi.idempotency.models import IdempotencyRecord

from . import views
from .models import HarvestBatch
from .serializers import HarvestBatchSerializer

SYNC_ID = '3f2c1a9e-8d7b-4c55-9a11-0b6e2d4f7a10'


class HarvestBatchTestBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.farmer = make_user('hf@example.com', UserRole.Role.FARMER)
        self.other = make_user('hf2@example.com', UserRole.Role.FARMER)
        self.buyer = make_user('hb@example.com', UserRole.Role.BUYER)
        self.admin = make_user('hops@example.com', UserRole.Role.OPERATIONS_ADMIN)
        self.category = CropCategory.objects.create(name='Cassava', slug='cassava')

    def payload(self, **overrides):
        data = {
            'category': str(self.category.id),
            'quantity': '120.500',
            'unit_code': 'kg',
            'harvested_on': '2026-01-15',
        }
        data.update(overrides)
        return data

    def sync_payload(self, **overrides):
        return self.payload(client_sync_id=SYNC_ID, **overrides)

    def make_batch(self, farmer):
        return HarvestBatch.objects.create(
            farmer=farmer, category=self.category, quantity='10', unit_code='kg',
            harvested_on='2026-01-01',
        )

    def post(self, payload, user=None):
        self.client.force_authenticate(user or self.farmer)
        return self.client.post(reverse('harvest-batch-list'), payload, format='json')

    def stale_first_lookup(self):
        """Make the pre-insert replay lookup miss once, as if a concurrent request
        committed just after it. The database constraint must then decide."""
        real_lookup = views.idempotency.find_record
        calls = []

        def lookup(owner, scope, key):
            calls.append(1)
            return None if len(calls) == 1 else real_lookup(owner, scope, key)

        return mock.patch.object(views.idempotency, 'find_record', side_effect=lookup)


class HarvestBatchApiTests(HarvestBatchTestBase):
    def test_farmer_creates_batch_owned_by_self(self):
        response = self.post(self.payload(farmer=str(self.other.id)))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(HarvestBatch.objects.get().farmer, self.farmer)

    def test_quantity_must_be_positive(self):
        for bad in ('0', '-1'):
            self.assertEqual(self.post(self.payload(quantity=bad)).status_code, 400)

    def test_inactive_category_rejected_for_new_batch(self):
        self.category.is_active = False
        self.category.save()
        self.assertEqual(self.post(self.payload()).status_code, 400)

    def test_buyer_and_anonymous_denied(self):
        self.assertEqual(self.client.get(reverse('harvest-batch-list')).status_code, 401)
        self.client.force_authenticate(self.buyer)
        self.assertEqual(self.client.get(reverse('harvest-batch-list')).status_code, 403)
        self.assertEqual(self.post(self.payload(), user=self.buyer).status_code, 403)

    def test_farmer_cannot_access_other_farmers_batch(self):
        batch = self.make_batch(self.other)
        self.client.force_authenticate(self.farmer)
        url = reverse('harvest-batch-detail', args=[batch.id])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.patch(url, {'notes': 'x'}, format='json').status_code, 404)
        self.assertEqual(self.client.get(reverse('harvest-batch-list')).data['count'], 0)

    def test_admin_can_read_all_but_not_write(self):
        batch = self.make_batch(self.farmer)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(reverse('harvest-batch-list')).data['count'], 1)
        url = reverse('harvest-batch-detail', args=[batch.id])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.patch(url, {'notes': 'x'}, format='json').status_code, 403)

    def test_owner_updates_and_cannot_delete(self):
        batch = self.make_batch(self.farmer)
        self.client.force_authenticate(self.farmer)
        url = reverse('harvest-batch-detail', args=[batch.id])
        self.assertEqual(self.client.patch(url, {'notes': 'dry'}, format='json').status_code, 200)
        self.assertEqual(self.client.delete(url).status_code, 405)

    def test_buyer_and_finance_operator_cannot_touch_batches(self):
        batch = self.make_batch(self.farmer)
        finance = make_user('hfin@example.com', UserRole.Role.FINANCE_OPERATOR)
        for user in (self.buyer, finance):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(reverse('harvest-batch-list')).status_code, 403)
            self.assertEqual(
                self.client.get(reverse('harvest-batch-detail', args=[batch.id])).status_code, 403
            )
            self.assertEqual(self.post(self.payload(), user=user).status_code, 403)

    def test_sync_id_cannot_be_changed_by_update(self):
        created = self.post(self.sync_payload())
        response = self.client.patch(
            reverse('harvest-batch-detail', args=[created.data['id']]),
            {'client_sync_id': '11111111-1111-4111-8111-111111111111'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_database_rejects_non_positive_quantity(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            HarvestBatch.objects.create(
                farmer=self.farmer, category=self.category, quantity='0', unit_code='kg',
                harvested_on='2026-01-01',
            )


class HarvestBatchIdempotencyTests(HarvestBatchTestBase):
    def test_first_request_creates_batch_and_record_together(self):
        response = self.post(self.sync_payload(farmer=str(self.other.id)))

        self.assertEqual(response.status_code, 201)
        batch = HarvestBatch.objects.get()
        record = IdempotencyRecord.objects.get()
        self.assertEqual(batch.farmer, self.farmer)
        self.assertEqual(record.owner, self.farmer)
        self.assertEqual(record.scope, 'harvest_batch.create')
        self.assertEqual(record.key, SYNC_ID)
        self.assertRegex(record.request_fingerprint, r'^[0-9a-f]{64}$')
        self.assertEqual(record.resource_type, 'inventory.harvestbatch')
        self.assertEqual(str(record.resource_id), str(batch.id))
        self.assertEqual(record.response_status, 201)
        self.assertEqual(record.response_body, response.data)

    def test_identical_replay_returns_original_response_with_200(self):
        first = self.post(self.sync_payload())
        replay = self.post(self.sync_payload())

        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(HarvestBatch.objects.count(), 1)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_replay_with_equivalent_decimal_formatting_is_identical(self):
        self.post(self.sync_payload(quantity='120.5'))
        replay = self.post(self.sync_payload(quantity='120.500'))
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(HarvestBatch.objects.count(), 1)

    def test_same_key_with_different_request_returns_409_and_changes_nothing(self):
        other_category = CropCategory.objects.create(name='Yam', slug='yam')
        self.post(self.sync_payload())
        changes = (
            {'quantity': '999'}, {'unit_code': 'bag'}, {'harvested_on': '2026-02-01'},
            {'notes': 'different'}, {'category': str(other_category.id)},
        )
        for change in changes:
            self.assertEqual(self.post(self.sync_payload(**change)).status_code, 409, change)

        batch = HarvestBatch.objects.get()
        self.assertEqual(str(batch.quantity), '120.500')
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_replay_after_batch_was_edited_returns_original_response(self):
        first = self.post(self.sync_payload())
        patched = self.client.patch(
            reverse('harvest-batch-detail', args=[first.data['id']]),
            {'quantity': '75', 'notes': 'edited'},
            format='json',
        )
        self.assertEqual(patched.status_code, 200)

        replay = self.post(self.sync_payload())

        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(replay.data['quantity'], '120.500')
        self.assertEqual(str(HarvestBatch.objects.get().quantity), '75.000')

    def test_replay_after_category_deactivation_returns_original_response(self):
        first = self.post(self.sync_payload())
        self.category.is_active = False
        self.category.save()

        replay = self.post(self.sync_payload())
        different = self.post(self.sync_payload(quantity='1'))
        fresh_key = self.post(self.payload(client_sync_id='22222222-2222-4222-8222-222222222222'))

        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(different.status_code, 409)
        self.assertEqual(fresh_key.status_code, 400)
        self.assertEqual(HarvestBatch.objects.count(), 1)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_keys_are_independent_per_farmer_and_responses_are_not_shared(self):
        mine = self.post(self.sync_payload())
        theirs = self.post(self.sync_payload(), user=self.other)

        self.assertEqual(theirs.status_code, 201)
        self.assertNotEqual(theirs.data['id'], mine.data['id'])
        self.assertEqual(HarvestBatch.objects.get(id=theirs.data['id']).farmer, self.other)
        self.assertEqual(IdempotencyRecord.objects.count(), 2)

        different = self.post(self.sync_payload(quantity='5'), user=self.other)
        self.assertEqual(different.status_code, 409)
        self.assertNotIn(mine.data['id'], different.content.decode())
        self.assertEqual(self.post(self.sync_payload(), user=self.other).data['id'], theirs.data['id'])

    def test_requests_without_key_are_not_deduplicated_and_have_no_record(self):
        self.post(self.payload())
        self.post(self.payload())
        self.assertEqual(HarvestBatch.objects.count(), 2)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)

    def test_validation_failure_leaves_no_record_and_key_remains_usable(self):
        self.assertEqual(self.post(self.sync_payload(quantity='-1')).status_code, 400)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)
        self.assertEqual(self.post(self.sync_payload()).status_code, 201)

    def test_failed_creation_leaves_no_batch_and_no_record(self):
        with mock.patch.object(HarvestBatchSerializer, 'create', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                self.post(self.sync_payload())

        self.assertEqual(HarvestBatch.objects.count(), 0)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)
        self.assertEqual(self.post(self.sync_payload()).status_code, 201)

    def test_lost_race_on_database_constraint_returns_original_response(self):
        first = self.post(self.sync_payload())
        with self.stale_first_lookup():
            replay = self.post(self.sync_payload())

        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(HarvestBatch.objects.count(), 1)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_lost_race_with_different_request_returns_409(self):
        self.post(self.sync_payload())
        with self.stale_first_lookup():
            response = self.post(self.sync_payload(quantity='5'))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(HarvestBatch.objects.count(), 1)

    def test_synthetic_unrelated_integrity_error_is_not_treated_as_replay(self):
        with mock.patch.object(
            HarvestBatchSerializer, 'create', side_effect=IntegrityError('some other constraint')
        ):
            with self.assertRaises(IntegrityError):
                self.post(self.sync_payload())

        self.assertEqual(HarvestBatch.objects.count(), 0)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)

    def test_real_unrelated_constraint_violation_is_not_treated_as_replay(self):
        # A batch holding this key but no idempotency record makes the batch table's own
        # unique constraint fire. It is a different constraint, so it must surface as an
        # error, and the idempotency record written earlier in the transaction must roll back.
        HarvestBatch.objects.create(
            farmer=self.farmer, category=self.category, quantity='1', unit_code='kg',
            harvested_on='2026-01-01', client_sync_id=SYNC_ID,
        )
        with self.assertRaises(IntegrityError):
            self.post(self.sync_payload())

        self.assertEqual(HarvestBatch.objects.count(), 1)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)

    def test_database_enforces_record_uniqueness_independently_of_the_view(self):
        self.post(self.sync_payload())
        existing = IdempotencyRecord.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            IdempotencyRecord.objects.create(
                owner=self.farmer, scope=existing.scope, key=existing.key,
                request_fingerprint='0' * 64, resource_type='inventory.harvestbatch',
                resource_id=existing.resource_id, response_status=201,
            )

    def test_batch_referenced_by_a_record_cannot_be_deleted(self):
        created = self.post(self.sync_payload())
        batch = HarvestBatch.objects.get(id=created.data['id'])

        with self.assertRaises(ProtectedError), transaction.atomic():
            batch.delete()
        with self.assertRaises(ProtectedError), transaction.atomic():
            HarvestBatch.objects.filter(id=batch.id).delete()
        self.assertTrue(HarvestBatch.objects.filter(id=batch.id).exists())

        unreferenced = self.make_batch(self.farmer)
        unreferenced.delete()


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL for real concurrent transactions.')
class HarvestBatchConcurrencyTests(TransactionTestCase):
    workers = 6

    def setUp(self):
        self.farmer = make_user('conc@example.com', UserRole.Role.FARMER)
        self.category = CropCategory.objects.create(name='Yam', slug='yam')

    def run_concurrently(self, payloads):
        barrier = Barrier(len(payloads))

        def submit(index):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(self.farmer)
                barrier.wait(timeout=10)
                response = client.post(reverse('harvest-batch-list'), payloads[index], format='json')
                return index, response.status_code, response.json()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(payloads)) as executor:
            return list(executor.map(submit, range(len(payloads))))

    def payload(self, quantity='10'):
        return {
            'category': str(self.category.id), 'quantity': quantity, 'unit_code': 'kg',
            'harvested_on': '2026-01-15', 'client_sync_id': SYNC_ID,
        }

    def test_concurrent_identical_requests_create_exactly_one_batch(self):
        results = self.run_concurrently([self.payload()] * self.workers)

        statuses = sorted(status for _, status, _ in results)
        self.assertEqual(statuses, [200] * (self.workers - 1) + [201], results)
        self.assertEqual(len({body['id'] for _, _, body in results}), 1)
        self.assertEqual(HarvestBatch.objects.filter(farmer=self.farmer).count(), 1)
        self.assertEqual(IdempotencyRecord.objects.filter(owner=self.farmer).count(), 1)

    def test_concurrent_conflicting_requests_create_at_most_one_batch(self):
        payloads = [self.payload('10' if i % 2 == 0 else '20') for i in range(self.workers)]
        results = self.run_concurrently(payloads)

        created = [r for r in results if r[1] == 201]
        self.assertEqual(len(created), 1, results)
        winner_index, _, winner_body = created[0]
        for index, status, body in results:
            if index == winner_index:
                continue
            if payloads[index] == payloads[winner_index]:
                self.assertEqual((status, body['id']), (200, winner_body['id']), results)
            else:
                self.assertEqual(status, 409, results)
        self.assertEqual(HarvestBatch.objects.filter(farmer=self.farmer).count(), 1)
        self.assertEqual(IdempotencyRecord.objects.filter(owner=self.farmer).count(), 1)
