from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    FinanceReportView, JournalViewSet, LedgerAccountViewSet, SimulatedPaymentViewSet,
    SimulatedRefundViewSet, SimulatedSettlementViewSet,
)

router = SimpleRouter()
router.register('simulated-payments', SimulatedPaymentViewSet, basename='simulated-payment')
router.register('simulated-refunds', SimulatedRefundViewSet, basename='simulated-refund')
router.register('simulated-settlements', SimulatedSettlementViewSet, basename='simulated-settlement')
router.register('finance/journal-entries', JournalViewSet, basename='finance-journal')
router.register('finance/ledger-accounts', LedgerAccountViewSet, basename='finance-ledger-account')

urlpatterns = [path('finance/reports/', FinanceReportView.as_view(), name='finance-report')] + router.urls
