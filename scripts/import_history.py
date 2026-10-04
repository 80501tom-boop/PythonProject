import os
import sys
import django
import requests
import pandas as pd
import time

from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta


# ============================================================
# Django 設定
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

sys.path.append(BASE_DIR)

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "PythonProject.settings"
)

django.setup()

from myapp.models import Stock, StockPrice


# ============================================================
# API 設定
# ============================================================

# TWSE 集中市場
TWSE_API_URL = (
    "https://www.twse.com.tw/"
    "exchangeReport/STOCK_DAY"
)


# ============================================================
# Request 設定
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    )
}

REQUEST_TIMEOUT = 15

# API 請求間隔
REQUEST_DELAY = 0.3


# ============================================================
# HTTP Request
# ============================================================

def request_get(url, params=None):

    response = requests.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    return response


# ============================================================
# 民國日期 → 西元日期
# ============================================================

def parse_tw_date(value):

    if value is None:
        return None

    text = str(value).strip()

    if text in [
        "",
        "nan",
        "NaN",
        "None",
        "--",
        "---"
    ]:
        return None

    # --------------------------------------------------------
    # 115/10/02
    # --------------------------------------------------------

    if "/" in text:

        parts = text.split("/")

        if len(parts) == 3:

            try:

                year = int(parts[0])
                month = int(parts[1])
                day = int(parts[2])

                if year < 1911:
                    year += 1911

                return datetime(
                    year,
                    month,
                    day
                ).date()

            except Exception:

                return None

    # --------------------------------------------------------
    # 1151002
    # --------------------------------------------------------

    if text.isdigit() and len(text) == 7:

        try:

            year = int(text[:3]) + 1911
            month = int(text[3:5])
            day = int(text[5:7])

            return datetime(
                year,
                month,
                day
            ).date()

        except Exception:

            return None

    # --------------------------------------------------------
    # YYYY-MM-DD
    # --------------------------------------------------------

    try:

        return datetime.strptime(
            text,
            "%Y-%m-%d"
        ).date()

    except Exception:
        pass

    # --------------------------------------------------------
    # YYYY/MM/DD
    # --------------------------------------------------------

    try:

        return datetime.strptime(
            text,
            "%Y/%m/%d"
        ).date()

    except Exception:
        pass

    return None


# ============================================================
# 數字清理
# ============================================================

def clean_number(value):

    if value is None:
        return None

    text = str(value).strip()

    text = text.replace(",", "")

    if text in [
        "",
        "--",
        "---",
        "nan",
        "NaN",
        "None"
    ]:
        return None

    try:

        return float(text)

    except (
        ValueError,
        TypeError
    ):

        return None


# ============================================================
# 成交量清理
# ============================================================

def clean_volume(value):

    if value is None:
        return None

    text = str(value).strip()

    text = text.replace(",", "")

    if text in [
        "",
        "--",
        "---",
        "nan",
        "NaN",
        "None"
    ]:
        return None

    try:

        return int(
            float(text)
        )

    except (
        ValueError,
        TypeError
    ):

        return None


# ============================================================
# TWSE：取得指定月份資料
# ============================================================

def get_twse_month_data(
    stock_code,
    date
):

    date_str = date.strftime(
        "%Y%m%d"
    )

    params = {

        "response": "json",

        "date": date_str,

        "stockNo": stock_code
    }

    response = request_get(
        TWSE_API_URL,
        params=params
    )

    content_type = (
        response.headers
        .get(
            "Content-Type",
            ""
        )
        .lower()
    )

    if "json" not in content_type:

        print(
            f"TWSE {stock_code} "
            f"{date_str}: "
            "API 非 JSON"
        )

        return None

    data = response.json()

    if data.get("stat") != "OK":

        print(
            f"TWSE {stock_code} "
            f"{date.strftime('%Y-%m')}: "
            f"{data.get('stat')}"
        )

        return None

    fields = data.get(
        "fields",
        []
    )

    records = data.get(
        "data",
        []
    )

    if not records:

        return None

    df = pd.DataFrame(
        records,
        columns=fields
    )

    return df


# ============================================================
# 取得交易日期
# ============================================================

def get_trade_date(row):

    if "日期" not in row.index:

        return None

    return parse_tw_date(
        row["日期"]
    )


# ============================================================
# 取得 OHLC + Volume
# ============================================================

