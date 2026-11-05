from django.apps import AppConfig


class OrdersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'agrifi.orders'
    label = 'orders'
    verbose_name = 'Orders'

    def ready(self):
        from agrifi.idempotency.services import protect_referenced_records

        from .models import Order

        protect_referenced_records(Order)
