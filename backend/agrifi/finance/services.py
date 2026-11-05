"""Simulated financial workflows and immutable double-entry postings.

No gateway, bank, cash, escrow or external payout is called by this module.
"""
import uuid

from django.db import transaction
from django.db.models import Count, Sum

from agrifi.accounts.models import UserRole
from agrifi.accounts.permissions import user_has_role
from agrifi.audit import services as audit
from agrifi.catalog.permissions import is_ops_admin
from agrifi.orders.models import Dispute, Order

from .models import (
    Journal, JournalLine, LedgerAccount, Refund, Settlement, SimulatedPayment,
)

MAX_MINOR = 9_223_372_036_854_775_807
SIM_PAYMENT_CLEARING = 'SIM_PAYMENT_CLEARING'
SELLER_PAYABLE = 'SELLER_PAYABLE'
SELLER_RECEIVABLE = 'SELLER_RECEIVABLE'
SIM_PAYOUT_CLEARING = 'SIM_PAYOUT_CLEARING'


class FinanceError(Exception):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _require_finance_operator(actor):
    if not (is_ops_admin(actor) or user_has_role(actor, UserRole.Role.FINANCE_OPERATOR)):
        raise FinanceError('forbidden', 'Only finance operators can perform this operation.', 403)


def _post_journal(source_type, source_id, kind, memo, actor, entries, journal_id=None,
                  reversal_of=None):
    """Validate and create a whole posted journal atomically; totals are stored for DB checks."""
    if len(entries) < 2:
        raise FinanceError('invalid_journal', 'A journal needs at least two lines.', 400)
    resolved = []
    debit_total = credit_total = 0
    for line_number, (code, debit, credit, line_memo) in enumerate(entries, start=1):
        if (not isinstance(debit, int) or isinstance(debit, bool)
                or not isinstance(credit, int) or isinstance(credit, bool)):
            raise FinanceError('invalid_amount', 'Journal amounts must be integer minor units.', 400)
        if debit < 0 or credit < 0 or (debit > 0) == (credit > 0):
            raise FinanceError('invalid_journal_line', 'Exactly one positive debit or credit is required.', 400)
        account = LedgerAccount.objects.get(code=code)
        if account.currency != 'NGN':
            raise FinanceError('currency_mismatch', 'Journal account currency must match the event.', 400)
        debit_total += debit
        credit_total += credit
        resolved.append((line_number, account, debit, credit, line_memo))
    if debit_total <= 0 or debit_total != credit_total:
        raise FinanceError('unbalanced_journal', 'Journal debits and credits must balance.', 400)
    if debit_total > MAX_MINOR or credit_total > MAX_MINOR:
        raise FinanceError('amount_too_large', 'Journal amount exceeds the supported range.', 400)

    journal = Journal.objects.create(
        id=journal_id or uuid.uuid4(),
        reference=f'SIM-{source_type.upper()}-{source_id}-{kind.upper()}',
        source_type=source_type,
        source_id=source_id,
        kind=kind,
        currency='NGN',
        debit_total_minor=debit_total,
        credit_total_minor=credit_total,
        memo=memo[:240],
        created_by=actor,
        reversal_of=reversal_of,
    )
    JournalLine.objects.bulk_create([
        JournalLine(
            journal=journal, account=account, line_number=line_number,
            debit_minor=debit, credit_minor=credit, memo=line_memo[:240],
        )
        for line_number, account, debit, credit, line_memo in resolved
    ])
    audit.record(
        f'finance.{kind}_posted', actor, journal,
        {'amount_minor': debit_total, 'currency': 'NGN', 'reason': memo},
    )
    return journal


def create_simulated_payment(order_id, buyer, payment_id=None):
    """Record a simulated successful payment for a confirmed order, never charge money."""
    with transaction.atomic():
        try:
            order = Order.objects.select_for_update().get(pk=order_id)
        except Order.DoesNotExist as exc:
            raise FinanceError('not_found', 'Order was not found.', 404) from exc
        if not user_has_role(buyer, UserRole.Role.BUYER) or order.buyer_id != buyer.pk:
            raise FinanceError('forbidden', 'Only the order buyer can record payment.', 403)
        if order.status != Order.Status.CONFIRMED:
            raise FinanceError('invalid_order_state', 'Payment simulation requires a confirmed order.')
        if SimulatedPayment.objects.filter(order=order).exists():
            raise FinanceError('payment_exists', 'This order already has a simulated payment.')
        payment = SimulatedPayment.objects.create(
            id=payment_id or uuid.uuid4(), order=order, buyer=buyer,
            amount_minor=order.total_minor, currency=order.currency,
        )
        _post_journal(
            'payment', payment.pk, 'capture', 'Simulated order payment; no money moved.',
            buyer,
            [
                (SIM_PAYMENT_CLEARING, payment.amount_minor, 0, 'Simulated payment clearing'),
                (SELLER_PAYABLE, 0, payment.amount_minor, 'Amount payable to seller'),
            ],
        )
    return payment