def get_ohlc(row):

    result = {

        "open_price": None,

        "high_price": None,

        "low_price": None,

        "close_price": None,

        "volume": None
    }

    # --------------------------------------------------------
    # 開盤
    # --------------------------------------------------------

    for column in [
        "開盤價",
        "開盤"
    ]:

        if column in row.index:

            result["open_price"] = (
                clean_number(
                    row[column]
                )
            )

            break

    # --------------------------------------------------------
    # 最高
    # --------------------------------------------------------

    for column in [
        "最高價",
        "最高"
    ]:

        if column in row.index:

            result["high_price"] = (
                clean_number(
                    row[column]
                )
            )

            break

    # --------------------------------------------------------
    # 最低
    # --------------------------------------------------------

    for column in [
        "最低價",
        "最低"
    ]:

        if column in row.index:

            result["low_price"] = (
                clean_number(
                    row[column]
                )
            )

            break

    # --------------------------------------------------------
    # 收盤
    # --------------------------------------------------------

    for column in [
        "收盤價",
        "收盤"
    ]:

        if column in row.index:

            result["close_price"] = (
                clean_number(
                    row[column]
                )
            )

            break

    # --------------------------------------------------------
    # 成交量
    # --------------------------------------------------------

    for column in [
        "成交股數",
        "成交量"
    ]:

        if column in row.index:

            result["volume"] = (
                clean_volume(
                    row[column]
                )
            )

            break

    return result


# ============================================================
# 儲存 StockPrice
# ============================================================

def save_stock_price(
    stock,
    trade_date,
    row
):

    if trade_date is None:

        return False

    ohlc = get_ohlc(
        row
    )

    # --------------------------------------------------------
    # OHLC 不完整，不儲存
    # --------------------------------------------------------

    if None in [

        ohlc["open_price"],

        ohlc["high_price"],

        ohlc["low_price"],

        ohlc["close_price"]
    ]:

        return False

    volume = (
        ohlc["volume"]
    )

    if volume is None:

        volume = 0

    # --------------------------------------------------------
    # 更新 / 建立
    # --------------------------------------------------------

    StockPrice.objects.update_or_create(

        stock=stock,

        date=trade_date,

        defaults={

            "open_price":
                ohlc[
                    "open_price"
                ],

            "high_price":
                ohlc[
                    "high_price"
                ],

            "low_price":
                ohlc[
                    "low_price"
                ],

            "close_price":
                ohlc[
                    "close_price"
                ],

            "volume":
                volume
        }
    )

    return True


# ============================================================
# DB 最新資料日期
# ============================================================

def get_last_date(stock):

    last_record = (

        StockPrice.objects

        .filter(
            stock=stock
        )

        .order_by(
            "-date"
        )

        .first()
    )

    if last_record is None:

        return None

    return last_record.date


# ============================================================
# 取得指定月份最後交易日
# ============================================================

def get_month_last_trade_date(
    stock_code,
    date
):

    try:

        df = get_twse_month_data(
            stock_code,
            date
        )

    except Exception as e:

        print(
            f"查詢市場日期失敗：{e}"
        )

        return None

    if df is None:
        return None

    if df.empty:
        return None

    dates = []

    for _, row in df.iterrows():

        trade_date = (
            get_trade_date(
                row
            )
        )

        if trade_date is not None:

            dates.append(
                trade_date
            )

    if not dates:

        return None

    return max(dates)


# ============================================================
# 取得市場最新交易日
#
# 從本月開始往前找
# 最多查 3 個月
#
# 通常只需要 1 次 API
# ============================================================

def get_latest_market_date(
    stock_code
):

    today = datetime.today()

    current_month = today.replace(
        day=1
    )

    for month_offset in range(
        0,
        3
    ):

        check_month = (
            current_month
            - relativedelta(
                months=month_offset
            )
        )

        print(
            f"檢查最新交易日："
            f"{check_month.strftime('%Y-%m')}"
        )

        trade_date = (
            get_month_last_trade_date(
                stock_code,
                check_month
            )
        )

        if trade_date is not None:

            # 不允許未來日期
            if trade_date <= today.date():

                return trade_date

        time.sleep(
            REQUEST_DELAY
        )

    return None


# ============================================================
# 匯入近一年資料
#
# 用於：
# DB 完全沒有資料
# ============================================================

