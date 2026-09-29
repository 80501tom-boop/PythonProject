from django.db import models


class Stock(models.Model):

    symbol = models.CharField(
        max_length=10,
        unique=True
    )

    name = models.CharField(
        max_length=50
    )

    market = models.CharField(
        max_length=20,
        default="TWSE"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ["symbol"]

    def __str__(self):
        return f"{self.symbol} {self.name}"


class StockPrice(models.Model):

    stock = models.ForeignKey(
        Stock,
        on_delete=models.CASCADE,
        related_name="prices"
    )

    date = models.DateField()

    open_price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    high_price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    low_price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    close_price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    volume = models.BigIntegerField(
        default=0
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:

        ordering = ["-date"]

        constraints = [
            models.UniqueConstraint(
                fields=["stock", "date"],
                name="unique_stock_date"
            )
        ]

    def __str__(self):
        return f"{self.stock.symbol} - {self.date}"