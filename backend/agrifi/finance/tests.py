from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models import Sum
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from agrifi.accounts.models import UserRole
from agrifi.catalog.models import CropCategory, Listing
from agrifi.catalog.tests import make_user
from agrifi.idempotency.models import IdempotencyRecord
from agrifi.inventory import services as stock
from agrifi.inventory.models import HarvestBatch
from agrifi.orders import services as orders
from agrifi.orders.models import Dispute, Order

from . import services
from .models import (
    ImmutableFinanceError, Journal, JournalLine, LedgerAccount, Refund, Settlement,
    SimulatedPayment,
)


class FinanceFixture:
    def build(self):
        self.buyer = make_user('finance-buyer@example.com', UserRole.Role.BUYER)
        self.buyer2 = make_user('finance-buyer2@example.com', UserRole.Role.BUYER)
        self.farmer = make_user('finance-farmer@example.com', UserRole.Role.FARMER)
        self.admin = make_user('finance-ops@example.com', UserRole.Role.OPERATIONS_ADMIN)
        self.operator = make_user('finance-operator@example.com', UserRole.Role.FINANCE_OPERATOR)
        self.category = CropCategory.objects.create(name='Sorghum', slug='sorghum')
        batch = HarvestBatch.objects.create(
            farmer=self.farmer, category=self.category, quantity='25', unit_code='kg',
            harvested_on='2026-01-01',
        )
        stock.accept_batch(batch.pk, self.admin)
        self.listing = Listing.objects.create(
            seller=self.farmer, category=self.category, name='Sorghum', unit_code='kg',
            unit_price_minor=5000, status=Listing.Status.ACTIVE,
        )
        stock.allocate(self.listing.pk, batch.pk, '25', self.farmer)

    def make_order(self, quantity='2'):
        order = orders.create_order(
            self.buyer, [{'listing': self.listing.pk, 'quantity': quantity}], 'Kano',
        )
        orders.transition(order.pk, Order.Status.CONFIRMED, self.farmer)
        return order

    def pay(self, order=None):
        order = order or self.make_order()
        return order, services.create_simulated_payment(order.pk, self.buyer)

    def complete_order(self):
        order, payment = self.pay()
        orders.transition(order.pk, Order.Status.SHIPPED, self.farmer)
        orders.transition(order.pk, Order.Status.DELIVERED, self.farmer)
        orders.transition(order.pk, Order.Status.COMPLETED, self.buyer)
        return order, payment

    def buyer_favoured_dispute(self, order):
        dispute = orders.open_dispute(order.pk, self.buyer, 'Order issue')
        services_order = orders.resolve_dispute(
            dispute.pk, self.admin, Dispute.Outcome.BUYER_FAVOURED, 'Resolved for buyer',
        )
        return services_order


