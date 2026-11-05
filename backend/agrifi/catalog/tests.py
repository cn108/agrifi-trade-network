from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from agrifi.accounts.models import BuyerProfile, FarmerProfile, User, UserRole

from .models import CropCategory, Listing


def make_user(email, role, **extra):
    user = User.objects.create_user(email=email, password='pw-test-2026-strong', **extra)
    UserRole.objects.create(user=user, role=role)
    if role == UserRole.Role.FARMER:
        FarmerProfile.objects.create(user=user, display_name=email)
    if role == UserRole.Role.BUYER:
        BuyerProfile.objects.create(user=user, business_name=email)
    return user


class CatalogTestBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.farmer = make_user('farmer@example.com', UserRole.Role.FARMER)
        self.other_farmer = make_user('farmer2@example.com', UserRole.Role.FARMER)
        self.buyer = make_user('buyer@example.com', UserRole.Role.BUYER)
        self.admin = make_user('ops@example.com', UserRole.Role.OPERATIONS_ADMIN)
        self.category = CropCategory.objects.create(name='Maize', slug='maize')

    def listing_payload(self, **overrides):
        payload = {
            'category': str(self.category.id),
            'name': 'Yellow maize',
            'unit_code': 'kg',
            'unit_price_minor': 45000,
            'status': 'active',
        }
        payload.update(overrides)
        return payload

    def make_listing(self, seller, **overrides):
        fields = dict(
            seller=seller, category=self.category, name='Item', unit_code='kg',
            unit_price_minor=1000, status=Listing.Status.ACTIVE,
        )
        fields.update(overrides)
        return Listing.objects.create(**fields)


class CategoryApiTests(CatalogTestBase):
    def test_requires_authentication(self):
        self.assertEqual(self.client.get(reverse('category-list')).status_code, 401)

    def test_buyer_reads_active_only_and_cannot_write(self):
        CropCategory.objects.create(name='Hidden', slug='hidden', is_active=False)
        self.client.force_authenticate(self.buyer)
        response = self.client.get(reverse('category-list'))

        self.assertEqual([c['slug'] for c in response.data['results']], ['maize'])
        denied = self.client.post(reverse('category-list'), {'name': 'Rice'}, format='json')
        self.assertEqual(denied.status_code, 403)

    def test_admin_creates_with_generated_slug_and_sees_inactive(self):
        self.client.force_authenticate(self.admin)
        created = self.client.post(reverse('category-list'), {'name': 'Sweet Potato'}, format='json')
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data['slug'], 'sweet-potato')

        self.client.patch(
            reverse('category-detail', args=[self.category.id]), {'is_active': False}, format='json'
        )
        slugs = [c['slug'] for c in self.client.get(reverse('category-list')).data['results']]
        self.assertIn('maize', slugs)

    def test_farmer_cannot_create_category_and_delete_is_not_allowed(self):
        self.client.force_authenticate(self.farmer)
        self.assertEqual(
            self.client.post(reverse('category-list'), {'name': 'Rice'}, format='json').status_code, 403
        )
        self.client.force_authenticate(self.admin)
        self.assertEqual(
            self.client.delete(reverse('category-detail', args=[self.category.id])).status_code, 405
        )


