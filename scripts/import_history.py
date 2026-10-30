# -*- coding: utf-8 -*-

"""
import_history.py

功能：
1. 支援上市股票（TWSE）與上櫃股票（TPEx）。
2. 新股票匯入約一年的歷史資料。
3. 已有股票只補抓資料庫最後日期之後的交易資料。
4. 更新前先檢查市場最新交易日期，避免不必要的重抓。
5. API 失敗、資料格式異常時，不再直接回報成功。
6. 支援單一股票及全部股票更新。

使用方式：
    python scripts/import_history.py 2330
    python scripts/import_history.py all
    python scripts/import_history.py 6488
    python scripts/import_history.py 2330 --months 60   # 回補 60 個月
    python scripts/import_history.py all --months 60    # 全部股票回補 60 個月
    python scripts/import_history.py 0050 --months 70 --force  # 強制重抓 70 個月（補缺漏）
"""

import os
import sys
import time
from datetime import date

import requests
import pandas as pd

import django


# =========================================================
# Django 設定
# =========================================================

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

from myapp.models import Stock, StockPrice
from config import POOL_SYMBOLS


# =========================================================
# API 設定
# =========================================================

TWSE_API_URL = (
    "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
)

TPEX_API_URL = (
    "https://www.tpex.org.tw/www/zh-tw/"
    "afterTrading/tradingStock"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
    ),
    "Referer": "https://www.twse.com.tw/",
}

REQUEST_TIMEOUT = 20
REQUEST_RETRIES = 5
REQUEST_DELAY = 0.3

# 429/5xx 額外退避（秒）
BACKOFF_BASE_SECONDS = 1.5
BACKOFF_MAX_SECONDS = 30.0

# 月份資料筆數達此門檻即視為完整，回補時略過（交易月約 18～23 日）
MIN_COMPLETE_MONTH_ROWS = 15


# =========================================================
# 自訂錯誤
# =========================================================

class MarketDataError(Exception):
    """市場 API 連線、回傳內容或資料解析錯誤。"""


# =========================================================
# 基礎資料處理
# =========================================================

def normalize_symbol(symbol):
    """統一股票代號格式，保留前導零。"""
    return str(symbol).strip().split(".")[0].zfill(4)


def parse_tw_date(value):
    """
    將民國日期轉換成 datetime.date。

    支援：
        115/10/08
        2026/10/08
        2026-10-08
    """
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    text = text.replace("-", "/")

    try:
        parts = text.split("/")

        if len(parts) != 3:
            return None

        year, month, day = map(int, parts)

        if year < 1911:
            year += 1911

        return date(year, month, day)

    except (ValueError, TypeError):
        return None


def clean_number(value):
    """將股價等數值欄位轉成 float。"""
    if value is None:
        return None

    text = str(value).strip().replace(",", "")

    if text in ("", "--", "---", "-", "X", "除權", "除息"):
        return None

    try:
        return float(text)
    except (ValueError, TypeError):
        return None


def clean_volume(value):
    """將成交量轉成整數股數。"""
    number = clean_number(value)

    if number is None:
        return 0

    return int(number)


def month_start(value):
    """取得日期所在月份的第一天。"""
    return date(value.year, value.month, 1)


def shift_month(value, offset):
    """以月份為單位移動日期。"""
    index = value.year * 12 + value.month - 1 + offset

    year = index // 12
    month = index % 12 + 1

    return date(year, month, 1)


def month_strings(start_date, end_date):
    """列出起訖日期涵蓋的月份。"""
    current = month_start(start_date)
    end_month = month_start(end_date)

    while current <= end_month:
        yield current.strftime("%Y%m")
        current = shift_month(current, 1)


def month_date_string(yyyymm):
    """將 YYYYMM 轉成 YYYYMM01，供 TWSE API 使用。"""
    return f"{yyyymm}01"


# =========================================================
# HTTP 請求
# =========================================================

def _parse_retry_after(value):
    """解析 Retry-After（秒），無法解析時回傳 None。"""
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        seconds = float(text)
        if seconds >= 0:
            return seconds
    except (ValueError, TypeError):
        pass

    return None


