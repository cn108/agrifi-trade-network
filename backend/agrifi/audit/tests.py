import json

from django.db import transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from agrifi.accounts.models import FarmerProfile, User, UserRole
from agrifi.catalog.models import CropCategory
from agrifi.request_context import REQUEST_ID_HEADER

from . import services
from .models import AuditEvent, AuditImmutableError

PASSWORD = 'strong-test-password-2026'


def make_user(email, role, **extra):
    user = User.objects.create_user(email=email, password=PASSWORD, **extra)
    UserRole.objects.create(user=user, role=role)
    return user


class AuditServiceTests(TestCase):
    def setUp(self):
        self.user = make_user('ops@example.com', UserRole.Role.OPERATIONS_ADMIN)

    def test_record_stores_actor_object_request_id_and_metadata(self):
        event = services.record('thing.done', self.user, self.user, {'reason': 'because', 'quantity': 3})

        event.refresh_from_db()
        self.assertEqual(event.actor, self.user)
        self.assertEqual(event.object_type, 'accounts.user')
        self.assertEqual(event.object_id, str(self.user.pk))
        self.assertEqual(event.metadata, {'reason': 'because', 'quantity': 3})

    def test_metadata_outside_the_allow_list_is_refused(self):
        for key in ('password', 'token', 'authorization', 'refresh', 'email'):
            with self.subTest(key=key), self.assertRaises(services.AuditError):
                services.record('x.y', self.user, metadata={key: 'secret'})
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_metadata_must_be_scalar(self):
        with self.assertRaises(services.AuditError):
            services.record('x.y', metadata={'reason': {'nested': 'value'}})

    def test_long_text_is_truncated(self):
        event = services.record('x.y', metadata={'reason': 'a' * 5000})

        self.assertEqual(len(event.metadata['reason']), services.MAX_TEXT)

    def test_hashed_identifier_is_stable_and_not_the_email(self):
        first = services.hash_identifier(' Person@Example.com ')

        self.assertEqual(first, services.hash_identifier('person@example.com'))
        self.assertNotIn('person', first)

    def test_events_cannot_be_updated_or_deleted_through_the_orm(self):
        event = services.record('x.y', self.user)

        event.action = 'tampered'
        with self.assertRaises(AuditImmutableError):
            event.save()
        with self.assertRaises(AuditImmutableError):
            event.delete()
        with self.assertRaises(AuditImmutableError):
            AuditEvent.objects.all().update(action='tampered')
        with self.assertRaises(AuditImmutableError):
            AuditEvent.objects.all().delete()
        self.assertEqual(AuditEvent.objects.get().action, 'x.y')

    def test_event_is_rolled_back_with_the_business_change(self):
        with self.assertRaises(RuntimeError), transaction.atomic():
            services.record('x.y', self.user)
            raise RuntimeError('business change failed')

        self.assertEqual(AuditEvent.objects.count(), 0)


