import io
import json
import logging
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from agrifi.accounts.models import User, UserRole
from agrifi.request_context import REQUEST_ID_HEADER
from config.logging import JsonFormatter

PASSWORD = 'strong-test-password-2026'


class RequestIdTests(SimpleTestCase):
    def test_every_response_has_a_generated_request_id(self):
        response = self.client.get(reverse('health-check'))

        self.assertRegex(response[REQUEST_ID_HEADER], r'^[0-9a-f]{32}$')

    def test_safe_supplied_request_id_is_echoed(self):
        response = self.client.get(reverse('health-check'), headers={REQUEST_ID_HEADER: 'client-trace-12345'})

        self.assertEqual(response[REQUEST_ID_HEADER], 'client-trace-12345')

    def test_unsafe_supplied_request_ids_are_replaced(self):
        for supplied in ('short', 'x' * 65, 'has space in it!', 'bad<script>id1'):
            with self.subTest(supplied=supplied):
                response = self.client.get(reverse('health-check'), headers={REQUEST_ID_HEADER: supplied})

                self.assertNotEqual(response[REQUEST_ID_HEADER], supplied)
                self.assertRegex(response[REQUEST_ID_HEADER], r'^[0-9a-f]{32}$')

    def test_request_log_carries_the_id_and_no_query_string(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        logger = logging.getLogger('agrifi.request')
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        self.addCleanup(logger.removeHandler, handler)

        self.client.get(reverse('health-check') + '?token=secret-value', headers={REQUEST_ID_HEADER: 'trace-id-abcdef'})

        record = json.loads(stream.getvalue().strip().splitlines()[-1])
        self.assertEqual(record['request_id'], 'trace-id-abcdef')
        self.assertEqual(record['status_code'], 200)
        self.assertNotIn('secret-value', stream.getvalue())


class ErrorEnvelopeTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email='buyer@example.com', password=PASSWORD)
        UserRole.objects.create(user=self.user, role=UserRole.Role.BUYER)

    def assert_envelope(self, response, status, code):
        self.assertEqual(response.status_code, status)
        data = response.json()
        self.assertEqual(data['code'], code)
        self.assertTrue(data['message'])
        self.assertEqual(data['detail'], data['message'])
        self.assertEqual(data['request_id'], response[REQUEST_ID_HEADER])
        return data

    def test_unauthenticated_request(self):
        response = self.client.get(reverse('accounts:me'))

        self.assert_envelope(response, 401, 'not_authenticated')

    def test_validation_error_lists_fields(self):
        response = self.client.post(reverse('accounts:register'), {'email': 'nope'}, format='json')

        data = self.assert_envelope(response, 400, 'validation_error')
        self.assertIn('email', data['fields'])
        self.assertIn('password', data['fields'])

    def test_permission_denied(self):
        self.client.force_authenticate(self.user)
        response = self.client.get('/api/v1/finance/ledger-accounts/')

        self.assert_envelope(response, 403, 'permission_denied')

    def test_not_found(self):
        self.client.force_authenticate(self.user)
        response = self.client.get('/api/v1/orders/00000000-0000-0000-0000-000000000000/')

        self.assert_envelope(response, 404, 'not_found')

    def test_business_rule_errors_keep_their_specific_code(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            '/api/v1/simulated-payments/', {'order': '00000000-0000-0000-0000-000000000000'},
            format='json', headers={'Idempotency-Key': 'key-for-envelope-test'},
        )

        data = response.json()
        self.assertGreaterEqual(response.status_code, 400)
        self.assertTrue(data['code'])
        self.assertEqual(data['request_id'], response[REQUEST_ID_HEADER])

    def test_unexpected_errors_return_a_generic_envelope(self):
        client = APIClient(raise_request_exception=False)
        client.force_authenticate(self.user)
        with mock.patch('agrifi.accounts.views.MeView.get_object', side_effect=RuntimeError('database password leaked')):
            response = client.get(reverse('accounts:me'))

        data = self.assert_envelope(response, 500, 'server_error')
        self.assertNotIn('leaked', json.dumps(data))


