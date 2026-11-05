from django.test import TestCase
from django.utils import timezone

from agrifi.orders.models import Order

from . import services
from .models import Journal
from .tests import FinanceFixture

URL = '/api/v1/finance/reports/'


class FinanceReportTests(FinanceFixture, TestCase):
    def setUp(self):
        self.build()
        from rest_framework.test import APIClient
        self.client = APIClient()

    def get(self, user, query=''):
        self.client.force_authenticate(user)
        return self.client.get(URL + query)

    def test_empty_report_is_balanced_and_labelled_simulated(self):
        body = self.get(self.operator).json()

        self.assertTrue(body['simulated'])
        self.assertIn('SIMULATED', body['simulation_label'])
        self.assertEqual(body['trial_balance']['accounts'], [])
        self.assertEqual(body['payments'], [])

    def test_report_aggregates_payments_refunds_and_trial_balance(self):
        order, payment = self.complete_order()
        services.create_simulated_settlement(order.pk, self.operator)
        disputed, disputed_payment = self.pay()
        self.buyer_favoured_dispute(disputed)
        services.create_simulated_refund(disputed_payment.pk, 1000, 'Partial', self.operator)

        body = self.get(self.admin).json()

        self.assertEqual(body['payments'], [{
            'currency': 'NGN', 'status': 'simulated_succeeded', 'count': 2,
            'total_minor': payment.amount_minor + disputed_payment.amount_minor,
        }])
        self.assertEqual(body['refunds'][0]['total_minor'], 1000)
        self.assertEqual(body['settlements'][0]['count'], 1)
        totals = body['trial_balance']['totals']
        self.assertEqual(len(totals), 1)
        self.assertTrue(totals[0]['balanced'])
        self.assertGreater(totals[0]['debit_minor'], 0)
        kinds = {row['kind'] for row in body['journals']}
        self.assertEqual(kinds, {'capture', 'refund', 'settlement'})
        self.assertEqual(sum(row['count'] for row in body['journals']), Journal.objects.count())
        self.assertEqual(
            sum(row['debit_minor'] for row in body['trial_balance']['accounts']),
            totals[0]['debit_minor'],
        )

    def test_period_filter_excludes_outside_records(self):
        self.pay()
        future = (timezone.now() + timezone.timedelta(days=1)).isoformat().replace('+', '%2B')

        outside = self.get(self.operator, f'?start={future}').json()
        inside = self.get(self.operator, '?end=' + future).json()

        self.assertEqual(outside['payments'], [])
        self.assertEqual(outside['trial_balance']['accounts'], [])
        self.assertEqual(len(inside['payments']), 1)

    def test_invalid_period_is_a_validation_error(self):
        for query in ('?start=yesterday', '?end=2026-01-01T00:00:00',
                      '?start=2026-02-01T00:00:00Z&end=2026-01-01T00:00:00Z'):
            with self.subTest(query=query):
                response = self.get(self.operator, query)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['code'], 'validation_error')

    def test_only_finance_roles_can_read(self):
        self.assertEqual(self.client.get(URL).status_code, 401)
        for user in (self.buyer, self.farmer):
            self.assertEqual(self.get(user).status_code, 403)
        for user in (self.operator, self.admin):
            self.assertEqual(self.get(user).status_code, 200)

    def test_report_is_read_only(self):
        self.client.force_authenticate(self.operator)

        self.assertEqual(self.client.post(URL, {}, format='json').status_code, 405)
        self.assertEqual(Order.objects.filter(status=Order.Status.CANCELLED).count(), 0)

    def test_query_count_does_not_grow_with_records(self):
        self.client.force_authenticate(self.operator)
        self.pay()
        with self.assertNumQueries(6):
            self.client.get(URL)
        self.pay(self.make_order('3'))
        with self.assertNumQueries(6):
            self.client.get(URL)
