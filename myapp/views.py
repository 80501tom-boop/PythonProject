import json
import os

import numpy as np
import pandas as pd
import requests

from datetime import datetime

from django.conf import settings
from django.core.paginator import Paginator
from django.shortcuts import render, redirect

from .models import Stock, StockPrice

from scripts.import_history import (
    import_stock,
    update_stock,
    update_all_stocks
)


# ============================================================
# 首頁
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
            print(
                f"網站啟動：開始更新股票資料 {today}"
            )
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

            print(
                f"股票資料更新失敗：{e}"
            )

    # =====================================
    # 股票搜尋
    # =====================================

    query = request.GET.get(
        "q",
        ""
    ).strip()

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

    context = {
        "stocks": stocks,
        "query": query,
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
                            "predicted_avg",
                            "actual_avg",
                            "market_avg",
                            "excess_return",
                            "cumulative_strategy",
                            "cumulative_market",
                            "cumulative_excess",
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
    V5.5 Top-N 策略績效頁面

    功能：
    1. 讀取 Top-N 策略回測結果
    2. 顯示 Top-N 累積報酬
    3. 顯示全市場累積報酬
    4. 顯示超額報酬
    5. 顯示每一期 Top-N 選股
    6. 顯示股票代號與股票名稱
    """

    import os
    import pandas as pd

    # =====================================================
    # CSV 路徑
    # =====================================================

    strategy_path = os.path.join(
        settings.BASE_DIR,
        "myapp",
        "ml",
        "output",
        "market_strategy_backtest.csv"
    )

    detail_path = os.path.join(
        settings.BASE_DIR,
        "myapp",
        "ml",
        "output",
        "market_strategy_detail.csv"
    )

    # =====================================================
    # 檢查檔案
    # =====================================================

    if not os.path.exists(strategy_path):
        return render(
            request,
            "stocks/market_strategy.html",
            {
                "error": "尚未產生市場策略回測資料。",
                "summary": {},
                "performance": [],
                "strategy_dates": [],
            }
        )

    # =====================================================
    # 讀取策略績效
    # =====================================================

    df = pd.read_csv(strategy_path)

    if df.empty:
        return render(
            request,
            "stocks/market_strategy.html",
            {
                "error": "市場策略回測資料為空。",
                "summary": {},
                "performance": [],
                "strategy_dates": [],
            }
        )

    # =====================================================
    # 日期
    # =====================================================

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

    # =====================================================
    # 數值欄位
    # =====================================================

    numeric_columns = [
        "actual_avg",
        "market_avg",
        "cumulative_strategy",
        "cumulative_market",
        "cumulative_excess",
    ]

    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(
                df[column],
                errors="coerce"
            )

    # =====================================================
    # Top-N
    # =====================================================

    if "top_n" in df.columns:
        top_n = int(
            pd.to_numeric(
                df["top_n"],
                errors="coerce"
            ).dropna().iloc[0]
        )
    else:
        top_n = 5

    # =====================================================
    # Summary
    #
    # 注意：
    # Template 直接使用這組欄位名稱
    # =====================================================

    summary = {
        "top_n": top_n,

        "periods": len(df),

        "start_date": (
            df["date"].min().strftime("%Y-%m-%d")
            if not df.empty
            else ""
        ),

        "end_date": (
            df["date"].max().strftime("%Y-%m-%d")
            if not df.empty
            else ""
        ),

        # Top-N 累積報酬
        "strategy_cumulative": float(
            df["cumulative_strategy"].iloc[-1]
        ),

        # 全市場累積報酬
        "market_cumulative": float(
            df["cumulative_market"].iloc[-1]
        ),

        # 超額報酬
        "excess_cumulative": float(
            df["cumulative_excess"].iloc[-1]
        ),

        "average_strategy": float(
            df["actual_avg"].mean()
        ),

        "average_market": float(
            df["market_avg"].mean()
        ),

        "positive_ratio": float(
            (
                df["actual_avg"] > 0
            ).mean() * 100
        ),

        "outperform_ratio": float(
            (
                df["actual_avg"]
                >
                df["market_avg"]
            ).mean() * 100
        ),
    }

    # =====================================================
    # Performance
    #
    # 給前端圖表使用
    # =====================================================

    performance = []

    for _, row in df.iterrows():
        performance.append({
            "date": row["date"].strftime("%Y-%m-%d"),

            "top_n": int(row["top_n"]),

            "predicted_avg": float(row["predicted_avg"]),
            "actual_avg": float(row["actual_avg"]),
            "market_avg": float(row["market_avg"]),
            "excess_return": float(row["excess_return"]),

            "cumulative_strategy": float(
                row["cumulative_strategy"]
            ),

            "cumulative_market": float(
                row["cumulative_market"]
            ),

            "cumulative_excess": float(
                row["cumulative_excess"]
            ),
        })

    # =====================================================
    # Top-N 每期選股
    # =====================================================

    strategy_dates = []

    if os.path.exists(detail_path):

        detail_df = pd.read_csv(
            detail_path
        )

        if not detail_df.empty:

            # -----------------------------
            # 日期
            # -----------------------------

            detail_df["date"] = pd.to_datetime(
                detail_df["date"],
                errors="coerce"
            )

            detail_df = detail_df.dropna(
                subset=["date"]
            )

            # -----------------------------
            # 股票代號
            # -----------------------------

            detail_df["symbol"] = (
                detail_df["symbol"]
                .astype(str)
                .str.replace(
                    ".0",
                    "",
                    regex=False
                )
                .str.zfill(4)
            )

            # -----------------------------
            # 數值
            # -----------------------------

            for column in [
                "predicted_return_20",
                "actual_return_20",
            ]:
                if column in detail_df.columns:

                    detail_df[column] = pd.to_numeric(
                        detail_df[column],
                        errors="coerce"
                    )

            # =================================================
            # 建立股票名稱對照
            # =================================================

            stock_map = {
                str(stock.symbol).zfill(4): stock.name
                for stock in Stock.objects.all()
            }

            # =================================================
            # 如果 CSV 沒有 name
            # 就從 Stock Model 補上
            # =================================================

            detail_df["name"] = (
                detail_df["symbol"]
                .map(stock_map)
                .fillna("")
            )

            # =================================================
            # 依日期處理
            # =================================================

            detail_df = detail_df.sort_values(
                [
                    "date",
                    "predicted_return_20"
                ],
                ascending=[
                    True,
                    False
                ]
            )

            for date, group in detail_df.groupby(
                "date"
            ):

                top_df = group.head(
                    top_n
                )

                stocks = []

                for rank, (_, row) in enumerate(
                    top_df.iterrows(),
                    start=1
                ):

                    stocks.append({
                        "rank": rank,

                        "symbol": str(
                            row["symbol"]
                        ).zfill(4),

                        "name": row["name"],

                        "predicted_return_20": (
                            float(
                                row["predicted_return_20"]
                            )
                            if pd.notna(
                                row["predicted_return_20"]
                            )
                            else None
                        ),

                        "actual_return_20": (
                            float(
                                row["actual_return_20"]
                            )
                            if pd.notna(
                                row["actual_return_20"]
                            )
                            else None
                        ),
                    })

                strategy_dates.append({
                    "date": date.strftime(
                        "%Y-%m-%d"
                    ),

                    "stocks": stocks,
                })

    # =====================================================
    # Django Template
    # =====================================================

    context = {
        "summary": summary,

        "performance": performance,

        "strategy_dates": strategy_dates,

        "error": "",
    }

    return render(
        request,
        "stocks/market_strategy.html",
        context
    )
