from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless
from unittest import mock

from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from agrifi.accounts.models import UserRole
from agrifi.catalog.models import CropCategory, Listing
from agrifi.catalog.tests import make_user
from agrifi.finance import services as finance
from agrifi.idempotency.models import IdempotencyRecord
from agrifi.inventory import services as stock
from agrifi.inventory.models import HarvestBatch, Reservation, StockMovement

from . import services
from .models import Dispute, ImmutableRowError, Order, OrderItem, OrderStatusHistory

D = Decimal
KEY = '7c1f0b52-3a0e-4a65-9d0e-5b1f0a9c2d11'


class OrderFixture:
    def build(self):
        self.farmer = make_user('o-farmer@example.com', UserRole.Role.FARMER)
        self.farmer2 = make_user('o-farmer2@example.com', UserRole.Role.FARMER)
        self.buyer = make_user('o-buyer@example.com', UserRole.Role.BUYER)
        self.buyer2 = make_user('o-buyer2@example.com', UserRole.Role.BUYER)
        self.admin = make_user('o-ops@example.com', UserRole.Role.OPERATIONS_ADMIN)
        self.finance = make_user('o-fin@example.com', UserRole.Role.FINANCE_OPERATOR)
        self.category = CropCategory.objects.create(name='Rice', slug='rice')

    def stocked_listing(self, seller=None, quantity='100', price=25000, name='Rice', status='active'):
        seller = seller or self.farmer
        batch = HarvestBatch.objects.create(
            farmer=seller, category=self.category, quantity=quantity, unit_code='kg',
            harvested_on='2026-01-01',
        )
        stock.accept_batch(batch.pk, self.admin)
        listing = Listing.objects.create(
            seller=seller, category=self.category, name=name, unit_code='kg',
            unit_price_minor=price, status=status,
        )
        stock.allocate(listing.pk, batch.pk, quantity, seller)
        return listing

    def items(self, *pairs):
        return [{'listing': listing.pk, 'quantity': D(quantity)} for listing, quantity in pairs]

    def place(self, listing, quantity='2', buyer=None):
        return services.create_order(
            buyer or self.buyer, self.items((listing, quantity)), 'Plot 4, Kano',
        )

    def pay(self, order, buyer=None):
        return finance.create_simulated_payment(order.pk, buyer or order.buyer)