class ListingApiTests(CatalogTestBase):
    def test_farmer_creates_listing_and_seller_is_server_assigned(self):
        self.client.force_authenticate(self.farmer)
        response = self.client.post(
            reverse('listing-list'),
            self.listing_payload(seller=str(self.other_farmer.id), currency='USD'),
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        listing = Listing.objects.get(id=response.data['id'])
        self.assertEqual(listing.seller, self.farmer)
        self.assertEqual(listing.currency, 'NGN')

    def test_buyer_and_admin_cannot_create_listings(self):
        for user in (self.buyer, self.admin):
            self.client.force_authenticate(user)
            response = self.client.post(reverse('listing-list'), self.listing_payload(), format='json')
            self.assertEqual(response.status_code, 403)

    def test_price_must_be_positive_integer_minor_units(self):
        self.client.force_authenticate(self.farmer)
        for bad in (0, -5, 10.5, 'abc'):
            response = self.client.post(
                reverse('listing-list'), self.listing_payload(unit_price_minor=bad), format='json'
            )
            self.assertEqual(response.status_code, 400, bad)

    def test_inactive_category_rejected(self):
        self.category.is_active = False
        self.category.save()
        self.client.force_authenticate(self.farmer)
        response = self.client.post(reverse('listing-list'), self.listing_payload(), format='json')
        self.assertEqual(response.status_code, 400)

    def test_buyer_sees_only_active_listings(self):
        active = self.make_listing(self.farmer)
        self.make_listing(self.farmer, status=Listing.Status.DRAFT)
        self.make_listing(self.farmer, status=Listing.Status.SUSPENDED)
        self.client.force_authenticate(self.buyer)

        ids = [item['id'] for item in self.client.get(reverse('listing-list')).data['results']]
        self.assertEqual(ids, [str(active.id)])

    def test_buyer_cannot_fetch_draft_listing(self):
        draft = self.make_listing(self.farmer, status=Listing.Status.DRAFT)
        self.client.force_authenticate(self.buyer)
        self.assertEqual(self.client.get(reverse('listing-detail', args=[draft.id])).status_code, 404)

    def test_hidden_when_category_or_seller_inactive(self):
        self.make_listing(self.farmer)
        self.client.force_authenticate(self.buyer)
        self.category.is_active = False
        self.category.save()
        self.assertEqual(self.client.get(reverse('listing-list')).data['count'], 0)
        self.category.is_active = True
        self.category.save()
        self.farmer.is_active = False
        self.farmer.save()
        self.assertEqual(self.client.get(reverse('listing-list')).data['count'], 0)

    def test_farmer_sees_own_drafts_but_not_other_farmers_drafts(self):
        mine = self.make_listing(self.farmer, status=Listing.Status.DRAFT)
        self.make_listing(self.other_farmer, status=Listing.Status.DRAFT)
        self.client.force_authenticate(self.farmer)
        ids = [item['id'] for item in self.client.get(reverse('listing-list')).data['results']]
        self.assertEqual(ids, [str(mine.id)])

    def test_cross_user_update_is_forbidden(self):
        listing = self.make_listing(self.farmer)
        self.client.force_authenticate(self.other_farmer)
        response = self.client.patch(
            reverse('listing-detail', args=[listing.id]), {'name': 'Hijacked'}, format='json'
        )
        self.assertEqual(response.status_code, 403)
        self.client.force_authenticate(self.buyer)
        self.assertEqual(
            self.client.patch(
                reverse('listing-detail', args=[listing.id]), {'name': 'x'}, format='json'
            ).status_code,
            403,
        )
        listing.refresh_from_db()
        self.assertEqual(listing.name, 'Item')

    def test_owner_cannot_change_seller_or_suspend(self):
        listing = self.make_listing(self.farmer)
        self.client.force_authenticate(self.farmer)
        url = reverse('listing-detail', args=[listing.id])
        self.client.patch(url, {'seller': str(self.other_farmer.id)}, format='json')
        listing.refresh_from_db()
        self.assertEqual(listing.seller, self.farmer)

        response = self.client.patch(url, {'status': 'suspended'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_admin_suspends_and_owner_cannot_edit_suspended(self):
        listing = self.make_listing(self.farmer)
        url = reverse('listing-detail', args=[listing.id])
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.patch(url, {'status': 'suspended'}, format='json').status_code, 200)

        self.client.force_authenticate(self.farmer)
        self.assertEqual(self.client.patch(url, {'status': 'active'}, format='json').status_code, 403)

    def test_archived_is_terminal_for_owner(self):
        listing = self.make_listing(self.farmer, status=Listing.Status.ARCHIVED)
        self.client.force_authenticate(self.farmer)
        response = self.client.patch(
            reverse('listing-detail', args=[listing.id]), {'status': 'active'}, format='json'
        )
        self.assertEqual(response.status_code, 400)

    def test_delete_not_allowed_and_unauthenticated_denied(self):
        listing = self.make_listing(self.farmer)
        url = reverse('listing-detail', args=[listing.id])
        self.assertEqual(self.client.get(url).status_code, 401)
        self.client.force_authenticate(self.farmer)
        self.assertEqual(self.client.delete(url).status_code, 405)

    def test_filters_and_page_size_cap(self):
        self.make_listing(self.farmer, name='Maize A')
        self.make_listing(self.farmer, name='Beans')
        self.client.force_authenticate(self.buyer)
        url = reverse('listing-list')
        self.assertEqual(self.client.get(url, {'q': 'maize'}).data['count'], 1)
        self.assertEqual(self.client.get(url, {'category': 'not-a-uuid'}).status_code, 400)
        self.assertEqual(self.client.get(url, {'page_size': 1}).data['results'].__len__(), 1)

    def test_missing_and_invalid_units_rejected(self):
        self.client.force_authenticate(self.farmer)
        url = reverse('listing-list')
        missing = self.listing_payload()
        del missing['unit_code']
        for payload in (missing, self.listing_payload(unit_code='lbs'), self.listing_payload(unit_code='')):
            self.assertEqual(self.client.post(url, payload, format='json').status_code, 400)
        self.assertEqual(Listing.objects.count(), 0)

    def test_unit_cannot_be_cleared_or_invalidated_on_update(self):
        listing = self.make_listing(self.farmer)
        self.client.force_authenticate(self.farmer)
        url = reverse('listing-detail', args=[listing.id])
        self.assertEqual(self.client.patch(url, {'unit_code': 'lbs'}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(url, {'unit_code': ''}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(url, {'unit_code': 'bag'}, format='json').status_code, 200)

    def test_database_rejects_non_positive_price(self):
        for price in (0, -1):
            with self.assertRaises(IntegrityError), transaction.atomic():
                self.make_listing(self.farmer, unit_price_minor=price)

    def test_category_deactivation_hides_existing_listings_from_buyers_only(self):
        listing = self.make_listing(self.farmer)
        self.category.is_active = False
        self.category.save()

        self.client.force_authenticate(self.buyer)
        self.assertEqual(self.client.get(reverse('listing-list')).data['count'], 0)
        self.assertEqual(self.client.get(reverse('listing-detail', args=[listing.id])).status_code, 404)

        self.client.force_authenticate(self.farmer)
        self.assertEqual(self.client.get(reverse('listing-detail', args=[listing.id])).status_code, 200)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(reverse('listing-detail', args=[listing.id])).status_code, 200)
        listing.refresh_from_db()
        self.assertEqual(listing.status, Listing.Status.ACTIVE)

    def test_inactive_category_blocks_new_and_reassigned_listings(self):
        listing = self.make_listing(self.farmer)
        self.category.is_active = False
        self.category.save()
        self.client.force_authenticate(self.farmer)

        created = self.client.post(reverse('listing-list'), self.listing_payload(), format='json')
        moved = self.client.patch(
            reverse('listing-detail', args=[listing.id]),
            {'category': str(self.category.id)},
            format='json',
        )
        self.assertEqual(created.status_code, 400)
        self.assertEqual(moved.status_code, 400)

    def test_reactivating_category_restores_buyer_visibility(self):
        self.make_listing(self.farmer)
        self.category.is_active = False
        self.category.save()
        self.category.is_active = True
        self.category.save()
        self.client.force_authenticate(self.buyer)
        self.assertEqual(self.client.get(reverse('listing-list')).data['count'], 1)

    def test_category_with_listings_cannot_be_deleted(self):
        self.make_listing(self.farmer)
        with self.assertRaises(ProtectedError):
            self.category.delete()

    def test_finance_operator_has_no_catalogue_privileges(self):
        finance = make_user('fin@example.com', UserRole.Role.FINANCE_OPERATOR)
        draft = self.make_listing(self.farmer, status=Listing.Status.DRAFT)
        active = self.make_listing(self.farmer)
        self.client.force_authenticate(finance)

        self.assertEqual(self.client.get(reverse('listing-detail', args=[draft.id])).status_code, 404)
        self.assertEqual(
            self.client.patch(reverse('listing-detail', args=[active.id]), {'name': 'x'}, format='json').status_code,
            403,
        )
        self.assertEqual(
            self.client.patch(
                reverse('listing-detail', args=[active.id]), {'status': 'suspended'}, format='json'
            ).status_code,
            403,
        )
        self.assertEqual(self.client.post(reverse('listing-list'), self.listing_payload(), format='json').status_code, 403)
        self.assertEqual(self.client.post(reverse('category-list'), {'name': 'Z'}, format='json').status_code, 403)

    def test_operations_admin_cannot_use_farmer_only_endpoints(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(reverse('accounts:farmer-profile')).status_code, 403)
        self.assertEqual(self.client.post(reverse('listing-list'), self.listing_payload(), format='json').status_code, 403)

    def test_farmer_cannot_read_another_farmers_draft_or_edit_active_listing(self):
        draft = self.make_listing(self.other_farmer, status=Listing.Status.DRAFT)
        active = self.make_listing(self.other_farmer)
        self.client.force_authenticate(self.farmer)
        self.assertEqual(self.client.get(reverse('listing-detail', args=[draft.id])).status_code, 404)
        self.assertEqual(
            self.client.patch(reverse('listing-detail', args=[draft.id]), {'name': 'x'}, format='json').status_code,
            404,
        )
        self.assertEqual(
            self.client.patch(reverse('listing-detail', args=[active.id]), {'status': 'paused'}, format='json').status_code,
            403,
        )
        active.refresh_from_db()
        self.assertEqual(active.status, Listing.Status.ACTIVE)

    def test_buyer_cannot_use_farmer_only_endpoints(self):
        self.client.force_authenticate(self.buyer)
        self.assertEqual(self.client.get(reverse('accounts:farmer-profile')).status_code, 403)
        self.assertEqual(self.client.get(reverse('harvest-batch-list')).status_code, 403)
        self.assertEqual(self.client.post(reverse('listing-list'), self.listing_payload(), format='json').status_code, 403)
