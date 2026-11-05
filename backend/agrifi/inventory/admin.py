from django.contrib import admin

from .models import HarvestBatch


@admin.register(HarvestBatch)
class HarvestBatchAdmin(admin.ModelAdmin):
    list_display = ('farmer', 'category', 'quantity', 'unit_code', 'harvested_on')
    list_filter = ('category',)