class AuditTrailTests(TestCase):
    """The workflow services write events in the same transaction as the change."""

    def setUp(self):
        self.client = APIClient()
        self.ops = make_user('ops@example.com', UserRole.Role.OPERATIONS_ADMIN)
        self.farmer = make_user('farmer@example.com', UserRole.Role.FARMER)
        FarmerProfile.objects.create(user=self.farmer, display_name='Farm')
        self.category = CropCategory.objects.create(name='Maize', slug='maize')

    def actions(self):
        return list(AuditEvent.objects.order_by('created_at', 'id').values_list('action', flat=True))

    def test_registration_login_and_failed_login_are_recorded(self):
        self.client.post('/api/v1/auth/register/', {
            'email': 'new@example.com', 'password': PASSWORD, 'password_confirm': PASSWORD,
            'role': 'buyer', 'business_name': 'Biz',
        }, format='json')
        self.client.post('/api/v1/auth/login/', {'email': 'new@example.com', 'password': PASSWORD}, format='json')
        self.client.post('/api/v1/auth/login/', {'email': 'new@example.com', 'password': 'wrong-password-1'}, format='json')

        self.assertEqual(self.actions(), ['auth.registered', 'auth.login_succeeded', 'auth.login_failed'])
        failed = AuditEvent.objects.get(action='auth.login_failed')
        self.assertIsNone(failed.actor)
        self.assertNotIn('new@example.com', json.dumps(failed.metadata))
        self.assertEqual(len(failed.metadata['email_hash']), 16)
        self.assertNotIn('wrong-password-1', json.dumps(failed.metadata))

    def test_duplicate_registration_creates_no_registered_event(self):
        payload = {
            'email': 'farmer@example.com', 'password': PASSWORD, 'password_confirm': PASSWORD,
            'role': 'buyer', 'business_name': 'Biz',
        }
        self.client.post('/api/v1/auth/register/', payload, format='json')

        self.assertEqual(self.actions(), [])

    def submit_batch(self):
        self.client.force_authenticate(self.farmer)
        response = self.client.post('/api/v1/harvest-batches/', {
            'category': str(self.category.pk), 'quantity': '10.000', 'unit_code': 'kg',
            'harvested_on': timezone.localdate().isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()['id']

    def test_batch_submission_review_and_request_id_are_recorded(self):
        batch_id = self.submit_batch()
        self.client.force_authenticate(self.ops)
        response = self.client.post(f'/api/v1/harvest-batches/{batch_id}/accept/')
        self.assertEqual(response.status_code, 200, response.content)

        self.assertEqual(self.actions(), ['harvest_batch.submitted', 'harvest_batch.accepted'])
        accepted = AuditEvent.objects.get(action='harvest_batch.accepted')
        self.assertEqual(accepted.actor, self.ops)
        self.assertEqual(accepted.object_id, batch_id)
        self.assertEqual(accepted.request_id, response[REQUEST_ID_HEADER])

    def test_failed_review_leaves_no_event(self):
        batch_id = self.submit_batch()
        self.client.force_authenticate(self.ops)
        self.client.post(f'/api/v1/harvest-batches/{batch_id}/accept/')
        before = AuditEvent.objects.count()
        again = self.client.post(f'/api/v1/harvest-batches/{batch_id}/accept/')

        self.assertEqual(again.status_code, 409)
        self.assertEqual(AuditEvent.objects.count(), before)

    def test_rejection_records_the_reason(self):
        batch_id = self.submit_batch()
        self.client.force_authenticate(self.ops)
        self.client.post(f'/api/v1/harvest-batches/{batch_id}/reject/', {'reason': 'Photo unclear'}, format='json')

        event = AuditEvent.objects.get(action='harvest_batch.rejected')
        self.assertEqual(event.metadata['reason'], 'Photo unclear')


class AuditEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.ops = make_user('ops@example.com', UserRole.Role.OPERATIONS_ADMIN)
        self.other = {
            role: make_user(f'{role}@example.com', role)
            for role in (UserRole.Role.FARMER, UserRole.Role.BUYER, UserRole.Role.FINANCE_OPERATOR)
        }
        services.record('a.one', self.ops, metadata={'reason': 'r1'})
        services.record('b.two', self.other['farmer'], object_type='x.y', object_id='42')

    def test_only_operations_administrators_can_read(self):
        self.assertEqual(self.client.get('/api/v1/audit-events/').status_code, 401)
        for user in self.other.values():
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get('/api/v1/audit-events/').status_code, 403)
        self.client.force_authenticate(self.ops)
        response = self.client.get('/api/v1/audit-events/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 2)

    def test_filters(self):
        self.client.force_authenticate(self.ops)

        by_action = self.client.get('/api/v1/audit-events/?action=b.two').json()
        by_object = self.client.get('/api/v1/audit-events/?object_type=x.y&object_id=42').json()
        by_actor = self.client.get(f'/api/v1/audit-events/?actor={self.ops.pk}').json()
        future = self.client.get('/api/v1/audit-events/?created_after=2999-01-01T00:00:00Z').json()

        self.assertEqual([e['action'] for e in by_action['results']], ['b.two'])
        self.assertEqual(by_object['count'], 1)
        self.assertEqual([e['action'] for e in by_actor['results']], ['a.one'])
        self.assertEqual(future['count'], 0)

    def test_bad_filter_values_are_validation_errors(self):
        self.client.force_authenticate(self.ops)

        self.assertEqual(self.client.get('/api/v1/audit-events/?actor=not-a-uuid').status_code, 400)
        self.assertEqual(self.client.get('/api/v1/audit-events/?created_after=yesterday').status_code, 400)

    def test_endpoint_is_read_only(self):
        self.client.force_authenticate(self.ops)
        event_id = str(services.record('c.three').pk)

        self.assertEqual(self.client.post('/api/v1/audit-events/', {}, format='json').status_code, 405)
        self.assertEqual(self.client.patch(f'/api/v1/audit-events/{event_id}/', {}, format='json').status_code, 405)
        self.assertEqual(self.client.delete(f'/api/v1/audit-events/{event_id}/').status_code, 405)

    def test_page_size_is_capped(self):
        self.client.force_authenticate(self.ops)

        self.assertLessEqual(len(self.client.get('/api/v1/audit-events/?page_size=1000').json()['results']), 100)
