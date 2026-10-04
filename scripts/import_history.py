import os
import sys
import django
import requests
import pandas as pd
import time
import io

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

# TWSE 當日全部股票
TWSE_ALL_API_URL = (
    "https://www.twse.com.tw/"
    "exchangeReport/STOCK_DAY_ALL"
)

# TPEx 上櫃
OTC_API_URL = (
    "https://www.tpex.org.tw/"
    "web/stock/aftertrading/"
    "daily_trading_info/st43.php"
)


# ============================================================
# Requests Header
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


# ============================================================
# 基本 Request
# ============================================================

def request_get(url, params=None):

    response = requests.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=15
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
        "--"
    ]:
        return None

    # --------------------------------------------------------
    # 格式：115/10/02
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
    # 格式：1151002
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
    # 西元 YYYY-MM-DD
    # --------------------------------------------------------

    try:

        return datetime.strptime(
            text,
            "%Y-%m-%d"
        ).date()

    except Exception:
        pass

    # --------------------------------------------------------
    # 西元 YYYY/MM/DD
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

    value = str(value).strip()

    value = value.replace(",", "")

    if value in [
        "",
        "--",
        "---",
        "nan",
        "NaN",
        "None"
    ]:
        return None

    try:

        return float(value)

    except (ValueError, TypeError):

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

    except (ValueError, TypeError):

        return None


# ============================================================
# 判斷股票市場
#
# 優先使用 Stock.market
# 如果你的 Stock model 還沒有 market 欄位，
# 就透過官方 API 判斷。
# ============================================================

def get_market(stock_code):

    stock_code = str(
        stock_code
    ).strip()

    # --------------------------------------------------------
    # 如果 Stock model 有 market 欄位
    # --------------------------------------------------------

    try:

        stock = Stock.objects.filter(
            symbol=stock_code
        ).first()

        if stock is not None:

            market = getattr(
                stock,
                "market",
                None
            )

            if market:

                market = str(
                    market
                ).strip().upper()

                if market in [
                    "TWSE",
                    "TSE",
                    "上市"
                ]:

                    return "TWSE"

                if market in [
                    "OTC",
                    "TPEx",
                    "上櫃"
                ]:

                    return "OTC"

    except Exception:
        pass


    # --------------------------------------------------------
    # 沒有 market 欄位時
    #
    # 優先測試 TWSE STOCK_DAY
    # --------------------------------------------------------

    try:

        test_date = datetime.today()

        params = {

            "response":
                "json",

            "date":
                test_date.strftime(
                    "%Y%m%d"
                ),

            "stockNo":
                stock_code
        }

        response = request_get(
            TWSE_API_URL,
            params=params
        )

        content_type = (
            response.headers
            .get("Content-Type", "")
            .lower()
        )

        if "json" in content_type:

            data = response.json()

            if data.get("stat") == "OK":

                return "TWSE"

    except Exception:
        pass


    # --------------------------------------------------------
    # TWSE 無資料
    # → 嘗試 OTC
    # --------------------------------------------------------

    return "OTC"


# ============================================================
# TWSE：取得單月資料
# ============================================================