def create_simulated_refund(payment_id, amount_minor, reason, actor, refund_id=None):
    """Record an operations-approved simulated refund, capped under payment/order locks."""
    _require_finance_operator(actor)
    if not isinstance(amount_minor, int) or isinstance(amount_minor, bool) or amount_minor <= 0:
        raise FinanceError('invalid_amount', 'Refund amount must be positive integer kobo.', 400)
    payment_ref = SimulatedPayment.objects.filter(pk=payment_id).values('order_id').first()
    if payment_ref is None:
        raise FinanceError('not_found', 'Payment was not found.', 404)
    with transaction.atomic():
        try:
            order = Order.objects.select_for_update().get(pk=payment_ref['order_id'])
            payment = SimulatedPayment.objects.select_for_update().get(pk=payment_id)
        except (Order.DoesNotExist, SimulatedPayment.DoesNotExist) as exc:
            raise FinanceError('not_found', 'Payment was not found.', 404) from exc
        if order.status not in (Order.Status.CANCELLED, Order.Status.DISPUTE_RESOLVED):
            raise FinanceError('refund_not_eligible', 'Refund requires a buyer-favoured dispute resolution.')
        if not order.disputes.filter(
            status=Dispute.Status.RESOLVED, outcome=Dispute.Outcome.BUYER_FAVOURED
        ).exists():
            raise FinanceError('refund_not_eligible', 'No buyer-favoured dispute is recorded.')
        refunded = payment.refunds.aggregate(total=Sum('amount_minor'))['total'] or 0
        remaining = payment.amount_minor - refunded
        if amount_minor > remaining:
            raise FinanceError('refund_exceeds_paid', 'Refund exceeds the remaining simulated-paid amount.', 400)
        refund = Refund.objects.create(
            id=refund_id or uuid.uuid4(), payment=payment, amount_minor=amount_minor,
            currency=payment.currency, reason=reason, created_by=actor,
        )
        settled = Settlement.objects.filter(payment=payment).exists()
        debit_account = SELLER_RECEIVABLE if settled else SELLER_PAYABLE
        _post_journal(
            'refund', refund.pk, 'refund', 'Simulated refund; no money moved.', actor,
            [
                (debit_account, amount_minor, 0, 'Reverse seller proceeds or record receivable'),
                (SIM_PAYMENT_CLEARING, 0, amount_minor, 'Simulated refund clearing'),
            ],
        )
    return refund


def create_simulated_settlement(order_id, actor, settlement_id=None):
    """Record a simulated seller settlement only after order completion."""
    _require_finance_operator(actor)
    with transaction.atomic():
        try:
            order = Order.objects.select_for_update().get(pk=order_id)
        except Order.DoesNotExist as exc:
            raise FinanceError('not_found', 'Order was not found.', 404) from exc
        if order.status != Order.Status.COMPLETED:
            raise FinanceError('settlement_not_eligible', 'Settlement requires a completed order.')
        try:
            payment = SimulatedPayment.objects.select_for_update().get(order=order)
        except SimulatedPayment.DoesNotExist as exc:
            raise FinanceError('payment_required', 'A simulated payment is required before settlement.') from exc
        if Settlement.objects.filter(payment=payment).exists():
            raise FinanceError('settlement_exists', 'This payment is already settled.')
        refunded = payment.refunds.aggregate(total=Sum('amount_minor'))['total'] or 0
        net_amount = payment.amount_minor - refunded
        if net_amount <= 0:
            raise FinanceError('no_settlement_due', 'No simulated seller proceeds remain.')
        settlement = Settlement.objects.create(
            id=settlement_id or uuid.uuid4(), payment=payment, seller=order.seller,
            amount_minor=net_amount, currency=payment.currency, created_by=actor,
        )
        _post_journal(
            'settlement', settlement.pk, 'settlement',
            'Simulated settlement record; no payout or money transfer occurred.', actor,
            [
                (SELLER_PAYABLE, net_amount, 0, 'Clear seller payable'),
                (SIM_PAYOUT_CLEARING, 0, net_amount, 'Simulated payout clearing'),
            ],
        )
    return settlement


