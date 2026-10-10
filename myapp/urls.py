from django.urls import path

from . import views
from .views import prediction_performance

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
    path(
        "prediction-history/",
        views.prediction_history,
        name="prediction_history"
    ),
    path(
        "prediction-performance/",
        prediction_performance,
        name="prediction_performance",
    ),
    path(
        "run-forward-prediction/",
        views.run_forward_prediction,
        name="run_forward_prediction",
    ),

    path(
        "run-forward-evaluation/",
        views.run_forward_evaluation,
        name="run_forward_evaluation",
    ),
    ]