def get_twse_month_data(
    stock_code,
    date
):

    date_str = date.strftime(
        "%Y%m%d"
    )

    params = {

        "response":
            "json",

        "date":
            date_str,

        "stockNo":
            stock_code
    }

    response = request_get(
        TWSE_API_URL,
        params=params
    )

    content_type = (
        response.headers
        .get("Content-Type", "")
        .lower()
    )

    # --------------------------------------------------------
    # TWSE STOCK_DAY 正常 JSON
    # --------------------------------------------------------

    if "json" in content_type:

        data = response.json()

        if data.get("stat") != "OK":

            print(
                f"TWSE {stock_code} "
                f"{date_str}: "
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

    # --------------------------------------------------------
    # 如果 API 回傳不是 JSON
    # --------------------------------------------------------

    print(
        f"TWSE {stock_code} "
        f"{date_str}: "
        f"API 非 JSON"
    )

    return None


# ============================================================
# OTC：取得單月資料
# ============================================================

def get_otc_month_data(
    stock_code,
    date
):

    # TPEx API 使用西元日期
    date_str = date.strftime(
        "%Y%m%d"
    )

    params = {

        "l": "zh-tw",

        "d":
            date_str,

        "stk_yn":
            "Y",

        "code":
            stock_code
    }

    response = request_get(
        OTC_API_URL,
        params=params
    )

    try:

        data = response.json()

    except Exception:

        print(
            f"OTC {stock_code} "
            f"{date_str}: "
            "API 無法解析 JSON"
        )

        return None

    # --------------------------------------------------------
    # TPEx 常見格式：
    #
    # tables[0].data
    # --------------------------------------------------------

    if isinstance(
        data,
        dict
    ):

        tables = data.get(
            "tables",
            []
        )

        if tables:

            for table in tables:

                records = table.get(
                    "data",
                    []
                )

                if records:

                    fields = table.get(
                        "fields",
                        []
                    )

                    df = pd.DataFrame(
                        records,
                        columns=fields
                        if fields
                        else None
                    )

                    return df

    return None


# ============================================================
# 統一取得單月資料
# ============================================================

def get_month_data(
    stock_code,
    date
):

    stock_code = str(
        stock_code
    ).strip()

    market = get_market(
        stock_code
    )

    print(
        f"市場判斷："
        f"{stock_code} → {market}"
    )

    if market == "TWSE":

        return get_twse_month_data(
            stock_code,
            date
        )

    elif market == "OTC":

        return get_otc_month_data(
            stock_code,
            date
        )

    print(
        f"{stock_code} "
        f"無法判斷市場"
    )

    return None


# ============================================================
# 標準化 TWSE 欄位
# ============================================================

def normalize_twse_dataframe(df):

    if df is None:
        return None

    required_columns = [

        "日期",

        "開盤價",

        "最高價",

        "最低價",

        "收盤價",

        "成交股數"
    ]

    for column in required_columns:

        if column not in df.columns:

            return None

    return df


# ============================================================
# 標準化 OTC 欄位
# ============================================================

def normalize_otc_dataframe(df):

    if df is None:
        return None

    # --------------------------------------------------------
    # 顯示原始欄位，方便之後 API 格式變動時除錯
    # --------------------------------------------------------

    print(
        "OTC 欄位：",
        list(df.columns)
    )

    return df


# ============================================================
# 從資料列取得日期
# ============================================================

def get_trade_date(
    row
):

    # --------------------------------------------------------
    # TWSE
    # --------------------------------------------------------

    if "日期" in row.index:

        return parse_tw_date(
            row["日期"]
        )

    # --------------------------------------------------------
    # OTC 常見欄位
    # --------------------------------------------------------

    for column in [
        "日期",
        "交易日期",
        "Date"
    ]:

        if column in row.index:

            return parse_tw_date(
                row[column]
            )

    return None


# ============================================================
# 從資料列取得 OHLC
# ============================================================

def get_ohlc(row):

    # --------------------------------------------------------
    # TWSE
    # --------------------------------------------------------

    column_mapping = {

        "open":
            [
                "開盤價",
                "開盤"
            ],

        "high":
            [
                "最高價",
                "最高"
            ],

        "low":
            [
                "最低價",
                "最低"
            ],

        "close":
            [
                "收盤價",
                "收盤"
            ],

        "volume":
            [
                "成交股數",
                "成交量"
            ]
    }

    result = {

        "open_price":
            None,

        "high_price":
            None,

        "low_price":
            None,

        "close_price":
            None,

        "volume":
            None
    }


    for key, columns in (
        column_mapping.items()
    ):

        for column in columns:

            if column in row.index:

                value = row[column]

                if key == "volume":

                    result[
                        "volume"
                    ] = clean_volume(
                        value
                    )

                else:

                    result[
                        f"{key}_price"
                    ] = clean_number(
                        value
                    )

                break

    return result


# ============================================================
# 儲存單筆 StockPrice
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

    if None in [

        ohlc["open_price"],

        ohlc["high_price"],

        ohlc["low_price"],

        ohlc["close_price"]
    ]:

        return False


    volume = ohlc[
        "volume"
    ]

    if volume is None:

        volume = 0


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
# 匯入單一股票近一年資料
# ============================================================

def import_stock(
    stock_code
):

    stock_code = str(
        stock_code
    ).strip()

    print()
    print("=" * 60)
    print(
        f"開始匯入：{stock_code}"
    )
    print("=" * 60)


    # --------------------------------------------------------
    # 取得股票
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
    # 判斷市場
    # --------------------------------------------------------

    market = get_market(
        stock_code
    )

    print(
        f"市場：{market}"
    )


    # --------------------------------------------------------
    # 過去 12 個月
    # --------------------------------------------------------

    today = datetime.today()

    start_date = (
        today
        - relativedelta(
            months=11
        )
    ).replace(
        day=1
    )

    current_date = (
        start_date
    )

    total = 0


    # --------------------------------------------------------
    # 逐月取得資料
    # --------------------------------------------------------

    while current_date <= today:

        print(
            f"取得 "
            f"{current_date.strftime('%Y-%m')}..."
        )


        try:

            df = get_month_data(
                stock_code,
                current_date
            )

        except Exception as e:

            print(
                f"取得失敗：{e}"
            )

            current_date += (
                relativedelta(
                    months=1
                )
            )

            continue


        # ----------------------------------------------------
        # 寫入資料庫
        # ----------------------------------------------------

        if df is not None:

            print(
                f"取得 {len(df)} 筆資料"
            )

            for _, row in (
                df.iterrows()
            ):

                try:

                    trade_date = (
                        get_trade_date(
                            row
                        )
                    )

                    if trade_date is None:

                        continue


                    if trade_date > (
                        today.date()
                    ):

                        continue


                    if save_stock_price(
                        stock,
                        trade_date,
                        row
                    ):

                        total += 1


                except Exception as e:

                    print(
                        f"資料處理錯誤："
                        f"{e}"
                    )


        # ----------------------------------------------------
        # 避免請求過於密集
        # ----------------------------------------------------

        time.sleep(
            0.5
        )


        current_date += (
            relativedelta(
                months=1
            )
        )


    # --------------------------------------------------------
    # 完成
    # --------------------------------------------------------

    print()

    print(
        f"{stock_code} 完成，"
        f"共處理 {total} 筆"
    )

    return True


# ============================================================
# 取得 DB 最新交易日
# ============================================================

def get_last_date(
    stock
):

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
# 找市場最新交易日
#
# 使用最近幾天逐日查詢，避免：
# - 週末
# - 國定假日
# - 非交易日
# ============================================================

def get_latest_market_date(
    stock_code
):

    stock_code = str(
        stock_code
    ).strip()

    market = get_market(
        stock_code
    )

    today = datetime.today().date()

    # 往前檢查 10 天
    for offset in range(
        0,
        11
    ):

        check_date = (
            today
            - timedelta(
                days=offset
            )
        )

        try:

            df = get_month_data(
                stock_code,
                check_date
            )

            if df is None:

                continue

            if len(df) == 0:

                continue

            # ------------------------------------------------
            # 從 API 回傳資料中找實際最後交易日
            # ------------------------------------------------

            dates = []

            for _, row in (
                df.iterrows()
            ):

                trade_date = (
                    get_trade_date(
                        row
                    )
                )

                if trade_date is not None:

                    if trade_date <= today:

                        dates.append(
                            trade_date
                        )

            if dates:

                return max(
                    dates
                )

        except Exception as e:

            print(
                f"查詢最新交易日失敗："
                f"{e}"
            )

    return None


# ============================================================
# 更新單一股票缺少的交易資料
# ============================================================

def update_stock(
    stock_code
):

    stock_code = str(
        stock_code
    ).strip()

    print()
    print("=" * 60)
    print(
        f"開始更新：{stock_code}"
    )
    print("=" * 60)


    # --------------------------------------------------------
    # 取得股票
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
    # DB 最後資料
    # --------------------------------------------------------

    last_date = get_last_date(
        stock
    )


    # --------------------------------------------------------
    # 完全沒有資料
    # --------------------------------------------------------

    if last_date is None:

        print(
            "目前沒有歷史資料，"
            "改用 import_stock()"
        )

        return import_stock(
            stock_code
        )


    print(
        f"DB 最後交易日："
        f"{last_date}"
    )


    # --------------------------------------------------------
    # 找真正市場最新交易日
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
    # 已經是最新
    #
    # ★ 這裡就是你要求的功能
    # --------------------------------------------------------

    if last_date >= (
        latest_market_date
    ):

        print(
            "資料已經是最新交易日，"
            "不需要重新抓取。"
        )

        return True


    # --------------------------------------------------------
    # 從 DB 最後一天的下一天開始
    # --------------------------------------------------------

    start_date = (
        last_date
        + timedelta(
            days=1
        )
    )

    today = datetime.today().date()


    current_date = (
        start_date.replace(
            day=1
        )
    )

    end_month = (
        today.replace(
            day=1
        )
    )


    total = 0


    # --------------------------------------------------------
    # 逐月抓取
    # --------------------------------------------------------

    while current_date <= end_month:

        print(
            f"取得 "
            f"{current_date.strftime('%Y-%m')}..."
        )


        try:

            df = get_month_data(
                stock_code,
                current_date
            )

        except Exception as e:

            print(
                f"取得失敗：{e}"
            )

            current_date += (
                relativedelta(
                    months=1
                )
            )

            continue


        # ----------------------------------------------------
        # 寫入資料庫
        # ----------------------------------------------------

        if df is not None:

            for _, row in (
                df.iterrows()
            ):

                try:

                    trade_date = (
                        get_trade_date(
                            row
                        )
                    )

                    if trade_date is None:

                        continue


                    # 只抓缺少資料

                    if trade_date <= last_date:

                        continue


                    if trade_date > today:

                        continue


                    if save_stock_price(
                        stock,
                        trade_date,
                        row
                    ):

                        total += 1

                        print(
                            f"新增："
                            f"{trade_date}"
                        )


                except Exception as e:

                    print(
                        f"資料處理錯誤："
                        f"{e}"
                    )


        # ----------------------------------------------------
        # 避免請求太密集
        # ----------------------------------------------------

        time.sleep(
            0.5
        )


        current_date += (
            relativedelta(
                months=1
            )
        )


    # --------------------------------------------------------
    # 完成
    # --------------------------------------------------------

    print()

    print(
        f"{stock_code} 更新完成，"
        f"新增 {total} 筆資料"
    )

    return True


# ============================================================
# 更新資料庫內所有股票
# ============================================================

def update_all_stocks():

    print()
    print("=" * 60)
    print(
        "開始更新所有股票"
    )
    print("=" * 60)


    stocks = Stock.objects.all()


    for stock in stocks:

        try:

            update_stock(
                stock.symbol
            )

        except Exception as e:

            print(
                f"{stock.symbol} "
                f"更新失敗：{e}"
            )


    print()
    print("=" * 60)
    print(
        "所有股票更新完成"
    )
    print("=" * 60)


# ============================================================
# 測試單一股票
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 60)
    print(
        "Stock History Import / Update"
    )
    print("=" * 60)

    print()
    print(
        "請在其他程式中呼叫："
    )

    print(
        "import_stock('2330')"
    )

    print(
        "update_stock('2330')"
    )

    print(
        "update_all_stocks()"
    )

    print()