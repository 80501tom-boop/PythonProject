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

        prices = stock.prices.all()

    except Stock.DoesNotExist:

        stock = None
        prices = Stock.objects.none()

    # =========================
    # 歷史價格分頁
    # 每頁 10 筆
    # =========================

    paginator = Paginator(
        prices,
        10
    )

    page_number = request.GET.get(
        "page"
    )

    prices_page = paginator.get_page(
        page_number
    )

    # 最新價格
    latest_price = prices.first()

    context = {
        "stock": stock,

        # 原本的 prices 改成分頁後資料
        "prices": prices_page,

        "latest_price": latest_price,

        # 額外提供分頁物件
        "paginator": paginator,
    }

    return render(
        request,
        "stocks/stock_detail.html",
        context
    )