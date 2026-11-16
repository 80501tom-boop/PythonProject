# -*- coding: utf-8 -*-

"""
新增股票佇列：網頁單檔與批量新增共用同一條流程（scripts/batch_add_stocks.py）。

- 送出時寫入 data/import_logs/batch.lock（JSON：代號 → 狀態），執行器逐檔更新。
- 結束後刪除鎖檔，結果寫入 data/import_logs/batch_last.json 供首頁顯示。
"""

import json
import os
import subprocess
import sys
import time

import requests

from .models import Stock


MAX_BATCH_SIZE = 20

# 執行器每 QUEUE_HEARTBEAT_SECONDS 更新一次鎖檔 mtime；超過 QUEUE_STALE_SECONDS 未更新視為已中斷。
QUEUE_HEARTBEAT_SECONDS = 30
QUEUE_STALE_SECONDS = 180

TWSE_LIST_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_LIST_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"

LOCK_NAME = "batch.lock"
LAST_RESULT_NAME = "batch_last.json"


def _log_dir(base_dir):
    return os.path.join(str(base_dir), "data", "import_logs")


def lock_path(base_dir):
    return os.path.join(_log_dir(base_dir), LOCK_NAME)


def last_result_path(base_dir):
    return os.path.join(_log_dir(base_dir), LAST_RESULT_NAME)


def normalize_symbols(raw_items):
    """把輸入文字（可用逗號、空白、全形逗號分隔）轉成去重後的代號清單。"""
    symbols = []

    for item in raw_items:
        for part in item.replace("，", ",").replace(",", " ").split():
            code = part.split(".")[0].zfill(4)

            if not code.isdigit():
                raise ValueError(f"股票代號只能是數字：{part}")

            if code not in symbols:
                symbols.append(code)

    return symbols


def lookup_stock(symbol):
    """先查 TWSE，找不到再查 TPEx；回傳 {"name", "market"}，兩邊都找不到回傳 None。"""
    try:
        response = requests.get(TWSE_LIST_URL, timeout=10)
        response.raise_for_status()
        for item in response.json():
            code = str(item.get("Code", "")).strip().zfill(4)
            if code == symbol:
                return {"name": str(item.get("Name", "")).strip(), "market": "TWSE"}
    except Exception as e:
        print("TWSE API 錯誤：", e)

    try:
        response = requests.get(TPEX_LIST_URL, timeout=10)
        response.raise_for_status()
        for item in response.json():
            code = str(item.get("SecuritiesCompanyCode", "")).strip().zfill(4)
            if code == symbol:
                return {"name": str(item.get("CompanyName", "")).strip(), "market": "TPEx"}
    except Exception as e:
        print("TPEx API 錯誤：", e)

    return None


def save_stock(symbol, info):
    """建立或更新 Stock（名稱、市場），回傳 Stock。"""
    stock, created = Stock.objects.get_or_create(
        symbol=symbol,
        defaults={"name": info["name"], "market": info["market"]},
    )

    if not created:
        changed = False
        if info["name"] and stock.name != info["name"]:
            stock.name = info["name"]
            changed = True
        if stock.market != info["market"]:
            stock.market = info["market"]
            changed = True
        if changed:
            stock.save(update_fields=["name", "market"])

    return stock


def write_queue_results(base_dir, results):
    os.makedirs(_log_dir(base_dir), exist_ok=True)
    with open(lock_path(base_dir), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False)


def touch_queue(base_dir):
    path = lock_path(base_dir)
    if os.path.isfile(path):
        os.utime(path, None)


def queue_results(base_dir, now=None):
    """回傳執行中佇列的 {代號: 狀態}；無執行或心跳逾時（程序已中斷）回傳 None。"""
    path = lock_path(base_dir)

    if not os.path.isfile(path):
        return None

    now = now or time.time()
    if now - os.path.getmtime(path) >= QUEUE_STALE_SECONDS:
        return None

    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_last_results(base_dir, results):
    os.makedirs(_log_dir(base_dir), exist_ok=True)
    with open(last_result_path(base_dir), "w", encoding="utf-8") as f:
        json.dump(
            {"finished": time.strftime("%Y-%m-%d %H:%M:%S"), "results": results},
            f,
            ensure_ascii=False,
        )


def last_results(base_dir):
    """回傳上一次佇列的 {"finished": 時間, "results": {...}}；沒有紀錄回傳 None。"""
    path = last_result_path(base_dir)

    if not os.path.isfile(path):
        return None

    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def start_queue(symbols, base_dir, months):
    """寫入鎖檔並啟動背景執行器；執行器會逐檔更新狀態。"""
    write_queue_results(base_dir, {s: "等待中" for s in symbols})

    subprocess.Popen(
        [
            sys.executable,
            os.path.join(str(base_dir), "scripts", "batch_add_stocks.py"),
            *symbols,
            "--months",
            str(months),
        ],
        cwd=str(base_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
        },
    )
