from django.contrib import admin

from .models import CropCategory, Listing


@admin.register(CropCategory)
class CropCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ('name', 'seller', 'category', 'status', 'unit_price_minor')
    list_filter = ('status', 'category')
    search_fields = ('name', 'seller__email')
