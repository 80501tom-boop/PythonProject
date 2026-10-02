import os
import sys
import django
import requests
import pandas as pd
import time

from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta


# =====================================
# Django 設定
# =====================================

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


# =====================================
# TWSE API
# =====================================

API_URL = (
    "https://www.twse.com.tw/"
    "exchangeReport/STOCK_DAY"
)


# =====================================
# 取得單月資料
# =====================================

def get_month_data(stock_code, date):

    date_str = date.strftime("%Y%m%d")

    params = {
        "response": "json",
        "date": date_str,
        "stockNo": stock_code,
    }

    response = requests.get(
        API_URL,
        params=params,
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    if data.get("stat") != "OK":

        print(
            f"{stock_code} {date_str}: "
            f"{data.get('stat')}"
        )

        return None

    fields = data["fields"]

    records = data["data"]

    df = pd.DataFrame(
        records,
        columns=fields
    )

    return df


# =====================================
# 數字清理
# =====================================

def clean_number(value):

    if value is None:
        return None

    value = str(value)

    value = value.replace(",", "")

    if value in [
        "",
        "--",
        "nan"
    ]:
        return None

    try:

        return float(value)

    except ValueError:

        return None


# =====================================
# 匯入單一股票近一年資料
# =====================================

def import_stock(stock_code):

    stock_code = str(
        stock_code
    ).strip()

    print()
    print("=" * 60)

    print(
        f"開始匯入：{stock_code}"
    )

    print("=" * 60)


    # =================================
    # 取得股票
    # =================================

    stock = Stock.objects.filter(
        symbol=stock_code
    ).first()


    if stock is None:

        print(
            f"找不到 Stock：{stock_code}"
        )

        return False


    print(
        f"股票：{stock.symbol} "
        f"{stock.name}"
    )


    # =================================
    # 過去 12 個月
    # =================================

    today = datetime.today()

    start_date = (
        today
        - relativedelta(months=11)
    ).replace(
        day=1
    )

    current_date = start_date

    total = 0


    # =================================
    # 逐月取得資料
    # =================================

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
                relativedelta(months=1)
            )

            continue


        # =================================
        # 寫入資料庫
        # =================================

        if df is not None:

            for _, row in df.iterrows():

                try:

                    # -------------------------
                    # 日期
                    # -------------------------

                    date_text = str(
                        row["日期"]
                    )

                    parts = date_text.split("/")

                    year = (
                        int(parts[0])
                        + 1911
                    )

                    month = int(parts[1])

                    day = int(parts[2])

                    trade_date = datetime(
                        year,
                        month,
                        day
                    ).date()


                    # -------------------------
                    # OHLC
                    # -------------------------

                    open_price = clean_number(
                        row["開盤價"]
                    )

                    high_price = clean_number(
                        row["最高價"]
                    )

                    low_price = clean_number(
                        row["最低價"]
                    )

                    close_price = clean_number(
                        row["收盤價"]
                    )


                    # -------------------------
                    # 成交量
                    # -------------------------

                    volume = int(
                        str(
                            row["成交股數"]
                        )
                        .replace(",", "")
                    )


                    # -------------------------
                    # 避免無效資料
                    # -------------------------

                    if None in [
                        open_price,
                        high_price,
                        low_price,
                        close_price
                    ]:

                        continue


                    # -------------------------
                    # 寫入 / 更新
                    # -------------------------

                    StockPrice.objects.update_or_create(

                        stock=stock,

                        date=trade_date,

                        defaults={

                            "open_price":
                                open_price,

                            "high_price":
                                high_price,

                            "low_price":
                                low_price,

                            "close_price":
                                close_price,

                            "volume":
                                volume,
                        }
                    )


                    total += 1


                except Exception as e:

                    print(
                        f"資料處理錯誤：{e}"
                    )


        # =================================
        # 避免請求太密集
        # =================================

        time.sleep(0.5)


        current_date += (
            relativedelta(months=1)
        )


    # =================================
    # 完成
    # =================================

    print()

    print(
        f"{stock_code} 完成，"
        f"共處理 {total} 筆"
    )

    return True
# =====================================
# 更新單一股票缺少的交易資料
# =====================================