def request_json(url, params):
    """
    發送 API 請求。

    - 支援 429（Too Many Requests）與 Retry-After
    - 5xx 進行指數退避重試
    - 非 JSON 回傳、格式錯誤會拋出 MarketDataError
    """
    last_error = None

    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            response = requests.get(
                url,
                params=params,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )

            status = response.status_code

            if status == 429:
                retry_after = _parse_retry_after(
                    response.headers.get("Retry-After")
                )
                wait_seconds = (
                    retry_after
                    if retry_after is not None
                    else min(
                        BACKOFF_MAX_SECONDS,
                        BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)),
                    )
                )

                err = MarketDataError(
                    f"API 限流(429)：{response.url}，"
                    f"等待 {wait_seconds:.1f} 秒後重試"
                )
                last_error = err
                print(f"  API 請求失敗 ({attempt}/{REQUEST_RETRIES})：{err}")

                if attempt < REQUEST_RETRIES:
                    time.sleep(wait_seconds)
                    continue

                raise err

            if 500 <= status < 600:
                wait_seconds = min(
                    BACKOFF_MAX_SECONDS,
                    BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)),
                )
                err = MarketDataError(
                    f"API 伺服器錯誤({status})：{response.url}，"
                    f"等待 {wait_seconds:.1f} 秒後重試"
                )
                last_error = err
                print(f"  API 請求失敗 ({attempt}/{REQUEST_RETRIES})：{err}")

                if attempt < REQUEST_RETRIES:
                    time.sleep(wait_seconds)
                    continue

                raise err

            response.raise_for_status()

            try:
                result = response.json()
            except ValueError as exc:
                raise MarketDataError(
                    f"API 回傳內容不是有效 JSON：{response.url}"
                ) from exc

            if not isinstance(result, (dict, list)):
                raise MarketDataError(
                    f"API 回傳格式不正確：{response.url}"
                )

            # 成功後節流，減少觸發限流
            time.sleep(REQUEST_DELAY)
            return result

        except (
            requests.RequestException,
            MarketDataError,
        ) as exc:
            last_error = exc
            print(
                f"  API 請求失敗 "
                f"({attempt}/{REQUEST_RETRIES})：{exc}"
            )

            if attempt < REQUEST_RETRIES:
                wait_seconds = min(
                    BACKOFF_MAX_SECONDS,
                    BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)),
                )
                time.sleep(wait_seconds)

    raise MarketDataError(
        f"API 重試 {REQUEST_RETRIES} 次仍失敗：{last_error}"
    )


# =========================================================
# TWSE 上市股票
# =========================================================

def get_twse_month_data(stock_code, yyyymm):
    """
    取得 TWSE 單一上市股票的月資料。

    回傳：
        list[dict]

    沒有交易資料時回傳空清單。
    API 連線或格式錯誤時拋出 MarketDataError。
    """
    params = {
        "response": "json",
        "date": month_date_string(yyyymm),
        "stockNo": stock_code,
    }

    result = request_json(TWSE_API_URL, params)

    if not isinstance(result, dict):
        raise MarketDataError("TWSE 回傳格式不是 JSON 物件")

    status = str(result.get("stat", "")).strip()

    if status not in ("OK", "查詢資料不存在"):
        raise MarketDataError(
            f"TWSE 回傳異常：{status or '缺少 stat 欄位'}"
        )

    fields = result.get("fields", [])
    rows = result.get("data", [])

    if status == "查詢資料不存在" or not rows:
        return []

    if not fields:
        raise MarketDataError("TWSE 有資料但缺少 fields 欄位")

    df = pd.DataFrame(rows, columns=fields)

    column_map = {
        "日期": "date",
        "開盤價": "open",
        "最高價": "high",
        "最低價": "low",
        "收盤價": "close",
        "成交股數": "volume",
    }

    missing = [
        name for name in column_map
        if name not in df.columns
    ]

    if missing:
        raise MarketDataError(
            f"TWSE 欄位不完整，缺少：{missing}"
        )

    df = df.rename(columns=column_map)

    records = []

    for _, row in df.iterrows():
        trade_date = parse_tw_date(row["date"])

        if trade_date is None:
            continue

        close_price = clean_number(row["close"])

        if close_price is None or close_price <= 0:
            continue

        records.append({
            "date": trade_date,
            "open": clean_number(row["open"]),
            "high": clean_number(row["high"]),
            "low": clean_number(row["low"]),
            "close": close_price,
            "volume": clean_volume(row["volume"]),
        })

    return records