def reverse_journal(journal_id, actor, reason, reversal_id=None):
    """Append a compensating journal; the original posted journal is never edited.

    Callers correcting a business event must update its projection in the same outer
    transaction; this primitive intentionally changes only ledger history.
    """
    _require_finance_operator(actor)
    with transaction.atomic():
        try:
            original = Journal.objects.select_for_update().get(pk=journal_id)
        except Journal.DoesNotExist as exc:
            raise FinanceError('not_found', 'Journal was not found.', 404) from exc
        if original.reversal_of_id:
            raise FinanceError('invalid_reversal', 'A reversal journal cannot itself be reversed.')
        existing_reversal = Journal.objects.filter(reversal_of=original).first()
        if existing_reversal is not None:
            return existing_reversal
        lines = list(original.lines.select_related('account').order_by('line_number'))
        if not lines:
            raise FinanceError('invalid_journal', 'Cannot reverse a journal with no lines.')
        reversal = _post_journal(
            'reversal', original.pk, 'reversal', f'Reversal: {reason}', actor,
            [
                (line.account.code, line.credit_minor, line.debit_minor, f'Reversal of {line.memo}')
                for line in lines
            ],
            journal_id=reversal_id,
            reversal_of=original,
        )
    return reversal


def journal_is_balanced(journal):
    totals = journal.lines.aggregate(
        debits=Sum('debit_minor'), credits=Sum('credit_minor'), count=Count('id'),
    )
    # The DB trigger enforces at least two lines on PostgreSQL; the posting service
    # independently validates it on every backend.
    return (
        totals['debits'] == journal.debit_total_minor
        and totals['credits'] == journal.credit_total_minor
        and journal.debit_total_minor == journal.credit_total_minor
        and totals['count'] >= 2
    )


def account_balance(account):
    """Derived net debit balance. No mutable account balance is stored."""
    totals = account.journal_lines.aggregate(
        debits=Sum('debit_minor'), credits=Sum('credit_minor'),
    )
    return (totals['debits'] or 0) - (totals['credits'] or 0)


def build_report(start=None, end=None):
    """Read-only reporting derived from the immutable journal with DB aggregates.

    `start` is inclusive and `end` is exclusive, both timezone-aware datetimes applied to
    journal posting time (journals) or creation time (payments/refunds/settlements)."""
    def window(queryset, field):
        if start is not None:
            queryset = queryset.filter(**{f'{field}__gte': start})
        if end is not None:
            queryset = queryset.filter(**{f'{field}__lt': end})
        return queryset

    lines = window(JournalLine.objects.all(), 'journal__posted_at')
    per_account = lines.values(
        'account__code', 'account__name', 'account__account_type', 'account__currency',
    ).annotate(debits=Sum('debit_minor'), credits=Sum('credit_minor')).order_by(
        'account__currency', 'account__code',
    )
    accounts = []
    totals = {}
    for row in per_account:
        debits, credits = row['debits'] or 0, row['credits'] or 0
        currency = row['account__currency']
        accounts.append({
            'code': row['account__code'], 'name': row['account__name'],
            'account_type': row['account__account_type'], 'currency': currency,
            'debit_minor': debits, 'credit_minor': credits, 'net_debit_minor': debits - credits,
        })
        total = totals.setdefault(currency, {'currency': currency, 'debit_minor': 0, 'credit_minor': 0})
        total['debit_minor'] += debits
        total['credit_minor'] += credits
    trial_balance_totals = []
    for total in totals.values():
        total['balanced'] = total['debit_minor'] == total['credit_minor']
        trial_balance_totals.append(total)

    def summarise(model, extra=()):
        rows = window(model.objects.all(), 'created_at').values('currency', 'status', *extra).annotate(
            count=Count('id'), total_minor=Sum('amount_minor'),
        ).order_by('currency', 'status', *extra)
        return [{**row, 'total_minor': row['total_minor'] or 0} for row in rows]

    journals = window(Journal.objects.all(), 'posted_at').values('currency', 'kind').annotate(
        count=Count('id'), total_minor=Sum('debit_total_minor'),
    ).order_by('currency', 'kind')
    return {
        'simulated': True,
        'simulation_label': 'SIMULATED — NO MONEY MOVED',
        'period': {
            'start': start.isoformat() if start else None,
            'end': end.isoformat() if end else None,
        },
        'trial_balance': {'accounts': accounts, 'totals': trial_balance_totals},
        'journals': list(journals),
        'payments': summarise(SimulatedPayment),
        'refunds': summarise(Refund),
        'settlements': summarise(Settlement),
    }
