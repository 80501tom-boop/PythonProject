
import json
import os
import subprocess
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import requests

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.core.paginator import Paginator
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST

from .models import Stock, StockPrice, PredictionHistory

from scripts.import_history import (
    import_stock,
    update_stock,
    update_all_stocks,
)

# ============================================================
# 首頁
# ============================================================


# ============================================================
# 首頁
# V6.1：整合最新前瞻預測 Top 5
# ============================================================

def index(request):

    # =====================================
    # 每天第一次開啟網站時，自動更新股票資料
    # =====================================

    today = datetime.today().date()

    if request.session.get(
        "stock_data_update_date"
    ) != str(today):

        try:
            print()
            print("=" * 60)
            print(f"網站啟動：開始更新股票資料 {today}")
            print("=" * 60)

            update_all_stocks()

            # 更新成功後才記錄日期
            request.session[
                "stock_data_update_date"
            ] = str(today)

            print("=" * 60)
            print("股票資料更新完成")
            print("=" * 60)

        except Exception as e:
            print(f"股票資料更新失敗：{e}")

    # =====================================
    # 股票搜尋（保留原功能）
    # =====================================

    query = request.GET.get("q", "").strip()

    if query:
        stocks = (
            Stock.objects.filter(
                symbol__icontains=query
            )
            |
            Stock.objects.filter(
                name__icontains=query
            )
        )
    else:
        stocks = Stock.objects.all()

    # =====================================
    # V6.1：取得最新一批前瞻預測
    # =====================================

    latest_prediction_date = (
        PredictionHistory.objects
        .order_by("-prediction_date")
        .values_list("prediction_date", flat=True)
        .first()
    )

    latest_data_date = None
    latest_predictions = []
    latest_model_version = None

    if latest_prediction_date:

        prediction_queryset = (
            PredictionHistory.objects
            .filter(
                prediction_date=latest_prediction_date
            )
            .order_by("rank")
        )

        # 取得預測所使用的最新資料日期
        first_prediction = prediction_queryset.first()

        if first_prediction:
            latest_data_date = first_prediction.data_date
            latest_model_version = first_prediction.model_version

        # 首頁只顯示 Top 5
        latest_predictions = list(
            prediction_queryset[:5].values(
                "prediction_date",
                "data_date",
                "symbol",
                "stock_name",
                "close_price",
                "predicted_return_20",
                "rank",
                "horizon",
                "model_version",
            )
        )

    # =====================================
    # 傳給首頁 HTML
    # =====================================

    context = {
        # 原有股票搜尋
        "stocks": stocks,
        "query": query,

        # V6.1 最新預測
        "latest_prediction_date": latest_prediction_date,
        "latest_data_date": latest_data_date,
        "latest_predictions": latest_predictions,
        "latest_model_version": latest_model_version,
    }

    return render(
        request,
        "stocks/index.html",
        context
    )



# ============================================================
# 新增股票
# ============================================================

def add_stock(request):

    if request.method != "POST":
        return redirect("index")

    symbol = request.POST.get(
        "symbol",
        ""
    ).strip()

    if not symbol:
        return redirect("index")

    # =====================================
    # TWSE 最新股票資料
    # =====================================

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

    # =====================================
    # 找股票
    # =====================================

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

    # =====================================
    # 建立 Stock
    # =====================================

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

    # =====================================
    # 更新名稱
    # =====================================

    if not created:

        stock.name = stock_data.get(
            "Name",
            stock.name
        )

        stock.save()

    # =====================================
    # 歷史資料檢查
    # =====================================

    print()
    print("=" * 60)
    print(
        f"股票 {symbol} 歷史資料檢查"
    )
    print("=" * 60)

    try:

        # =================================
        # 檢查資料庫是否已有歷史資料
        # =================================

        has_history = StockPrice.objects.filter(
            stock=stock
        ).exists()

        # =================================
        # 情況 1：
        # 完全沒有歷史資料
        # =================================

        if not has_history:

            print(
                f"{symbol} 尚無歷史資料"
            )

            print(
                f"開始抓取 {symbol} 近一年歷史資料..."
            )

            success = import_stock(
                symbol
            )

            if success:

                print(
                    f"{symbol} 近一年歷史資料完成"
                )

            else:

                print(
                    f"{symbol} 歷史資料抓取失敗"
                )

        # =================================
        # 情況 2：
        # 已經有歷史資料
        # =================================

        else:

            print(
                f"{symbol} 已有歷史資料"
            )

            print(
                f"檢查是否需要更新..."
            )

            update_stock(
                symbol
            )

            print(
                f"{symbol} 資料檢查完成"
            )

    except Exception as e:

        print(
            "歷史資料更新錯誤：",
            e
        )

    print("=" * 60)

    # =====================================
    # 前往股票詳細頁
    # =====================================

    return redirect(
        "stock_detail",
        symbol=symbol
    )