# =========================================================
# TPEx 上櫃股票
# =========================================================

def get_tpex_month_data(stock_code, yyyymm):
    """
    取得 TPEx 單一上櫃股票的月行情。

    回傳 date/open/high/low/close/volume。
    volume 由 API 的成交張數換算成股數；
    精確程度仍受來源資料的顯示精度限制。
    """
    import math
    from decimal import Decimal, InvalidOperation

    year = int(yyyymm[:4])
    month = int(yyyymm[4:6])

    params = {
        "code": str(stock_code).strip(),
        "date": f"{year}/{month:02d}/01",
        "id": "",
        "response": "json",
    }

    result = request_json(TPEX_API_URL, params)

    if not isinstance(result, dict):
        raise MarketDataError("TPEx 回傳格式不是 JSON 物件")

    status = str(result.get("stat", "")).strip()

    if status in ("查詢資料不存在", "查無資料"):
        return []

    if status.upper() != "OK":
        raise MarketDataError(
            f"TPEx 回傳異常：{status or '缺少 stat 欄位'}"
        )

    returned_code = str(result.get("code", "")).strip()
    if returned_code != str(stock_code).strip():
        raise MarketDataError(
            f"TPEx 回傳代號不符："
            f"要求 {stock_code}，收到 {returned_code!r}"
        )

    tables = result.get("tables")

    if not isinstance(tables, list):
        raise MarketDataError("TPEx 回傳缺少有效的 tables 清單")

    required_fields = {"日 期", "開盤", "最高", "最低", "收盤"}
    volume_fields = ("成交張數", "成交仟股")
    price_table = None

    for table in tables:
        if not isinstance(table, dict):
            continue

        fields = table.get("fields")

        if (
            isinstance(fields, list)
            and all(isinstance(field, str) for field in fields)
            and required_fields.issubset(fields)
            and any(name in fields for name in volume_fields)
        ):
            price_table = table
            break

    if price_table is None:
        raise MarketDataError(
            "TPEx 找不到預期的行情欄位，請檢查 API 回傳格式"
        )

    fields = price_table["fields"]
    volume_field = next(name for name in volume_fields if name in fields)
    rows = price_table.get("data")

    if not isinstance(rows, list):
        raise MarketDataError("TPEx 行情 data 不是清單")

    records = []

    for index, values in enumerate(rows, start=1):
        if not isinstance(values, list) or len(values) != len(fields):
            raise MarketDataError(f"TPEx 第 {index} 列欄位數異常")

        row = dict(zip(fields, values))
        trade_date = parse_tw_date(row["日 期"])

        if trade_date is None:
            raise MarketDataError(f"TPEx 第 {index} 列日期無法解析")

        if (trade_date.year, trade_date.month) != (year, month):
            raise MarketDataError(
                f"TPEx 回傳日期 {trade_date} 不屬於要求月份 {yyyymm}"
            )

        prices = {
            "open": clean_number(row["開盤"]),
            "high": clean_number(row["最高"]),
            "low": clean_number(row["最低"]),
            "close": clean_number(row["收盤"]),
        }

        if any(
            value is None or not math.isfinite(value) or value <= 0
            for value in prices.values()
        ):
            continue

        try:
            volume_lots = Decimal(
                str(row[volume_field]).strip().replace(",", "")
            )

            if not volume_lots.is_finite() or volume_lots < 0:
                raise ValueError("成交張數不是有效的非負數")

            shares = volume_lots * 1000

            if shares != shares.to_integral_value():
                raise ValueError("換算後不是整數股數")

            volume_shares = int(shares)

        except (InvalidOperation, ValueError) as exc:
            raise MarketDataError(
                f"TPEx {trade_date} 成交量異常："
                f"{row[volume_field]!r}"
            ) from exc

        records.append({
            "date": trade_date,
            **prices,
            "volume": volume_shares,
        })

    if rows and not records:
        raise MarketDataError(
            "TPEx 有回傳資料，但沒有可用的完整行情"
        )

    return records


# =========================================================
# 市場判斷與資料來源
# =========================================================