@override_settings(AGRIFI_THROTTLE_RATES={'auth_ip': '', 'login_email': '3/min'})
class LoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()
        User.objects.create_user(email='target@example.com', password=PASSWORD)

    def login(self, email, password):
        return self.client.post(reverse('accounts:login'), {'email': email, 'password': password}, format='json')

    def test_repeated_failures_for_one_account_are_throttled(self):
        for _ in range(3):
            self.assertEqual(self.login('target@example.com', 'wrong-password-xyz').status_code, 401)

        blocked = self.login('target@example.com', PASSWORD)

        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()['code'], 'throttled')
        self.assertIn('Retry-After', blocked)

    def test_throttle_is_per_account_and_case_insensitive(self):
        for _ in range(3):
            self.login('Target@Example.com', 'wrong-password-xyz')

        self.assertEqual(self.login('TARGET@example.com', PASSWORD).status_code, 429)
        self.assertEqual(self.login('someone.else@example.com', 'wrong-password-xyz').status_code, 401)

    def test_account_is_not_stored_in_clear_in_the_cache_key(self):
        self.login('target@example.com', 'wrong-password-xyz')

        from django.core.cache import cache as shared_cache
        keys = list(getattr(shared_cache, '_cache', {}).keys())
        self.assertTrue(keys)
        self.assertFalse(any('target@example.com' in key for key in keys))


@override_settings(AGRIFI_THROTTLE_RATES={'auth_ip': '2/min', 'login_email': ''})
class AddressThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_registration_attempts_from_one_address_are_limited(self):
        client = APIClient()
        statuses = [client.post(reverse('accounts:register'), {}, format='json').status_code for _ in range(3)]

        self.assertEqual(statuses, [400, 400, 429])

    def test_spoofed_forwarded_for_header_does_not_evade_the_address_limit(self):
        client = APIClient()
        statuses = [
            client.post(
                reverse('accounts:register'), {}, format='json', HTTP_X_FORWARDED_FOR=f'203.0.113.{n}'
            ).status_code
            for n in range(3)
        ]

        self.assertEqual(statuses, [400, 400, 429])


class RegistrationEnumerationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.existing = User.objects.create_user(email='taken@example.com', password=PASSWORD)
        UserRole.objects.create(user=self.existing, role=UserRole.Role.BUYER)

    payload = {
        'password': 'another-strong-password-2026',
        'password_confirm': 'another-strong-password-2026',
        'role': 'buyer',
        'business_name': 'Intruder Ltd',
    }

    def register(self, email):
        return self.client.post(reverse('accounts:register'), {**self.payload, 'email': email}, format='json')

    def test_existing_and_new_emails_get_the_same_status_and_shape(self):
        existing = self.register('taken@example.com')
        mixed_case = self.register('Taken@Example.com')
        fresh = self.register('fresh@example.com')

        for response in (existing, mixed_case, fresh):
            self.assertEqual(response.status_code, 201)
            self.assertEqual(set(response.json()), set(fresh.json()))
            self.assertNotIn('already', json.dumps(response.json()).lower())
        self.assertEqual(User.objects.filter(email__iexact='taken@example.com').count(), 1)

    def test_existing_account_is_untouched(self):
        self.register('taken@example.com')

        self.existing.refresh_from_db()
        self.assertTrue(self.existing.check_password(PASSWORD))
        self.assertEqual(User.objects.filter(email__iexact='taken@example.com').count(), 1)
        self.assertFalse(hasattr(self.existing, 'buyer_profile'))
        self.assertEqual(list(self.existing.roles.values_list('role', flat=True)), ['buyer'])

    def test_validation_errors_do_not_depend_on_whether_the_email_exists(self):
        bad = {**self.payload, 'password_confirm': 'does-not-match'}
        for email in ('taken@example.com', 'fresh@example.com'):
            response = self.client.post(reverse('accounts:register'), {**bad, 'email': email}, format='json')
            self.assertEqual(response.status_code, 400)
            self.assertEqual(list(response.json()['fields']), ['password_confirm'])
