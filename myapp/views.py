import json

from django.core.paginator import Paginator
from django.shortcuts import render

from .models import Stock


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
        all_prices = stock.prices.all().order_by("date")

    except Stock.DoesNotExist:

        stock = None
        all_prices = Stock.objects.none()

    # =========================
    # 最新價格
    # =========================

    latest_price = (
        all_prices.last()
        if stock
        else None
    )

    # =========================
    # 圖表資料
    # =========================

    chart_data = []

    for price in all_prices:

        chart_data.append({
            "date": price.date.strftime("%Y-%m-%d"),
            "close": float(price.close_price),
        })

    chart_data_json = json.dumps(
        chart_data
    )

    # =========================
    # 歷史價格分頁
    # 每頁 10 筆
    # =========================

    prices_for_table = (
        all_prices.order_by("-date")
        if stock
        else Stock.objects.none()
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

    context = {

        "stock": stock,

        # 歷史價格表格
        "prices": prices,

        # 最新價格
        "latest_price": latest_price,

        # 圖表
        "chart_data": chart_data_json,

        # 分頁
        "paginator": paginator,
    }

    return render(
        request,
        "stocks/stock_detail.html",
        context
    )