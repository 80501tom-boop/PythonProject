
# -*- coding: utf-8 -*-
"""
V6.1 - 前瞻預測實際績效追蹤

功能：
1. 讀取尚未完成評估的 PredictionHistory。
2. 依每筆紀錄的 horizon，尋找基準日之後第 N 個有效交易日。
3. 計算實際報酬、預測誤差及方向正確率。
4. 未滿交易日數的紀錄繼續等待，不提前評分。
5. 排除無效基準價、無效實際收盤價。
6. 不修改原始預測值，不重新訓練模型。
7. 已完成評估的紀錄不重複計算。

執行：
    python myapp/ml/evaluate_forward_predictions.py
"""

import csv
import os
import sys
from datetime import date, datetime
from pathlib import Path
from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_HALF_UP,
)

# ==================================================
# Django 初始化
# ==================================================

BASE_DIR = Path(__file__).resolve().parents[2]

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "PythonProject.settings",
)

import django

django.setup()

from django.db import transaction
from django.utils import timezone

from myapp.models import Stock, StockPrice, PredictionHistory


# ==================================================
# 設定
# ==================================================

VERSION = "V6.1"
FOUR_PLACES = Decimal("0.0001")
ZERO = Decimal("0")
ADJUSTED_PATH = BASE_DIR / "adjusted_prices.csv"
_ADJ_CACHE = {}


# ==================================================
# 數值與股票代號處理
# ==================================================

def to_decimal(value):
    """安全轉換 Decimal。"""
    if value is None:
        raise ValueError("數值不可為空")

    result = Decimal(str(value))

    if not result.is_finite():
        raise ValueError("數值不是有效的有限數字")

    return result


def load_adjusted_map():
    """
    讀取還原收盤價，回傳 {symbol: [(date, adj_close), ...]}（依日期排序）。

    預測時的訓練標籤也使用還原價，評估需使用同一基準，
    否則高配息標的（如 ETF）會被低估報酬。
    """
    if "map" in _ADJ_CACHE:
        return _ADJ_CACHE["map"]

    if not ADJUSTED_PATH.exists():
        raise FileNotFoundError(
            f"找不到 {ADJUSTED_PATH}，請先執行 scripts/adjust_prices.py"
        )

    grouped = {}

    with ADJUSTED_PATH.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            symbol = normalize_symbol(row["symbol"])
            day = date.fromisoformat(row["date"].strip()[:10])
            grouped.setdefault(symbol, []).append(
                (day, to_decimal(row["adj_close"]))
            )

    for rows in grouped.values():
        rows.sort(key=lambda item: item[0])

    _ADJ_CACHE["map"] = grouped
    return grouped


def normalize_symbol(value):
    """
    正規化股票代號。

    0050 -> 0050
    2330 -> 2330

    保留字母及其他字元，不以 int() 轉換，
    避免代號中的前導零或字母被破壞。
    """
    return str(value or "").strip().upper()


def find_stock(symbol):
    """
    先精確比對股票代號。
    若為純數字代號，再允許比較去除前導零後的結果。
    """
    normalized = normalize_symbol(symbol)

    stock = Stock.objects.filter(
        symbol=normalized
    ).first()

    if stock:
        return stock

    if normalized.isdigit():
        target = normalized.lstrip("0") or "0"

        candidates = Stock.objects.filter(
            symbol__regex=r"^[0-9]+$"
        )

        for candidate in candidates:
            candidate_symbol = normalize_symbol(
                candidate.symbol
            )

            if (candidate_symbol.lstrip("0") or "0") == target:
                return candidate

    return None


def calculate_actual_return(base_price, actual_price):
    """
    計算實際報酬率，單位為百分比。

    例如：
        5.2500 代表 +5.25%
    """
    base_price = to_decimal(base_price)
    actual_price = to_decimal(actual_price)

    if base_price <= ZERO:
        raise ValueError("預測基準收盤價必須大於 0")

    if actual_price <= ZERO:
        raise ValueError("實際收盤價必須大於 0")

    result = (
        actual_price / base_price - Decimal("1")
    ) * Decimal("100")

    return result.quantize(
        FOUR_PLACES,
        rounding=ROUND_HALF_UP,
    )


# ==================================================
# 方向判斷
# ==================================================

def check_direction(predicted_return, actual_return):
    """
    預測與實際報酬方向一致時回傳 True。

    預測正報酬：實際報酬必須 > 0
    預測負報酬：實際報酬必須 < 0
    預測零報酬：實際報酬必須 = 0
    """
    if predicted_return > ZERO:
        return actual_return > ZERO

    if predicted_return < ZERO:
        return actual_return < ZERO

    return actual_return == ZERO


# ==================================================
# 單筆預測評估
# ==================================================

