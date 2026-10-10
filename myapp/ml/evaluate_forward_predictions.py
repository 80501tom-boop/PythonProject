
# -*- coding: utf-8 -*-
"""
V6.0 - 前瞻預測實際績效追蹤

功能：
1. 讀取 PredictionHistory 中尚未評估的預測。
2. 從預測基準日之後，尋找第 N 個交易日的收盤價。
3. 計算實際報酬率、預測誤差、漲跌方向是否正確。
4. 未滿預測天數的紀錄保留等待，不提前評分。
5. 不修改原始預測值，也不重新訓練模型。
"""

import os
import sys
from pathlib import Path
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# ==================================================
# Django 初始化
# ==================================================

BASE_DIR = Path(__file__).resolve().parents[2]

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "PythonProject.settings"
)

import django

django.setup()

from django.utils import timezone
from myapp.models import Stock, PredictionHistory


# ==================================================
# 設定
# ==================================================

VERSION = "V6.0"

FOUR_PLACES = Decimal("0.0001")


def to_decimal(value):
    """將數值安全轉換為 Decimal。"""
    return Decimal(str(value))


def calculate_actual_return(base_price, actual_price):
    """
    計算實際報酬率，單位為百分比。
    例如 5.25 表示 +5.25%。
    """
    base_price = to_decimal(base_price)
    actual_price = to_decimal(actual_price)

    if base_price <= 0:
        raise ValueError("預測基準收盤價必須大於 0。")

    actual_return = (
        (actual_price / base_price) - Decimal("1")
    ) * Decimal("100")

    return actual_return.quantize(
        FOUR_PLACES,
        rounding=ROUND_HALF_UP
    )


def evaluate_one(record):
    """評估單筆預測。"""

    symbol = str(record.symbol).strip()
    horizon = int(record.horizon)

    if horizon <= 0:
        print(f"[略過] {symbol}：預測交易日數不正確")
        return "skipped"

    # 依股票代號尋找股票資料
    stock = Stock.objects.filter(
        symbol=symbol
    ).first()

    if stock is None:
        # 避免前導零格式不同造成找不到股票
        stock = Stock.objects.filter(
            symbol=symbol.lstrip("0")
        ).first()

    if stock is None:
        print(f"[略過] {symbol}：找不到 Stock 資料")
        return "missing_stock"

    # 只取基準日之後的交易日，按日期由早到晚排序
    future_prices = list(
        stock.prices
        .filter(date__gt=record.data_date)
        .order_by("date")
        .values("date", "close_price")[:horizon]
    )

    # 尚未累積足夠交易日
    if len(future_prices) < horizon:
        print(
            f"[等待] {symbol}："
            f"目前 {len(future_prices)}/{horizon} 個交易日"
        )
        return "waiting"

    target = future_prices[horizon - 1]

    actual_date = target["date"]
    actual_close = to_decimal(target["close_price"])

    try:
        actual_return = calculate_actual_return(
            record.close_price,
            actual_close
        )

        predicted_return = to_decimal(
            record.predicted_return_20
        )

    except (InvalidOperation, ValueError) as exc:
        print(f"[錯誤] {symbol}：{exc}")
        return "error"

    # 誤差定義：實際報酬 - 預測報酬，單位為百分點
    prediction_error = (
        actual_return - predicted_return
    ).quantize(
        FOUR_PLACES,
        rounding=ROUND_HALF_UP
    )

    # 漲跌方向相同才算命中。
    # 預測或實際報酬為 0 時，只有兩者都為 0 才算相同。
    if predicted_return > 0:
        direction_correct = actual_return > 0
    elif predicted_return < 0:
        direction_correct = actual_return < 0
    else:
        direction_correct = actual_return == 0

    # 保存評估結果，保留原始預測資料
    record.actual_date = actual_date
    record.actual_close_price = actual_close
    record.actual_return_20 = actual_return
    record.prediction_error = prediction_error
    record.direction_correct = direction_correct
    record.evaluated_at = timezone.now()

    record.save(
        update_fields=[
            "actual_date",
            "actual_close_price",
            "actual_return_20",
            "prediction_error",
            "direction_correct",
            "evaluated_at",
        ]
    )

    print(
        f"[完成] {symbol} | "
        f"基準日 {record.data_date} | "
        f"實際日期 {actual_date} | "
        f"預測 {predicted_return:+.4f}% | "
        f"實際 {actual_return:+.4f}% | "
        f"誤差 {prediction_error:+.4f} 個百分點"
    )

    return "evaluated"


def main():
    print("=" * 65)
    print(f"{VERSION} 前瞻預測績效評估")
    print("=" * 65)

    # 只處理尚未評估的紀錄；已完成的紀錄不重複計算
    records = PredictionHistory.objects.filter(
        actual_return_20__isnull=True
    ).order_by(
        "prediction_date",
        "rank"
    )

    total = records.count()

    print(f"待評估紀錄：{total} 筆")
    print()

    counts = {
        "evaluated": 0,
        "waiting": 0,
        "missing_stock": 0,
        "skipped": 0,
        "error": 0,
    }

    for record in records.iterator():
        try:
            result = evaluate_one(record)
            counts[result] = counts.get(result, 0) + 1
        except Exception as exc:
            counts["error"] += 1
            print(
                f"[錯誤] ID={record.pk} "
                f"股票={record.symbol}：{exc}"
            )

    print()
    print("=" * 65)
    print("評估執行摘要")
    print("=" * 65)
    print(f"本次完成評估：{counts['evaluated']} 筆")
    print(f"等待更多股價：{counts['waiting']} 筆")
    print(f"找不到股票資料：{counts['missing_stock']} 筆")
    print(f"略過：{counts['skipped']} 筆")
    print(f"錯誤：{counts['error']} 筆")
    print("=" * 65)


if __name__ == "__main__":
    main()
