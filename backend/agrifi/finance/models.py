import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class ImmutableFinanceError(Exception):
    pass


class ImmutableFinanceQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ImmutableFinanceError('Posted financial records are immutable.')

    def delete(self):
        raise ImmutableFinanceError('Posted financial records are immutable.')

    def bulk_update(self, *args, **kwargs):
        raise ImmutableFinanceError('Posted financial records are immutable.')


class ImmutableFinanceModel(models.Model):
    objects = ImmutableFinanceQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableFinanceError('Posted financial records are immutable.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableFinanceError('Posted financial records are immutable.')


class LedgerAccount(models.Model):
    class Type(models.TextChoices):
        ASSET = 'asset', 'Asset (simulated)'
        LIABILITY = 'liability', 'Liability (simulated)'
        EQUITY = 'equity', 'Equity'
        REVENUE = 'revenue', 'Revenue'
        EXPENSE = 'expense', 'Expense'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    account_type = models.CharField(max_length=20, choices=Type.choices)
    currency = models.CharField(max_length=3, default='NGN')
    is_system = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('code',)

    def __str__(self):
        return f'{self.code} — {self.name}'


class Journal(ImmutableFinanceModel):
    """A posted, balanced journal. Corrections use a separate reversal journal."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=160, unique=True)
    source_type = models.CharField(max_length=40)
    source_id = models.UUIDField()
    kind = models.CharField(max_length=32)
    currency = models.CharField(max_length=3, default='NGN')
    debit_total_minor = models.BigIntegerField()
    credit_total_minor = models.BigIntegerField()
    memo = models.CharField(max_length=240)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='finance_journals_created',
    )
    reversal_of = models.OneToOneField(
        'self', null=True, blank=True, on_delete=models.PROTECT, related_name='reversal',
    )
    posted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-posted_at',)
        constraints = [
            models.CheckConstraint(
                condition=Q(debit_total_minor__gt=0), name='journal_debits_positive'
            ),
            models.CheckConstraint(
                condition=Q(debit_total_minor=F('credit_total_minor')),
                name='journal_totals_balanced',
            ),
            models.UniqueConstraint(
                fields=('source_type', 'source_id', 'kind'), name='journal_source_kind_unique'
            ),
        ]
        indexes = [models.Index(fields=('source_type', 'source_id'), name='journal_source_idx')]

    def __str__(self):
        return self.reference


class JournalLine(ImmutableFinanceModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journal = models.ForeignKey(Journal, on_delete=models.PROTECT, related_name='lines')
    account = models.ForeignKey(
        LedgerAccount, on_delete=models.PROTECT, related_name='journal_lines'
    )
    line_number = models.PositiveSmallIntegerField()
    debit_minor = models.BigIntegerField(default=0)
    credit_minor = models.BigIntegerField(default=0)
    memo = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ('journal_id', 'line_number')
        constraints = [
            models.UniqueConstraint(
                fields=('journal', 'line_number'), name='journal_line_number_unique'
            ),
            models.CheckConstraint(
                condition=(
                    Q(debit_minor__gt=0, credit_minor=0)
                    | Q(debit_minor=0, credit_minor__gt=0)
                ),
                name='journal_line_one_positive_side',
            ),
        ]


class SimulatedPayment(ImmutableFinanceModel):
    class Status(models.TextChoices):
        SUCCEEDED = 'simulated_succeeded', 'Simulated payment succeeded'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.OneToOneField(
        'orders.Order', on_delete=models.PROTECT, related_name='simulated_payment'
    )
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='simulated_payments'
    )
    amount_minor = models.BigIntegerField()
    currency = models.CharField(max_length=3, default='NGN')
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.SUCCEEDED)
    simulation_label = models.CharField(max_length=64, default='SIMULATED — NO MONEY MOVED')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_minor__gt=0), name='sim_payment_amount_positive'
            ),
        ]
        indexes = [models.Index(fields=('buyer', 'created_at'), name='sim_payment_buyer_idx')]


class Refund(ImmutableFinanceModel):
    class Status(models.TextChoices):
        SUCCEEDED = 'simulated_succeeded', 'Simulated refund succeeded'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(
        SimulatedPayment, on_delete=models.PROTECT, related_name='refunds'
    )
    amount_minor = models.BigIntegerField()
    currency = models.CharField(max_length=3, default='NGN')
    reason = models.TextField()
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.SUCCEEDED)
    simulation_label = models.CharField(max_length=64, default='SIMULATED — NO MONEY MOVED')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='simulated_refunds'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.CheckConstraint(condition=Q(amount_minor__gt=0), name='sim_refund_positive'),
        ]


class Settlement(ImmutableFinanceModel):
    class Status(models.TextChoices):
        RECORDED = 'simulated_recorded', 'Simulated settlement recorded'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.OneToOneField(
        SimulatedPayment, on_delete=models.PROTECT, related_name='settlement'
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='simulated_settlements'
    )
    amount_minor = models.BigIntegerField()
    currency = models.CharField(max_length=3, default='NGN')
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.RECORDED)
    simulation_label = models.CharField(max_length=64, default='SIMULATED — NO MONEY MOVED')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='settlements_recorded'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_minor__gt=0), name='sim_settlement_positive'
            ),
        ]
