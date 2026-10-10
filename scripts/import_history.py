
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
"""

import os
import sys
import time
import calendar
from datetime import date, datetime, timedelta

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


# =========================================================
# API 設定
# =========================================================

TWSE_API_URL = (
    "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
)

TPEX_API_URL = (
    "https://www.tpex.org.tw/web/stock/aftertrading/"
    "stock_day/trading_stock.php"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
    ),
    "Referer": "https://www.twse.com.tw/",
}

REQUEST_TIMEOUT = 20
REQUEST_RETRIES = 3
REQUEST_DELAY = 0.3


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


def month_roc_string(yyyymm):
    """將 YYYYMM 轉成 TPEx 使用的民國年/月格式。"""
    year = int(yyyymm[:4]) - 1911
    month = int(yyyymm[4:6])

    return f"{year}/{month:02d}"


# =========================================================
# HTTP 請求
# =========================================================

def request_json(url, params):
    """
    發送 API 請求。

    HTTP 錯誤、連線錯誤、非 JSON 回應都會明確拋出錯誤，
    不會把 API 失敗當成成功。
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
                time.sleep(attempt)

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
    取得 TPEx 單一上櫃股票的月資料。

    使用 TPEx 歷史個股行情 API。
    回傳欄位統一成 date/open/high/low/close/volume。
    """
    params = {
        "l": "zh-tw",
        "d": month_roc_string(yyyymm),
        "stkno": stock_code,
    }

    result = request_json(TPEX_API_URL, params)

    if not isinstance(result, dict):
        raise MarketDataError("TPEx 回傳格式不是 JSON 物件")

    # TPEx 舊版 API 常見格式：
    # tables[0]["fields"] / tables[0]["data"]
    # 或直接使用 fields / data。
    fields = result.get("fields", [])
    rows = result.get("data", [])

    if not fields and isinstance(result.get("tables"), list):
        for table in result["tables"]:
            if not isinstance(table, dict):
                continue

            table_fields = table.get("fields", [])
            table_rows = table.get("data", [])

            if table_fields and table_rows:
                fields = table_fields
                rows = table_rows
                break

    if not rows:
        # 某些版本可能使用 stat 表示沒有資料。
        status = str(result.get("stat", "")).strip()

        if status and status not in (
            "OK",
            "查詢資料不存在",
            "查無資料",
        ):
            raise MarketDataError(
                f"TPEx 回傳異常：{status}"
            )

        return []

    if not fields:
        raise MarketDataError(
            "TPEx 有資料但缺少 fields 欄位，請檢查 API 格式"
        )

    df = pd.DataFrame(rows, columns=fields)

    # 兼容不同 API 版本可能出現的欄位名稱。
    aliases = {
        "日期": "date",
        "交易日期": "date",
        "開盤": "open",
        "開盤價": "open",
        "最高": "high",
        "最高價": "high",
        "最低": "low",
        "最低價": "low",
        "收盤": "close",
        "收盤價": "close",
        "成交股數": "volume",
        "成交量": "volume",
    }

    df = df.rename(columns=aliases)

    required = ["date", "open", "high", "low", "close", "volume"]

    missing = [
        name for name in required
        if name not in df.columns
    ]

    if missing:
        raise MarketDataError(
            f"TPEx 欄位不完整，缺少：{missing}；"
            f"實際欄位：{list(df.columns)}"
        )

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

    if market in ("TPEX", "TPEX", "OTC", "上櫃"):
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
                # 找到資料後，更新股票市場欄位。
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
            "open": record["open"],
            "high": record["high"],
            "low": record["low"],
            "close": record["close"],
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

    不直接使用今天日期，避免週末、休市日被當成交易日。
    API 若持續失敗，會拋出 MarketDataError。
    """
    today = date.today()
    errors = []

    for offset in range(lookback_months):
        target_month = shift_month(
            month_start(today),
            -offset,
        ).strftime("%Y%m")

        try:
            records = get_month_data(stock, target_month)

            valid_dates = [
                item["date"]
                for item in records
                if item["date"] <= today
            ]

            if valid_dates:
                return max(valid_dates)

        except MarketDataError as exc:
            errors.append(
                f"{target_month}: {exc}"
            )

    if errors:
        raise MarketDataError(
            "查詢市場最新交易日期失敗；" + "；".join(errors)
        )

    return None


# =========================================================
# 匯入約一年歷史資料
# =========================================================

def import_stock(stock_code, months=12):
    """
    匯入指定股票約一年的歷史資料。

    若股票尚未存在於 Stock，會先建立基本紀錄。
    股票名稱或市場若沒有可靠資料，不會自行猜測名稱。
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

    for yyyymm in month_strings(start_date, today):
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
    2. 查詢市場最新交易日期。
    3. 若資料已最新，不重抓歷史資料。
    4. 否則從最後日期所在月份開始補抓。
    5. 只儲存資料庫最後日期之後的交易資料。
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
        latest_market_date = get_latest_market_date(stock)

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
    failed_months = []

    # 從資料庫最後日期所在月份開始，
    # 確保同月後續交易日可以被補進來。
    for yyyymm in month_strings(last_date, latest_market_date):
        print(f"\n更新 {yyyymm} 行情...")

        try:
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
            failed_months.append(yyyymm)
            print(f"  更新失敗：{exc}")

    new_last_date = get_last_date(stock)

    if failed_months:
        print(
            f"\n更新未完全成功：{stock_code}"
            f"；已儲存 {total_saved} 筆"
            f"；失敗月份：{', '.join(failed_months)}"
        )
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
    """更新資料庫內全部股票，統計成功與失敗數量。"""
    stocks = Stock.objects.all().order_by("symbol")

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
            # 單一股票出錯，不中斷其他股票更新。
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

if __name__ == "__main__":
    if len(sys.argv) >= 2:
        argument = sys.argv[1].strip()
    else:
        argument = "2330"

    if argument.lower() == "all":
        success = update_all_stocks()

    elif len(sys.argv) >= 3 and sys.argv[2].lower() == "import":
        success = import_stock(argument)

    else:
        success = update_stock(argument)

    sys.exit(0 if success else 1)