class CheckoutServiceTests(OrderFixture, TestCase):
    def setUp(self):
        self.build()

    def test_checkout_computes_server_totals_and_snapshots(self):
        a = self.stocked_listing(price=25000, name='Rice A')
        b = self.stocked_listing(price=999, name='Rice B')
        order = services.create_order(
            self.buyer, self.items((a, '2.5'), (b, '3')), 'Kano',
        )
        by_name = {i.listing_name: i for i in order.items.all()}
        self.assertEqual(by_name['Rice A'].line_total_minor, 62500)
        self.assertEqual(by_name['Rice B'].line_total_minor, 2997)
        self.assertEqual(order.total_minor, 65497)
        self.assertEqual(order.status, 'pending')
        self.assertEqual(order.seller, self.farmer)
        self.assertEqual(order.history.get().to_status, 'pending')
        self.assertEqual(stock.listing_stock(a)['reserved'], D('2.5'))
        self.assertEqual(stock.listing_on_hand(a), D('100'))  # reserved, not yet sold

    def test_line_total_rounds_half_up_to_whole_kobo(self):
        self.assertEqual(services.line_total_minor(1001, D('0.5')), 501)
        self.assertEqual(services.line_total_minor(999, D('0.001')), 1)
        self.assertEqual(services.line_total_minor(100, D('1.234')), 123)
        with self.assertRaises(services.OrderError) as ctx:
            services.line_total_minor(1, D('0.001'))
        self.assertEqual(ctx.exception.code, 'invalid_line_total')

    def test_snapshots_survive_listing_changes(self):
        listing = self.stocked_listing(price=25000)
        order = self.place(listing)
        Listing.objects.filter(pk=listing.pk).update(unit_price_minor=1, name='Renamed')
        item = OrderItem.objects.get(order=order)
        self.assertEqual((item.unit_price_minor, item.listing_name), (25000, 'Rice'))

    def test_validation_rules(self):
        listing = self.stocked_listing()
        other_seller = self.stocked_listing(seller=self.farmer2)
        cases = [
            (self.buyer, [], 'invalid_items'),
            (self.buyer, self.items((listing, '1'), (listing, '1')), 'duplicate_items'),
            (self.buyer, self.items((listing, '1'), (other_seller, '1')), 'multiple_sellers'),
            (self.buyer, self.items((listing, '0')), 'invalid_quantity'),
            (self.buyer, self.items((listing, '1.0001')), 'invalid_quantity'),
            (self.farmer2, self.items((listing, '1')), 'forbidden'),
            (self.admin, self.items((listing, '1')), 'forbidden'),
        ]
        for user, items, code in cases:
            with self.assertRaises((services.OrderError, stock.InventoryError)) as ctx:
                services.create_order(user, items, 'x')
            self.assertEqual(ctx.exception.code, code)
        missing = [{'listing': '00000000-0000-0000-0000-000000000000', 'quantity': D('1')}]
        with self.assertRaises(services.OrderError) as ctx:
            services.create_order(self.buyer, missing, 'x')
        self.assertEqual(ctx.exception.code, 'listing_not_found')
        self.assertFalse(Order.objects.exists())
        self.assertFalse(Reservation.objects.exists())

    def test_cannot_buy_own_listing_or_inactive_listing(self):
        own = self.stocked_listing()
        farmer_buyer_role = make_user('dual@example.com', UserRole.Role.BUYER)
        UserRole.objects.create(user=farmer_buyer_role, role=UserRole.Role.FARMER)
        mine = self.stocked_listing(seller=farmer_buyer_role)
        with self.assertRaises(services.OrderError) as ctx:
            services.create_order(farmer_buyer_role, self.items((mine, '1')), 'x')
        self.assertEqual(ctx.exception.code, 'own_listing')
        paused = self.stocked_listing(status='paused')
        with self.assertRaises(services.OrderError) as ctx:
            services.create_order(self.buyer, self.items((paused, '1')), 'x')
        self.assertEqual(ctx.exception.code, 'listing_not_active')
        self.assertTrue(own.pk)

    def test_insufficient_stock_rolls_back_everything(self):
        a = self.stocked_listing(quantity='5', name='A')
        b = self.stocked_listing(quantity='1', name='B')
        with self.assertRaises(stock.InsufficientStock):
            services.create_order(self.buyer, self.items((a, '2'), (b, '2')), 'x')
        self.assertFalse(Order.objects.exists())
        self.assertFalse(OrderItem.objects.exists())
        self.assertFalse(Reservation.objects.exists())
        self.assertEqual(stock.listing_stock(a)['available'], D('5'))

    def test_cannot_oversell_across_orders(self):
        listing = self.stocked_listing(quantity='5')
        self.place(listing, '3')
        with self.assertRaises(stock.InsufficientStock):
            self.place(listing, '3', buyer=self.buyer2)
        self.place(listing, '2', buyer=self.buyer2)
        self.assertEqual(stock.listing_stock(listing)['available'], D('0'))


