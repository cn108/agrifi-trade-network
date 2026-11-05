from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from threading import Barrier
from types import SimpleNamespace
from unittest import mock

from django.db import close_old_connections
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from .models import BuyerProfile, FarmerProfile, RevokedRefreshToken, User, UserRole
from .permissions import HasRequiredRole, IsOwnerOrHasRequiredRole


class UserManagerTests(TestCase):
    def test_create_user_normalizes_email_and_hashes_password(self):
        user = User.objects.create_user(
            email='  Farmer@Example.COM ',
            password='test-password-123',
        )

        self.assertEqual(user.email, 'farmer@example.com')
        self.assertTrue(user.check_password('test-password-123'))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_superuser_sets_required_privileges(self):
        user = User.objects.create_superuser(
            email='admin@example.com',
            password='test-password-123',
        )

        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)


class HealthCheckTests(SimpleTestCase):
    def test_health_check_returns_ok(self):
        response = self.client.get(reverse('health-check'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})


class UserAdminTests(TestCase):
    def test_staff_can_open_add_user_form(self):
        admin_user = User.objects.create_superuser(
            email='admin@example.com',
            password='test-password-123',
        )
        self.client.force_login(admin_user)

        response = self.client.get(reverse('admin:accounts_user_add'))

        self.assertEqual(response.status_code, 200)


class AuthApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='buyer@example.com',
            password='strong-test-password-2026',
        )
        UserRole.objects.create(user=self.user, role=UserRole.Role.BUYER)

    def login(self, email='buyer@example.com', password='strong-test-password-2026'):
        return self.client.post(
            reverse('accounts:login'),
            {'email': email, 'password': password},
            format='json',
        )

    def test_invalid_credentials_are_rejected(self):
        response = self.login(password='incorrect-password')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('refresh', response.data)

    def test_registration_creates_hashed_password_and_limited_role(self):
        response = self.client.post(
            reverse('accounts:register'),
            {
                'email': ' New.Farmer@Example.com ',
                'password': 'strong-farmer-password-2026',
                'password_confirm': 'strong-farmer-password-2026',
                'role': UserRole.Role.FARMER,
                'display_name': 'Ada Farms',
                'region': 'Kaduna',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        created_user = User.objects.get(email='new.farmer@example.com')
        self.assertTrue(created_user.check_password('strong-farmer-password-2026'))
        self.assertEqual(list(created_user.roles.values_list('role', flat=True)), ['farmer'])
        self.assertEqual(created_user.farmer_profile.display_name, 'Ada Farms')
        self.assertEqual(created_user.farmer_profile.verification_status, 'unverified')
        self.assertNotIn('password', response.data)

    def test_registration_requires_role_specific_profile_name(self):
        base = {
            'email': 'noprofile@example.com',
            'password': 'strong-password-2026',
            'password_confirm': 'strong-password-2026',
        }
        farmer = self.client.post(
            reverse('accounts:register'), {**base, 'role': 'farmer'}, format='json'
        )
        buyer = self.client.post(reverse('accounts:register'), base, format='json')

        self.assertEqual(farmer.status_code, 400)
        self.assertIn('display_name', farmer.data['fields'])
        self.assertEqual(buyer.status_code, 400)
        self.assertIn('business_name', buyer.data['fields'])
        self.assertFalse(User.objects.filter(email='noprofile@example.com').exists())

    def test_buyer_registration_creates_buyer_profile(self):
        response = self.client.post(
            reverse('accounts:register'),
            {
                'email': 'shop@example.com',
                'password': 'strong-password-2026',
                'password_confirm': 'strong-password-2026',
                'business_name': 'Shop Ltd',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(User.objects.get(email='shop@example.com').buyer_profile.business_name, 'Shop Ltd')

    def test_registration_cannot_self_assign_privileged_role(self):
        response = self.client.post(
            reverse('accounts:register'),
            {
                'email': 'attacker@example.com',
                'password': 'strong-password-2026',
                'password_confirm': 'strong-password-2026',
                'role': UserRole.Role.OPERATIONS_ADMIN,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email='attacker@example.com').exists())

    def test_me_requires_authentication_and_returns_current_user(self):
        unauthenticated = self.client.get(reverse('accounts:me'))
        self.assertEqual(unauthenticated.status_code, 401)

        token_response = self.login()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_response.data['access']}")
        response = self.client.get(reverse('accounts:me'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], str(self.user.id))
        self.assertEqual(response.data['roles'], ['buyer'])

    def test_expired_access_token_is_rejected(self):
        from datetime import timedelta

        from rest_framework_simplejwt.tokens import AccessToken

        token = AccessToken.for_user(self.user)
        token.set_exp(lifetime=timedelta(seconds=-1))
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        response = self.client.get(reverse('accounts:me'))

        self.assertEqual(response.status_code, 401)

    def test_expired_refresh_token_is_rejected(self):
        from datetime import timedelta

        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(self.user)
        refresh.set_exp(lifetime=timedelta(seconds=-1))

        response = self.client.post(
            reverse('accounts:refresh'),
            {'refresh': str(refresh)},
            format='json',
        )

        self.assertEqual(response.status_code, 401)

    def test_identity_headers_do_not_authenticate_requests(self):
        response = self.client.get(
            reverse('accounts:me'),
            HTTP_X_USER_ID=str(self.user.id),
            HTTP_X_ADMIN_ID=str(self.user.id),
        )

        self.assertEqual(response.status_code, 401)

    def test_refresh_rotates_and_blacklists_previous_token(self):
        login = self.login()
        old_refresh = login.data['refresh']

        first_refresh = self.client.post(
            reverse('accounts:refresh'),
            {'refresh': old_refresh},
            format='json',
        )
        self.assertEqual(first_refresh.status_code, 200)
        self.assertNotEqual(first_refresh.data['refresh'], old_refresh)
        self.assertEqual(RevokedRefreshToken.objects.count(), 1)
        self.assertFalse(hasattr(RevokedRefreshToken, 'token'))

        reused_refresh = self.client.post(
            reverse('accounts:refresh'),
            {'refresh': old_refresh},
            format='json',
        )
        self.assertEqual(reused_refresh.status_code, 401)

        second_refresh = self.client.post(
            reverse('accounts:refresh'),
            {'refresh': first_refresh.data['refresh']},
            format='json',
        )
        self.assertEqual(second_refresh.status_code, 200)

    def test_revocation_cannot_be_applied_twice(self):
        from rest_framework_simplejwt.exceptions import TokenError

        from .tokens import RevocableRefreshToken

        login = self.login()
        token = RevocableRefreshToken(login.data['refresh'])
        token.blacklist()

        with self.assertRaises(TokenError):
            token.blacklist()

    def test_expired_revocation_records_can_be_purged(self):
        expired = RevokedRefreshToken.objects.create(
            user=self.user,
            jti='expired-jti',
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        current = RevokedRefreshToken.objects.create(
            user=self.user,
            jti='current-jti',
            expires_at=timezone.now() + timedelta(days=1),
        )
        output = StringIO()

        call_command('purge_expired_refresh_tokens', stdout=output)

        self.assertFalse(RevokedRefreshToken.objects.filter(pk=expired.pk).exists())
        self.assertTrue(RevokedRefreshToken.objects.filter(pk=current.pk).exists())
        self.assertIn('Deleted 1', output.getvalue())

    def test_logout_revokes_refresh_token(self):
        login = self.login()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        logout = self.client.post(
            reverse('accounts:logout'),
            {'refresh': login.data['refresh']},
            format='json',
        )
        self.assertEqual(logout.status_code, 200)

        refresh = self.client.post(
            reverse('accounts:refresh'),
            {'refresh': login.data['refresh']},
            format='json',
        )
        self.assertEqual(refresh.status_code, 401)

    def test_logout_rejects_another_users_refresh_token(self):
        other_user = User.objects.create_user(
            email='other@example.com',
            password='other-strong-password-2026',
        )
        other_tokens = self.client.post(
            reverse('accounts:login'),
            {'email': other_user.email, 'password': 'other-strong-password-2026'},
            format='json',
        )
        own_tokens = self.login()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {own_tokens.data['access']}")

        response = self.client.post(
            reverse('accounts:logout'),
            {'refresh': other_tokens.data['refresh']},
            format='json',
        )

        self.assertEqual(response.status_code, 403)
        still_valid = self.client.post(
            reverse('accounts:refresh'),
            {'refresh': other_tokens.data['refresh']},
            format='json',
        )
        self.assertEqual(still_valid.status_code, 200)


class PermissionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email='owner@example.com',
            password='owner-strong-password-2026',
        )
        self.other_user = User.objects.create_user(
            email='other@example.com',
            password='other-strong-password-2026',
        )

    def test_role_permission_denies_and_allows_approved_role(self):
        class ProtectedView(APIView):
            permission_classes = (IsAuthenticated, HasRequiredRole)
            required_roles = (UserRole.Role.OPERATIONS_ADMIN,)

            def get(self, request, *args, **kwargs):
                return Response({'ok': True})

        view = ProtectedView.as_view()
        factory = APIRequestFactory()
        request = factory.get('/protected/')
        force_authenticate(request, user=self.owner)
        self.assertEqual(view(request).status_code, 403)

        UserRole.objects.create(user=self.owner, role=UserRole.Role.OPERATIONS_ADMIN)
        request = factory.get('/protected/')
        force_authenticate(request, user=self.owner)
        self.assertEqual(view(request).status_code, 200)

    def test_object_permission_denies_cross_user_access(self):
        class OwnerView(APIView):
            permission_classes = (IsAuthenticated, IsOwnerOrHasRequiredRole)
            owner_field = 'owner'

            def get(self, request, *args, **kwargs):
                self.check_object_permissions(
                    request,
                    SimpleNamespace(owner_id=self.kwargs['owner_id']),
                )
                return Response({'ok': True})

        view = OwnerView.as_view()
        factory = APIRequestFactory()
        request = factory.get('/owned/')
        force_authenticate(request, user=self.other_user)
        response = view(request, owner_id=self.owner.id)

        self.assertEqual(response.status_code, 403)

        request = factory.get('/owned/')
        force_authenticate(request, user=self.owner)
        self.assertEqual(view(request, owner_id=self.owner.id).status_code, 200)


class ProfileApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.farmer = User.objects.create_user(email='f@example.com', password='pw-farmer-2026-xyz')
        UserRole.objects.create(user=self.farmer, role=UserRole.Role.FARMER)
        FarmerProfile.objects.create(user=self.farmer, display_name='Farm A')
        self.buyer = User.objects.create_user(email='b@example.com', password='pw-buyer-2026-xyz')
        UserRole.objects.create(user=self.buyer, role=UserRole.Role.BUYER)
        BuyerProfile.objects.create(user=self.buyer, business_name='Buyer A')

    def test_farmer_reads_and_updates_own_profile_but_not_verification(self):
        self.client.force_authenticate(self.farmer)
        url = reverse('accounts:farmer-profile')
        response = self.client.patch(
            url, {'region': 'Kano', 'verification_status': 'verified'}, format='json'
        )

        self.assertEqual(response.status_code, 200)
        self.farmer.farmer_profile.refresh_from_db()
        self.assertEqual(self.farmer.farmer_profile.region, 'Kano')
        self.assertEqual(self.farmer.farmer_profile.verification_status, 'unverified')

    def test_buyer_reads_and_updates_own_profile(self):
        self.client.force_authenticate(self.buyer)
        url = reverse('accounts:buyer-profile')
        self.assertEqual(self.client.get(url).data['business_name'], 'Buyer A')
        self.assertEqual(self.client.patch(url, {'location': 'Lagos'}, format='json').status_code, 200)

    def test_profiles_are_role_restricted_and_authenticated(self):
        self.assertEqual(self.client.get(reverse('accounts:farmer-profile')).status_code, 401)
        self.client.force_authenticate(self.buyer)
        self.assertEqual(self.client.get(reverse('accounts:farmer-profile')).status_code, 403)
        self.client.force_authenticate(self.farmer)
        self.assertEqual(self.client.get(reverse('accounts:buyer-profile')).status_code, 403)

    def test_profile_endpoint_never_returns_another_users_profile(self):
        other = User.objects.create_user(email='f2@example.com', password='pw-farmer2-2026-xyz')
        UserRole.objects.create(user=other, role=UserRole.Role.FARMER)
        FarmerProfile.objects.create(user=other, display_name='Farm B')
        self.client.force_authenticate(self.farmer)

        self.assertEqual(self.client.get(reverse('accounts:farmer-profile')).data['display_name'], 'Farm A')


class RegistrationIntegrityAndEscalationTests(TestCase):
    password = 'strong-password-2026'

    def register_payload(self, **overrides):
        payload = {
            'email': 'rb@example.com', 'password': self.password,
            'password_confirm': self.password, 'role': 'farmer', 'display_name': 'Rollback Farm',
        }
        payload.update(overrides)
        return payload

    def test_registration_rolls_back_user_and_role_when_profile_creation_fails(self):
        with mock.patch.object(FarmerProfile.objects, 'create', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                APIClient().post(reverse('accounts:register'), self.register_payload(), format='json')

        self.assertFalse(User.objects.filter(email='rb@example.com').exists())
        self.assertEqual(UserRole.objects.count(), 0)
        self.assertEqual(FarmerProfile.objects.count(), 0)

    def test_buyer_registration_rolls_back_when_profile_creation_fails(self):
        payload = self.register_payload(role='buyer', business_name='B Ltd')
        with mock.patch.object(BuyerProfile.objects, 'create', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                APIClient().post(reverse('accounts:register'), payload, format='json')
        self.assertFalse(User.objects.filter(email='rb@example.com').exists())
        self.assertEqual(UserRole.objects.count(), 0)

    def test_registration_ignores_privilege_and_verification_fields(self):
        response = APIClient().post(
            reverse('accounts:register'),
            self.register_payload(
                verification_status='verified', is_superuser=True, is_staff=True, roles=['operations_admin'],
            ),
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(email='rb@example.com')
        self.assertFalse(user.is_superuser or user.is_staff)
        self.assertEqual(list(user.roles.values_list('role', flat=True)), ['farmer'])
        self.assertEqual(user.farmer_profile.verification_status, 'unverified')

    def test_me_endpoint_cannot_change_roles_email_or_privileges(self):
        user = User.objects.create_user(email='me@example.com', password='pw-me-2026-strong')
        UserRole.objects.create(user=user, role=UserRole.Role.BUYER)
        client = APIClient()
        client.force_authenticate(user)
        response = client.patch(
            reverse('accounts:me'),
            {'roles': ['operations_admin'], 'is_superuser': True, 'is_staff': True,
             'email': 'new@example.com', 'first_name': 'Okay'},
            format='json',
        )
        user.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(user.first_name, 'Okay')
        self.assertEqual(user.email, 'me@example.com')
        self.assertFalse(user.is_superuser or user.is_staff)
        self.assertEqual(list(user.roles.values_list('role', flat=True)), ['buyer'])

    def test_buyer_profile_verification_cannot_be_self_set(self):
        user = User.objects.create_user(email='bp@example.com', password='pw-bp-2026-strong')
        UserRole.objects.create(user=user, role=UserRole.Role.BUYER)
        BuyerProfile.objects.create(user=user, business_name='BP')
        client = APIClient()
        client.force_authenticate(user)
        client.patch(reverse('accounts:buyer-profile'), {'verification_status': 'verified'}, format='json')
        user.buyer_profile.refresh_from_db()
        self.assertEqual(user.buyer_profile.verification_status, 'unverified')

    def test_finance_operator_has_no_profile_access(self):
        user = User.objects.create_user(email='fin@example.com', password='pw-fin-2026-strong')
        UserRole.objects.create(user=user, role=UserRole.Role.FINANCE_OPERATOR)
        client = APIClient()
        client.force_authenticate(user)
        self.assertEqual(client.get(reverse('accounts:farmer-profile')).status_code, 403)
        self.assertEqual(client.get(reverse('accounts:buyer-profile')).status_code, 403)

    def test_superuser_without_farmer_role_cannot_use_farmer_profile(self):
        user = User.objects.create_superuser(email='root@example.com', password='pw-root-2026-strong')
        client = APIClient()
        client.force_authenticate(user)
        self.assertEqual(client.get(reverse('accounts:farmer-profile')).status_code, 403)


class CookieTokenTransportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='browser@example.com',
            password='browser-strong-password-2026',
        )
        self.client = APIClient(enforce_csrf_checks=True)

    def csrf_headers(self):
        response = self.client.get(reverse('accounts:csrf'))
        return {'HTTP_X_CSRFTOKEN': response.json()['csrfToken']}

    def test_cookie_transport_requires_csrf_and_hides_refresh_token(self):
        login_url = reverse('accounts:login')
        credentials = {
            'email': self.user.email,
            'password': 'browser-strong-password-2026',
            'token_transport': 'cookie',
        }

        denied = self.client.post(login_url, credentials, format='json')
        self.assertEqual(denied.status_code, 403)

        response = self.client.post(
            login_url,
            credentials,
            format='json',
            **self.csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)
        self.assertNotIn('refresh', response.data)
        self.assertTrue(self.client.cookies['agrifi_refresh']['httponly'])
        self.assertEqual(self.client.cookies['agrifi_refresh']['samesite'], 'Lax')

    def test_cookie_refresh_rotates_cookie_and_logout_revokes_it(self):
        headers = self.csrf_headers()
        login = self.client.post(
            reverse('accounts:login'),
            {
                'email': self.user.email,
                'password': 'browser-strong-password-2026',
                'token_transport': 'cookie',
            },
            format='json',
            **headers,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        old_refresh = self.client.cookies['agrifi_refresh'].value

        csrf_denied = self.client.post(
            reverse('accounts:refresh'),
            {'token_transport': 'cookie'},
            format='json',
        )
        self.assertEqual(csrf_denied.status_code, 403)
        self.assertEqual(self.client.cookies['agrifi_refresh'].value, old_refresh)

        refreshed = self.client.post(
            reverse('accounts:refresh'),
            {'token_transport': 'cookie'},
            format='json',
            **headers,
        )
        self.assertEqual(refreshed.status_code, 200)
        self.assertNotIn('refresh', refreshed.data)
        new_refresh = self.client.cookies['agrifi_refresh'].value
        self.assertNotEqual(new_refresh, old_refresh)

        logout = self.client.post(
            reverse('accounts:logout'),
            {'token_transport': 'cookie'},
            format='json',
            **headers,
        )
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(self.client.cookies['agrifi_refresh'].value, '')


@skipUnlessDBFeature('has_select_for_update')
class RefreshConcurrencyTests(TransactionTestCase):
    def test_only_one_concurrent_refresh_request_succeeds(self):
        user = User.objects.create_user(
            email='concurrent@example.com',
            password='concurrent-strong-password-2026',
        )
        login = APIClient().post(
            reverse('accounts:login'),
            {'email': user.email, 'password': 'concurrent-strong-password-2026'},
            format='json',
        )
        refresh_token = login.data['refresh']
        barrier = Barrier(2)

        def refresh():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                response = APIClient().post(
                    reverse('accounts:refresh'),
                    {'refresh': refresh_token},
                    format='json',
                )
                return response.status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = sorted(executor.map(lambda _: refresh(), range(2)))

        self.assertEqual(statuses, [200, 401])
