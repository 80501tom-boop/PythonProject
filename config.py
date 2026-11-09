# -*- coding: utf-8 -*-

"""
專案共用設定：股票池與 point-in-time 納入規則。

股票池來自資料庫 Stock 表（網頁新增／刪除即同步），
因此需在 django.setup() 之後才能匯入。
"""

import csv
import os
import sys
from datetime import date


def _load_stock_pool():
    """從資料庫 Stock 表讀取股票池。

    ETF 以代號開頭 "00" 判定；pool_start 由 _load_pool_start() 補上。
    若 Django 尚未初始化（例如直接執行 python -c "import config"），會自動初始化。
    """
    import django
    from django.apps import apps

    if not apps.ready:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        if base_dir not in sys.path:
            sys.path.append(base_dir)
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "PythonProject.settings")
        django.setup()

    from myapp.models import Stock

    pool = [
        {
            "symbol": s.symbol,
            "market": s.market,
            "asset_type": "ETF" if s.symbol.startswith("00") else "STOCK",
            "pool_start": None,
        }
        for s in Stock.objects.order_by("symbol")
    ]

    if not pool:
        raise RuntimeError("資料庫 Stock 表為空，股票池無法建立")

    return pool


# asset_type 為 "ETF" 或 "STOCK"；pool_start 為首次納入日（None 表示資料起點即納入）。
STOCK_POOL = _load_stock_pool()

POOL_SYMBOLS = [item["symbol"] for item in STOCK_POOL]

TOP_N = 10

# False：只要在股票池內且當天有資料即納入排名（不看首次納入日）
# True ：依 data/pool_history.csv 的 pool_start 做 point-in-time 過濾
USE_POOL_START = False

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
    """回傳某股票在指定日期是否可被選取。

    USE_POOL_START=False 時，只要是股票池內的股票即可選取
    （資料列本身即代表當日已上市櫃）。
    """
    item = POOL_BY_SYMBOL.get(symbol)

    if item is None:
        return False

    if not USE_POOL_START:
        return True

    start = item["pool_start"]

    if start is None:
        return True

    if isinstance(day, str):
        day = date.fromisoformat(day)

    return day >= start
