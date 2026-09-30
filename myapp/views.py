import json

from django.core.paginator import Paginator
from django.shortcuts import render

from .models import Stock

import pandas as pd

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
                )

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
    # ==================================================
    # 傳給 HTML
    # ==================================================

    context = {

        "stock": stock,

        "prices": prices,

        "latest_price": latest_price,

        "chart_data": chart_data_json,

        "paginator": paginator,
        
        # 技術指標
        "ma5": ma5_value,
        
        "ma20": ma20_value,
        
        "ma60": ma60_value,
    }


    return render(
        request,
        "stocks/stock_detail.html",
        context
    )

