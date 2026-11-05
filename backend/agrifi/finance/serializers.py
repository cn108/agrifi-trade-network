from rest_framework import serializers

from .models import (
    Journal, JournalLine, LedgerAccount, Refund, Settlement, SimulatedPayment,
)


class SimulatedPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SimulatedPayment
        fields = (
            'id', 'order', 'buyer', 'amount_minor', 'currency', 'status',
            'simulation_label', 'created_at',
        )
        read_only_fields = fields


class RefundSerializer(serializers.ModelSerializer):
    class Meta:
        model = Refund
        fields = (
            'id', 'payment', 'amount_minor', 'currency', 'reason', 'status',
            'simulation_label', 'created_by', 'created_at',
        )
        read_only_fields = fields


class SettlementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Settlement
        fields = (
            'id', 'payment', 'seller', 'amount_minor', 'currency', 'status',
            'simulation_label', 'created_by', 'created_at',
        )
        read_only_fields = fields


class JournalLineSerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(source='account.code', read_only=True)
    account_name = serializers.CharField(source='account.name', read_only=True)

    class Meta:
        model = JournalLine
        fields = (
            'line_number', 'account_code', 'account_name', 'debit_minor', 'credit_minor', 'memo',
        )
        read_only_fields = fields


class JournalSerializer(serializers.ModelSerializer):
    lines = JournalLineSerializer(many=True, read_only=True)

    class Meta:
        model = Journal
        fields = (
            'id', 'reference', 'source_type', 'source_id', 'kind', 'currency',
            'debit_total_minor', 'credit_total_minor', 'memo', 'reversal_of',
            'posted_at', 'lines',
        )
        read_only_fields = fields


class LedgerAccountSerializer(serializers.ModelSerializer):
    debit_balance_minor = serializers.SerializerMethodField()

    class Meta:
        model = LedgerAccount
        fields = ('code', 'name', 'account_type', 'currency', 'debit_balance_minor')
        read_only_fields = fields

    def get_debit_balance_minor(self, account) -> int:
        from .services import account_balance

        return account_balance(account)


class CreatePaymentSerializer(serializers.Serializer):
    order = serializers.UUIDField()
    client_request_id = serializers.UUIDField()


class CreateRefundSerializer(serializers.Serializer):
    payment = serializers.UUIDField()
    amount_minor = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=1000)
    client_request_id = serializers.UUIDField()


class CreateSettlementSerializer(serializers.Serializer):
    order = serializers.UUIDField()
    client_request_id = serializers.UUIDField()