class FinanceServiceTests(FinanceFixture, TestCase):
    def setUp(self):
        self.build()

    def test_simulated_payment_is_atomic_balanced_and_disclosed(self):
        order = self.make_order()
        payment = services.create_simulated_payment(order.pk, self.buyer)
        self.assertEqual(payment.amount_minor, order.total_minor)
        self.assertEqual(payment.status, 'simulated_succeeded')
        self.assertIn('SIMULATED', payment.simulation_label)
        journal = Journal.objects.get(source_type='payment', source_id=payment.pk)
        self.assertTrue(services.journal_is_balanced(journal))
        lines = list(journal.lines.order_by('line_number'))
        self.assertEqual(
            [(line.account.code, line.debit_minor, line.credit_minor) for line in lines],
            [
                ('SIM_PAYMENT_CLEARING', 10000, 0),
                ('SELLER_PAYABLE', 0, 10000),
            ],
        )
        self.assertEqual(services.account_balance(lines[0].account), 10000)

    def test_payment_requires_confirmed_order_and_owning_buyer(self):
        pending = orders.create_order(
            self.buyer, [{'listing': self.listing.pk, 'quantity': '1'}], 'Kano',
        )
        with self.assertRaises(services.FinanceError) as ctx:
            services.create_simulated_payment(pending.pk, self.buyer)
        self.assertEqual(ctx.exception.code, 'invalid_order_state')
        confirmed = self.make_order('1')
        with self.assertRaises(services.FinanceError) as ctx:
            services.create_simulated_payment(confirmed.pk, self.buyer2)
        self.assertEqual(ctx.exception.code, 'forbidden')
        self.assertFalse(SimulatedPayment.objects.exists())

    def test_duplicate_payment_and_invalid_amount_are_rejected(self):
        order, payment = self.pay()
        with self.assertRaises(services.FinanceError) as ctx:
            services.create_simulated_payment(order.pk, self.buyer)
        self.assertEqual(ctx.exception.code, 'payment_exists')
        self.assertEqual(SimulatedPayment.objects.count(), 1)
        with self.assertRaises(services.FinanceError) as ctx:
            services.create_simulated_refund(payment.pk, True, 'invalid', self.operator)
        self.assertEqual(ctx.exception.code, 'invalid_amount')

    def test_refund_is_capped_and_debits_payable_before_settlement(self):
        order, payment = self.pay()
        self.buyer_favoured_dispute(order)
        refund = services.create_simulated_refund(payment.pk, 4000, 'Partial', self.operator)
        self.assertEqual(refund.status, 'simulated_succeeded')
        with self.assertRaises(services.FinanceError) as ctx:
            services.create_simulated_refund(payment.pk, 6001, 'Too much', self.operator)
        self.assertEqual(ctx.exception.code, 'refund_exceeds_paid')
        refund_journal = Journal.objects.get(source_type='refund', source_id=refund.pk)
        self.assertEqual(refund_journal.lines.get(line_number=1).account.code, 'SELLER_PAYABLE')
        self.assertTrue(services.journal_is_balanced(refund_journal))
        self.assertEqual(
            services.account_balance(LedgerAccount.objects.get(code='SELLER_PAYABLE')), -6000,
        )

    def test_full_refund_dispute_cannot_be_settled(self):
        order, payment = self.complete_order()
        dispute = orders.open_dispute(order.pk, self.buyer, 'Order issue')
        orders.resolve_dispute(dispute.pk, self.admin, Dispute.Outcome.BUYER_FAVOURED)
        services.create_simulated_refund(payment.pk, payment.amount_minor, 'Full', self.operator)
        with self.assertRaises(services.FinanceError) as ctx:
            services.create_simulated_settlement(order.pk, self.operator)
        self.assertEqual(ctx.exception.code, 'settlement_not_eligible')

    def test_settlement_requires_completed_order_and_nets_prior_refunds(self):
        order, payment = self.pay()
        self.buyer_favoured_dispute(order)
        # A buyer-favoured dispute cancels an unshipped order, so it cannot settle.
        with self.assertRaises(services.FinanceError):
            services.create_simulated_settlement(order.pk, self.operator)

        completed, completed_payment = self.complete_order()
        with self.assertRaises(services.FinanceError) as ctx:
            services.create_simulated_settlement(completed.pk, self.buyer)
        self.assertEqual(ctx.exception.code, 'forbidden')
        settlement = services.create_simulated_settlement(completed.pk, self.operator)
        self.assertEqual(settlement.amount_minor, completed.total_minor)
        self.assertEqual(settlement.seller, self.farmer)
        self.assertIn('SIMULATED', settlement.simulation_label)
        journal = Journal.objects.get(source_type='settlement', source_id=settlement.pk)
        self.assertTrue(services.journal_is_balanced(journal))
        with self.assertRaises(services.FinanceError) as ctx:
            services.create_simulated_settlement(completed.pk, self.admin)
        self.assertEqual(ctx.exception.code, 'settlement_exists')

    def test_post_settlement_refund_creates_seller_receivable(self):
        order, payment = self.complete_order()
        services.create_simulated_settlement(order.pk, self.operator)
        dispute = orders.open_dispute(order.pk, self.buyer, 'Damaged')
        orders.resolve_dispute(dispute.pk, self.admin, Dispute.Outcome.BUYER_FAVOURED)
        refund = services.create_simulated_refund(payment.pk, 3000, 'After settlement', self.operator)
        journal = Journal.objects.get(source_type='refund', source_id=refund.pk)
        self.assertEqual(journal.lines.get(line_number=1).account.code, 'SELLER_RECEIVABLE')
        self.assertEqual(
            services.account_balance(LedgerAccount.objects.get(code='SELLER_RECEIVABLE')), 3000,
        )

    def test_refund_requires_buyer_favoured_resolution(self):
        order, payment = self.pay()
        with self.assertRaises(services.FinanceError) as ctx:
            services.create_simulated_refund(payment.pk, 100, 'Not eligible', self.operator)
        self.assertEqual(ctx.exception.code, 'refund_not_eligible')
        with self.assertRaises(services.FinanceError) as ctx:
            services.create_simulated_refund(payment.pk, 100, 'Wrong role', self.buyer)
        self.assertEqual(ctx.exception.code, 'forbidden')

    def test_unbalanced_journals_are_rejected_before_writing(self):
        before = Journal.objects.count()
        with self.assertRaises(services.FinanceError) as ctx:
            services._post_journal(
                'test', __import__('uuid').uuid4(), 'bad', 'bad', self.operator,
                [('SIM_PAYMENT_CLEARING', 10, 0, ''), ('SELLER_PAYABLE', 0, 9, '')],
            )
        self.assertEqual(ctx.exception.code, 'unbalanced_journal')
        self.assertEqual(Journal.objects.count(), before)

    def test_reversal_appends_opposite_lines_without_mutating_original(self):
        _, payment = self.pay()
        original = Journal.objects.get(source_type='payment', source_id=payment.pk)
        original_lines = list(original.lines.values_list('account_id', 'debit_minor', 'credit_minor'))
        reversal = services.reverse_journal(original.pk, self.operator, 'Correction')
        self.assertEqual(reversal.reversal_of_id, original.pk)
        self.assertEqual(
            list(reversal.lines.values_list('account_id', 'debit_minor', 'credit_minor')),
            [(account, credit, debit) for account, debit, credit in original_lines],
        )
        self.assertEqual(
            list(original.lines.values_list('account_id', 'debit_minor', 'credit_minor')),
            original_lines,
        )
        replay = services.reverse_journal(original.pk, self.operator, 'Again')
        self.assertEqual(replay.pk, reversal.pk)
        self.assertEqual(Journal.objects.filter(reversal_of=original).count(), 1)

    def test_financial_rows_are_immutable_in_python(self):
        _, payment = self.pay()
        journal = Journal.objects.get(source_type='payment', source_id=payment.pk)
        line = journal.lines.first()
        for operation in (
            lambda: setattr(payment, 'amount_minor', 1) or payment.save(),
            payment.delete,
            lambda: SimulatedPayment.objects.all().update(amount_minor=1),
            journal.delete,
            lambda: JournalLine.objects.all().delete(),
            lambda: setattr(line, 'debit_minor', 1) or line.save(),
        ):
            with self.assertRaises(ImmutableFinanceError):
                operation()

    def test_migration_seeds_disclosed_system_accounts(self):
        accounts = {account.code: account for account in LedgerAccount.objects.all()}
        self.assertEqual(set(accounts), {
            'SIM_PAYMENT_CLEARING', 'SELLER_PAYABLE', 'SELLER_RECEIVABLE', 'SIM_PAYOUT_CLEARING',
        })
        self.assertIn('no real funds', accounts['SIM_PAYMENT_CLEARING'].name)
        self.assertIn('no real payout', accounts['SIM_PAYOUT_CLEARING'].name)


