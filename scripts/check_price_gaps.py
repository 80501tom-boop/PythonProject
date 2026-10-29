# -*- coding: utf-8 -*-

"""
check_price_gaps.py

功能：檢查 StockPrice 資料是否有缺漏或異常。

檢查項目：
1. 每檔股票的起訖日期、筆數。
2. 缺日：參考交易日（多數股票皆有資料的日期）中，該股票缺少的日期。
3. 最新日期落後：該股票最後日期早於參考最新日期。
4. 異常價格：收盤價 <= 0 或空值。
5. 單日報酬絕對值超過 20%（可能是未還原的除權息或股票分割）。

使用方式：
    python scripts/check_price_gaps.py

輸出：終端機摘要，以及專案根目錄下的 price_gap_report.csv。
"""

import os
import sys

import django
import pandas as pd


BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "PythonProject.settings"
)

django.setup()

from myapp.models import StockPrice


# 參考交易日：至少此比例的股票當天有資料
REFERENCE_SHARE = 0.5

# 單日報酬絕對值門檻
JUMP_THRESHOLD = 0.20

# 已確認為暫停交易的日期，不計入缺漏
HALTED_DAYS = {
    "0050": {"2025-06-11", "2025-06-12", "2025-06-13", "2025-06-16", "2025-06-17"},
    "0052": {"2025-11-19", "2025-11-20", "2025-11-21", "2025-11-24", "2025-11-25"},
}

REPORT_PATH = os.path.join(BASE_DIR, "price_gap_report.csv")


def load_prices():

    rows = StockPrice.objects.values_list(
        "stock__symbol",
        "date",
        "close_price",
        "volume",
    )

    df = pd.DataFrame(
        list(rows),
        columns=["symbol", "date", "close", "volume"],
    )

    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])

    return df.sort_values(["symbol", "date"]).reset_index(drop=True)


def reference_dates(df):

    total_symbols = df["symbol"].nunique()

    counts = df.groupby("date")["symbol"].nunique()

    return set(
        counts[counts / total_symbols >= REFERENCE_SHARE].index
    )


def check_symbol(symbol, sdf, ref_dates, ref_max):

    dates = set(sdf["date"])
    first = min(dates)
    last = max(dates)

    expected = {d for d in ref_dates if first <= d <= last}
    missing = sorted(expected - dates)

    bad_price = int(
        ((sdf["close"] <= 0) | sdf["close"].isna()).sum()
    )

    zero_volume = int((sdf["volume"] == 0).sum())

    returns = sdf["close"].pct_change().abs()
    jumps = int((returns > JUMP_THRESHOLD).sum())

    return {
        "symbol": symbol,
        "first_date": first.date(),
        "last_date": last.date(),
        "rows": len(sdf),
        "missing_days": len(missing),
        "missing_sample": ", ".join(
            d.strftime("%Y-%m-%d") for d in missing[:5]
        ),
        "stale": last < ref_max,
        "bad_price": bad_price,
        "zero_volume": zero_volume,
        "jumps_over_20pct": jumps,
    }


def main():

    df = load_prices()

    if df.empty:
        print("資料庫沒有 StockPrice 資料")
        sys.exit(1)

    ref_dates = reference_dates(df)
    ref_max = max(ref_dates)

    print("=" * 70)
    print(f"股票數：{df['symbol'].nunique()}　總筆數：{len(df)}")
    print(f"參考交易日數：{len(ref_dates)}　參考最新日期：{ref_max.date()}")
    print("=" * 70)

    results = [
        check_symbol(symbol, sdf, ref_dates, ref_max)
        for symbol, sdf in df.groupby("symbol")
    ]

    report = pd.DataFrame(results)
    report.to_csv(REPORT_PATH, index=False, encoding="utf-8-sig")

    issues = report[
        (report["missing_days"] > 0)
        | report["stale"]
        | (report["bad_price"] > 0)
        | (report["jumps_over_20pct"] > 0)
    ]

    print(f"無異常股票：{len(report) - len(issues)} 檔")
    print(f"有異常股票：{len(issues)} 檔")
    print()

    if not issues.empty:
        print(issues.to_string(index=False))

    print()
    print(f"完整報告：{REPORT_PATH}")


if __name__ == "__main__":
    main()
