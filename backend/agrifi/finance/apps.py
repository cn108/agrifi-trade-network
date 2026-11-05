from django.apps import AppConfig


class FinanceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'agrifi.finance'
    label = 'finance'
    verbose_name = 'Simulated Finance'

    def ready(self):
        from agrifi.idempotency.services import protect_referenced_records

        from .models import Journal, JournalLine, Refund, Settlement, SimulatedPayment

        for model in (Journal, JournalLine, Refund, Settlement, SimulatedPayment):
            protect_referenced_records(model)
