from django.contrib import admin
from .models import Stock


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):

    list_display = (
        "symbol",
        "name",
        "market",
        "created_at",
        "updated_at",
    )

    search_fields = (
        "symbol",
        "name",
    )

    list_filter = (
        "market",
    )