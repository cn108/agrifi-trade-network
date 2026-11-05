import uuid

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from agrifi.accounts.models import UserRole
from agrifi.audit.models import AuditEvent
from agrifi.catalog.models import CropCategory
from agrifi.catalog.tests import make_user
from agrifi.inventory.models import HarvestBatch

URL = '/api/v1/sync/operations/'


class SyncOperationTests(TestCase):
    def setUp(self):
        self.farmer = make_user('sync-farmer@example.com', UserRole.Role.FARMER)
        self.other = make_user('sync-other@example.com', UserRole.Role.FARMER)
        self.ops = make_user('sync-ops@example.com', UserRole.Role.OPERATIONS_ADMIN)
        self.buyer = make_user('sync-buyer@example.com', UserRole.Role.BUYER)
        self.category = CropCategory.objects.create(name='Maize', slug='maize')
        self.client = APIClient()
        self.client.force_authenticate(self.farmer)

    def body(self, operation_id=None, **payload):
        data = {
            'category': str(self.category.pk), 'quantity': '12.500', 'unit_code': 'kg',
            'harvested_on': timezone.localdate().isoformat(), 'notes': '',
        }
        data.update(payload)
        return {
            'operation_id': str(operation_id or uuid.uuid4()),
            'operation_type': 'harvest_batch.create',
            'schema_version': 1,
            'payload': data,
        }

    def test_first_application_returns_a_receipt_and_creates_one_batch(self):
        body = self.body()
        response = self.client.post(URL, body, format='json')

        self.assertEqual(response.status_code, 201, response.content)
        receipt = response.json()
        self.assertEqual(receipt['status'], 'applied')
        self.assertFalse(receipt['replayed'])
        self.assertEqual(receipt['operation_id'], body['operation_id'])
        batch = HarvestBatch.objects.get()
        self.assertEqual(receipt['resource_id'], str(batch.pk))
        self.assertEqual(receipt['result']['id'], str(batch.pk))
        self.assertEqual(str(batch.client_sync_id), body['operation_id'])
        self.assertEqual(batch.farmer, self.farmer)

    def test_replay_returns_the_stored_result_without_new_effects(self):
        body = self.body()
        first = self.client.post(URL, body, format='json').json()
        events = AuditEvent.objects.count()
        replay = self.client.post(URL, body, format='json')

        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json()['replayed'])
        self.assertEqual(replay.json()['result'], first['result'])
        self.assertEqual(HarvestBatch.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.count(), events)

    def test_same_operation_id_with_a_different_payload_conflicts(self):
        body = self.body()
        self.client.post(URL, body, format='json')
        changed = self.body(body['operation_id'], quantity='99.000')
        response = self.client.post(URL, changed, format='json')

        self.assertEqual(response.status_code, 409)
        self.assertEqual(HarvestBatch.objects.count(), 1)

    def test_receipt_lookup_after_a_lost_response(self):
        body = self.body()
        self.assertEqual(self.client.get(f'{URL}{body["operation_id"]}/').status_code, 404)
        self.client.post(URL, body, format='json')

        response = self.client.get(f'{URL}{body["operation_id"]}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'applied')

    def test_receipts_are_scoped_to_the_owner(self):
        body = self.body()
        self.client.post(URL, body, format='json')
        self.client.force_authenticate(self.other)

        self.assertEqual(self.client.get(f'{URL}{body["operation_id"]}/').status_code, 404)
        # Another farmer reusing the id creates their own independent batch.
        self.assertEqual(self.client.post(URL, body, format='json').status_code, 201)
        self.assertEqual(HarvestBatch.objects.count(), 2)

    def test_validation_failure_uses_the_error_envelope_and_creates_nothing(self):
        response = self.client.post(URL, self.body(quantity='-1'), format='json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'validation_error')
        self.assertEqual(HarvestBatch.objects.count(), 0)

    def test_envelope_validation(self):
        bad_version = {**self.body(), 'schema_version': 2}
        bad_type = {**self.body(), 'operation_type': 'order.create'}
        bad_id = {**self.body(), 'operation_id': 'nope'}
        mismatch = self.body(client_sync_id=str(uuid.uuid4()))
        for label, body in (('version', bad_version), ('type', bad_type), ('id', bad_id), ('mismatch', mismatch)):
            with self.subTest(label):
                response = self.client.post(URL, body, format='json')
                self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(HarvestBatch.objects.count(), 0)

    def test_correction_through_sync_links_to_the_rejected_original(self):
        original = self.client.post(URL, self.body(), format='json').json()['resource_id']
        self.client.force_authenticate(self.ops)
        self.client.post(f'/api/v1/harvest-batches/{original}/reject/', {'reason': 'Blurry'}, format='json')
        self.client.force_authenticate(self.farmer)

        response = self.client.post(URL, self.body(resubmission_of=original), format='json')

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['result']['resubmission_of'], original)
        self.assertEqual(HarvestBatch.objects.get(pk=original).status, 'rejected')
        again = self.client.post(URL, self.body(resubmission_of=original), format='json')
        self.assertEqual(again.status_code, 409)

    def test_only_farmers_and_authenticated_users_can_use_it(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(URL, self.body(), format='json').status_code, 401)
        for user in (self.buyer, self.ops):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.post(URL, self.body(), format='json').status_code, 403)
            self.assertEqual(self.client.get(f'{URL}{uuid.uuid4()}/').status_code, 403)
        self.assertEqual(HarvestBatch.objects.count(), 0)
