from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'agrifi.inventory'
    label = 'inventory'
    verbose_name = 'Inventory'

    def ready(self):
        from agrifi.idempotency.services import protect_referenced_records

        from .models import HarvestBatch

        protect_referenced_records(HarvestBatch)
