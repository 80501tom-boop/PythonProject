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

    except Stock.DoesNotExist:

        stock = None

    context = {
        "stock": stock
    }

    return render(
        request,
        "stocks/stock_detail.html",
        context
    )