def get_market(stock):
    """
    依 Stock.market 判斷市場。

    支援常見值：
        TWSE、上市
        TPEx、TPEX、OTC、上櫃

    若市場欄位沒有明確值，回傳 None，
    由呼叫端嘗試上市與上櫃 API。
    """
    market = str(
        getattr(stock, "market", "") or ""
    ).strip().upper()

    if market in ("TWSE", "上市"):
        return "TWSE"

    if market in ("TPEX", "OTC", "上櫃"):
        return "TPEx"

    return None


def get_month_data(stock, yyyymm):
    """
    依股票市場取得月資料。

    如果市場未設定，先嘗試 TWSE，再嘗試 TPEx。
    只有成功取得資料或確認沒有資料才回傳。
    若兩邊 API 都失敗，拋出錯誤。
    """
    market = get_market(stock)

    if market == "TWSE":
        return get_twse_month_data(stock.symbol, yyyymm)

    if market == "TPEx":
        return get_tpex_month_data(stock.symbol, yyyymm)

    errors = []

    for market_name, fetcher in (
        ("TWSE", get_twse_month_data),
        ("TPEx", get_tpex_month_data),
    ):
        try:
            records = fetcher(stock.symbol, yyyymm)

            if records:
                if hasattr(stock, "market"):
                    stock.market = market_name
                    stock.save(update_fields=["market"])

                return records

        except MarketDataError as exc:
            errors.append(f"{market_name}: {exc}")

    if errors:
        raise MarketDataError(
            "無法確認股票市場或取得資料；" + "；".join(errors)
        )

    return []


# =========================================================
# 儲存資料
# =========================================================

def save_stock_price(stock, record):
    """
    新增或更新單日股價。

    若同一股票、同一日期已存在，更新原資料，
    避免產生重複紀錄。
    """
    StockPrice.objects.update_or_create(
        stock=stock,
        date=record["date"],
        defaults={
            "open_price": record["open"],
            "high_price": record["high"],
            "low_price": record["low"],
            "close_price": record["close"],
            "volume": record["volume"],
        },
    )


def save_records(stock, records, after_date=None):
    """
    儲存行情紀錄。

    after_date 不為 None 時，只儲存該日期之後的資料。
    回傳實際新增或更新的筆數。
    """
    saved_count = 0

    for record in records:
        trade_date = record["date"]

        if after_date is not None and trade_date <= after_date:
            continue

        if trade_date > date.today():
            continue

        save_stock_price(stock, record)
        saved_count += 1

    return saved_count


def get_last_date(stock):
    """取得資料庫中該股票最後一筆交易日期。"""
    latest = (
        StockPrice.objects
        .filter(stock=stock)
        .order_by("-date")
        .values_list("date", flat=True)
        .first()
    )

    return latest


# =========================================================
# 查詢市場最新日期
# =========================================================

def get_latest_market_date(stock, lookback_months=3):
    """
    往回查詢最近幾個月份，取得 API 中最新的交易日期。

    回傳：
        (latest_market_date, month_cache)

    month_cache: dict[yyyymm] = records
    可重用已抓取月份資料，避免 update 時重複抓同月份。
    """
    today = date.today()
    errors = []
    month_cache = {}

    for offset in range(lookback_months):
        target_month = shift_month(
            month_start(today),
            -offset,
        ).strftime("%Y%m")

        try:
            records = get_month_data(stock, target_month)
            month_cache[target_month] = records

            valid_dates = [
                item["date"]
                for item in records
                if item["date"] <= today
            ]

            if valid_dates:
                return max(valid_dates), month_cache

        except MarketDataError as exc:
            errors.append(
                f"{target_month}: {exc}"
            )

    if errors:
        raise MarketDataError(
            "查詢市場最新交易日期失敗；" + "；".join(errors)
        )

    return None, month_cache


# =========================================================
# 匯入約一年歷史資料
# =========================================================

def count_existing_rows_by_month(stock, start_date):
    """統計 start_date 之後，資料庫中每個月已有的交易日筆數。"""
    counts = {}

    dates = (
        StockPrice.objects
        .filter(stock=stock, date__gte=start_date)
        .values_list("date", flat=True)
    )

    for trade_date in dates:
        key = trade_date.strftime("%Y%m")
        counts[key] = counts.get(key, 0) + 1

    return counts


