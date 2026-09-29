import os
import sys
import django
import requests
import pandas as pd
import time
from datetime import datetime
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

API_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"


# =====================================
# 股票
# =====================================

STOCK_CODES = [
    "2330",
    "2454",
    "2317",
    "0050",
]


# =====================================
# 股票名稱
# =====================================

STOCK_NAMES = {
    "2330": "台積電",
    "2454": "聯發科",
    "2317": "鴻海",
    "0050": "元大台灣50",
}


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

    if value in ["", "--", "nan"]:
        return None

    try:
        return float(value)

    except ValueError:
        return None


# =====================================
# 匯入單一股票
# =====================================

def import_stock(stock_code):

    name = STOCK_NAMES.get(
        stock_code,
        stock_code
    )

    print()
    print("=" * 60)
    print(f"開始匯入：{stock_code} {name}")
    print("=" * 60)

    # -----------------------------
    # 建立 Stock
    # -----------------------------

    stock, created = Stock.objects.get_or_create(
        symbol=stock_code,
        defaults={
            "name": name,
            "market": "TWSE",
        }
    )

    if created:
        print("建立 Stock")

    # -----------------------------
    # 過去 12 個月
    # -----------------------------

    today = datetime.today()

    start_date = (
        today - relativedelta(months=11)
    ).replace(
        day=1
    )

    current_date = start_date

    total = 0

    while current_date <= today:

        print(
            f"取得 {current_date.strftime('%Y-%m')}..."
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

            current_date += relativedelta(
                months=1
            )

            continue

        if df is not None:

            for _, row in df.iterrows():

                try:

                    # 民國日期，例如 115/09/29
                    date_text = str(
                        row["日期"]
                    )

                    parts = date_text.split("/")

                    year = int(parts[0]) + 1911
                    month = int(parts[1])
                    day = int(parts[2])

                    trade_date = datetime(
                        year,
                        month,
                        day
                    ).date()

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

                    volume = int(
                        str(row["成交股數"])
                        .replace(",", "")
                    )

                    if None in [
                        open_price,
                        high_price,
                        low_price,
                        close_price
                    ]:
                        continue

                    StockPrice.objects.update_or_create(

                        stock=stock,

                        date=trade_date,

                        defaults={

                            "open_price": open_price,

                            "high_price": high_price,

                            "low_price": low_price,

                            "close_price": close_price,

                            "volume": volume,
                        }
                    )

                    total += 1

                except Exception as e:

                    print(
                        f"資料處理錯誤：{e}"
                    )

        # 避免請求太密集
        time.sleep(0.5)

        current_date += relativedelta(
            months=1
        )

    print()
    print(
        f"{stock_code} 完成，共處理 {total} 筆"
    )


# =====================================
# 主程式
# =====================================

if __name__ == "__main__":

    print()
    print("=" * 60)
    print("       STOCK AI - 歷史股價匯入")
    print("=" * 60)

    for code in STOCK_CODES:

        import_stock(code)

    print()
    print("=" * 60)
    print("          所有歷史資料匯入完成")
    print("=" * 60)