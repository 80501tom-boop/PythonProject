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


class PredictionHistory(models.Model):
    """
    AI 前瞻預測歷史紀錄。
    每次產生排名時，保存當次預測結果，不覆蓋先前紀錄。
    """

    prediction_date = models.DateField(
        verbose_name="預測產生日期"
    )

    data_date = models.DateField(
        verbose_name="股價資料日期"
    )

    symbol = models.CharField(
        max_length=10,
        db_index=True,
        verbose_name="股票代號"
    )

    stock_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="股票名稱"
    )

    close_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="預測基準收盤價"
    )

    predicted_return_20 = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        verbose_name="預測20日報酬率（百分比）"
    )

    rank = models.PositiveIntegerField(
        verbose_name="當次排名"
    )

    model_version = models.CharField(
        max_length=50,
        default="V5.7-FORWARD",
        verbose_name="模型版本"
    )

    horizon = models.PositiveIntegerField(
        default=20,
        verbose_name="預測交易日數"
    )

    # ===== V6.0 實際績效追蹤欄位 =====

    actual_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="實際報酬計算日期"
    )

    actual_close_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="實際收盤價"
    )

    actual_return_20 = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name="實際報酬率（百分比）"
    )

    prediction_error = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name="預測誤差（百分點）"
    )

    direction_correct = models.BooleanField(
        null=True,
        blank=True,
        verbose_name="漲跌方向是否預測正確"
    )

    evaluated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="績效評估時間"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="紀錄建立時間"
    )

    class Meta:
        ordering = ["-created_at", "rank"]
        indexes = [
            models.Index(
                fields=["prediction_date", "symbol"],
                name="pred_date_symbol_idx"
            ),
        ]
        verbose_name = "AI 歷史預測"
        verbose_name_plural = "AI 歷史預測"

    def __str__(self):
        return (
            f"{self.prediction_date} "
            f"{self.symbol} "
            f"Rank {self.rank}"
        )
