import json
from pathlib import Path

from django.conf import settings
from django.urls import reverse

from agrifi.inventory.models import HarvestBatch

from .test_availability_resubmission import Base, sync_id

CONTRACT = json.loads(
    (Path(settings.BASE_DIR).parent / 'web/src/app/integration/harvest-correction.contract.json').read_text()
)


class HarvestCorrectionContractTests(Base):
    """Drives the real DRF API over HTTP with exactly the request shapes the Angular app sends.

    Counterpart of web/src/app/integration/harvest-correction.contract.spec.ts (same JSON contract).
    """

    def angular_payload(self, key, original, **overrides):
        values = {
            'category': str(self.category.id), 'quantity': '10.000', 'unit_code': 'kg',
            'harvested_on': '2026-11-01', 'client_sync_id': key, 'notes': 'corrected',
            'resubmission_of': original,
        }
        values.update(overrides)
        self.assertEqual(sorted(values), sorted(CONTRACT['correction_request_keys']))
        return values

    def reject_over_http(self, batch_id, reason='Quantity looks wrong'):
        body = {'reason': reason}
        self.assertEqual(sorted(body), sorted(CONTRACT['reject_request_keys']))
        return self.as_user(self.admin).post(
            reverse('harvest-batch-reject', args=[batch_id]), body, format='json')

    def create_original(self):
        response = self.as_user(self.farmer).post(reverse('harvest-batch-list'), {
            'category': str(self.category.id), 'quantity': '100.000', 'unit_code': 'kg',
            'harvested_on': '2026-11-01', 'client_sync_id': sync_id(1), 'notes': 'first try',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()['id']

    def test_full_correction_flow_over_http(self):
        farmer = self.as_user(self.farmer)
        original = self.create_original()
        rejected = self.reject_over_http(original)
        self.assertEqual(rejected.status_code, 200, rejected.content)
        before = farmer.get(reverse('harvest-batch-detail', args=[original])).json()

        created = farmer.post(
            reverse('harvest-batch-list'), self.angular_payload(sync_id(2), original), format='json')
        self.assertEqual(created.status_code, 201, created.content)
        correction = created.json()

        for key in CONTRACT['response_keys_read_by_angular']:
            self.assertIn(key, correction)
        self.assertEqual(correction['resubmission_of'], original)
        self.assertEqual(correction['status'], 'submitted')
        self.assertEqual(correction['client_sync_id'], sync_id(2))

        # Original is unchanged apart from the back-link.
        after = farmer.get(reverse('harvest-batch-detail', args=[original])).json()
        self.assertEqual(after.pop('correction_id'), correction['id'])
        before.pop('correction_id')
        self.assertEqual(after, before)
        self.assertEqual((after['status'], after['rejection_reason']), ('rejected', 'Quantity looks wrong'))

        # The paginated list the Angular page loads shows both with independent statuses.
        rows = {row['id']: row for row in farmer.get(reverse('harvest-batch-list')).json()['results']}
        self.assertEqual((rows[original]['status'], rows[correction['id']]['status']), ('rejected', 'submitted'))

    def test_duplicates_do_not_create_extra_corrections(self):
        farmer = self.as_user(self.farmer)
        original = self.create_original()
        self.reject_over_http(original)
        payload = self.angular_payload(sync_id(2), original)
        first = farmer.post(reverse('harvest-batch-list'), payload, format='json')
        replay = farmer.post(reverse('harvest-batch-list'), payload, format='json')
        self.assertEqual((first.status_code, replay.status_code), (201, 200))
        self.assertEqual(first.json()['id'], replay.json()['id'])
        another = farmer.post(
            reverse('harvest-batch-list'), self.angular_payload(sync_id(3), original), format='json')
        self.assertEqual(another.status_code, 409)
        reused = farmer.post(
            reverse('harvest-batch-list'), self.angular_payload(sync_id(1), original), format='json')
        self.assertEqual(reused.status_code, 409)
        self.assertEqual(HarvestBatch.objects.count(), 2)

    def test_non_ops_cannot_reject_over_http(self):
        original = self.create_original()
        response = self.as_user(self.farmer).post(
            reverse('harvest-batch-reject', args=[original]), {'reason': 'x'}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(HarvestBatch.objects.get(pk=original).status, 'submitted')