def import_stock(
    stock_code
):

    stock_code = str(
        stock_code
    ).strip()

    print()
    print("=" * 70)
    print(
        f"開始匯入近一年資料："
        f"{stock_code}"
    )
    print("=" * 70)

    # --------------------------------------------------------
    # 找 Stock
    # --------------------------------------------------------

    stock = (
        Stock.objects
        .filter(
            symbol=stock_code
        )
        .first()
    )

    if stock is None:

        print(
            f"找不到 Stock："
            f"{stock_code}"
        )

        return False

    print(
        f"股票："
        f"{stock.symbol} "
        f"{stock.name}"
    )

    today = datetime.today()

    # --------------------------------------------------------
    # 從 11 個月前的月初開始
    #
    # 例如：
    # 2026/10
    # → 2025/11 ~ 2026/10
    # --------------------------------------------------------

    start_month = (
        today
        - relativedelta(
            months=11
        )
    ).replace(
        day=1
    )

    current_month = (
        start_month
    )

    total = 0

    month_count = 0

    # --------------------------------------------------------
    # 逐月取得
    # --------------------------------------------------------

    while current_month <= today:

        month_count += 1

        print(
            f"[{month_count:02d}] "
            f"取得 "
            f"{current_month.strftime('%Y-%m')}..."
        )

        try:

            df = get_twse_month_data(
                stock_code,
                current_month
            )

        except Exception as e:

            print(
                f"    API 失敗：{e}"
            )

            current_month += (
                relativedelta(
                    months=1
                )
            )

            continue

        if df is None:

            print(
                "    無資料"
            )

        else:

            saved_count = 0

            for _, row in df.iterrows():

                try:

                    trade_date = (
                        get_trade_date(
                            row
                        )
                    )

                    if trade_date is None:
                        continue

                    if trade_date > today.date():
                        continue

                    if save_stock_price(
                        stock,
                        trade_date,
                        row
                    ):

                        total += 1
                        saved_count += 1

                except Exception as e:

                    print(
                        f"    資料處理錯誤："
                        f"{e}"
                    )

            print(
                f"    API："
                f"{len(df)} 筆"
                f" / 寫入："
                f"{saved_count} 筆"
            )

        # ----------------------------------------------------
        # API 間隔
        # ----------------------------------------------------

        time.sleep(
            REQUEST_DELAY
        )

        current_month += (
            relativedelta(
                months=1
            )
        )

    print()
    print(
        f"{stock_code} 歷史資料匯入完成"
    )
    print(
        f"共寫入：{total} 筆"
    )

    return True


# ============================================================
# 增量更新
#
# 已有資料：
# 只抓 DB 最後日期之後的月份
# ============================================================

