from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless

from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from agrifi.accounts.models import UserRole
from agrifi.catalog.models import CropCategory, Listing
from agrifi.catalog.tests import make_user

from . import services as stock
from .models import HarvestBatch, ImmutableRecordError, Reservation, StockMovement

D = Decimal


class StockFixtureMixin:
    def build(self):
        self.farmer = make_user('s-farmer@example.com', UserRole.Role.FARMER)
        self.other = make_user('s-farmer2@example.com', UserRole.Role.FARMER)
        self.buyer = make_user('s-buyer@example.com', UserRole.Role.BUYER)
        self.admin = make_user('s-ops@example.com', UserRole.Role.OPERATIONS_ADMIN)
        self.finance = make_user('s-fin@example.com', UserRole.Role.FINANCE_OPERATOR)
        self.category = CropCategory.objects.create(name='Maize', slug='maize')

    def batch(self, quantity='100', farmer=None, accepted=True, unit='kg'):
        batch = HarvestBatch.objects.create(
            farmer=farmer or self.farmer, category=self.category, quantity=quantity,
            unit_code=unit, harvested_on='2026-01-01',
        )
        if accepted:
            stock.accept_batch(batch.pk, self.admin)
            batch.refresh_from_db()
        return batch

    def listing(self, seller=None, status=Listing.Status.ACTIVE, unit='kg'):
        return Listing.objects.create(
            seller=seller or self.farmer, category=self.category, name='Maize',
            unit_code=unit, unit_price_minor=50000, status=status,
        )