class FinanceApiTests(FinanceFixture, TestCase):
    def setUp(self):
        self.build()
        self.client = APIClient()

    def auth(self, user):
        self.client.force_authenticate(user)
        return self.client

    def request_payment(self, order, key='22222222-2222-4222-8222-222222222222', user=None):
        return self.auth(user or self.buyer).post(
            reverse('simulated-payment-list'),
            {'order': str(order.pk), 'client_request_id': key},
            format='json',
        )

    def test_payment_api_is_idempotent_labeled_and_scoped(self):
        order = self.make_order()
        body = {'order': str(order.pk), 'client_request_id': '22222222-2222-4222-8222-222222222222'}
        first = self.auth(self.buyer).post(reverse('simulated-payment-list'), body, format='json')
        replay = self.auth(self.buyer).post(reverse('simulated-payment-list'), body, format='json')
        self.assertEqual((first.status_code, replay.status_code), (201, 200))
        self.assertEqual(first.json(), replay.json())
        self.assertIn('SIMULATED', first.json()['simulation_label'])
        self.assertEqual(first.json()['amount_minor'], order.total_minor)
        changed = dict(body, order=str(self.make_order('1').pk))
        conflict = self.auth(self.buyer).post(reverse('simulated-payment-list'), changed, format='json')
        self.assertEqual(conflict.status_code, 409)
        payment_id = first.json()['id']
        detail = reverse('simulated-payment-detail', args=[payment_id])
        self.assertEqual(self.auth(self.buyer2).get(detail).status_code, 404)
        self.assertEqual(self.auth(self.operator).get(detail).status_code, 200)
        self.assertEqual(self.auth(self.farmer).get(detail).status_code, 403)

    def test_refund_and_settlement_apis_are_idempotent(self):
        order, payment = self.pay()
        self.buyer_favoured_dispute(order)
        refund_body = {
            'payment': str(payment.pk),
            'amount_minor': 1000,
            'reason': 'Approved adjustment',
            'client_request_id': 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
        }
        refund_first = self.auth(self.operator).post(
            reverse('simulated-refund-list'), refund_body, format='json',
        )
        refund_retry = self.auth(self.operator).post(
            reverse('simulated-refund-list'), refund_body, format='json',
        )
        self.assertEqual((refund_first.status_code, refund_retry.status_code), (201, 200))
        self.assertEqual(refund_first.json(), refund_retry.json())
        self.assertEqual(Refund.objects.count(), 1)

        completed, _ = self.complete_order()
        settlement_body = {
            'order': str(completed.pk),
            'client_request_id': 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
        }
        settlement_first = self.auth(self.operator).post(
            reverse('simulated-settlement-list'), settlement_body, format='json',
        )
        settlement_retry = self.auth(self.operator).post(
            reverse('simulated-settlement-list'), settlement_body, format='json',
        )
        self.assertEqual((settlement_first.status_code, settlement_retry.status_code), (201, 200))
        self.assertEqual(settlement_first.json(), settlement_retry.json())
        self.assertEqual(Settlement.objects.count(), 1)

    def test_refund_and_settlement_apis_require_finance_role(self):
        order = self.make_order()
        payment = services.create_simulated_payment(order.pk, self.buyer)
        self.buyer_favoured_dispute(order)
        body = {
            'payment': str(payment.pk), 'amount_minor': 1000, 'reason': 'Decision',
            'client_request_id': '33333333-3333-4333-8333-333333333333',
        }
        for user in (self.buyer, self.farmer):
            response = self.auth(user).post(reverse('simulated-refund-list'), body, format='json')
            self.assertEqual(response.status_code, 403, response.content)
        response = self.auth(self.operator).post(
            reverse('simulated-refund-list'), body, format='json',
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertIn('SIMULATED', response.json()['simulation_label'])
        # Read-only journal/report surfaces are restricted to finance and operations.
        self.assertEqual(self.auth(self.buyer).get(reverse('finance-journal-list')).status_code, 403)
        self.assertEqual(self.auth(self.operator).get(reverse('finance-journal-list')).status_code, 200)
        self.assertEqual(self.auth(self.admin).get(reverse('finance-ledger-account-list')).status_code, 200)
        self.assertEqual(
            self.auth(self.operator).post(reverse('finance-journal-list'), {}).status_code, 405,
        )

    def test_unrelated_integrity_errors_are_not_replayed(self):
        order = self.make_order()
        body = {'order': str(order.pk), 'client_request_id': '44444444-4444-4444-8444-444444444444'}
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                from unittest import mock
                with mock.patch.object(
                    services, 'create_simulated_payment',
                    side_effect=IntegrityError('unrelated integrity failure'),
                ):
                    self.auth(self.buyer).post(reverse('simulated-payment-list'), body, format='json')
        self.assertFalse(IdempotencyRecord.objects.filter(scope='finance.payment.create').exists())


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL triggers and row locks only.')
class FinancePostgresTests(FinanceFixture, TransactionTestCase):
    def setUp(self):
        # Earlier TransactionTestCase classes flush migration-seeded rows. Restore only
        # the system accounts this PostgreSQL-only class needs; serialized rollback
        # collides with content types recreated by post_migrate.
        for code, name, account_type in (
            ('SIM_PAYMENT_CLEARING', 'Simulated payment clearing (no real funds)', 'asset'),
            ('SELLER_PAYABLE', 'Simulated seller payable', 'liability'),
            ('SELLER_RECEIVABLE', 'Simulated seller receivable', 'asset'),
            ('SIM_PAYOUT_CLEARING', 'Simulated payout clearing (no real payout)', 'asset'),
        ):
            LedgerAccount.objects.get_or_create(
                code=code,
                defaults={
                    'name': name, 'account_type': account_type, 'currency': 'NGN',
                    'is_system': True,
                },
            )
        self.build()

    def test_database_rejects_unbalanced_posted_journal(self):
        account = LedgerAccount.objects.get(code='SIM_PAYMENT_CLEARING')
        with self.assertRaises(Exception) as ctx:
            with transaction.atomic():
                journal = Journal.objects.create(
                    reference='unbalanced-test', source_type='test', source_id='00000000-0000-0000-0000-000000000001',
                    kind='invalid', debit_total_minor=100, credit_total_minor=100, memo='invalid',
                )
                JournalLine.objects.create(
                    journal=journal, account=account, line_number=1, debit_minor=100, credit_minor=0,
                )
                JournalLine.objects.create(
                    journal=journal, account=account, line_number=2, debit_minor=0, credit_minor=90,
                )
        self.assertIn('not balanced', str(ctx.exception))

    def test_postgresql_triggers_block_finance_mutations(self):
        order = self.make_order()
        payment = services.create_simulated_payment(order.pk, self.buyer)
        journal = Journal.objects.get(source_type='payment', source_id=payment.pk)
        line = journal.lines.first()
        sql_statements = (
            ('UPDATE finance_ledgeraccount SET name = %s WHERE id = %s', ['changed', line.account_id]),
            ('DELETE FROM finance_journal WHERE id = %s', [journal.pk]),
            ('UPDATE finance_journalline SET debit_minor = 1 WHERE id = %s', [line.pk]),
            ('DELETE FROM finance_simulatedpayment WHERE id = %s', [payment.pk]),
        )
        for sql, params in sql_statements:
            with self.assertRaises(Exception) as ctx, transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(sql, params)
            self.assertIn('immutable', str(ctx.exception))

    def test_concurrent_payment_retries_post_once(self):
        order = self.make_order()
        barrier = Barrier(8)
        key = '55555555-5555-4555-8555-555555555555'

        def submit(_):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(self.buyer)
                barrier.wait(timeout=10)
                response = client.post(reverse('simulated-payment-list'), {
                    'order': str(order.pk), 'client_request_id': key,
                }, format='json')
                return response.status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=8) as executor:
            statuses = list(executor.map(submit, range(8)))
        self.assertEqual(sorted(statuses), [200] * 7 + [201], statuses)
        self.assertEqual(SimulatedPayment.objects.count(), 1)
        self.assertEqual(Journal.objects.filter(source_type='payment').count(), 1)

    def test_concurrent_refunds_respect_paid_amount_cap(self):
        order = self.make_order()
        payment = services.create_simulated_payment(order.pk, self.buyer)
        self.buyer_favoured_dispute(order)
        barrier = Barrier(4)

        def refund(_):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return services.create_simulated_refund(
                    payment.pk, 6000, 'Concurrent test', self.operator,
                )
            except services.FinanceError as exc:
                return exc
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(refund, range(4)))
        successful = [result for result in results if isinstance(result, Refund)]
        self.assertEqual(len(successful), 1, results)
        self.assertEqual(Refund.objects.aggregate(total=Sum('amount_minor'))['total'], 6000)
        self.assertEqual(Journal.objects.filter(source_type='refund').count(), 1)
