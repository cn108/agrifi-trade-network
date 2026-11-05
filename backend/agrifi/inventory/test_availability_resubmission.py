from datetime import timedelta
from decimal import Decimal

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless

from django.db import IntegrityError, close_old_connections, transaction
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from agrifi.accounts.models import UserRole
from agrifi.catalog.models import CropCategory, Listing
from agrifi.catalog.tests import make_user
from agrifi.idempotency.models import IdempotencyRecord

from . import services as stock
from .models import HarvestBatch, Reservation

D = Decimal


def sync_id(n):
    return f'{n:08d}-1111-4111-8111-111111111111'


class Base(TestCase):
    def setUp(self):
        self.farmer = make_user('avail-farmer@example.com', UserRole.Role.FARMER)
        self.other_farmer = make_user('avail-farmer2@example.com', UserRole.Role.FARMER)
        self.buyer = make_user('avail-buyer@example.com', UserRole.Role.BUYER)
        self.admin = make_user('avail-ops@example.com', UserRole.Role.OPERATIONS_ADMIN)
        self.category = CropCategory.objects.create(name='Millet', slug='millet')

    def as_user(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def batch(self, quantity='100', accepted=True, farmer=None):
        batch = HarvestBatch.objects.create(
            farmer=farmer or self.farmer, category=self.category, quantity=quantity,
            unit_code='kg', harvested_on='2026-01-01',
        )
        if accepted:
            stock.accept_batch(batch.pk, self.admin)
        return batch

    def listing(self, **kwargs):
        fields = dict(seller=self.farmer, category=self.category, name='Millet', unit_code='kg',
                      unit_price_minor=1000, status=Listing.Status.ACTIVE)
        fields.update(kwargs)
        return Listing.objects.create(**fields)

    def shown(self, listing):
        rows = self.as_user(self.buyer).get(reverse('listing-list')).json()['results']
        return {row['id']: row['available_quantity'] for row in rows}[str(listing.pk)]


class ListingAvailabilityTests(Base):
    def test_list_query_count_does_not_grow_with_listing_count(self):
        def count_queries():
            with CaptureQueriesContext(connection) as queries:
                response = self.as_user(self.buyer).get(reverse('listing-list'))
            self.assertEqual(response.status_code, 200)
            return len(queries), len(response.json()['results'])

        batch = self.batch('1000')
        for _ in range(2):
            stock.allocate(self.listing().pk, batch.pk, '10', self.farmer)
        few_queries, few_rows = count_queries()
        for _ in range(8):
            listing = self.listing()
            stock.allocate(listing.pk, batch.pk, '10', self.farmer)
            stock.reserve(listing.pk, '3')
        many_queries, many_rows = count_queries()
        self.assertEqual((few_rows, many_rows), (2, 10))
        self.assertEqual(few_queries, many_queries)

    def test_only_accepted_stock_is_available(self):
        listing = self.listing()
        self.batch('50', accepted=False)
        self.assertEqual(self.shown(listing), '0.000')
        accepted = self.batch('50')
        stock.allocate(listing.pk, accepted.pk, '20', self.farmer)
        self.assertEqual(self.shown(listing), '20.000')

    def test_reservation_states_affect_availability_correctly(self):
        listing = self.listing()
        batch = self.batch('100')
        stock.allocate(listing.pk, batch.pk, '40', self.farmer)
        active = stock.reserve(listing.pk, '10')
        self.assertEqual(self.shown(listing), '30.000')

        expired = stock.reserve(listing.pk, '5')
        Reservation.objects.filter(pk=expired.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.shown(listing), '30.000')  # expired hold no longer reduces availability

        released = stock.reserve(listing.pk, '4')
        stock.release(released.pk)
        self.assertEqual(self.shown(listing), '30.000')

        stock.release(active.pk)
        self.assertEqual(self.shown(listing), '40.000')

        consumed = stock.reserve(listing.pk, '6')
        stock.commit_reservation(consumed.pk)
        stock.consume(consumed.pk)
        self.assertEqual(self.shown(listing), '34.000')  # sold stock leaves on-hand once

    def test_negative_availability_is_never_displayed(self):
        listing = self.listing()
        batch = self.batch('10')
        stock.allocate(listing.pk, batch.pk, '5', self.farmer)
        # Corrupt state bypassing the service: more reserved than on hand.
        Reservation.objects.create(listing=listing, quantity='9', expires_at=timezone.now() + timedelta(hours=1))
        self.assertLess(stock.listing_stock(listing)['available'], 0)
        self.assertEqual(self.shown(listing), '0.000')

    def test_annotation_matches_the_service_calculation(self):
        batch = self.batch('100')
        listings = [self.listing() for _ in range(3)]
        stock.allocate(listings[0].pk, batch.pk, '30', self.farmer)
        stock.allocate(listings[1].pk, batch.pk, '20', self.farmer)
        stock.reserve(listings[0].pk, '7')
        expired = stock.reserve(listings[1].pk, '2')
        Reservation.objects.filter(pk=expired.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        for row in stock.annotate_listing_stock(Listing.objects.all()):
            expected = stock.listing_stock(row)
            self.assertEqual(row.stock_on_hand, expected['on_hand'])
            self.assertEqual(row.stock_reserved, expected['reserved'])

    def test_checkout_validates_independently_of_displayed_availability(self):
        listing = self.listing()
        batch = self.batch('100')
        stock.allocate(listing.pk, batch.pk, '10', self.farmer)
        self.assertEqual(self.shown(listing), '10.000')  # buyer A and B both see 10
        body = lambda key: {
            'client_request_id': key, 'delivery_address': 'Kano',
            'items': [{'listing': str(listing.pk), 'quantity': '10'}],
        }
        buyer_b = make_user('avail-buyer-b@example.com', UserRole.Role.BUYER)
        self.assertEqual(self.as_user(self.buyer).post(
            reverse('order-list'), body(sync_id(1)), format='json').status_code, 201)
        stale = self.as_user(buyer_b).post(reverse('order-list'), body(sync_id(2)), format='json')
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self.shown(listing), '0.000')


class RejectedBatchResubmissionTests(Base):
    def submit(self, key, quantity='50', **extra):
        return self.as_user(self.farmer).post(reverse('harvest-batch-list'), {
            'category': str(self.category.id), 'quantity': quantity, 'unit_code': 'kg',
            'harvested_on': '2026-01-01', 'client_sync_id': key, **extra,
        }, format='json')

    def rejected(self, key=None):
        response = self.submit(key or sync_id(1))
        self.assertEqual(response.status_code, 201, response.content)
        batch_id = response.json()['id']
        stock.reject_batch(batch_id, self.admin, 'Moisture too high')
        return batch_id

    def test_farmer_sees_reason_and_correction_link(self):
        original = self.rejected()
        shown = self.as_user(self.farmer).get(reverse('harvest-batch-detail', args=[original])).json()
        self.assertEqual((shown['status'], shown['rejection_reason']), ('rejected', 'Moisture too high'))
        self.assertIsNone(shown['correction_id'])
        corrected = self.submit(sync_id(2), quantity='45', resubmission_of=original)
        self.assertEqual(corrected.status_code, 201, corrected.content)
        self.assertEqual(corrected.json()['resubmission_of'], original)
        self.assertEqual(corrected.json()['status'], 'submitted')
        after = self.as_user(self.farmer).get(reverse('harvest-batch-detail', args=[original])).json()
        self.assertEqual(after['status'], 'rejected')  # history is not rewritten
        self.assertEqual(after['correction_id'], corrected.json()['id'])
        self.assertEqual(HarvestBatch.objects.count(), 2)

    def test_retry_of_resubmission_replays_without_duplicating(self):
        original = self.rejected()
        first = self.submit(sync_id(2), quantity='45', resubmission_of=original)
        replay = self.submit(sync_id(2), quantity='45', resubmission_of=original)
        self.assertEqual((first.status_code, replay.status_code), (201, 200))
        self.assertEqual(first.json(), replay.json())
        self.assertEqual(HarvestBatch.objects.count(), 2)

    def test_same_key_with_different_original_or_payload_conflicts(self):
        original = self.rejected()
        self.submit(sync_id(2), quantity='45', resubmission_of=original)
        self.assertEqual(self.submit(sync_id(2), quantity='46', resubmission_of=original).status_code, 409)
        self.assertEqual(self.submit(sync_id(2), quantity='45').status_code, 409)
        # The rejected submission's own key cannot be reused for a corrected payload.
        self.assertEqual(self.submit(sync_id(1), quantity='45', resubmission_of=original).status_code, 409)

    def test_rejected_batch_can_only_be_corrected_once(self):
        original = self.rejected()
        self.assertEqual(self.submit(sync_id(2), resubmission_of=original).status_code, 201)
        second = self.submit(sync_id(3), resubmission_of=original)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(HarvestBatch.objects.filter(resubmission_of=original).count(), 1)
        self.assertFalse(IdempotencyRecord.objects.filter(key=sync_id(3)).exists())  # rolled back together

    def test_database_enforces_single_correction(self):
        original = HarvestBatch.objects.get(pk=self.rejected())
        make = lambda: HarvestBatch.objects.create(
            farmer=self.farmer, category=self.category, quantity='1', unit_code='kg',
            harvested_on='2026-01-01', resubmission_of=original)
        make()
        with self.assertRaises(IntegrityError), transaction.atomic():
            make()

    def test_only_own_rejected_batches_can_be_resubmitted(self):
        submitted = self.submit(sync_id(1)).json()['id']
        self.assertEqual(self.submit(sync_id(2), resubmission_of=submitted).status_code, 400)
        accepted = self.batch('10')
        self.assertEqual(self.submit(sync_id(3), resubmission_of=str(accepted.pk)).status_code, 400)
        theirs = self.batch('10', accepted=False, farmer=self.other_farmer)
        stock.reject_batch(theirs.pk, self.admin, 'no')
        self.assertEqual(self.submit(sync_id(4), resubmission_of=str(theirs.pk)).status_code, 400)
        self.assertFalse(HarvestBatch.objects.filter(resubmission_of__isnull=False).exists())

    def test_correction_creates_no_stock_until_accepted(self):
        original = self.rejected()
        self.submit(sync_id(2), resubmission_of=original)
        from .models import StockMovement
        self.assertFalse(StockMovement.objects.exists())

    def test_resubmission_link_cannot_be_edited_after_creation(self):
        original = self.rejected()
        corrected = self.submit(sync_id(2), resubmission_of=original).json()['id']
        other = self.rejected(sync_id(5))
        response = self.as_user(self.farmer).patch(
            reverse('harvest-batch-detail', args=[corrected]), {'resubmission_of': other}, format='json')
        self.assertEqual(response.status_code, 400)


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row locking and real concurrency.')
class ResubmissionConcurrencyTests(TransactionTestCase):
    """PostgreSQL-only; NOT yet executed (no PostgreSQL environment available)."""

    def test_concurrent_corrections_of_one_rejected_batch_create_exactly_one(self):
        farmer = make_user('rc-farmer@example.com', UserRole.Role.FARMER)
        admin = make_user('rc-ops@example.com', UserRole.Role.OPERATIONS_ADMIN)
        category = CropCategory.objects.create(name='Rice', slug='rice')
        original = HarvestBatch.objects.create(
            farmer=farmer, category=category, quantity='10', unit_code='kg', harvested_on='2026-01-01',
        )
        stock.reject_batch(original.pk, admin, 'wet')
        barrier = threading.Barrier(6)

        def submit(index):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(farmer)
                barrier.wait(timeout=10)
                return client.post(reverse('harvest-batch-list'), {
                    'category': str(category.id), 'quantity': '9', 'unit_code': 'kg',
                    'harvested_on': '2026-01-01', 'client_sync_id': sync_id(index + 1),
                    'resubmission_of': str(original.pk),
                }, format='json').status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=6) as executor:
            codes = list(executor.map(submit, range(6)))
        self.assertEqual(codes.count(201), 1, codes)
        self.assertEqual(codes.count(409), 5, codes)
        self.assertEqual(HarvestBatch.objects.filter(resubmission_of=original).count(), 1)
        self.assertEqual(IdempotencyRecord.objects.filter(scope='harvest_batch.create').count(), 1)