class StockServiceTests(StockFixtureMixin, TestCase):
    def setUp(self):
        self.build()

    def test_accept_posts_one_receipt_and_makes_batch_free(self):
        batch = self.batch('100')
        self.assertEqual(batch.status, 'accepted')
        self.assertEqual(batch.reviewed_by, self.admin)
        self.assertEqual(StockMovement.objects.filter(batch=batch, movement_type='receipt').count(), 1)
        self.assertEqual(stock.batch_free(batch), D('100'))

    def test_cannot_accept_twice_or_after_rejection(self):
        batch = self.batch('10')
        with self.assertRaises(stock.InventoryError):
            stock.accept_batch(batch.pk, self.admin)
        rejected = self.batch('10', accepted=False)
        stock.reject_batch(rejected.pk, self.admin, 'bad')
        with self.assertRaises(stock.InventoryError):
            stock.accept_batch(rejected.pk, self.admin)
        self.assertFalse(StockMovement.objects.filter(batch=rejected).exists())

    def test_cannot_accept_batch_with_inactive_category(self):
        batch = self.batch('10', accepted=False)
        CropCategory.objects.filter(pk=self.category.pk).update(is_active=False)
        with self.assertRaises(stock.InventoryError) as ctx:
            stock.accept_batch(batch.pk, self.admin)
        self.assertEqual(ctx.exception.code, 'inactive_category')

    def test_allocation_moves_stock_from_batch_to_listing(self):
        batch, listing = self.batch('100'), self.listing()
        stock.allocate(listing.pk, batch.pk, '40', self.farmer)
        self.assertEqual(stock.batch_free(batch), D('60'))
        self.assertEqual(stock.listing_stock(listing), {
            'on_hand': D('40'), 'reserved': D('0'), 'available': D('40'),
        })

    def test_allocation_cannot_exceed_batch_free_stock(self):
        batch, listing = self.batch('100'), self.listing()
        stock.allocate(listing.pk, batch.pk, '70', self.farmer)
        with self.assertRaises(stock.InsufficientStock):
            stock.allocate(listing.pk, batch.pk, '30.001', self.farmer)
        stock.allocate(listing.pk, batch.pk, '30', self.farmer)
        self.assertEqual(stock.batch_free(batch), D('0'))

    def test_allocation_rules(self):
        batch, listing = self.batch('100'), self.listing()
        unaccepted = self.batch('5', accepted=False)
        with self.assertRaises(stock.InventoryError) as ctx:
            stock.allocate(listing.pk, unaccepted.pk, '1', self.farmer)
        self.assertEqual(ctx.exception.code, 'batch_not_accepted')
        with self.assertRaises(stock.InventoryError) as ctx:
            stock.allocate(self.listing(seller=self.other).pk, batch.pk, '1', self.farmer)
        self.assertEqual(ctx.exception.code, 'owner_mismatch')
        with self.assertRaises(stock.InventoryError) as ctx:
            stock.allocate(self.listing(unit='bag').pk, batch.pk, '1', self.farmer)
        self.assertEqual(ctx.exception.code, 'mismatch')
        for bad in ('0', '-1', '1.0001'):
            with self.assertRaises(stock.InventoryError) as ctx:
                stock.allocate(listing.pk, batch.pk, bad, self.farmer)
            self.assertEqual(ctx.exception.code, 'invalid_quantity')
        self.assertEqual(StockMovement.objects.filter(movement_type='allocation').count(), 0)

    def test_deallocation_returns_stock_but_not_reserved_or_foreign_stock(self):
        batch, listing = self.batch('100'), self.listing()
        stock.allocate(listing.pk, batch.pk, '50', self.farmer)
        stock.reserve(listing.pk, '30')
        with self.assertRaises(stock.InsufficientStock):
            stock.deallocate(listing.pk, batch.pk, '21', self.farmer)
        stock.deallocate(listing.pk, batch.pk, '20', self.farmer)
        self.assertEqual(stock.batch_free(batch), D('70'))
        self.assertEqual(stock.listing_stock(listing)['available'], D('0'))
        other_batch = self.batch('10')
        with self.assertRaises(stock.InsufficientStock):
            stock.deallocate(listing.pk, other_batch.pk, '1', self.farmer)

    def test_reserve_prevents_overselling(self):
        batch, listing = self.batch('100'), self.listing()
        stock.allocate(listing.pk, batch.pk, '10', self.farmer)
        stock.reserve(listing.pk, '6')
        with self.assertRaises(stock.InsufficientStock):
            stock.reserve(listing.pk, '4.001')
        stock.reserve(listing.pk, '4')
        self.assertEqual(stock.listing_stock(listing)['available'], D('0'))

    def test_reserve_requires_active_listing(self):
        batch = self.batch('100')
        listing = self.listing(status=Listing.Status.PAUSED)
        stock.allocate(listing.pk, batch.pk, '10', self.farmer)
        with self.assertRaises(stock.InventoryError) as ctx:
            stock.reserve(listing.pk, '1')
        self.assertEqual(ctx.exception.code, 'listing_not_active')

    def test_release_restores_availability_and_cannot_repeat(self):
        batch, listing = self.batch('100'), self.listing()
        stock.allocate(listing.pk, batch.pk, '10', self.farmer)
        reservation = stock.reserve(listing.pk, '10')
        stock.release(reservation.pk)
        self.assertEqual(stock.listing_stock(listing)['available'], D('10'))
        with self.assertRaises(stock.InventoryError):
            stock.release(reservation.pk)

    def test_committed_reservation_does_not_expire_or_restore_availability(self):
        batch, listing = self.batch('100'), self.listing()
        stock.allocate(listing.pk, batch.pk, '10', self.farmer)
        reservation = stock.reserve(listing.pk, '10', ttl=timedelta(seconds=-1))
        with self.assertRaises(stock.InventoryError):
            stock.commit_reservation(reservation.pk)
        reservation = stock.reserve(listing.pk, '10')
        stock.commit_reservation(reservation.pk)
        reservation.refresh_from_db()
        self.assertIsNone(reservation.expires_at)
        self.assertEqual(stock.listing_stock(listing)['available'], D('0'))
        self.assertEqual(stock.expire_reservations(now=timezone.now() + timedelta(days=365)), 1)
        self.assertEqual(stock.listing_stock(listing)['available'], D('0'))
        self.assertEqual(stock.expire_reservations(now=timezone.now() + timedelta(days=365)), 0)
        stock.consume(reservation.pk, self.farmer)
        self.assertEqual(stock.listing_stock(listing)['on_hand'], D('0'))

    def test_expired_reservation_stops_counting_immediately_and_is_marked_by_job(self):
        batch, listing = self.batch('100'), self.listing()
        stock.allocate(listing.pk, batch.pk, '10', self.farmer)
        reservation = stock.reserve(listing.pk, '10', ttl=timedelta(seconds=-1))
        self.assertEqual(stock.listing_stock(listing)['available'], D('10'))
        with self.assertRaises(stock.InventoryError) as ctx:
            stock.consume(reservation.pk)
        self.assertEqual(ctx.exception.code, 'reservation_expired')
        self.assertEqual(stock.expire_reservations(), 1)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, 'expired')
        self.assertEqual(stock.expire_reservations(), 0)

    def test_consume_posts_fifo_sale_movements_and_reduces_on_hand(self):
        first, second = self.batch('10'), self.batch('10')
        listing = self.listing()
        stock.allocate(listing.pk, first.pk, '10', self.farmer)
        stock.allocate(listing.pk, second.pk, '10', self.farmer)
        reservation = stock.reserve(listing.pk, '14')
        stock.consume(reservation.pk, self.farmer)
        sales = {m.batch_id: m.quantity for m in StockMovement.objects.filter(movement_type='sale')}
        self.assertEqual(sales, {first.pk: D('10'), second.pk: D('4')})
        self.assertEqual(stock.listing_stock(listing), {
            'on_hand': D('6'), 'reserved': D('0'), 'available': D('6'),
        })
        # Sold stock can never be returned to the batch.
        with self.assertRaises(stock.InsufficientStock):
            stock.deallocate(listing.pk, first.pk, '1', self.farmer)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, 'consumed')

    def test_balances_are_never_stored_only_derived(self):
        for model in (HarvestBatch, Listing, StockMovement, Reservation):
            names = {f.name for f in model._meta.get_fields()}
            self.assertFalse(names & {'stock', 'available', 'on_hand', 'balance', 'remaining'}, model)


