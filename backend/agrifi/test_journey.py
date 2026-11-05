"""End-to-end API journeys using real JWT login (no force_authenticate).

These run on SQLite in fast mode; they prove API wiring and business rules, not PostgreSQL
concurrency."""
from decimal import Decimal

from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from agrifi.accounts.models import User, UserRole
from agrifi.catalog.models import CropCategory
from agrifi.finance.models import Journal, JournalLine
from agrifi.inventory.models import HarvestBatch, Reservation, StockMovement
from agrifi.inventory.services import audit_stock

PASSWORD = 'journey-password-2026-strong'


def uid(n):
    return f'{n:08d}-0000-4000-8000-000000000000'


class JourneyBase(TestCase):
    def setUp(self):
        self.category = CropCategory.objects.create(name='Maize', slug='maize')
        for email, role in (('ops@example.com', UserRole.Role.OPERATIONS_ADMIN),
                            ('fin@example.com', UserRole.Role.FINANCE_OPERATOR)):
            user = User.objects.create_user(email=email, password=PASSWORD)
            UserRole.objects.create(user=user, role=role)
        self.clients = {}

    def register(self, email, role, **profile):
        client = APIClient()
        response = client.post(reverse('accounts:register'), {
            'email': email, 'password': PASSWORD, 'password_confirm': PASSWORD,
            'role': role, **profile,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        return self.login(email)

    def login(self, email):
        client = APIClient()
        response = client.post(reverse('accounts:login'), {'email': email, 'password': PASSWORD},
                               format='json')
        self.assertEqual(response.status_code, 200, response.content)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
        self.clients[email] = client
        return client

    def setup_actors(self):
        self.farmer = self.register('farmer@example.com', 'farmer', display_name='Ada Farms',
                                    region='Kaduna')
        self.buyer = self.register('buyer@example.com', 'buyer', business_name='Lagos Foods')
        self.ops = self.login('ops@example.com')
        self.fin = self.login('fin@example.com')

    def submit_batch(self, quantity='100', sync_id=1):
        response = self.farmer.post(reverse('harvest-batch-list'), {
            'category': str(self.category.id), 'quantity': quantity, 'unit_code': 'kg',
            'harvested_on': '2026-01-01', 'client_sync_id': uid(sync_id),
        }, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()['id']

    def create_listing(self, price=45000):
        response = self.farmer.post(reverse('listing-list'), {
            'category': str(self.category.id), 'name': 'Yellow maize', 'unit_code': 'kg',
            'unit_price_minor': price, 'status': 'active',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()['id']

    def stocked_listing(self, quantity='100', allocate='60'):
        batch_id = self.submit_batch(quantity)
        self.assertEqual(self.ops.post(reverse('harvest-batch-accept', args=[batch_id])).status_code, 200)
        listing_id = self.create_listing()
        response = self.farmer.post(reverse('listing-allocate', args=[listing_id]), {
            'batch': batch_id, 'quantity': allocate, 'client_request_id': uid(900),
        }, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        return batch_id, listing_id

    def place_order(self, listing_id, quantity='10', key=uid(100)):
        return self.buyer.post(reverse('order-list'), {
            'client_request_id': key, 'delivery_address': 'Plot 4, Lagos',
            'items': [{'listing': listing_id, 'quantity': quantity}],
        }, format='json')

    def assert_ledgers_consistent(self):
        for journal in Journal.objects.all():
            lines = JournalLine.objects.filter(journal=journal)
            debit = lines.aggregate(t=Sum('debit_minor'))['t']
            credit = lines.aggregate(t=Sum('credit_minor'))['t']
            self.assertEqual(debit, credit)
            self.assertEqual(debit, journal.debit_total_minor)
        self.assertEqual(audit_stock(), [])


class BuyerTransactionJourneyTests(JourneyBase):
    def test_full_buyer_transaction(self):
        self.setup_actors()
        batch_id = self.submit_batch('100')
        self.assertFalse(StockMovement.objects.exists())

        # Submitted-but-unaccepted supply cannot be allocated.
        listing_id = self.create_listing()
        early = self.farmer.post(reverse('listing-allocate', args=[listing_id]), {
            'batch': batch_id, 'quantity': '10', 'client_request_id': uid(901),
        }, format='json')
        self.assertGreaterEqual(early.status_code, 400)
        self.assertFalse(StockMovement.objects.exists())

        # Only operations may accept.
        self.assertEqual(self.farmer.post(reverse('harvest-batch-accept', args=[batch_id])).status_code, 403)
        self.assertEqual(self.ops.post(reverse('harvest-batch-accept', args=[batch_id])).status_code, 200)
        self.assertEqual(StockMovement.objects.filter(movement_type='receipt').count(), 1)

        allocated = self.farmer.post(reverse('listing-allocate', args=[listing_id]), {
            'batch': batch_id, 'quantity': '60', 'client_request_id': uid(902),
        }, format='json')
        self.assertEqual(allocated.status_code, 201, allocated.content)

        # Buyer browses and sees server-derived availability.
        listings = self.buyer.get(reverse('listing-list')).json()['results']
        self.assertEqual([row['available_quantity'] for row in listings], ['60.000'])

        # Server calculates the price; the client cannot influence it.
        order_response = self.place_order(listing_id, '10')
        self.assertEqual(order_response.status_code, 201, order_response.content)
        order = order_response.json()
        self.assertEqual(order['total_minor'], 450000)
        listings = self.buyer.get(reverse('listing-list')).json()['results']
        self.assertEqual(listings[0]['available_quantity'], '50.000')

        # Payment before seller confirmation is rejected and posts nothing.
        unpaid = self.buyer.post(reverse('simulated-payment-list'),
                                 {'order': order['id'], 'client_request_id': uid(200)}, format='json')
        self.assertGreaterEqual(unpaid.status_code, 400)
        self.assertFalse(Journal.objects.exists())

        self.assertEqual(self.farmer.post(reverse('order-confirm', args=[order['id']])).status_code, 200)
        payment = self.buyer.post(reverse('simulated-payment-list'),
                                  {'order': order['id'], 'client_request_id': uid(201)}, format='json')
        self.assertEqual(payment.status_code, 201, payment.content)
        self.assertIn('SIMULATED', payment.json()['simulation_label'])

        # Fulfilment: shipping consumes stock exactly once.
        for action, client in (('ship', self.farmer), ('deliver', self.farmer), ('complete', self.buyer)):
            response = client.post(reverse(f'order-{action}', args=[order['id']]))
            self.assertEqual(response.status_code, 200, (action, response.content))
        self.assertEqual(StockMovement.objects.filter(movement_type='sale').count(), 1)
        self.assertEqual(
            StockMovement.objects.filter(movement_type='sale').aggregate(t=Sum('quantity'))['t'],
            Decimal('10'),
        )

        # Settlement is a finance-only, idempotent internal record.
        body = {'order': order['id'], 'client_request_id': uid(202)}
        self.assertEqual(self.farmer.post(reverse('simulated-settlement-list'), body, format='json').status_code, 403)
        self.assertEqual(self.buyer.post(reverse('simulated-settlement-list'), body, format='json').status_code, 403)
        first = self.fin.post(reverse('simulated-settlement-list'), body, format='json')
        replay = self.fin.post(reverse('simulated-settlement-list'), body, format='json')
        self.assertEqual((first.status_code, replay.status_code), (201, 200), first.content)
        self.assertEqual(Journal.objects.count(), 2)  # payment + settlement, no duplicates
        self.assert_ledgers_consistent()

        final = self.buyer.get(reverse('listing-list')).json()['results'][0]
        self.assertEqual(final['available_quantity'], '50.000')

    def test_rejected_batch_creates_no_stock_and_cannot_back_a_listing(self):
        self.setup_actors()
        batch_id = self.submit_batch('40')
        rejected = self.ops.post(reverse('harvest-batch-reject', args=[batch_id]),
                                 {'reason': 'Moisture too high'}, format='json')
        self.assertEqual(rejected.status_code, 200)
        listing_id = self.create_listing()
        response = self.farmer.post(reverse('listing-allocate', args=[listing_id]), {
            'batch': batch_id, 'quantity': '5', 'client_request_id': uid(903),
        }, format='json')
        self.assertGreaterEqual(response.status_code, 400)
        self.assertFalse(StockMovement.objects.exists())
        self.assertEqual(self.place_order(listing_id, '1').status_code, 409)

    def test_cancellation_releases_reservation_without_financial_records(self):
        self.setup_actors()
        _, listing_id = self.stocked_listing()
        order = self.place_order(listing_id, '25').json()
        self.assertEqual(self.buyer.get(reverse('listing-list')).json()['results'][0]['available_quantity'], '35.000')
        cancelled = self.buyer.post(reverse('order-cancel', args=[order['id']]),
                                    {'reason': 'Changed plans'}, format='json')
        self.assertEqual(cancelled.status_code, 200, cancelled.content)
        self.assertEqual(self.buyer.get(reverse('listing-list')).json()['results'][0]['available_quantity'], '60.000')
        self.assertFalse(Reservation.objects.filter(status=Reservation.Status.ACTIVE).exists())
        self.assertFalse(StockMovement.objects.filter(movement_type='sale').exists())
        self.assertFalse(Journal.objects.exists())
        # A cancelled order cannot be confirmed or paid.
        self.assertGreaterEqual(self.farmer.post(reverse('order-confirm', args=[order['id']])).status_code, 400)
        self.assertGreaterEqual(self.buyer.post(
            reverse('simulated-payment-list'), {'order': order['id'], 'client_request_id': uid(210)},
            format='json').status_code, 400)
        self.assertFalse(Journal.objects.exists())

    def test_duplicate_order_request_creates_one_order_and_one_reservation(self):
        self.setup_actors()
        _, listing_id = self.stocked_listing()
        first = self.place_order(listing_id, '10')
        replay = self.place_order(listing_id, '10')
        self.assertEqual((first.status_code, replay.status_code), (201, 200))
        self.assertEqual(first.json()['id'], replay.json()['id'])
        self.assertEqual(Reservation.objects.count(), 1)
        self.assertEqual(self.place_order(listing_id, '11').status_code, 409)
        self.assertEqual(Reservation.objects.count(), 1)

    def test_overselling_is_rejected_and_leaves_stock_unchanged(self):
        self.setup_actors()
        _, listing_id = self.stocked_listing(allocate='20')
        self.assertEqual(self.place_order(listing_id, '21').status_code, 409)
        self.assertFalse(Reservation.objects.exists())
        self.assertEqual(self.place_order(listing_id, '20', key=uid(101)).status_code, 201)
        self.assertEqual(self.place_order(listing_id, '1', key=uid(102)).status_code, 409)

    def test_roles_are_enforced_by_the_backend(self):
        self.setup_actors()
        _, listing_id = self.stocked_listing()
        order = self.place_order(listing_id, '5').json()
        other = self.register('buyer2@example.com', 'buyer', business_name='Other')
        self.assertEqual(other.get(reverse('order-detail', args=[order['id']])).status_code, 404)
        self.assertEqual(other.post(reverse('order-cancel', args=[order['id']]), {}, format='json').status_code, 404)
        self.assertEqual(self.buyer.get(reverse('finance-journal-list')).status_code, 403)
        self.assertEqual(self.farmer.get(reverse('finance-journal-list')).status_code, 403)
        self.assertEqual(self.fin.get(reverse('finance-journal-list')).status_code, 200)
        self.assertEqual(self.buyer.post(reverse('harvest-batch-list'), {
            'category': str(self.category.id), 'quantity': '1', 'unit_code': 'kg',
            'harvested_on': '2026-01-01',
        }, format='json').status_code, 403)
        self.assertEqual(HarvestBatch.objects.count(), 1)  # only the farmer's batch from setup