class OrderLifecycleTests(OrderFixture, TestCase):
    def setUp(self):
        self.build()
        self.listing = self.stocked_listing(quantity='10')

    def go(self, order, to, user, **kw):
        return services.transition(order.pk, to, user, **kw)

    def test_full_happy_path_consumes_stock_once(self):
        order = self.place(self.listing, '4')
        self.go(order, 'confirmed', self.farmer)
        reservation = order.items.get().reservation
        reservation.refresh_from_db()
        self.assertIsNone(reservation.expires_at)
        self.pay(order)
        self.assertEqual(StockMovement.objects.filter(movement_type='sale').count(), 0)
        self.assertEqual(stock.listing_stock(self.listing), {
            'on_hand': D('10'), 'reserved': D('4'), 'available': D('6'),
        })
        self.go(order, 'shipped', self.farmer)
        self.assertEqual(StockMovement.objects.filter(movement_type='sale').count(), 1)
        self.assertEqual(stock.listing_stock(self.listing), {
            'on_hand': D('6'), 'reserved': D('0'), 'available': D('6'),
        })
        self.go(order, 'delivered', self.farmer)
        self.go(order, 'completed', self.buyer)
        order.refresh_from_db()
        self.assertEqual(order.status, 'completed')
        self.assertEqual(
            [h.to_status for h in order.history.all()],
            ['pending', 'confirmed', 'shipped', 'delivered', 'completed'],
        )
        self.assertEqual(stock.audit_stock(), [])

    def test_invalid_and_out_of_order_transitions_are_rejected(self):
        order = self.place(self.listing)
        for to in ('shipped', 'delivered', 'completed', 'pending', 'disputed'):
            with self.assertRaises(services.OrderError) as ctx:
                self.go(order, to, self.farmer)
            self.assertEqual(ctx.exception.code, 'invalid_transition', to)
        self.go(order, 'confirmed', self.farmer)
        with self.assertRaises(services.OrderError):  # confirmed orders cannot be cancelled
            self.go(order, 'cancelled', self.buyer)
        with self.assertRaises(services.OrderError):
            self.go(order, 'confirmed', self.farmer)  # no double confirm

    def test_role_restrictions_on_transitions(self):
        order = self.place(self.listing)
        for user in (self.buyer, self.farmer2, self.admin, self.finance):
            with self.assertRaises(services.OrderError) as ctx:
                self.go(order, 'confirmed', user)
            self.assertEqual(ctx.exception.code, 'forbidden')
        self.assertFalse(StockMovement.objects.filter(movement_type='sale').exists())
        self.go(order, 'confirmed', self.farmer)
        with self.assertRaises(services.OrderError):
            self.go(order, 'shipped', self.buyer)
        with self.assertRaises(services.OrderError) as ctx:
            self.go(order, 'shipped', self.farmer)
        self.assertEqual(ctx.exception.code, 'payment_required')
        self.pay(order)
        self.go(order, 'shipped', self.farmer)
        self.go(order, 'delivered', self.farmer)
        with self.assertRaises(services.OrderError):
            self.go(order, 'completed', self.farmer)

    def test_cancel_releases_reservation_and_restores_availability(self):
        for actor in (self.buyer, self.farmer, self.admin):
            order = self.place(self.listing, '2')
            self.assertEqual(stock.listing_stock(self.listing)['available'], D('8'))
            self.go(order, 'cancelled', actor, reason='changed mind')
            self.assertEqual(stock.listing_stock(self.listing)['available'], D('10'))
            self.assertEqual(order.items.get().reservation.status, 'released')
        with self.assertRaises(services.OrderError):
            self.go(order, 'cancelled', self.buyer)  # not twice
        self.assertFalse(StockMovement.objects.filter(movement_type='sale').exists())

    def test_other_buyer_cannot_cancel(self):
        order = self.place(self.listing)
        with self.assertRaises(services.OrderError) as ctx:
            self.go(order, 'cancelled', self.buyer2)
        self.assertEqual(ctx.exception.code, 'forbidden')

    def test_confirm_after_reservation_expiry_fails_and_changes_nothing(self):
        order = self.place(self.listing, '4')
        Reservation.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        with self.assertRaises(stock.InventoryError) as ctx:
            self.go(order, 'confirmed', self.farmer)
        self.assertEqual(ctx.exception.code, 'reservation_expired')
        order.refresh_from_db()
        self.assertEqual(order.status, 'pending')
        self.assertFalse(StockMovement.objects.filter(movement_type='sale').exists())

    def test_expiry_sweep_cancels_pending_orders_and_never_touches_stock_twice(self):
        stale = self.place(self.listing, '4')
        fresh = self.place(self.listing, '1', buyer=self.buyer2)
        Reservation.objects.filter(order_item__order=stale).update(
            expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(services.cancel_expired_orders(), 1)
        stale.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual((stale.status, fresh.status), ('cancelled', 'pending'))
        self.assertEqual(stale.history.last().actor, None)
        self.assertEqual(stock.listing_stock(self.listing)['available'], D('9'))
        self.assertEqual(services.cancel_expired_orders(), 0)
        # Reservation already marked expired by the stock job: still cancellable.
        again = self.place(self.listing, '2')
        Reservation.objects.filter(order_item__order=again).update(
            expires_at=timezone.now() - timedelta(minutes=1))
        stock.expire_reservations()
        self.assertEqual(services.cancel_expired_orders(), 1)
        self.assertEqual(stock.audit_stock(), [])

    def test_reservation_cannot_be_consumed_twice(self):
        order = self.place(self.listing, '4')
        self.go(order, 'confirmed', self.farmer)
        self.pay(order)
        self.go(order, 'shipped', self.farmer)
        with self.assertRaises(stock.InventoryError):
            stock.consume(order.items.get().reservation_id)
        self.assertEqual(StockMovement.objects.filter(movement_type='sale').count(), 1)


class DisputeTests(OrderFixture, TestCase):
    def setUp(self):
        self.build()
        self.listing = self.stocked_listing()
        self.order = self.place(self.listing)

    def test_dispute_rules_and_resolution(self):
        with self.assertRaises(services.OrderError):  # pending cannot be disputed
            services.open_dispute(self.order.pk, self.buyer, 'late')
        services.transition(self.order.pk, 'confirmed', self.farmer)
        for user in (self.farmer, self.buyer2, self.admin):
            with self.assertRaises(services.OrderError) as ctx:
                services.open_dispute(self.order.pk, user, 'x')
            self.assertEqual(ctx.exception.code, 'forbidden')
        dispute = services.open_dispute(self.order.pk, self.buyer, 'damaged')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'disputed')
        self.assertEqual(dispute.previous_order_status, 'confirmed')
        with self.assertRaises(services.OrderError):
            services.open_dispute(self.order.pk, self.buyer, 'again')
        for user in (self.buyer, self.farmer, self.finance):
            with self.assertRaises(services.OrderError) as ctx:
                services.resolve_dispute(dispute.pk, user, 'buyer_favoured')
            self.assertEqual(ctx.exception.code, 'forbidden')
        with self.assertRaises(services.OrderError):
            services.resolve_dispute(dispute.pk, self.admin, 'nonsense')
        services.resolve_dispute(dispute.pk, self.admin, 'seller_favoured', 'ok')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'confirmed')
        self.assertEqual(stock.listing_stock(self.listing)['reserved'], D('2'))
        with self.assertRaises(services.OrderError):
            services.resolve_dispute(dispute.pk, self.admin, 'buyer_favoured')

    def test_buyer_favoured_confirmed_dispute_releases_unshipped_stock(self):
        services.transition(self.order.pk, 'confirmed', self.farmer)
        dispute = services.open_dispute(self.order.pk, self.buyer, 'wrong item')
        services.resolve_dispute(dispute.pk, self.admin, 'buyer_favoured')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'cancelled')
        self.assertEqual(stock.listing_stock(self.listing)['available'], D('100'))
        self.assertFalse(StockMovement.objects.filter(movement_type='sale').exists())

    def test_buyer_favoured_shipped_dispute_is_terminal_without_fabricated_refund(self):
        services.transition(self.order.pk, 'confirmed', self.farmer)
        self.pay(self.order)
        services.transition(self.order.pk, 'shipped', self.farmer)
        dispute = services.open_dispute(self.order.pk, self.buyer, 'damaged')
        services.resolve_dispute(dispute.pk, self.admin, 'buyer_favoured')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'dispute_resolved')
        self.assertEqual(stock.listing_stock(self.listing)['on_hand'], D('98'))
        self.assertEqual(StockMovement.objects.filter(movement_type='sale').count(), 1)

    def test_database_allows_one_open_dispute_per_order(self):
        services.transition(self.order.pk, 'confirmed', self.farmer)
        services.open_dispute(self.order.pk, self.buyer, 'a')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Dispute.objects.create(
                order=self.order, opened_by=self.buyer, reason='b', previous_order_status='confirmed')