class StockImmutabilityTests(StockFixtureMixin, TestCase):
    def setUp(self):
        self.build()

    def test_movements_cannot_be_changed_or_deleted(self):
        movement = StockMovement.objects.get(batch=self.batch('10'))
        movement.quantity = D('99')
        with self.assertRaises(ImmutableRecordError):
            movement.save()
        with self.assertRaises(ImmutableRecordError):
            movement.delete()
        with self.assertRaises(ImmutableRecordError):
            StockMovement.objects.all().update(quantity=1)
        with self.assertRaises(ImmutableRecordError):
            StockMovement.objects.all().delete()
        self.assertEqual(StockMovement.objects.get(pk=movement.pk).quantity, D('10.000'))

    def test_database_rejects_non_positive_quantity_and_bad_listing_link(self):
        from django.db import IntegrityError, transaction
        batch, listing = self.batch('10'), self.listing()
        for kwargs in (
            dict(movement_type='receipt', quantity='0'),
            dict(movement_type='allocation', quantity='1'),  # needs a listing
            dict(movement_type='receipt', quantity='1', listing=listing),  # must not have one
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                StockMovement.objects.create(batch=batch, **kwargs)

    def test_batch_with_movements_cannot_be_deleted(self):
        from django.db import transaction
        from django.db.models import ProtectedError
        batch = self.batch('10')
        with self.assertRaises(ProtectedError), transaction.atomic():
            batch.delete()


class StockApiTests(StockFixtureMixin, TestCase):
    def setUp(self):
        self.build()
        self.client = APIClient()

    def as_user(self, user):
        self.client.force_authenticate(user)
        return self.client

    def test_only_ops_admin_can_accept_and_reject(self):
        batch = self.batch('10', accepted=False)
        url = reverse('harvest-batch-accept', args=[batch.pk])
        for user in (self.farmer, self.buyer, self.finance, self.other):
            self.assertEqual(self.as_user(user).post(url).status_code, 403, user)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(url).status_code, 401)
        response = self.as_user(self.admin).post(url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['status'], 'accepted')
        self.assertEqual(self.as_user(self.admin).post(url).status_code, 409)
        other = self.batch('10', accepted=False)
        response = self.as_user(self.admin).post(
            reverse('harvest-batch-reject', args=[other.pk]), {'reason': 'wet'}, format='json')
        self.assertEqual(response.json()['status'], 'rejected')

    def test_status_cannot_be_set_by_farmer(self):
        response = self.as_user(self.farmer).post(reverse('harvest-batch-list'), {
            'category': str(self.category.id), 'quantity': '5', 'unit_code': 'kg',
            'harvested_on': '2026-01-01', 'status': 'accepted',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['status'], 'submitted')
        self.assertFalse(StockMovement.objects.exists())

    def test_accepted_batch_is_not_editable(self):
        batch = self.batch('10')
        response = self.as_user(self.farmer).patch(
            reverse('harvest-batch-detail', args=[batch.pk]), {'quantity': '999'}, format='json')
        self.assertEqual(response.status_code, 409)
        batch.refresh_from_db()
        self.assertEqual(batch.quantity, D('10.000'))
        submitted = self.batch('10', accepted=False)
        response = self.as_user(self.farmer).patch(
            reverse('harvest-batch-detail', args=[submitted.pk]), {'quantity': '11'}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_allocate_and_stock_endpoints(self):
        batch, listing = self.batch('100'), self.listing()
        allocation_key = '66666666-6666-4666-8666-666666666666'
        allocation_body = {
            'batch': str(batch.pk), 'quantity': '40', 'client_request_id': allocation_key,
        }
        response = self.as_user(self.farmer).post(
            reverse('listing-allocate', args=[listing.pk]),
            allocation_body, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        replay = self.as_user(self.farmer).post(
            reverse('listing-allocate', args=[listing.pk]),
            allocation_body, format='json')
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json(), response.json())
        self.assertEqual(
            StockMovement.objects.filter(movement_type='allocation').count(), 1,
        )
        conflict = self.as_user(self.farmer).post(
            reverse('listing-allocate', args=[listing.pk]),
            {**allocation_body, 'quantity': '41'}, format='json')
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(
            StockMovement.objects.filter(movement_type='allocation').count(), 1,
        )
        response = self.as_user(self.farmer).get(reverse('listing-stock', args=[listing.pk]))
        self.assertEqual(response.json()['available'], '40.000')
        response = self.as_user(self.farmer).post(
            reverse('listing-allocate', args=[listing.pk]),
            {
                'batch': str(batch.pk), 'quantity': '61',
                'client_request_id': '77777777-7777-4777-8777-777777777777',
            }, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'insufficient_stock')
        deallocation_key = '88888888-8888-4888-8888-888888888888'
        response = self.as_user(self.farmer).post(
            reverse('listing-deallocate', args=[listing.pk]),
            {
                'batch': str(batch.pk), 'quantity': '10',
                'client_request_id': deallocation_key,
            }, format='json')
        self.assertEqual(response.status_code, 201)
        replay = self.as_user(self.farmer).post(
            reverse('listing-deallocate', args=[listing.pk]),
            {
                'batch': str(batch.pk), 'quantity': '10',
                'client_request_id': deallocation_key,
            }, format='json')
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(
            StockMovement.objects.filter(movement_type='deallocation').count(), 1,
        )
        self.assertEqual(stock.listing_stock(listing)['on_hand'], D('30'))

    def test_allocation_validates_input(self):
        batch, listing = self.batch('100'), self.listing()
        url = reverse('listing-allocate', args=[listing.pk])
        for index, quantity in enumerate(('0', '-5', 'abc')):
            response = self.as_user(self.farmer).post(
                url, {
                    'batch': str(batch.pk), 'quantity': quantity,
                    'client_request_id': f'99999999-9999-4999-8999-{index:012d}',
                }, format='json')
            self.assertEqual(response.status_code, 400, quantity)

    def test_cross_user_and_role_restrictions(self):
        batch, listing = self.batch('100'), self.listing()
        url = reverse('listing-allocate', args=[listing.pk])
        body = {
            'batch': str(batch.pk), 'quantity': '1',
            'client_request_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        }
        # Another farmer cannot touch this listing or batch (404, no existence leak).
        self.assertEqual(self.as_user(self.other).post(url, body, format='json').status_code, 404)
        foreign_listing = self.listing(seller=self.other)
        response = self.as_user(self.other).post(
            reverse('listing-allocate', args=[foreign_listing.pk]), body, format='json')
        self.assertEqual(response.status_code, 404)
        # Buyers, finance operators and ops admins cannot allocate.
        for user in (self.buyer, self.finance, self.admin):
            self.assertEqual(self.as_user(user).post(url, body, format='json').status_code, 403, user)
        # Stock visibility: seller and ops admin only.
        stock_url = reverse('listing-stock', args=[listing.pk])
        self.assertEqual(self.as_user(self.farmer).get(stock_url).status_code, 200)
        self.assertEqual(self.as_user(self.admin).get(stock_url).status_code, 200)
        self.assertEqual(self.as_user(self.other).get(stock_url).status_code, 404)
        for user in (self.buyer, self.finance):
            self.assertEqual(self.as_user(user).get(stock_url).status_code, 403, user)
        self.assertEqual(StockMovement.objects.filter(movement_type='allocation').count(), 0)

    def test_stock_movement_list_scoping(self):
        self.batch('10')
        self.batch('20', farmer=self.other)
        url = reverse('stock-movement-list')
        self.assertEqual(self.as_user(self.farmer).get(url).json()['count'], 1)
        self.assertEqual(self.as_user(self.admin).get(url).json()['count'], 2)
        self.assertEqual(self.as_user(self.buyer).get(url).status_code, 403)
        self.assertEqual(self.as_user(self.finance).get(url).status_code, 403)
        self.assertEqual(self.as_user(self.farmer).post(url, {}).status_code, 405)

    def test_listing_category_and_unit_cannot_change_after_allocation(self):
        batch, listing = self.batch('10'), self.listing()
        stock.allocate(listing.pk, batch.pk, '5', self.farmer)
        other_category = CropCategory.objects.create(name='Beans', slug='beans')
        response = self.as_user(self.farmer).patch(
            reverse('listing-detail', args=[listing.pk]), {'category': str(other_category.pk)},
            format='json',
        )
        self.assertEqual(response.status_code, 400, response.content)
        response = self.as_user(self.farmer).patch(
            reverse('listing-detail', args=[listing.pk]), {'unit_code': 'bag'}, format='json',
        )
        self.assertEqual(response.status_code, 400, response.content)
        listing.refresh_from_db()
        self.assertEqual((listing.category_id, listing.unit_code), (self.category.pk, 'kg'))


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row locking and real concurrency.')
class StockConcurrencyTests(StockFixtureMixin, TransactionTestCase):
    workers = 8

    def setUp(self):
        self.build()

    def run_concurrently(self, function, count):
        barrier = Barrier(count)

        def call(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return function(index)
            except stock.InventoryError as exc:
                return exc
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=count) as executor:
            return list(executor.map(call, range(count)))

    def test_concurrent_reservations_never_oversell(self):
        batch, listing = self.batch('100'), self.listing()
        stock.allocate(listing.pk, batch.pk, '5', self.farmer)
        results = self.run_concurrently(lambda i: stock.reserve(listing.pk, '1'), self.workers)
        succeeded = [r for r in results if isinstance(r, Reservation)]
        self.assertEqual(len(succeeded), 5, results)
        self.assertTrue(all(isinstance(r, stock.InsufficientStock) for r in results if r not in succeeded))
        self.assertEqual(stock.listing_stock(listing)['available'], D('0'))

    def test_concurrent_allocations_never_exceed_batch_quantity(self):
        batch, listing = self.batch('5'), self.listing()
        results = self.run_concurrently(
            lambda i: stock.allocate(listing.pk, batch.pk, '1', self.farmer), self.workers)
        self.assertEqual(sum(isinstance(r, StockMovement) for r in results), 5, results)
        self.assertEqual(stock.batch_free(batch), D('0'))
        self.assertEqual(stock.listing_on_hand(listing), D('5'))

    def test_concurrent_consume_of_one_reservation_happens_once(self):
        batch, listing = self.batch('10'), self.listing()
        stock.allocate(listing.pk, batch.pk, '10', self.farmer)
        reservation = stock.reserve(listing.pk, '4')
        results = self.run_concurrently(lambda i: stock.consume(reservation.pk), 4)
        self.assertEqual(sum(isinstance(r, Reservation) for r in results), 1, results)
        self.assertEqual(stock.listing_on_hand(listing), D('6'))

    def test_reserve_and_deallocate_race_cannot_break_invariant(self):
        batch, listing = self.batch('10'), self.listing()
        stock.allocate(listing.pk, batch.pk, '10', self.farmer)

        def work(i):
            if i % 2:
                return stock.reserve(listing.pk, '6')
            return stock.deallocate(listing.pk, batch.pk, '6', self.farmer)

        self.run_concurrently(work, 4)
        stock_now = stock.listing_stock(listing)
        self.assertGreaterEqual(stock_now['available'], 0)
        self.assertGreaterEqual(stock.batch_free(batch), 0)
        self.assertEqual(stock.batch_free(batch) + stock_now['on_hand'], D('10'))