def import_stock(stock_code, months=12, force=False):
    """
    匯入指定股票約一年的歷史資料。

    若股票尚未存在於 Stock，需先建立基本紀錄後再匯入。
    """
    stock_code = normalize_symbol(stock_code)

    print("\n" + "=" * 60)
    print(f"開始匯入股票：{stock_code}")
    print("=" * 60)

    stock = Stock.objects.filter(symbol=stock_code).first()

    if stock is None:
        print(
            "錯誤：資料庫尚無此股票的基本資料。"
            "請先在網站新增股票，或建立 Stock 紀錄後再匯入。"
        )
        return False

    today = date.today()
    start_date = shift_month(month_start(today), -(months - 1))
    start_date = date(start_date.year, start_date.month, 1)

    total_saved = 0
    failed_months = []

    existing_counts = count_existing_rows_by_month(stock, start_date)
    current_yyyymm = today.strftime("%Y%m")

    for yyyymm in month_strings(start_date, today):
        # 已完整存在的月份略過；當月一律重抓以更新最新資料
        if (
            not force
            and yyyymm != current_yyyymm
            and existing_counts.get(yyyymm, 0) >= MIN_COMPLETE_MONTH_ROWS
        ):
            print(f"\n略過 {yyyymm}（資料庫已有完整資料）")
            continue

        print(f"\n取得 {yyyymm} 行情...")

        try:
            records = get_month_data(stock, yyyymm)

            count = save_records(stock, records)
            total_saved += count

            print(
                f"  本月取得 {len(records)} 筆，"
                f"新增／更新 {count} 筆"
            )

        except MarketDataError as exc:
            failed_months.append(yyyymm)
            print(f"  匯入失敗：{exc}")

    latest_date = get_last_date(stock)

    if failed_months:
        print(
            f"\n匯入未完全成功：{stock_code}"
            f"；成功儲存 {total_saved} 筆"
            f"；失敗月份：{', '.join(failed_months)}"
        )
        return False

    if latest_date is None:
        print(f"\n匯入失敗：{stock_code} 沒有可用行情資料")
        return False

    print(f"\n匯入完成：{stock_code}")
    print(f"新增／更新筆數：{total_saved}")
    print(f"資料庫最新日期：{latest_date}")

    return True


# =========================================================
# 更新單一股票
# =========================================================

def update_stock(stock_code):
    """
    增量更新單一股票。

    1. 查詢資料庫最後日期。
    2. 查詢市場最新交易日期（帶快取）。
    3. 若資料已最新，不重抓。
    4. 否則從最後日期所在月份開始補抓。
    5. 只儲存最後日期之後資料。
    6. 任何月份失敗即停止該股票後續月份（避免中間缺口）。
    """
    stock_code = normalize_symbol(stock_code)

    print("\n" + "=" * 60)
    print(f"更新股票：{stock_code}")
    print("=" * 60)

    stock = Stock.objects.filter(symbol=stock_code).first()

    if stock is None:
        print(f"錯誤：找不到股票 {stock_code} 的基本資料")
        return False

    last_date = get_last_date(stock)

    if last_date is None:
        print("資料庫沒有歷史行情，改為匯入約一年資料")
        return import_stock(stock_code)

    try:
        latest_market_date, month_cache = get_latest_market_date(stock)

    except MarketDataError as exc:
        print(f"更新失敗：無法確認市場最新日期：{exc}")
        return False

    if latest_market_date is None:
        print("更新失敗：API 沒有提供可確認的最新交易日期")
        return False

    print(f"資料庫最後日期：{last_date}")
    print(f"市場最新交易日期：{latest_market_date}")

    if last_date >= latest_market_date:
        print("資料已是最新，無須重新抓取")
        return True

    total_saved = 0
    failed_month = None

    for yyyymm in month_strings(last_date, latest_market_date):
        print(f"\n更新 {yyyymm} 行情...")

        try:
            if yyyymm in month_cache:
                records = month_cache[yyyymm]
                print("  使用快取資料（避免重複請求）")
            else:
                records = get_month_data(stock, yyyymm)

            count = save_records(
                stock,
                records,
                after_date=last_date,
            )

            total_saved += count

            print(
                f"  API 回傳 {len(records)} 筆，"
                f"新增／更新 {count} 筆"
            )

        except MarketDataError as exc:
            failed_month = yyyymm
            print(f"  更新失敗：{exc}")
            print("  已停止後續月份更新（避免中間缺口）。")
            break

    new_last_date = get_last_date(stock)

    if failed_month is not None:
        print(
            f"\n更新未完全成功：{stock_code}"
            f"；已儲存 {total_saved} 筆"
            f"；失敗月份：{failed_month}"
        )
        print("請修復後重跑，程式會從資料庫最後日期續抓。")
        return False

    if new_last_date is None or new_last_date < latest_market_date:
        print(
            "\n更新未完成：資料庫最新日期仍落後市場最新日期。"
        )
        print(f"目前資料庫最新日期：{new_last_date}")
        return False

    print(f"\n更新完成：{stock_code}")
    print(f"新增資料筆數：{total_saved}")
    print(f"目前最新日期：{new_last_date}")

    return True