def update_stock(stock_code):

    stock_code = str(
        stock_code
    ).strip()

    print()
    print("=" * 60)

    print(
        f"開始更新：{stock_code}"
    )

    print("=" * 60)


    # =================================
    # 取得股票
    # =================================

    stock = Stock.objects.filter(
        symbol=stock_code
    ).first()


    if stock is None:

        print(
            f"找不到 Stock：{stock_code}"
        )

        return False


    print(
        f"股票：{stock.symbol} "
        f"{stock.name}"
    )


    # =================================
    # 找 DB 最後一筆資料
    # =================================

    last_record = (
        StockPrice.objects
        .filter(stock=stock)
        .order_by("-date")
        .first()
    )


    # =================================
    # 如果完全沒有資料
    # =================================

    if last_record is None:

        print(
            "目前沒有歷史資料，"
            "改用 import_stock()"
        )

        return import_stock(
            stock_code
        )


    last_date = last_record.date

    today = datetime.today().date()


    print(
        f"DB 最後交易日："
        f"{last_date}"
    )

    print(
        f"今天："
        f"{today}"
    )


    # =================================
    # 已經是最新
    # =================================

    if last_date >= today:

        print(
            "資料已經是最新，"
            "不需要更新。"
        )

        return True


    # =================================
    # 從最後一天的下一天開始
    # =================================

    start_date = (
        last_date
        + timedelta(days=1)
    )


    # =================================
    # 逐月抓取
    # =================================

    current_date = (
        start_date.replace(day=1)
    )

    end_month = (
        today.replace(day=1)
    )


    total = 0


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
                relativedelta(months=1)
            )

            continue


        # =================================
        # 寫入資料庫
        # =================================

        if df is not None:

            for _, row in df.iterrows():

                try:

                    # -------------------------
                    # 日期
                    # -------------------------

                    date_text = str(
                        row["日期"]
                    )

                    parts = (
                        date_text.split("/")
                    )

                    year = (
                        int(parts[0])
                        + 1911
                    )

                    month = int(parts[1])

                    day = int(parts[2])


                    trade_date = datetime(
                        year,
                        month,
                        day
                    ).date()


                    # -------------------------
                    # 只處理缺少日期
                    # -------------------------

                    if trade_date <= last_date:

                        continue


                    if trade_date > today:

                        continue


                    # -------------------------
                    # OHLC
                    # -------------------------

                    open_price = clean_number(
                        row["開盤價"]
                    )

                    high_price = clean_number(
                        row["最高價"]
                    )

                    low_price = clean_number(
                        row["最低價"]
                    )

                    close_price = clean_number(
                        row["收盤價"]
                    )


                    # -------------------------
                    # 成交量
                    # -------------------------

                    volume_text = str(
                        row["成交股數"]
                    ).replace(",", "")


                    if (
                        volume_text == ""
                        or volume_text == "--"
                    ):

                        continue


                    volume = int(
                        float(volume_text)
                    )


                    # -------------------------
                    # 避免無效資料
                    # -------------------------

                    if None in [
                        open_price,
                        high_price,
                        low_price,
                        close_price
                    ]:

                        continue


                    # -------------------------
                    # 寫入資料庫
                    # -------------------------

                    obj, created = (
                        StockPrice.objects
                        .update_or_create(

                            stock=stock,

                            date=trade_date,

                            defaults={

                                "open_price":
                                    open_price,

                                "high_price":
                                    high_price,

                                "low_price":
                                    low_price,

                                "close_price":
                                    close_price,

                                "volume":
                                    volume,
                            }
                        )
                    )


                    if created:

                        total += 1

                        print(
                            f"新增："
                            f"{trade_date}"
                        )


                except Exception as e:

                    print(
                        f"資料處理錯誤：{e}"
                    )


        # =================================
        # 避免請求太密集
        # =================================

        time.sleep(0.5)


        current_date += (
            relativedelta(months=1)
        )


    # =================================
    # 完成
    # =================================

    print()

    print(
        f"{stock_code} 更新完成，"
        f"新增 {total} 筆資料"
    )

    return True
# =====================================
# 更新資料庫內所有股票
# =====================================

def update_all_stocks():

    print()
    print("=" * 60)
    print("開始更新所有股票")
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
    print("所有股票更新完成")
    print("=" * 60)