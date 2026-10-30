# -*- coding: utf-8 -*-

"""
專案共用設定：股票池與 point-in-time 納入規則。

不依賴 Django，可被 scripts/ 與 myapp/ml/ 直接匯入。
"""

import csv
import os
from datetime import date


# 股票池：asset_type 為 "ETF" 或 "STOCK"；
# pool_start 為首次納入日（None 表示資料起點即納入）。
# 0050 保留、006208 已移除（同一標的只保留一檔）。
STOCK_POOL = [
    {"symbol": "0050", "market": "TWSE", "asset_type": "ETF", "pool_start": None},
    {"symbol": "0052", "market": "TWSE", "asset_type": "ETF", "pool_start": None},
    {"symbol": "0056", "market": "TWSE", "asset_type": "ETF", "pool_start": None},
    {"symbol": "00713", "market": "TWSE", "asset_type": "ETF", "pool_start": None},
    {"symbol": "00877", "market": "TPEx", "asset_type": "ETF", "pool_start": None},
    {"symbol": "00878", "market": "TWSE", "asset_type": "ETF", "pool_start": None},
    {"symbol": "00919", "market": "TWSE", "asset_type": "ETF", "pool_start": None},
    {"symbol": "00929", "market": "TWSE", "asset_type": "ETF", "pool_start": None},
    {"symbol": "00951", "market": "TWSE", "asset_type": "ETF", "pool_start": None},
    {"symbol": "00981A", "market": "TWSE", "asset_type": "ETF", "pool_start": None},
    {"symbol": "1216", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "1301", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "1303", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2059", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2303", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2308", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2317", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2327", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2330", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2345", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2357", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2376", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2382", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2383", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2408", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2412", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2454", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2603", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2615", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2880", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2881", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2882", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2884", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2885", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2886", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2890", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2891", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2892", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "2912", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "3008", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "3017", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "3037", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "3045", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "3231", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "3653", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "3711", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "4904", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "5274", "market": "TPEx", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "6505", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
    {"symbol": "6669", "market": "TWSE", "asset_type": "STOCK", "pool_start": None},
]

POOL_SYMBOLS = [item["symbol"] for item in STOCK_POOL]

POOL_BY_SYMBOL = {item["symbol"]: item for item in STOCK_POOL}

POOL_HISTORY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "pool_history.csv",
)


def _load_pool_start():
    """從 data/pool_history.csv 讀取 pool_start（空白表示資料起點即納入）。"""
    if not os.path.exists(POOL_HISTORY_PATH):
        return

    with open(POOL_HISTORY_PATH, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            item = POOL_BY_SYMBOL.get(row["symbol"].strip())

            if item is None:
                continue

            value = (row.get("pool_start") or "").strip()
            item["pool_start"] = (
                date.fromisoformat(value) if value else None
            )


_load_pool_start()


def is_eligible(symbol, day):
    """回傳某股票在指定日期是否可被選取（point-in-time）。

    未知代號或 pool_start 晚於 day 的股票皆不可選。
    """
    item = POOL_BY_SYMBOL.get(symbol)

    if item is None:
        return False

    start = item["pool_start"]

    if start is None:
        return True

    if isinstance(day, str):
        day = date.fromisoformat(day)

    return day >= start
