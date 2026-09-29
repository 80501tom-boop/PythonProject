from django.contrib import admin
from .models import Stock, StockPrice

# username: tom password: 12345
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


@admin.register(StockPrice)
class StockPriceAdmin(admin.ModelAdmin):

    list_display = (
        "stock",
        "date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
    )

    search_fields = (
        "stock__symbol",
        "stock__name",
    )

    list_filter = (
        "date",
    )

    ordering = (
        "-date",
    )