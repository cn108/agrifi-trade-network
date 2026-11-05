"""Contract tests shared with the MAUI client.

`contracts/sync-harvest-create.*.json` are the single source of truth for the request the
mobile app sends and the receipt it parses. The MAUI test project asserts its client
produces/accepts exactly these shapes; these tests assert the real Django API accepts the
request and returns a receipt with exactly these keys. If either side drifts, one fails.

Requests go through the real URL routing, JWT authentication, permissions, middleware,
serializers and database via the Django test client (no sockets)."""
import copy
import json
import os
import uuid
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from agrifi.accounts.models import UserRole
from agrifi.catalog.models import CropCategory
from agrifi.catalog.tests import make_user
from agrifi.inventory.models import HarvestBatch
from agrifi.inventory.views import HarvestBatchViewSet
URL = '/api/v1/sync/operations/'
CONTRACTS = Path(os.environ.get('AGRIFI_CONTRACTS_DIR') or Path(__file__).resolve().parents[3] / 'contracts')


def load(name):
    return json.loads((CONTRACTS / name).read_text(encoding='utf-8'))


class SyncContractTests(TestCase):
    def setUp(self):
        self.farmer = make_user('contract-farmer@example.com', UserRole.Role.FARMER)
        self.category = CropCategory.objects.create(name='Cassava', slug='cassava')
        self.client = APIClient(raise_request_exception=False)
        self.token = str(AccessToken.for_user(self.farmer))
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')

    def request_body(self, operation_id=None):
        body = load('sync-harvest-create.request.json')
        operation_id = str(operation_id or uuid.uuid4())
        body['operation_id'] = operation_id
        body['payload']['client_sync_id'] = operation_id
        body['payload']['category'] = str(self.category.pk)
        body['payload']['harvested_on'] = timezone.localdate().isoformat()
        return body

    def test_the_mobile_request_shape_is_accepted_with_a_real_jwt(self):
        response = self.client.post(URL, self.request_body(), format='json')

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(HarvestBatch.objects.count(), 1)

    def test_receipt_keys_match_what_the_mobile_client_parses(self):
        expected = load('sync-harvest-create.receipt.json')
        receipt = self.client.post(URL, self.request_body(), format='json').json()

        self.assertEqual(set(receipt), set(expected))
        self.assertEqual(set(receipt['result']), set(expected['result']))
        self.assertEqual(receipt['status'], expected['status'])
        self.assertEqual(receipt['result']['status'], 'submitted')
        self.assertEqual(receipt['operation_type'], expected['operation_type'])
        self.assertEqual(receipt['schema_version'], expected['schema_version'])

    def test_replay_has_the_same_shape_and_identifiers(self):
        body = self.request_body()
        first = self.client.post(URL, body, format='json').json()
        replay = self.client.post(URL, body, format='json')

        self.assertEqual(replay.status_code, 200)
        self.assertEqual(set(replay.json()), set(first))
        self.assertTrue(replay.json()['replayed'])
        self.assertEqual(replay.json()['resource_id'], first['resource_id'])
        self.assertEqual(HarvestBatch.objects.count(), 1)

    def test_uppercase_guid_from_a_client_is_the_same_operation(self):
        operation_id = uuid.uuid4()
        lower = self.request_body(operation_id)
        upper = copy.deepcopy(lower)
        upper['operation_id'] = str(operation_id).upper()
        upper['payload']['client_sync_id'] = str(operation_id).upper()

        self.assertEqual(self.client.post(URL, lower, format='json').status_code, 201)
        response = self.client.post(URL, upper, format='json')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(HarvestBatch.objects.count(), 1)

    def test_conflicting_payload_is_409_and_original_is_untouched(self):
        body = self.request_body()
        self.client.post(URL, body, format='json')
        changed = copy.deepcopy(body)
        changed['payload']['quantity'] = '99.000'

        response = self.client.post(URL, changed, format='json')

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'idempotency_conflict')
        self.assertEqual(str(HarvestBatch.objects.get().quantity), '12.500')

    def test_validation_error_names_the_field_and_has_a_request_id(self):
        body = self.request_body()
        body['payload']['quantity'] = '-1'

        response = self.client.post(URL, body, format='json')

        self.assertEqual(response.status_code, 400)
        envelope = response.json()
        self.assertEqual(envelope['code'], 'validation_error')
        self.assertTrue(envelope['message'])
        self.assertTrue(envelope['request_id'])
        self.assertEqual(response.headers['X-Request-ID'], envelope['request_id'])
        self.assertEqual(HarvestBatch.objects.count(), 0)

    def test_missing_invalid_and_expired_tokens_are_401_with_the_envelope(self):
        expired = AccessToken.for_user(self.farmer)
        expired.set_exp(from_time=timezone.now() - timedelta(hours=2), lifetime=timedelta(minutes=1))
        for label, header in (
            ('missing', None),
            ('garbage', 'Bearer not-a-token'),
            ('expired', f'Bearer {expired}'),
        ):
            with self.subTest(label):
                client = APIClient(raise_request_exception=False)
                if header:
                    client.credentials(HTTP_AUTHORIZATION=header)
                response = client.post(URL, self.request_body(), format='json')
                self.assertEqual(response.status_code, 401)
                self.assertIn('code', response.json())
        self.assertEqual(HarvestBatch.objects.count(), 0)

    def test_a_crash_mid_request_creates_nothing_and_the_retry_creates_exactly_one(self):
        body = self.request_body()
        with mock.patch.object(HarvestBatchViewSet, 'audit_submission', side_effect=RuntimeError('boom')):
            with self.assertLogs(level='ERROR'):
                crashed = self.client.post(URL, body, format='json')
        self.assertEqual(crashed.status_code, 500)
        self.assertEqual(HarvestBatch.objects.count(), 0)

        retried = self.client.post(URL, body, format='json')
        again = self.client.post(URL, body, format='json')

        self.assertEqual(retried.status_code, 201, retried.content)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(HarvestBatch.objects.count(), 1)

    def test_lost_response_is_recoverable_by_receipt_lookup(self):
        body = self.request_body()
        self.client.post(URL, body, format='json')

        lookup = self.client.get(f'{URL}{body["operation_id"]}/')

        self.assertEqual(lookup.status_code, 200)
        self.assertEqual(lookup.json()['resource_id'], str(HarvestBatch.objects.get().pk))
