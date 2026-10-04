from django.urls import path

from . import views


urlpatterns = [

    path(
        "",
        views.index,
        name="index"
    ),

    path(
        "add-stock/",
        views.add_stock,
        name="add_stock"
    ),

    path(
        "stock/<str:symbol>/",
        views.stock_detail,
        name="stock_detail"
    ),

    path(
        "market-ranking/",
        views.market_ranking,
        name="market_ranking"
    ),
    path(
        "market-backtest/",
        views.market_backtest,
        name="market_backtest"
    ),
    path(
    "market-strategy/",
    views.market_strategy,
    name="market_strategy",
    ),
]