def update_stock(
    stock_code
):

    stock_code = str(
        stock_code
    ).strip()

    print()
    print("=" * 70)
    print(
        f"開始更新："
        f"{stock_code}"
    )
    print("=" * 70)

    # --------------------------------------------------------
    # 找 Stock
    # --------------------------------------------------------

    stock = (
        Stock.objects
        .filter(
            symbol=stock_code
        )
        .first()
    )

    if stock is None:

        print(
            f"找不到 Stock："
            f"{stock_code}"
        )

        return False

    print(
        f"股票："
        f"{stock.symbol} "
        f"{stock.name}"
    )

    # --------------------------------------------------------
    # 查 DB 最後日期
    # --------------------------------------------------------

    last_date = get_last_date(
        stock
    )

    # --------------------------------------------------------
    # 完全沒有資料
    # --------------------------------------------------------

    if last_date is None:

        print(
            "目前沒有歷史資料"
        )

        return import_stock(
            stock_code
        )

    print(
        f"DB 最後交易日："
        f"{last_date}"
    )

    # --------------------------------------------------------
    # 查市場最新交易日
    # --------------------------------------------------------

    latest_market_date = (
        get_latest_market_date(
            stock_code
        )
    )

    if latest_market_date is None:

        print(
            "無法取得市場最新交易日"
        )

        return False

    print(
        f"市場最新交易日："
        f"{latest_market_date}"
    )

    # --------------------------------------------------------
    # 已經最新
    # --------------------------------------------------------

    if last_date >= latest_market_date:

        print()
        print(
            "✓ 資料已經是最新交易日"
        )
        print(
            "✓ 不需要重新抓取"
        )

        return True

    # --------------------------------------------------------
    # 開始增量更新
    # --------------------------------------------------------

    print()
    print(
        "發現缺少資料"
    )

    start_date = (
        last_date
        + timedelta(
            days=1
        )
    )

    today = (
        datetime.today().date()
    )

    # --------------------------------------------------------
    # 從最後日期所在月份開始
    #
    # 例如：
    # DB 最後 = 2026-09-30
    #
    # 會先抓：
    # 2026-09
    #
    # 再抓：
    # 2026-10
    #
    # 但只寫入 > last_date 的資料
    # --------------------------------------------------------

    current_month = (
        start_date
        .replace(
            day=1
        )
    )

    end_month = (
        today
        .replace(
            day=1
        )
    )

    total = 0
    month_count = 0

    # --------------------------------------------------------
    # 逐月抓取
    # --------------------------------------------------------

    while current_month <= end_month:

        month_count += 1

        print(
            f"[{month_count:02d}] "
            f"取得 "
            f"{current_month.strftime('%Y-%m')}..."
        )

        try:

            df = get_twse_month_data(
                stock_code,
                current_month
            )

        except Exception as e:

            print(
                f"    API 失敗：{e}"
            )

            current_month += (
                relativedelta(
                    months=1
                )
            )

            continue

        if df is None:

            print(
                "    無資料"
            )

        else:

            saved_count = 0

            for _, row in df.iterrows():

                try:

                    trade_date = (
                        get_trade_date(
                            row
                        )
                    )

                    if trade_date is None:
                        continue

                    # 不抓舊資料
                    if trade_date <= last_date:
                        continue

                    # 不抓未來資料
                    if trade_date > today:
                        continue

                    # 儲存
                    if save_stock_price(
                        stock,
                        trade_date,
                        row
                    ):

                        total += 1
                        saved_count += 1

                        print(
                            f"    新增："
                            f"{trade_date}"
                        )

                except Exception as e:

                    print(
                        f"    資料處理錯誤："
                        f"{e}"
                    )

            print(
                f"    新增："
                f"{saved_count} 筆"
            )

        time.sleep(
            REQUEST_DELAY
        )

        current_month += (
            relativedelta(
                months=1
            )
        )

    print()
    print(
        f"{stock_code} 更新完成"
    )
    print(
        f"本次新增："
        f"{total} 筆"
    )

    return True


# ============================================================
# 更新全部股票
# ============================================================

def update_all_stocks():

    print()
    print("=" * 70)
    print(
        "開始更新所有 TWSE 股票"
    )
    print("=" * 70)

    stocks = (
        Stock.objects
        .all()
        .order_by(
            "symbol"
        )
    )

    total_stocks = (
        stocks.count()
    )

    print(
        f"股票數量："
        f"{total_stocks}"
    )

    print()

    success_count = 0
    fail_count = 0

    for index, stock in enumerate(
        stocks,
        start=1
    ):

        print()
        print(
            f"[{index}/{total_stocks}] "
            f"{stock.symbol} "
            f"{stock.name}"
        )

        try:

            result = update_stock(
                stock.symbol
            )

            if result:

                success_count += 1

            else:

                fail_count += 1

        except Exception as e:

            fail_count += 1

            print(
                f"{stock.symbol} "
                f"更新失敗：{e}"
            )

    print()
    print("=" * 70)
    print(
        "所有股票更新完成"
    )
    print(
        f"成功：{success_count}"
    )
    print(
        f"失敗：{fail_count}"
    )
    print("=" * 70)


# ============================================================
# 主程式
#
# 使用方式：
#
# 1. 指定股票
#    python scripts\import_history.py 2330
#
# 2. 更新全部股票
#    python scripts\import_history.py all
#
# 3. 沒有參數
#    預設更新 2330
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 70)
    print(
        "STOCK AI"
    )
    print(
        "TWSE 股票歷史資料更新系統"
    )
    print("=" * 70)

    # --------------------------------------------------------
    # 取得命令列參數
    # --------------------------------------------------------

    if len(sys.argv) >= 2:

        argument = (
            sys.argv[1]
            .strip()
        )

        # ----------------------------------------------------
        # 更新全部
        # ----------------------------------------------------

        if argument.lower() == "all":

            update_all_stocks()

        # ----------------------------------------------------
        # 指定股票
        # ----------------------------------------------------

        else:

            update_stock(
                argument
            )

    else:

        # ----------------------------------------------------
        # 預設股票
        # ----------------------------------------------------

        print()
        print(
            "未指定股票代號"
        )

        print(
            "預設更新：2330"
        )

        update_stock(
            "2330"
        )
