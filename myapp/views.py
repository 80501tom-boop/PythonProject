import json
from django.core.paginator import Paginator
from django.shortcuts import render,redirect

from .models import Stock

import pandas as pd
import requests
from scripts.import_history import import_stock

def index(request):

    query = request.GET.get("q", "").strip()

    if query:

        stocks = Stock.objects.filter(
            symbol__icontains=query
        ) | Stock.objects.filter(
            name__icontains=query
        )

    else:

        stocks = Stock.objects.all()

    context = {
        "stocks": stocks,
        "query": query,
    }

    return render(
        request,
        "stocks/index.html",
        context
    )

def add_stock(request):

    if request.method != "POST":
        return redirect("index")

    symbol = request.POST.get(
        "symbol",
        ""
    ).strip()

    if not symbol:
        return redirect("index")


    # =================================
    # TWSE 最新股票資料
    # =================================

    url = (
        "https://openapi.twse.com.tw/"
        "v1/exchangeReport/STOCK_DAY_ALL"
    )


    try:

        response = requests.get(
            url,
            timeout=10
        )

        response.raise_for_status()

        data = response.json()

    except Exception as e:

        print(
            "TWSE API 錯誤：",
            e
        )

        return redirect("index")


    # =================================
    # 找股票
    # =================================

    stock_data = None

    for item in data:

        if item.get("Code") == symbol:

            stock_data = item

            break


    if not stock_data:

        print(
            f"找不到股票：{symbol}"
        )

        return redirect("index")


    # =================================
    # 建立 Stock
    # =================================

    stock, created = (
        Stock.objects.get_or_create(

            symbol=symbol,

            defaults={
                "name": stock_data.get(
                    "Name",
                    ""
                ),
                "market": "TWSE",
            }
        )
    )


    # =================================
    # 更新名稱
    # =================================

    if not created:

        stock.name = stock_data.get(
            "Name",
            stock.name
        )

        stock.save()


    # =================================
    # 抓近一年歷史資料
    # =================================

    print()
    print(
        f"開始抓取 {symbol} "
        f"近一年歷史資料..."
    )


    try:

        success = import_stock(
            symbol
        )

        if success:

            print(
                f"{symbol} 歷史資料完成"
            )

    except Exception as e:

        print(
            "歷史資料匯入錯誤：",
            e
        )


    # =================================
    # 前往股票詳細頁
    # =================================

    return redirect(
        "stock_detail",
        symbol=symbol
    )

def stock_detail(request, symbol):

    try:

        stock = Stock.objects.get(
            symbol=symbol
        )

        # 完整歷史資料
        all_prices = list(
            stock.prices.all()
            .order_by("date")
        )

    except Stock.DoesNotExist:

        stock = None
        all_prices = []


    # ==================================================
    # 最新價格
    # ==================================================

    latest_price = (
        all_prices[-1]
        if all_prices
        else None
    )


    # ==================================================
    # 建立 Pandas DataFrame
    # ==================================================

    chart_data = []


    if all_prices:

        data = []

        for price in all_prices:

            data.append({

                "date": price.date,

                "close": float(
                    price.close_price
                )

            })


        df = pd.DataFrame(data)


        # ==================================================
        # 移動平均
        # ==================================================

        df["MA5"] = (
            df["close"]
            .rolling(window=5)
            .mean()
        )

        df["MA20"] = (
            df["close"]
            .rolling(window=20)
            .mean()
        )

        df["MA60"] = (
            df["close"]
            .rolling(window=60)
            .mean()
        )
        
        # ==================================================
        # RSI 14
        # ==================================================

        delta = df["close"].diff()

        gain = delta.clip(lower=0)

        loss = -delta.clip(upper=0)

        avg_gain = gain.rolling(
            window=14
        ).mean()

        avg_loss = loss.rolling(
            window=14
        ).mean()

        rs = avg_gain / avg_loss

        df["RSI"] = 100 - (
            100 / (1 + rs)
        )


        # ==================================================
        # 轉換成 JavaScript 可以使用的資料
        # ==================================================

        for _, row in df.iterrows():

            chart_data.append({

                "date": row["date"].strftime(
                    "%Y-%m-%d"
                ),

                "close": round(
                    float(row["close"]),
                    2
                ),

                "ma5": (
                    round(
                        float(row["MA5"]),
                        2
                    )
                    if pd.notna(row["MA5"])
                    else None
                ),

                "ma20": (
                    round(
                        float(row["MA20"]),
                        2
                    )
                    if pd.notna(row["MA20"])
                    else None
                ),

                "ma60": (
                    round(
                        float(row["MA60"]),
                        2
                    )
                    if pd.notna(row["MA60"])
                    else None
                ),
                "rsi": (
                round(
                    float(row["RSI"]),
                    2
                )
                if pd.notna(row["RSI"])
                else None
),

            })


    # ==================================================
    # JSON
    # ==================================================

    chart_data_json = json.dumps(
        chart_data
    )


    # ==================================================
    # 歷史價格分頁
    # 每頁 10 筆
    # ==================================================

    prices_for_table = (
        list(
            reversed(all_prices)
        )
        if all_prices
        else []
    )


    paginator = Paginator(
        prices_for_table,
        10
    )


    page_number = request.GET.get(
        "page"
    )


    prices = paginator.get_page(
        page_number
    )

    ma5_value = None
    ma20_value = None
    ma60_value = None
    rsi_value = None
    
    if all_prices:

        if len(all_prices) >= 5:

            ma5_value = round(
                sum(
                    float(
                        p.close_price
                    )
                    for p in all_prices[-5:]
                ) / 5,
                2
            )


        if len(all_prices) >= 20:

            ma20_value = round(
                sum(
                    float(
                        p.close_price
                    )
                    for p in all_prices[-20:]
                ) / 20,
                2
            )


        if len(all_prices) >= 60:

            ma60_value = round(
                sum(
                    float(
                        p.close_price
                    )
                    for p in all_prices[-60:]
                ) / 60,
                2
            )
        # =========================
        # 最新 RSI
        # =========================

        if len(df) >= 15:

            latest_rsi = df["RSI"].iloc[-1]

            if pd.notna(latest_rsi):

                rsi_value = round(
                    float(latest_rsi),
                    2
                )
    # ==================================================
    # 傳給 HTML
    # ==================================================

    context = {

        "stock": stock,

        "prices": prices,

        "latest_price": latest_price,

        "chart_data": chart_data_json,

        "paginator": paginator,

        "ma5": ma5_value,

        "ma20": ma20_value,

        "ma60": ma60_value,

        "rsi": rsi_value,

    }


    return render(
        request,
        "stocks/stock_detail.html",
        context
    )