class ImmutabilityTests(OrderFixture, TestCase):
    def setUp(self):
        self.build()
        self.order = self.place(self.stocked_listing())

    def test_items_and_history_are_immutable_in_python(self):
        item = self.order.items.get()
        item.unit_price_minor = 1
        for call in (item.save, item.delete,
                     OrderItem.objects.all().delete,
                     lambda: OrderItem.objects.all().update(quantity=1)):
            with self.assertRaises(ImmutableRowError):
                call()
        entry = self.order.history.get()
        for call in (entry.save, entry.delete, OrderStatusHistory.objects.all().delete):
            with self.assertRaises(ImmutableRowError):
                call()

    def test_order_cannot_be_deleted_and_buyer_cannot_equal_seller(self):
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError), transaction.atomic():
            self.order.delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Order.objects.filter(pk=self.order.pk).update(buyer=self.order.seller)

    @skipUnless(connection.vendor == 'postgresql', 'PostgreSQL triggers only.')
    def test_postgresql_triggers_block_raw_sql_mutation(self):
        movement = StockMovement.objects.first()
        statements = [
            ('inventory_stockmovement', movement.pk, 'UPDATE inventory_stockmovement SET reference = %s WHERE id = %s'),
            ('inventory_stockmovement', movement.pk, 'DELETE FROM inventory_stockmovement WHERE id = %s'),
            ('orders_orderitem', self.order.items.get().pk, 'UPDATE orders_orderitem SET unit_price_minor = 1 WHERE id = %s'),
            ('orders_orderitem', self.order.items.get().pk, 'DELETE FROM orders_orderitem WHERE id = %s'),
            ('orders_orderstatushistory', self.order.history.get().pk, 'DELETE FROM orders_orderstatushistory WHERE id = %s'),
        ]
        for _, pk, sql in statements:
            params = ['x', pk] if '%s WHERE' in sql and 'reference' in sql else [pk]
            with self.assertRaises(Exception) as ctx, transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(sql, params)
            self.assertIn('immutable', str(ctx.exception))


