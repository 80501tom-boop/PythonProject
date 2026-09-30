import os
import sys
import django
import requests
import pandas as pd


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
    "https://openapi.twse.com.tw/"
    "v1/exchangeReport/STOCK_DAY_ALL"
)


# =====================================
# 要更新的股票
# =====================================

STOCK_CODES = [
    "2330",
    "0052",
]


# =====================================
# 取得 TWSE 資料
# =====================================

def get_twse_data():

    print("正在取得 TWSE 資料...")

    response = requests.get(
        API_URL,
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    df = pd.DataFrame(data)

    print(
        f"取得 {len(df)} 筆股票資料"
    )

    return df


# =====================================
# 更新單一股票
# =====================================

def update_stock(df, code):

    stock_data = df[
        df["Code"].astype(str) == code
    ]

    if stock_data.empty:

        print(
            f"{code}：找不到股票資料"
        )

        return

    row = stock_data.iloc[0]

    name = row["Name"]

    print()
    print("-" * 50)
    print(f"股票：{code} {name}")
    print("-" * 50)

    # -----------------------------
    # 建立或取得 Stock
    # -----------------------------

    stock, created = Stock.objects.get_or_create(

        symbol=code,

        defaults={
            "name": name,
            "market": "TWSE",
        }
    )

    if created:

        print("建立 Stock 資料")

    else:

        print("Stock 已存在")

        # 如果股票名稱有更新
        if stock.name != name:

            stock.name = name
            stock.save()

    # -----------------------------
    # 注意：
    # STOCK_DAY_ALL 是當日資料
    # -----------------------------

    try:

        # TWSE 日期為民國年，例如 1150929 → 2026-09-29
        twse_date = str(row["Date"]).strip()

        year = int(twse_date[:3]) + 1911
        month = int(twse_date[3:5])
        day = int(twse_date[5:7])

        date = pd.Timestamp(
            year=year,
            month=month,
            day=day
        ).date()

        open_price = float(
            row["OpeningPrice"]
        )

        high_price = float(
            row["HighestPrice"]
        )

        low_price = float(
            row["LowestPrice"]
        )

        close_price = float(
            row["ClosingPrice"]
        )

        volume = int(
            row["TradeVolume"]
        )

    except Exception as e:

        print(
            f"資料格式錯誤：{e}"
        )

        return

    # -----------------------------
    # 寫入 StockPrice
    # -----------------------------

    price, created = StockPrice.objects.update_or_create(

        stock=stock,

        date=date,

        defaults={

            "open_price": open_price,

            "high_price": high_price,

            "low_price": low_price,

            "close_price": close_price,

            "volume": volume,
        }
    )

    if created:

        print(
            f"新增價格資料：{date}"
        )

    else:

        print(
            f"更新價格資料：{date}"
        )

    print(
        f"開盤：{open_price}"
    )

    print(
        f"最高：{high_price}"
    )

    print(
        f"最低：{low_price}"
    )

    print(
        f"收盤：{close_price}"
    )

    print(
        f"成交量：{volume}"
    )


# =====================================
# 主程式
# =====================================

if __name__ == "__main__":

    print()
    print("=" * 60)
    print("       STOCK AI - TWSE 股票資料更新")
    print("=" * 60)

    try:

        df = get_twse_data()

    except Exception as e:

        print()
        print("TWSE API 取得失敗")
        print(e)

        sys.exit(1)

    for code in STOCK_CODES:

        update_stock(
            df,
            code
        )

    print()
    print("=" * 60)
    print("             更新完成")
    print("=" * 60)