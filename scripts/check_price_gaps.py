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
from config import POOL_SYMBOLS


# 參考交易日：至少此比例的股票當天有資料
REFERENCE_SHARE = 0.5

# 單日報酬絕對值門檻
JUMP_THRESHOLD = 0.20

# 已確認為暫停交易的日期，不計入缺漏（原因皆為市場暫停交易）
HALTED_DAYS = {
    "0050": {"2025-06-11", "2025-06-12", "2025-06-13", "2025-06-16", "2025-06-17"},
    "0052": {"2025-11-19", "2025-11-20", "2025-11-21", "2025-11-24", "2025-11-25"},
    "2317": {"2025-07-30"},
    "2327": {
        "2021-06-30", "2022-10-20", "2022-10-21", "2022-10-24", "2022-10-25",
        "2022-10-26", "2022-10-27", "2022-10-28", "2025-08-14", "2025-08-15",
        "2025-08-18", "2025-08-19", "2025-08-20", "2025-08-21", "2025-08-22",
    },
    "2603": {
        "2022-09-07", "2022-09-08", "2022-09-12", "2022-09-13", "2022-09-14",
        "2022-09-15", "2022-09-16",
    },
    "2884": {"2025-11-05"},
    "3037": {"2022-02-22"},
}

REPORT_PATH = os.path.join(BASE_DIR, "price_gap_report.csv")


def load_prices():

    rows = StockPrice.objects.filter(
        stock__symbol__in=POOL_SYMBOLS
    ).values_list(
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
    halted = {
        pd.Timestamp(d) for d in HALTED_DAYS.get(symbol, set())
    }
    missing = sorted(expected - dates - halted)

    bad_price = int(
        ((sdf["close"] <= 0) | sdf["close"].isna()).sum()
    )

    zero_volume = int((sdf["volume"] == 0).sum())

    raw_returns = sdf["close"].pct_change()
    jump_mask = raw_returns.abs() > JUMP_THRESHOLD
    jumps = int(jump_mask.sum())
    jump_dates = "; ".join(
        f"{d:%Y-%m-%d} {r:+.1%}"
        for d, r in zip(
            sdf.loc[jump_mask, "date"],
            raw_returns[jump_mask],
        )
    )

    return {
        "symbol": symbol,
        "first_date": first.date(),
        "last_date": last.date(),
        "rows": len(sdf),
        "missing_days": len(missing),
        "missing_sample": ", ".join(
            d.strftime("%Y-%m-%d") for d in missing[:5]
        ),
        "missing_all": ", ".join(
            d.strftime("%Y-%m-%d") for d in missing
        ),
        "stale": last < ref_max,
        "bad_price": bad_price,
        "zero_volume": zero_volume,
        "jumps_over_20pct": jumps,
        "jump_dates": jump_dates,
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