class OrderApiTests(OrderFixture, TestCase):
    def setUp(self):
        self.build()
        self.client = APIClient()
        self.listing = self.stocked_listing(quantity='10', price=25000)

    def as_user(self, user):
        self.client.force_authenticate(user)
        return self.client

    def body(self, **overrides):
        data = {
            'client_request_id': KEY,
            'items': [{'listing': str(self.listing.pk), 'quantity': '2'}],
            'delivery_address': 'Plot 4, Kano',
        }
        data.update(overrides)
        return data

    def post(self, body, user=None):
        return self.as_user(user or self.buyer).post(reverse('order-list'), body, format='json')

    def test_checkout_ignores_client_supplied_prices_and_identity(self):
        body = self.body(buyer=str(self.buyer2.pk), seller=str(self.farmer2.pk), total_minor=1,
                         status='confirmed')
        body['items'][0]['unit_price_minor'] = 1
        response = self.post(body)
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(data['total_minor'], 50000)
        self.assertEqual(data['buyer'], self.buyer.pk if isinstance(data['buyer'], int) else str(self.buyer.pk))
        self.assertEqual(data['status'], 'pending')
        self.assertEqual(data['items'][0]['unit_price_minor'], 25000)

    def test_checkout_role_access(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(reverse('order-list'), self.body(), format='json').status_code, 401)
        for user in (self.farmer, self.admin, self.finance):
            self.assertEqual(self.post(self.body(), user).status_code, 403, user)
        self.assertFalse(Order.objects.exists())

    def test_input_validation(self):
        for bad in (
            self.body(items=[]),
            self.body(items=[{'listing': str(self.listing.pk), 'quantity': '0'}]),
            self.body(items=[{'listing': str(self.listing.pk), 'quantity': '-1'}]),
            self.body(items=[{'listing': 'nope', 'quantity': '1'}]),
            self.body(delivery_address=''),
            {k: v for k, v in self.body().items() if k != 'client_request_id'},
        ):
            self.assertEqual(self.post(bad).status_code, 400, bad)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)

    def test_insufficient_stock_is_409_and_leaves_no_record(self):
        response = self.post(self.body(items=[{'listing': str(self.listing.pk), 'quantity': '11'}]))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'insufficient_stock')
        self.assertEqual(IdempotencyRecord.objects.count(), 0)
        self.assertEqual(Order.objects.count(), 0)
        # The same key can then be used for a corrected request.
        self.assertEqual(self.post(self.body()).status_code, 201)

    def test_idempotent_replay_conflict_and_independent_users(self):
        first = self.post(self.body())
        second = self.post(self.body())
        self.assertEqual((first.status_code, second.status_code), (201, 200))
        self.assertEqual(first.json(), second.json())
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(stock.listing_stock(self.listing)['reserved'], D('2'))
        changed = self.body(items=[{'listing': str(self.listing.pk), 'quantity': '3'}])
        self.assertEqual(self.post(changed).status_code, 409)
        reordered_equal = self.body(items=[{'listing': str(self.listing.pk), 'quantity': '2.000'}])
        self.assertEqual(self.post(reordered_equal).status_code, 200)
        other = self.post(self.body(), self.buyer2)  # same key, different buyer: independent
        self.assertEqual(other.status_code, 201)
        self.assertNotEqual(other.json()['id'], first.json()['id'])
        self.assertEqual(Order.objects.count(), 2)

    def test_replay_survives_later_state_changes(self):
        first = self.post(self.body())
        order_id = first.json()['id']
        services.transition(order_id, 'cancelled', self.buyer)
        Listing.objects.update(status='paused')
        replay = self.post(self.body())
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()['id'], order_id)

    def test_unrelated_integrity_error_is_not_a_replay(self):
        with mock.patch.object(services, 'create_order', side_effect=IntegrityError('other_constraint')):
            with self.assertRaises(IntegrityError):
                self.post(self.body())
        self.assertEqual(IdempotencyRecord.objects.count(), 0)
        self.assertEqual(Order.objects.count(), 0)

    def test_visibility_is_scoped_to_participants(self):
        order_id = self.post(self.body()).json()['id']
        detail = reverse('order-detail', args=[order_id])
        for user, expected in ((self.buyer, 200), (self.farmer, 200), (self.admin, 200),
                               (self.buyer2, 404), (self.farmer2, 404), (self.finance, 403)):
            self.assertEqual(self.as_user(user).get(detail).status_code, expected, user)
        counts = {u: self.as_user(u).get(reverse('order-list')).json()['count']
                  for u in (self.buyer, self.farmer, self.admin, self.buyer2, self.farmer2)}
        self.assertEqual(list(counts.values()), [1, 1, 1, 0, 0])

    def test_action_endpoints_enforce_roles_and_participation(self):
        order_id = self.post(self.body()).json()['id']
        url = lambda name: reverse(f'order-{name}', args=[order_id])
        self.assertEqual(self.as_user(self.buyer).post(url('confirm')).status_code, 403)
        self.assertEqual(self.as_user(self.buyer2).post(url('confirm')).status_code, 404)
        self.assertEqual(self.as_user(self.farmer2).post(url('confirm')).status_code, 404)
        self.assertEqual(self.as_user(self.finance).post(url('confirm')).status_code, 403)
        self.assertEqual(self.as_user(self.farmer).post(url('ship')).status_code, 409)
        self.assertEqual(self.as_user(self.farmer).post(url('confirm')).json()['status'], 'confirmed')
        self.assertEqual(self.as_user(self.farmer).post(url('confirm')).status_code, 409)
        self.assertEqual(self.as_user(self.buyer).post(url('cancel')).status_code, 409)
        finance.create_simulated_payment(order_id, self.buyer)
        self.assertEqual(self.as_user(self.farmer).post(url('ship')).json()['status'], 'shipped')
        self.assertEqual(self.as_user(self.farmer).post(url('deliver')).json()['status'], 'delivered')
        self.assertEqual(self.as_user(self.farmer).post(url('complete')).status_code, 403)
        self.assertEqual(self.as_user(self.buyer).post(url('complete')).json()['status'], 'completed')
        self.assertEqual(self.as_user(self.buyer).patch(reverse('order-detail', args=[order_id]), {}).status_code, 405)

    def test_cancel_and_dispute_endpoints(self):
        order_id = self.post(self.body()).json()['id']
        response = self.as_user(self.buyer).post(
            reverse('order-cancel', args=[order_id]), {'reason': 'oops'}, format='json')
        self.assertEqual(response.json()['status'], 'cancelled')
        self.assertEqual(stock.listing_stock(self.listing)['available'], D('10'))
        second = self.post(self.body(client_request_id='11111111-1111-4111-8111-111111111111')).json()['id']
        services.transition(second, 'confirmed', self.farmer)
        dispute = self.as_user(self.buyer).post(
            reverse('order-dispute', args=[second]), {'reason': 'damaged'}, format='json')
        self.assertEqual(dispute.status_code, 201, dispute.content)
        dispute_id = dispute.json()['id']
        resolve = reverse('dispute-resolve', args=[dispute_id])
        for user in (self.buyer, self.farmer):
            self.assertEqual(self.as_user(user).post(
                resolve, {'outcome': 'buyer_favoured'}, format='json').status_code, 403)
        self.assertEqual(self.as_user(self.buyer2).get(reverse('dispute-detail', args=[dispute_id])).status_code, 404)
        self.assertEqual(self.as_user(self.farmer).get(reverse('dispute-detail', args=[dispute_id])).status_code, 200)
        done = self.as_user(self.admin).post(resolve, {'outcome': 'buyer_favoured'}, format='json')
        self.assertEqual(done.status_code, 200, done.content)
        self.assertEqual(done.json()['status'], 'resolved')


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row locking and real concurrency.')
class OrderConcurrencyTests(OrderFixture, TransactionTestCase):
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
            except (services.OrderError, stock.InventoryError) as exc:
                return exc
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=count) as executor:
            return list(executor.map(call, range(count)))

    def test_concurrent_checkouts_never_oversell(self):
        listing = self.stocked_listing(quantity='5')
        buyers = [make_user(f'cb{i}@example.com', UserRole.Role.BUYER) for i in range(self.workers)]
        results = self.run_concurrently(
            lambda i: services.create_order(buyers[i], self.items((listing, '1')), 'x'), self.workers)
        self.assertEqual(sum(isinstance(r, Order) for r in results), 5, results)
        self.assertEqual(Order.objects.count(), 5)
        self.assertEqual(stock.listing_stock(listing)['available'], D('0'))
        self.assertEqual(stock.audit_stock(), [])

    def test_opposite_listing_order_checkouts_do_not_deadlock(self):
        a = self.stocked_listing(quantity='50', name='A')
        b = self.stocked_listing(quantity='50', name='B')
        buyers = [make_user(f'dl{i}@example.com', UserRole.Role.BUYER) for i in range(6)]

        def work(i):
            pairs = ((a, '1'), (b, '1')) if i % 2 else ((b, '1'), (a, '1'))
            return services.create_order(buyers[i], self.items(*pairs), 'x')

        results = self.run_concurrently(work, 6)
        self.assertTrue(all(isinstance(r, Order) for r in results), results)

    def test_confirm_races_with_cancel_exactly_one_wins(self):
        listing = self.stocked_listing(quantity='10')
        order = self.place(listing, '4')

        def work(i):
            if i % 2:
                return services.transition(order.pk, 'confirmed', self.farmer)
            return services.transition(order.pk, 'cancelled', self.buyer)

        results = self.run_concurrently(work, 6)
        self.assertEqual(sum(isinstance(r, Order) for r in results), 1, results)
        order.refresh_from_db()
        sold = StockMovement.objects.filter(movement_type='sale').count()
        self.assertEqual(sold, 0)
        self.assertEqual(stock.audit_stock(), [])

    def test_concurrent_identical_order_requests_create_one_order(self):
        listing = self.stocked_listing(quantity='10')
        results = self.run_http(listing, [KEY] * 6)
        statuses = sorted(r[0] for r in results)
        self.assertEqual(statuses, [200] * 5 + [201], results)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)
        self.assertEqual(stock.listing_stock(listing)['reserved'], D('2'))

    def test_concurrent_conflicting_order_requests_create_at_most_one_order(self):
        listing = self.stocked_listing(quantity='10')
        quantities = ['1' if i % 2 else '2' for i in range(6)]
        results = self.run_http(listing, [KEY] * len(quantities), quantities)
        statuses = [status for status, _ in results]
        self.assertEqual(statuses.count(201), 1, results)
        self.assertTrue(all(status in (200, 201, 409) for status in statuses), results)
        self.assertGreaterEqual(statuses.count(409), 1, results)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)
        created = next(body for status, body in results if status == 201)
        winning_quantity = created['items'][0]['quantity']
        self.assertEqual(
            stock.listing_stock(listing)['reserved'], D(winning_quantity),
        )

    def run_http(self, listing, keys, quantities=None):
        barrier = Barrier(len(keys))
        quantities = quantities or ['2'] * len(keys)

        def submit(i):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(self.buyer)
                barrier.wait(timeout=10)
                response = client.post(reverse('order-list'), {
                    'client_request_id': keys[i],
                    'items': [{'listing': str(listing.pk), 'quantity': quantities[i]}],
                    'delivery_address': 'x',
                }, format='json')
                return response.status_code, response.json()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(keys)) as executor:
            return list(executor.map(submit, range(len(keys))))
