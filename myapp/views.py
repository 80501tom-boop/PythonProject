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
        prices = []

    latest_price = prices.first()

    context = {
        "stock": stock,
        "prices": prices,
        "latest_price": latest_price,
    }

    return render(
        request,
        "stocks/stock_detail.html",
        context
    )