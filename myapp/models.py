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