def evaluate_one(record):
    """評估一筆尚未完成評估的預測。"""

    symbol = normalize_symbol(record.symbol)

    try:
        horizon = int(record.horizon)
    except (TypeError, ValueError):
        print(f"[略過] {symbol}：horizon 不是有效整數")
        return "skipped"

    if horizon <= 0:
        print(f"[略過] {symbol}：horizon 必須大於 0")
        return "skipped"

    stock = find_stock(symbol)

    if stock is None:
        print(f"[略過] {symbol}：找不到對應的 Stock")
        return "missing_stock"

    # 基準價與實際價皆使用還原收盤價，報酬才不會被配息扭曲
    try:
        predicted_return = to_decimal(
            record.predicted_return_20
        )

    except (InvalidOperation, ValueError) as exc:
        print(f"[錯誤] {symbol}：預測資料無效：{exc}")
        return "error"

    adj_rows = load_adjusted_map().get(
        normalize_symbol(stock.symbol),
        [],
    )

    data_day = record.data_date
    if isinstance(data_day, datetime):
        data_day = data_day.date()

    base_entry = next(
        (item for item in adj_rows if item[0] == data_day),
        None,
    )

    if base_entry is None:
        print(f"[等待] {symbol}：還原價檔缺少基準日 {data_day}")
        return "waiting"

    base_price = base_entry[1]

    if base_price <= ZERO:
        print(f"[錯誤] {symbol}：還原基準收盤價必須大於 0")
        return "error"

    future_rows = [
        item for item in adj_rows if item[0] > data_day
    ][:horizon]

    if len(future_rows) < horizon:
        print(
            f"[等待] {symbol}："
            f"{len(future_rows)}/{horizon} 個有效交易日"
        )
        return "waiting"

    actual_date, adj_actual_close = future_rows[horizon - 1]

    # 資料庫仍保存原始收盤價，供畫面顯示與人工核對
    raw_actual_close = (
        StockPrice.objects
        .filter(stock=stock, date=actual_date, close_price__gt=0)
        .values_list("close_price", flat=True)
        .first()
    )

    if raw_actual_close is None:
        print(f"[等待] {symbol}：{actual_date} 缺少原始收盤價")
        return "waiting"

    try:
        actual_close = to_decimal(raw_actual_close)

        actual_return = calculate_actual_return(
            base_price,
            adj_actual_close,
        )

    except (InvalidOperation, ValueError) as exc:
        print(f"[錯誤] {symbol}：實際報酬計算失敗：{exc}")
        return "error"

    # 誤差單位：百分點
    prediction_error = (
        actual_return - predicted_return
    ).quantize(
        FOUR_PLACES,
        rounding=ROUND_HALF_UP,
    )

    # 實際報酬為 0 時，不納入方向準確率分母。
    if actual_return == ZERO:
        direction_correct = None
    else:
        direction_correct = check_direction(
            predicted_return,
            actual_return,
        )

    # 再確認一次紀錄仍未完成評估，避免覆寫既有結果。
    # 將資料庫更新集中在交易中。
    with transaction.atomic():
        locked_record = (
            PredictionHistory.objects
            .select_for_update()
            .get(pk=record.pk)
        )

        if (
            locked_record.evaluated_at is not None
            or locked_record.actual_return_20 is not None
        ):
            print(
                f"[略過] {symbol}："
                "該筆紀錄已被其他程序完成評估"
            )
            return "already_evaluated"

        locked_record.actual_date = actual_date
        locked_record.actual_close_price = actual_close
        locked_record.actual_return_20 = actual_return
        locked_record.prediction_error = prediction_error
        locked_record.direction_correct = direction_correct
        locked_record.evaluated_at = timezone.now()

        locked_record.save(
            update_fields=[
                "actual_date",
                "actual_close_price",
                "actual_return_20",
                "prediction_error",
                "direction_correct",
                "evaluated_at",
            ]
        )

    if direction_correct is None:
        direction_text = "不計入（實際=0）"
    else:
        direction_text = "正確" if direction_correct else "錯誤"

    print(
        f"[完成] {symbol} | "
        f"基準日 {record.data_date} | "
        f"實際日期 {actual_date} | "
        f"預測 {predicted_return:+.4f}% | "
        f"實際 {actual_return:+.4f}% | "
        f"誤差 {prediction_error:+.4f} 個百分點 | "
        f"方向 {direction_text}"
    )

    return "evaluated"


# ==================================================
# 主程式
# ==================================================

def main():
    print("=" * 68)
    print(f"{VERSION} 前瞻預測績效評估")
    print("=" * 68)

    records = (
        PredictionHistory.objects
        .filter(
            actual_return_20__isnull=True,
            evaluated_at__isnull=True,
        )
        .order_by(
            "prediction_date",
            "rank",
        )
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
        "already_evaluated": 0,
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
    print("=" * 68)
    print("評估執行摘要")
    print("=" * 68)
    print(f"本次完成評估：{counts['evaluated']} 筆")
    print(f"等待更多交易日：{counts['waiting']} 筆")
    print(f"找不到股票資料：{counts['missing_stock']} 筆")
    print(f"略過不合格資料：{counts['skipped']} 筆")
    print(f"已由其他程序完成：{counts['already_evaluated']} 筆")
    print(f"錯誤：{counts['error']} 筆")
    print("=" * 68)


if __name__ == "__main__":
    main()