# ============================================================
# 股票詳細頁
# ============================================================

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

    # 預防沒有資料時 df 未定義
    df = pd.DataFrame()

    if all_prices:

        data = []

        for price in all_prices:

            data.append({

                "date": price.date,

                "close": float(
                    price.close_price
                )

            })

        df = pd.DataFrame(
            data
        )

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

        gain = delta.clip(
            lower=0
        )

        loss = -delta.clip(
            upper=0
        )

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

    # ==================================================
    # 技術指標
    # ==================================================

    ma5_value = None
    ma20_value = None
    ma60_value = None
    rsi_value = None

    if all_prices:

        # =====================================
        # MA5
        # =====================================

        if len(all_prices) >= 5:

            ma5_value = round(

                sum(
                    float(
                        p.close_price
                    )
                    for p in all_prices[-5:]
                )
                / 5,

                2
            )

        # =====================================
        # MA20
        # =====================================

        if len(all_prices) >= 20:

            ma20_value = round(

                sum(
                    float(
                        p.close_price
                    )
                    for p in all_prices[-20:]
                )
                / 20,

                2
            )

        # =====================================
        # MA60
        # =====================================

        if len(all_prices) >= 60:

            ma60_value = round(

                sum(
                    float(
                        p.close_price
                    )
                    for p in all_prices[-60:]
                )
                / 60,

                2
            )

        # =====================================
        # 最新 RSI
        # =====================================

        if len(df) >= 15:

            latest_rsi = (
                df["RSI"].iloc[-1]
            )

            if pd.notna(
                latest_rsi
            ):

                rsi_value = round(
                    float(
                        latest_rsi
                    ),
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


# ============================================================
# 市場排名
# ============================================================

def market_ranking(request):

    csv_path = os.path.join(
        settings.BASE_DIR,
        "myapp",
        "ml",
        "output",
        "market_ranking.csv"
    )

    ranking = []
    prediction_date = None

    if os.path.exists(csv_path):

        df = pd.read_csv(
            csv_path,
            dtype={
                "symbol": str
            }
        )

        if not df.empty:

            # 股票代號固定 4 碼
            df["symbol"] = (
                df["symbol"]
                .astype(str)
                .str.zfill(4)
            )

            df["rank"] = pd.to_numeric(
                df["rank"],
                errors="coerce"
            )

            df["close"] = pd.to_numeric(
                df["close"],
                errors="coerce"
            )

            df["predicted_return_20"] = (
                pd.to_numeric(
                    df["predicted_return_20"],
                    errors="coerce"
                )
            )

            prediction_date = str(
                df["date"].iloc[0]
            )

            ranking = df.to_dict(
                "records"
            )

    return render(
        request,
        "stocks/market_ranking.html",
        {
            "ranking": ranking,
            "prediction_date": prediction_date,
        }
    )


def prediction_history(request):
    """顯示已保存的前瞻預測歷史紀錄"""

    # 取得所有有預測紀錄的日期，最新日期優先
    prediction_dates = list(
        PredictionHistory.objects
        .values_list("prediction_date", flat=True)
        .distinct()
        .order_by("-prediction_date")
    )

    # 預設顯示最新一次預測
    selected_date = request.GET.get("date")

    if prediction_dates:
        valid_dates = {
            d.isoformat() for d in prediction_dates
        }

        if selected_date not in valid_dates:
            selected_date = prediction_dates[0].isoformat()

        history = list(
            PredictionHistory.objects
            .filter(prediction_date=selected_date)
            .order_by("rank")
            .values(
                "prediction_date",
                "data_date",
                "symbol",
                "stock_name",
                "close_price",
                "predicted_return_20",
                "rank",
                "horizon",
                "model_version",
            )
        )
    else:
        selected_date = None
        history = []

    return render(
        request,
        "stocks/prediction_history.html",
        {
            "prediction_dates": prediction_dates,
            "selected_date": selected_date,
            "history": history,
        }
    )

# ============================================================
# 市場回測
# ============================================================

def market_backtest(request):

    csv_path = os.path.join(
        settings.BASE_DIR,
        "myapp",
        "ml",
        "output",
        "market_backtest.csv"
    )

    stocks = {}
    summary = {}
    performance = []

    if os.path.exists(csv_path):

        df = pd.read_csv(
            csv_path,
            dtype={
                "symbol": str
            }
        )

        if not df.empty:

            # ==================================================
            # 基本資料整理
            # ==================================================

            # 股票代號固定 4 碼
            df["symbol"] = (
                df["symbol"]
                .astype(str)
                .str.replace(
                    ".0",
                    "",
                    regex=False
                )
                .str.zfill(4)
            )

            # 日期
            df["date"] = pd.to_datetime(
                df["date"],
                errors="coerce"
            )

            # ==================================================
            # 數值欄位
            # ==================================================

            numeric_columns = [
                "rank",
                "close",
                "predicted_return_20",
                "actual_return_20",
                "prediction_error"
            ]

            for column in numeric_columns:

                if column in df.columns:

                    df[column] = pd.to_numeric(
                        df[column],
                        errors="coerce"
                    )
                    df = df.dropna(
                        subset=[
                            "date",
                            "rank",
                            "symbol",
                            "predicted_return_20",
                            "actual_return_20",
                            "prediction_error",
                        ]
                    )

            # ==================================================
            # 移除重要資料缺失
            # ==================================================

            df = df.dropna(
                subset=[
                    "date",
                    "symbol",
                    "predicted_return_20",
                    "actual_return_20"
                ]
            )

            # ==================================================
            # 整體回測摘要
            # ==================================================

            if not df.empty:

                summary = {

                    # 回測筆數
                    "samples":
                        len(df),

                    # 平均預測報酬
                    "average_predicted":
                        df[
                            "predicted_return_20"
                        ].mean(),

                    # 平均實際報酬
                    "average_actual":
                        df[
                            "actual_return_20"
                        ].mean(),

                    # 正報酬比例
                    "positive_ratio":
                        (
                            df[
                                "actual_return_20"
                            ] > 0
                        ).mean() * 100,

                    # MAE
                    "mae":
                        df[
                            "prediction_error"
                        ]
                        .abs()
                        .mean(),

                    # RMSE
                    "rmse":
                        np.sqrt(
                            (
                                df[
                                    "prediction_error"
                                ] ** 2
                            ).mean()
                        ),
                }

                # ==================================================
                # 每檔股票分開
                # 日期：新 → 舊
                # ==================================================

                for symbol, group in df.groupby(
                    "symbol"
                ):

                    group = group.sort_values(
                        "date",
                        ascending=False
                    ).copy()

                    # 日期轉成 HTML 顯示格式
                    group["date"] = (
                        group["date"]
                        .dt.strftime(
                            "%Y-%m-%d"
                        )
                    )

                    stocks[symbol] = (
                        group
                        .to_dict("records")
                    )

                # ==================================================
                # 回測績效圖表資料
                # ==================================================

                performance_df = (

                    df
                    .groupby("date")
                    .agg(

                        # 每個回測日期：
                        # 所有股票預測報酬平均
                        predicted_return=(
                            "predicted_return_20",
                            "mean"
                        ),

                        # 每個回測日期：
                        # 所有股票實際報酬平均
                        actual_return=(
                            "actual_return_20",
                            "mean"
                        )

                    )
                    .reset_index()
                )

                # ==================================================
                # 日期排序
                # 舊 → 新
                # ==================================================

                performance_df = (
                    performance_df
                    .sort_values("date")
                )

                # ==================================================
                # 累積報酬
                # ==================================================

                performance_df[
                    "cumulative_return"
                ] = (

                    (
                        1
                        +
                        performance_df[
                            "actual_return"
                        ] / 100
                    )
                    .cumprod()
                    - 1

                ) * 100

                # ==================================================
                # 日期轉字串
                # ==================================================

                performance_df["date"] = (

                    performance_df["date"]
                    .dt.strftime(
                        "%Y-%m-%d"
                    )

                )

                # ==================================================
                # NaN / inf 處理
                # ==================================================

                performance_df = (

                    performance_df
                    .replace(
                        [
                            np.inf,
                            -np.inf
                        ],
                        np.nan
                    )
                    .fillna(0)

                )

                # ==================================================
                # 傳給 HTML
                # ==================================================

                performance = (

                    performance_df
                    .to_dict("records")

                )

    # ==================================================
    # Render
    # ==================================================

    return render(
        request,
        "stocks/market_backtest.html",
        {
            "stocks": stocks,
            "summary": summary,
            "performance": performance,
        }
    )


# ============================================================
# 市場策略
# ============================================================

def market_strategy(request):
    """
    V5.7 Top-N 股票選股策略績效頁

    對應：
    - market_strategy_backtest.csv
    - market_strategy_detail.csv
    - market_strategy_summary.csv

    V5.7 不再使用累積報酬欄位。
    """


    output_dir = os.path.join(
        settings.BASE_DIR,
        "myapp",
        "ml",
        "output"
    )

    strategy_file = os.path.join(
        output_dir,
        "market_strategy_backtest.csv"
    )

    detail_file = os.path.join(
        output_dir,
        "market_strategy_detail.csv"
    )

    summary_file = os.path.join(
        output_dir,
        "market_strategy_summary.csv"
    )

    # ==========================================
    # 預設資料
    # ==========================================

    summary = {
        "top_n": 5,
        "backtest_periods": 0,
        "start_date": "",
        "end_date": "",
        "average_actual": 0,
        "average_market": 0,
        "average_excess": 0,
        "positive_return_rate": 0,
        "outperform_rate": 0,
        "direction_accuracy": 0,
        "max_drawdown": 0,
        "best_date": "",
        "best_return": 0,
        "worst_date": "",
        "worst_return": 0,
    }

    performance = []
    strategy_dates = []

    error = ""

    # ==========================================
    # 1. 讀取策略績效 CSV
    # ==========================================

    try:

        if not os.path.exists(strategy_file):
            raise FileNotFoundError(
                "找不到 market_strategy_backtest.csv"
            )

        df = pd.read_csv(strategy_file)

        required_columns = [
            "date",
            "top_n",
            "predicted_avg",
            "actual_avg",
            "market_avg",
            "excess_return",
            "positive_rate",
            "outperform_market",
            "direction_accuracy",
        ]

        missing_columns = [
            col
            for col in required_columns
            if col not in df.columns
        ]

        if missing_columns:
            raise ValueError(
                "V5.7 策略 CSV 缺少欄位："
                + ", ".join(missing_columns)
            )

        # 日期
        df["date"] = pd.to_datetime(
            df["date"],
            errors="coerce"
        )

        df = df.dropna(
            subset=["date"]
        )

        df = df.sort_values(
            "date"
        )

        # 數值欄位
        numeric_columns = [
            "top_n",
            "predicted_avg",
            "actual_avg",
            "market_avg",
            "excess_return",
            "positive_rate",
            "outperform_market",
            "direction_accuracy",
        ]

        for col in numeric_columns:
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

        # ======================================
        # 建立績效資料
        # ======================================

        for _, row in df.iterrows():

            performance.append({
                "date": row["date"].strftime("%Y-%m-%d"),

                "top_n": int(
                    row["top_n"]
                ),

                "predicted_avg": round(
                    float(row["predicted_avg"]),
                    2
                ),

                "actual_avg": round(
                    float(row["actual_avg"]),
                    2
                ),

                "market_avg": round(
                    float(row["market_avg"]),
                    2
                ),

                "excess_return": round(
                    float(row["excess_return"]),
                    2
                ),

                "positive_rate": round(
                    float(row["positive_rate"]),
                    2
                ),

                "outperform_market": int(
                    row["outperform_market"]
                ),

                "direction_accuracy": round(
                    float(row["direction_accuracy"]),
                    2
                ),
            })

        # ======================================
        # 圖表資料
        # ======================================

        chart_dates = [
            row["date"]
            for row in performance
        ]

        chart_topn = [
            row["actual_avg"]
            for row in performance
        ]

        chart_market = [
            row["market_avg"]
            for row in performance
        ]

        chart_excess = [
            row["excess_return"]
            for row in performance
        ]

    except Exception as e:

        chart_dates = []
        chart_topn = []
        chart_market = []
        chart_excess = []

        error = str(e)

    # ==========================================
    # 2. 讀取 V5.7 Summary
    # ==========================================

    try:

        if os.path.exists(summary_file):

            summary_df = pd.read_csv(
                summary_file
            )

            if not summary_df.empty:

                row = summary_df.iloc[0]

                def safe_float(
                    value,
                    default=0
                ):
                    try:
                        if pd.isna(value):
                            return default
                        return float(value)
                    except Exception:
                        return default

                def safe_int(
                    value,
                    default=0
                ):
                    try:
                        if pd.isna(value):
                            return default
                        return int(value)
                    except Exception:
                        return default

                summary["top_n"] = safe_int(
                    row.get(
                        "top_n",
                        5
                    ),
                    5
                )

                summary["backtest_periods"] = safe_int(
                    row.get(
                        "backtest_periods",
                        0
                    )
                )

                summary["start_date"] = str(
                    row.get(
                        "start_date",
                        ""
                    )
                )

                summary["end_date"] = str(
                    row.get(
                        "end_date",
                        ""
                    )
                )

                summary["average_actual"] = round(
                    safe_float(
                        row.get(
                            "average_actual",
                            0
                        )
                    ),
                    2
                )

                summary["average_market"] = round(
                    safe_float(
                        row.get(
                            "average_market",
                            0
                        )
                    ),
                    2
                )

                summary["average_excess"] = round(
                    safe_float(
                        row.get(
                            "average_excess",
                            0
                        )
                    ),
                    2
                )

                summary["positive_return_rate"] = round(
                    safe_float(
                        row.get(
                            "positive_return_rate",
                            0
                        )
                    ),
                    2
                )

                summary["outperform_rate"] = round(
                    safe_float(
                        row.get(
                            "outperform_rate",
                            0
                        )
                    ),
                    2
                )

                summary["direction_accuracy"] = round(
                    safe_float(
                        row.get(
                            "direction_accuracy",
                            0
                        )
                    ),
                    2
                )

                summary["max_drawdown"] = round(
                    safe_float(
                        row.get(
                            "max_drawdown",
                            0
                        )
                    ),
                    2
                )

                summary["best_date"] = str(
                    row.get(
                        "best_date",
                        ""
                    )
                )

                summary["best_return"] = round(
                    safe_float(
                        row.get(
                            "best_return",
                            0
                        )
                    ),
                    2
                )

                summary["worst_date"] = str(
                    row.get(
                        "worst_date",
                        ""
                    )
                )

                summary["worst_return"] = round(
                    safe_float(
                        row.get(
                            "worst_return",
                            0
                        )
                    ),
                    2
                )

    except Exception as e:

        if not error:
            error = f"Summary 讀取失敗：{e}"

    # ==========================================
    # 3. 讀取 Top-5 選股明細
    # ==========================================

    try:

        if os.path.exists(detail_file):

            detail_df = pd.read_csv(
                detail_file
            )

            if not detail_df.empty:

                required_detail_columns = [
                    "date",
                    "rank",
                    "symbol",
                    "predicted_return_20",
                    "actual_return_20",
                ]

                missing_detail = [
                    col
                    for col in required_detail_columns
                    if col not in detail_df.columns
                ]

                if missing_detail:
                    raise ValueError(
                        "Top-5 明細缺少欄位："
                        + ", ".join(missing_detail)
                    )

                detail_df["date"] = pd.to_datetime(
                    detail_df["date"],
                    errors="coerce"
                )

                detail_df["rank"] = pd.to_numeric(
                    detail_df["rank"],
                    errors="coerce"
                )

                detail_df["predicted_return_20"] = pd.to_numeric(
                    detail_df["predicted_return_20"],
                    errors="coerce"
                )

                detail_df["actual_return_20"] = pd.to_numeric(
                    detail_df["actual_return_20"],
                    errors="coerce"
                )

                detail_df = detail_df.dropna(
                    subset=[
                        "date",
                        "rank"
                    ]
                )

                # 最新回測日期
                latest_date = detail_df["date"].max()

                latest_df = detail_df[
                    detail_df["date"] == latest_date
                ].copy()

                latest_df = latest_df[
                    latest_df["rank"] <= 5
                ]

                latest_df = latest_df.sort_values(
                    "rank"
                )

                # ==================================
                # 股票名稱
                # ==================================

                try:

                    stock_map = {
                        str(stock.symbol).zfill(4): stock.name
                        for stock in Stock.objects.all()
                    }

                except Exception:

                    stock_map = {}

                for _, row in latest_df.iterrows():

                    symbol = str(
                        row["symbol"]
                    ).strip().zfill(4)

                    strategy_dates.append({

                        "rank": int(
                            row["rank"]
                        ),

                        "symbol": symbol,

                        "name": stock_map.get(
                            symbol,
                            symbol
                        ),

                        "predicted_return_20": round(
                            float(
                                row[
                                    "predicted_return_20"
                                ]
                            ),
                            2
                        ),

                        "actual_return_20": round(
                            float(
                                row[
                                    "actual_return_20"
                                ]
                            ),
                            2
                        ),
                    })

    except Exception as e:

        if not error:
            error = f"Top-5 明細讀取失敗：{e}"

    # ==========================================
    # 4. Template Context
    # ==========================================

    context = {

        "summary": summary,

        "performance": performance,

        "strategy_dates": strategy_dates,

        "chart_dates": chart_dates,

        "chart_topn": chart_topn,

        "chart_market": chart_market,

        "chart_excess": chart_excess,

        "error": error,
    }

    return render(
        request,
        "stocks/market_strategy.html",
        context
    )


def prediction_performance(request):
    """
    V6.2：前瞻預測績效儀表板
    只統計已完成實際報酬評估的紀錄。
    """
    records = list(
        PredictionHistory.objects
        .filter(
            evaluated_at__isnull=False,
            actual_return_20__isnull=False,
        )
        .order_by("-prediction_date", "rank")
    )

    total_evaluated = len(records)

    # 計算預測方向準確率與平均絕對誤差
    valid_direction = [
        row for row in records
        if row.direction_correct is not None
    ]

    direction_accuracy = None
    if valid_direction:
        direction_accuracy = (
            sum(bool(row.direction_correct) for row in valid_direction)
            / len(valid_direction) * 100
        )

    errors = []
    for row in records:
        if (
            row.predicted_return_20 is not None
            and row.actual_return_20 is not None
        ):
            errors.append(
                abs(
                    float(row.predicted_return_20)
                    - float(row.actual_return_20)
                )
            )

    mae = sum(errors) / len(errors) if errors else None

    # 等待評估的紀錄
    pending_count = PredictionHistory.objects.filter(
        evaluated_at__isnull=True
    ).count()

    # 依預測批次統計 Top 5 實際報酬
    batch_dates = sorted(
        {row.prediction_date for row in records},
        reverse=True,
    )

    batch_performance = []

    for batch_date in batch_dates:
        batch_records = [
            row for row in records
            if row.prediction_date == batch_date
        ]

        top5 = sorted(
            batch_records,
            key=lambda row: (
                row.rank if row.rank is not None else 999999
            ),
        )[:5]

        if not top5:
            continue

        top5_returns = [
            float(row.actual_return_20)
            for row in top5
            if row.actual_return_20 is not None
        ]

        all_returns = [
            float(row.actual_return_20)
            for row in batch_records
            if row.actual_return_20 is not None
        ]

        batch_performance.append({
            "prediction_date": batch_date,
            "top5_count": len(top5_returns),
            "top5_actual_avg": (
                sum(top5_returns) / len(top5_returns)
                if top5_returns else None
            ),
            "universe_actual_avg": (
                sum(all_returns) / len(all_returns)
                if all_returns else None
            ),
            "top5_stocks": top5,
        })
    # 最近 30 筆預測紀錄，包含尚未完成評估的資料
    recent_records = list(
        PredictionHistory.objects
        .order_by("-prediction_date", "rank")[:30]
    )
    context = {
        "total_evaluated": total_evaluated,
        "pending_count": pending_count,
        "direction_count": len(valid_direction),
        "direction_accuracy": direction_accuracy,
        "mae": mae,
        "batch_performance": batch_performance,
        "recent_records": recent_records,
    }

    return render(
        request,
        "stocks/prediction_performance.html",
        context,
    )


# ============================================================
# V6.2：歷史預測頁面執行實驗程式
# ============================================================


def run_forward_prediction(request):
    """執行前瞻預測，避免重複訓練。"""

    MODEL_VERSION = "V5.7-FORWARD"
    LOCK_KEY = "stock_ai_forward_prediction_running"

    # 僅允許由頁面 POST 表單啟動
    if request.method != "POST":
        return redirect("prediction_history")

    # 防止執行期間重複啟動
    if not cache.add(LOCK_KEY, True, timeout=1800):
        messages.warning(
            request,
            "前瞻預測正在執行中，請勿重複點擊。"
        )
        return redirect("prediction_history")

    try:
        # 取得目前資料庫最新的股價日期
        latest_data_date = (
            StockPrice.objects
            .order_by("-date")
            .values_list("date", flat=True)
            .first()
        )

        if latest_data_date is None:
            messages.error(
                request,
                "找不到股價資料，請先更新股票歷史資料。"
            )
            return redirect("prediction_history")

        # 如果相同資料日期已有預測，就不再執行
        already_predicted = PredictionHistory.objects.filter(
            model_version=MODEL_VERSION,
            data_date=latest_data_date
        ).exists()

        if already_predicted:
            messages.warning(
                request,
                f"資料日期 {latest_data_date} 已有前瞻預測紀錄，"
                "為避免重複訓練，本次未執行。"
            )
            return redirect("prediction_history")

        # 執行預測程式
        script_path = os.path.join(
            settings.BASE_DIR,
            "myapp",
            "ml",
            "forward_prediction.py"
        )

        result = subprocess.run(
            [sys.executable, script_path],
            cwd=str(settings.BASE_DIR),
            capture_output=True,
            text=True,
            timeout=1800
        )

        if result.returncode != 0:
            error_text = (result.stderr or result.stdout or "").strip()
            messages.error(
                request,
                "前瞻預測執行失敗："
                + (error_text[-800:] if error_text else "請檢查終端機錯誤訊息。")
            )
            return redirect("prediction_history")

        # 確認資料庫是否真的寫入預測紀錄
        saved_count = PredictionHistory.objects.filter(
            model_version=MODEL_VERSION,
            data_date=latest_data_date
        ).count()

        if saved_count > 0:
            messages.success(
                request,
                f"前瞻預測完成！資料日期：{latest_data_date}，"
                f"已確認 {saved_count} 筆預測紀錄。"
            )
        else:
            messages.warning(
                request,
                "程式執行結束，但未找到對應日期的資料庫紀錄，"
                "請檢查預測程式輸出。"
            )

    except subprocess.TimeoutExpired:
        messages.error(
            request,
            "前瞻預測執行超過 30 分鐘，請檢查程式是否仍在運作。"
        )

    except Exception as e:
        messages.error(
            request,
            f"前瞻預測發生錯誤：{e}"
        )

    finally:
        # 無論成功或失敗，都解除執行鎖定
        cache.delete(LOCK_KEY)

    return redirect("prediction_history")




def run_forward_evaluation(request):

    MODEL_VERSION = "V5.7-FORWARD"
    LOCK_KEY = "stock_ai_forward_evaluation_running"

    if request.method != "POST":
        return redirect("prediction_history")

    # 防止重複點擊
    if not cache.add(LOCK_KEY, True, timeout=1800):
        messages.warning(
            request,
            "前瞻預測績效評估正在執行中，請勿重複點擊。"
        )
        return redirect("prediction_history")

    try:
        records = PredictionHistory.objects.filter(
            model_version=MODEL_VERSION
        )

        # 執行前：統計尚未完成評估的紀錄
        pending_before = records.filter(
            evaluated_at__isnull=True
        ).count()

        evaluated_before = records.filter(
            evaluated_at__isnull=False
        ).count()

        script_path = os.path.join(
            settings.BASE_DIR,
            "myapp",
            "ml",
            "evaluate_forward_predictions.py"
        )

        result = subprocess.run(
            [sys.executable, script_path],
            cwd=str(settings.BASE_DIR),
            capture_output=True,
            text=True,
            timeout=1800
        )

        if result.returncode != 0:
            error_text = (
                result.stderr or result.stdout or ""
            ).strip()

            messages.error(
                request,
                "績效評估執行失敗：" +
                (
                    error_text[-800:]
                    if error_text
                    else "請檢查終端機錯誤訊息。"
                )
            )
            return redirect("prediction_history")

        # 執行後：重新統計資料庫紀錄
        records = PredictionHistory.objects.filter(
            model_version=MODEL_VERSION
        )

        evaluated_after = records.filter(
            evaluated_at__isnull=False
        ).count()

        pending_after = records.filter(
            evaluated_at__isnull=True
        ).count()

        newly_evaluated = max(
            0, evaluated_after - evaluated_before
        )

        if newly_evaluated > 0:
            messages.success(
                request,
                f"績效評估完成！本次新增評估 "
                f"{newly_evaluated} 筆；"
                f"尚未完成評估 {pending_after} 筆。"
            )
        elif pending_before == 0:
            messages.info(
                request,
                "績效評估完成，目前沒有尚未完成評估的紀錄。"
            )
        else:
            messages.info(
                request,
                f"評估程式已執行完畢，本次新增評估 0 筆；"
                f"尚未完成評估 {pending_after} 筆。"
                "這些紀錄可能尚未滿 20 個交易日，"
                "或需檢查評估程式的執行條件。"
            )

    except subprocess.TimeoutExpired:
        messages.error(
            request,
            "績效評估執行超過 30 分鐘，請檢查程式是否仍在運作。"
        )

    except Exception as e:
        messages.error(
            request,
            f"績效評估發生錯誤：{e}"
        )

    finally:
        cache.delete(LOCK_KEY)

    return redirect("prediction_history")