# =========================================================
# 更新全部股票
# =========================================================

def update_all_stocks():
    """更新股票池內全部股票，統計成功與失敗數量。"""
    stocks = Stock.objects.filter(
        symbol__in=POOL_SYMBOLS
    ).order_by("symbol")

    total = stocks.count()
    success_count = 0
    fail_count = 0

    print("\n" + "=" * 60)
    print(f"開始更新全部股票，共 {total} 檔")
    print("=" * 60)

    for index, stock in enumerate(stocks, start=1):
        print(f"\n[{index}/{total}] {stock.symbol}")

        try:
            success = update_stock(stock.symbol)

            if success:
                success_count += 1
            else:
                fail_count += 1

        except Exception as exc:
            fail_count += 1
            print(
                f"股票 {stock.symbol} 發生未預期錯誤：{exc}"
            )

    print("\n" + "=" * 60)
    print("全部股票更新結束")
    print(f"總數：{total}")
    print(f"成功：{success_count}")
    print(f"失敗：{fail_count}")
    print("=" * 60)

    return fail_count == 0


# =========================================================
# 命令列入口
# =========================================================

def import_all_stocks(months, force=False):
    """以指定月數回補股票池內全部股票，並統計成功與失敗數量。"""
    stocks = Stock.objects.filter(
        symbol__in=POOL_SYMBOLS
    ).order_by("symbol")

    total = stocks.count()
    success_count = 0
    fail_count = 0

    print("\n" + "=" * 60)
    print(f"開始回補全部股票 {months} 個月，共 {total} 檔")
    print("=" * 60)

    for index, stock in enumerate(stocks, start=1):
        print(f"\n[{index}/{total}] {stock.symbol}")

        try:
            if import_stock(stock.symbol, months=months, force=force):
                success_count += 1
            else:
                fail_count += 1

        except Exception as exc:
            fail_count += 1
            print(
                f"股票 {stock.symbol} 發生未預期錯誤：{exc}"
            )

    print("\n" + "=" * 60)
    print(f"總數：{total}　成功：{success_count}　失敗：{fail_count}")
    print("=" * 60)

    return fail_count == 0


if __name__ == "__main__":
    months = None

    # 解析 --months N，例如：--months 60
    if "--months" in sys.argv:
        idx = sys.argv.index("--months")

        try:
            months = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            print("錯誤：--months 需要正整數，例如 --months 60")
            sys.exit(1)

        if months <= 0:
            print("錯誤：--months 需要正整數")
            sys.exit(1)

        del sys.argv[idx:idx + 2]

    # --force：忽略既有資料，重抓指定期間所有月份（用於補缺漏）
    force = "--force" in sys.argv
    sys.argv = [arg for arg in sys.argv if arg != "--force"]

    if len(sys.argv) >= 2:
        argument = sys.argv[1].strip()
    else:
        argument = "2330"

    if argument.lower() == "all":
        if months is not None:
            success = import_all_stocks(months, force=force)
        else:
            success = update_all_stocks()

    elif months is not None or (
        len(sys.argv) >= 3 and sys.argv[2].lower() == "import"
    ):
        success = import_stock(argument, months=months or 12, force=force)

    else:
        success = update_stock(argument)

    sys.exit(0 if success else 1)