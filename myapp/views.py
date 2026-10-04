import json
from django.core.paginator import Paginator
from django.shortcuts import render,redirect

from .models import Stock

import pandas as pd
import requests
from scripts.import_history import (
    import_stock,
    update_all_stocks
)

import os
from django.conf import settings

import numpy as np

# from datetime import date
from datetime import datetime
def index(request):

    # =====================================
    # 每天第一次開啟網站時，自動更新股票資料
    # =====================================

    today = datetime.today().date()

    if request.session.get("stock_data_update_date") != str(today):

        try:

            print()
            print("=" * 60)
            print(f"網站啟動：開始更新股票資料 {today}")
            print("=" * 60)

            update_all_stocks()

            # 更新成功後才記錄日期
            request.session["stock_data_update_date"] = str(today)

            print("=" * 60)
            print("股票資料更新完成")
            print("=" * 60)

        except Exception as e:

            print(
                f"股票資料更新失敗：{e}"
            )

    # =====================================
    # 以下接你原本 index() 的程式
    # =====================================

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

def add_stock(request):

    if request.method != "POST":
        return redirect("index")

    symbol = request.POST.get(
        "symbol",
        ""
    ).strip()

    if not symbol:
        return redirect("index")


    # =================================
    # TWSE 最新股票資料
    # =================================

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


    # =================================
    # 找股票
    # =================================

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


    # =================================
    # 建立 Stock
    # =================================

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


    # =================================
    # 更新名稱
    # =================================

    if not created:

        stock.name = stock_data.get(
            "Name",
            stock.name
        )

        stock.save()


    # =================================
    # 抓近一年歷史資料
    # =================================

    print()
    print(
        f"開始抓取 {symbol} "
        f"近一年歷史資料..."
    )


    try:

        success = import_stock(
            symbol
        )

        if success:

            print(
                f"{symbol} 歷史資料完成"
            )

    except Exception as e:

        print(
            "歷史資料匯入錯誤：",
            e
        )


    # =================================
    # 前往股票詳細頁
    # =================================

    return redirect(
        "stock_detail",
        symbol=symbol
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
        # RSI 14
        # ==================================================

        delta = df["close"].diff()

        gain = delta.clip(lower=0)

        loss = -delta.clip(upper=0)

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

    ma5_value = None
    ma20_value = None
    ma60_value = None
    rsi_value = None
    
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
        # =========================
        # 最新 RSI
        # =========================

        if len(df) >= 15:

            latest_rsi = df["RSI"].iloc[-1]

            if pd.notna(latest_rsi):

                rsi_value = round(
                    float(latest_rsi),
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

            df["predicted_return_20"] = pd.to_numeric(
                df["predicted_return_20"],
                errors="coerce"
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
                .str.replace(".0", "", regex=False)
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
                    #
                    # 例如：
                    # 0.60 → 60%
                    #
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
    
def market_strategy(request):

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

    summary = {}
    performance = []
    strategy_dates = []

    # =====================================
    # 讀取策略績效 CSV
    # =====================================

    if os.path.exists(strategy_path):

        df = pd.read_csv(
            strategy_path
        )

        if not df.empty:

            # -----------------------------
            # 日期
            # -----------------------------

            if "date" in df.columns:
                df["date"] = pd.to_datetime(
                    df["date"],
                    errors="coerce"
                )

            # -----------------------------
            # 數值欄位
            # -----------------------------

            numeric_columns = [
                "top_n",
                "predicted_avg",
                "actual_avg",
                "market_avg",
                "excess_return",
                "cumulative_strategy",
                "cumulative_market",
            ]

            for column in numeric_columns:

                if column in df.columns:

                    df[column] = pd.to_numeric(
                        df[column],
                        errors="coerce"
                    )

            # -----------------------------
            # 移除無效資料
            # -----------------------------

            df = df.dropna(
                subset=[
                    "date",
                    "actual_avg",
                    "market_avg"
                ]
            )

            if not df.empty:

                # =============================
                # 排序
                # =============================

                df = df.sort_values(
                    "date"
                ).reset_index(
                    drop=True
                )

                # =============================
                # 回測期間
                # =============================

                start_date = df["date"].min()
                end_date = df["date"].max()

                # =============================
                # Summary
                # =============================

                summary = {

                    "top_n":
                        int(
                            df["top_n"].iloc[0]
                        )
                        if "top_n" in df.columns
                        else 5,

                    "periods":
                        len(df),

                    "start_date":
                        start_date.strftime(
                            "%Y-%m-%d"
                        ),

                    "end_date":
                        end_date.strftime(
                            "%Y-%m-%d"
                        ),

                    "cumulative_strategy":
                        float(
                            df[
                                "cumulative_strategy"
                            ].iloc[-1]
                        )
                        if "cumulative_strategy"
                        in df.columns
                        else 0,

                    "cumulative_market":
                        float(
                            df[
                                "cumulative_market"
                            ].iloc[-1]
                        )
                        if "cumulative_market"
                        in df.columns
                        else 0,
                }

                # =============================
                # 超額報酬
                # =============================

                summary["excess_return"] = (
                    summary["cumulative_strategy"]
                    -
                    summary["cumulative_market"]
                )

                # =============================
                # 策略平均報酬
                # =============================

                summary["average_strategy"] = float(
                    df["actual_avg"].mean()
                )

                summary["average_market"] = float(
                    df["market_avg"].mean()
                )

                # =============================
                # 策略勝率
                # =============================

                summary["positive_ratio"] = (
                    (
                        df["actual_avg"] > 0
                    ).mean()
                    * 100
                )

                # =============================
                # 超越大盤比例
                # =============================

                summary["outperform_ratio"] = (
                    (
                        df["actual_avg"]
                        >
                        df["market_avg"]
                    ).mean()
                    * 100
                )

                # =============================
                # 表格資料
                # =============================

                display_df = df.copy()

                display_df["date"] = (
                    display_df["date"]
                    .dt.strftime(
                        "%Y-%m-%d"
                    )
                )

                display_df = (
                    display_df
                    .replace(
                        [np.inf, -np.inf],
                        np.nan
                    )
                    .fillna(0)
                )

                performance = (
                    display_df
                    .to_dict("records")
                )

    # =====================================
    # 讀取 Top-N 明細
    # =====================================

    if os.path.exists(detail_path):

        detail_df = pd.read_csv(
            detail_path,
            dtype={
                "symbol": str
            }
        )

        if not detail_df.empty:

            # -----------------------------
            # 股票代號
            # -----------------------------

            if "symbol" in detail_df.columns:

                detail_df["symbol"] = (
                    detail_df["symbol"]
                    .astype(str)
                    .str.strip()
                    .str.replace(
                        ".0",
                        "",
                        regex=False
                    )
                    .str.zfill(4)
                )

            # -----------------------------
            # 日期
            # -----------------------------

            detail_df["date"] = pd.to_datetime(
                detail_df["date"],
                errors="coerce"
            )

            # -----------------------------
            # 數值欄位
            # -----------------------------

            numeric_columns = [
                "rank",
                "predicted_return_20",
                "actual_return_20",
                "model_rank",
                "close",
            ]

            for column in numeric_columns:

                if column in detail_df.columns:

                    detail_df[column] = pd.to_numeric(
                        detail_df[column],
                        errors="coerce"
                    )

            detail_df = detail_df.dropna(
                subset=[
                    "date",
                    "symbol"
                ]
            )

            # =============================
            # 依日期建立 Top 5
            # =============================

            if not detail_df.empty:

                detail_df = (
                    detail_df
                    .sort_values(
                        [
                            "date",
                            "rank"
                        ]
                    )
                )

                for date, group in detail_df.groupby(
                    "date",
                    sort=False
                ):

                    group = group.copy()

                    group["date"] = (
                        group["date"]
                        .dt.strftime(
                            "%Y-%m-%d"
                        )
                    )

                    # NaN / inf 處理
                    group = (
                        group
                        .replace(
                            [
                                np.inf,
                                -np.inf
                            ],
                            np.nan
                        )
                        .fillna("")
                    )

                    strategy_dates.append({
                        "date": group["date"].iloc[0],
                        "stocks":
                            group.to_dict(
                                "records"
                            )
                    })

                # 最新日期放前面
                strategy_dates.reverse()

    # =====================================
    # Render
    # =====================================

    return render(
        request,
        "stocks/market_strategy.html",
        {
            "summary": summary,
            "performance": performance,
            "strategy_dates": strategy_dates,
        }
    )