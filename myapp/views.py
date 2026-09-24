from django.shortcuts import render


# 暫時使用的股票資料
stocks = [
    {
        "symbol": "2330",
        "name": "台積電",
        "market": "TWSE"
    },
    {
        "symbol": "2454",
        "name": "聯發科",
        "market": "TWSE"
    },
    {
        "symbol": "2317",
        "name": "鴻海",
        "market": "TWSE"
    },
    {
        "symbol": "2303",
        "name": "聯電",
        "market": "TWSE"
    },
    {
        "symbol": "2382",
        "name": "廣達",
        "market": "TWSE"
    },
]


def index(request):

    # 取得搜尋關鍵字
    query = request.GET.get("q", "").strip()

    # 如果沒有輸入搜尋
    if query == "":
        search_results = stocks

    else:
        search_results = []

        for stock in stocks:

            # 搜尋股票代號
            if query.lower() in stock["symbol"].lower():

                search_results.append(stock)

            # 搜尋股票名稱
            elif query in stock["name"]:

                search_results.append(stock)

    context = {
        "stocks": search_results,
        "query": query,
    }

    return render(
        request,
        "stocks/index.html",
        context
    )


def stock_detail(request, symbol):

    stock_data = None

    for stock in stocks:

        if stock["symbol"] == symbol:
            stock_data = stock
            break

    context = {
        "stock": stock_data
    }

    return render(
        request,
        "stocks/stock_detail.html",
        context
    )