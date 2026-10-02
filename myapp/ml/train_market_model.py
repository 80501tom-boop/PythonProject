# -*- coding: utf-8 -*-

"""
V4.1 AI 全市場股票排名

功能：
1. 取得股票歷史資料
2. 建立技術指標
3. 建立未來 20 交易日報酬
4. LightGBM 訓練
5. 預測每支股票未來 20 日報酬
6. 依預測報酬率進行全市場排名
7. 顯示 Top 5
8. 匯出 CSV
"""

import os
import sys

import django
import pandas as pd
import numpy as np
import lightgbm as lgb

from sklearn.metrics import mean_squared_error, mean_absolute_error


# =========================================================
# Django 設定
# =========================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

sys.path.append(BASE_DIR)

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "PythonProject.settings"
)

django.setup()

from myapp.models import Stock, StockPrice


# =========================================================
# 設定
# =========================================================

LOOK_FORWARD = 20

MIN_DATA_LENGTH = 120

TOP_N = 5

FEATURE_COLUMNS = [
    "return_1",
    "return_5",
    "return_20",
    "ma5_ratio",
    "ma20_ratio",
    "ma60_ratio",
    "rsi",
    "volume_change",
    "volume_ratio",
    "volatility_20",
]


# =========================================================
# 取得股票資料
# =========================================================

def get_stock_data(stock):

    queryset = (
        StockPrice.objects
        .filter(stock=stock)
        .order_by("date")
        .values(
            "date",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
        )
    )

    df = pd.DataFrame(
        list(queryset)
    )

    if df.empty:
        return df

    # -----------------------------------------------------
    # 欄位重新命名
    # -----------------------------------------------------

    df = df.rename(
        columns={
            "open_price": "open",
            "high_price": "high",
            "low_price": "low",
            "close_price": "close",
        }
    )

    # -----------------------------------------------------
    # Decimal -> float
    # -----------------------------------------------------

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]

    for column in numeric_columns:

        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        )

    df = df.dropna(
        subset=numeric_columns
    )

    df["date"] = pd.to_datetime(
        df["date"]
    )

    return df


# =========================================================
# RSI
# =========================================================

def calculate_rsi(
    series,
    period=14
):

    delta = series.diff()

    gain = delta.clip(
        lower=0
    )

    loss = -delta.clip(
        upper=0
    )

    avg_gain = gain.rolling(
        period
    ).mean()

    avg_loss = loss.rolling(
        period
    ).mean()

    rs = (
        avg_gain /
        avg_loss.replace(
            0,
            np.nan
        )
    )

    rsi = (
        100 -
        100 / (1 + rs)
    )

    return rsi


# =========================================================
# 建立特徵
# =========================================================

def create_features(df):

    df = df.copy()

    # -----------------------------------------------------
    # 報酬率
    # -----------------------------------------------------

    df["return_1"] = (
        df["close"]
        .pct_change(1)
    )

    df["return_5"] = (
        df["close"]
        .pct_change(5)
    )

    df["return_20"] = (
        df["close"]
        .pct_change(20)
    )

    # -----------------------------------------------------
    # 移動平均
    # -----------------------------------------------------

    df["ma5"] = (
        df["close"]
        .rolling(5)
        .mean()
    )

    df["ma20"] = (
        df["close"]
        .rolling(20)
        .mean()
    )

    df["ma60"] = (
        df["close"]
        .rolling(60)
        .mean()
    )

    # -----------------------------------------------------
    # MA 比率
    # -----------------------------------------------------

    df["ma5_ratio"] = (
        df["close"] /
        df["ma5"] - 1
    )

    df["ma20_ratio"] = (
        df["close"] /
        df["ma20"] - 1
    )

    df["ma60_ratio"] = (
        df["close"] /
        df["ma60"] - 1
    )

    # -----------------------------------------------------
    # RSI
    # -----------------------------------------------------

    df["rsi"] = calculate_rsi(
        df["close"],
        14
    )

    # -----------------------------------------------------
    # 成交量變化
    # -----------------------------------------------------

    df["volume_change"] = (
        df["volume"]
        .pct_change(1)
    )

    # -----------------------------------------------------
    # 成交量比例
    # -----------------------------------------------------

    volume_ma20 = (
        df["volume"]
        .rolling(20)
        .mean()
    )

    df["volume_ratio"] = (
        df["volume"] /
        volume_ma20
    )

    # -----------------------------------------------------
    # 20 日波動率
    # -----------------------------------------------------

    df["volatility_20"] = (
        df["return_1"]
        .rolling(20)
        .std()
    )

    # -----------------------------------------------------
    # 未來 20 交易日報酬
    # -----------------------------------------------------

    df["future_return_20"] = (
        df["close"].shift(
            -LOOK_FORWARD
        )
        / df["close"]
        - 1
    )

    return df


# =========================================================
# 建立全市場資料
# =========================================================

def build_market_dataset():

    stocks = (
        Stock.objects
        .all()
        .order_by("symbol")
    )

    total = stocks.count()

    print(
        f"Total stocks: {total}"
    )

    market_data = []

    for index, stock in enumerate(
        stocks,
        start=1
    ):

        print(
            f"[{index}/{total}] "
            f"{stock.symbol} "
            f"{stock.name}"
        )

        df = get_stock_data(
            stock
        )

        if df.empty:

            print(
                "  -> No data"
            )

            continue

        if len(df) < MIN_DATA_LENGTH:

            print(
                f"  -> Skip: "
                f"{len(df)} rows"
            )

            continue

        df = create_features(
            df
        )

        df["symbol"] = (
            stock.symbol
        )

        df["stock_id"] = (
            stock.id
        )

        market_data.append(
            df
        )

    if not market_data:

        return pd.DataFrame()

    market_df = pd.concat(
        market_data,
        ignore_index=True
    )

    return market_df


# =========================================================
# 訓練模型
# =========================================================

def train_model(df):

    print()
    print(
        "Preparing dataset..."
    )

    train_df = df.dropna(
        subset=
        FEATURE_COLUMNS +
        ["future_return_20"]
    ).copy()

    train_df = train_df.sort_values(
        "date"
    ).reset_index(
        drop=True
    )

    print(
        f"Dataset size: "
        f"{len(train_df)}"
    )

    if len(train_df) < 100:

        raise ValueError(
            "Training dataset too small."
        )

    # -----------------------------------------------------
    # 時間切分
    # -----------------------------------------------------

    split_date = (
        train_df["date"]
        .quantile(0.8)
    )

    train_data = train_df[
        train_df["date"] <= split_date
    ]

    valid_data = train_df[
        train_df["date"] > split_date
    ]

    X_train = train_data[
        FEATURE_COLUMNS
    ]

    y_train = train_data[
        "future_return_20"
    ]

    X_valid = valid_data[
        FEATURE_COLUMNS
    ]

    y_valid = valid_data[
        "future_return_20"
    ]

    print()
    print(
        f"Training: {len(X_train)}"
    )

    print(
        f"Validation: {len(X_valid)}"
    )

    # -----------------------------------------------------
    # LightGBM
    # -----------------------------------------------------

    model = lgb.LGBMRegressor(

        objective="regression",

        n_estimators=500,

        learning_rate=0.03,

        num_leaves=31,

        max_depth=-1,

        subsample=0.8,

        colsample_bytree=0.8,

        random_state=42,

        n_jobs=-1
    )

    # -----------------------------------------------------
    # 訓練
    # -----------------------------------------------------

    model.fit(

        X_train,

        y_train,

        eval_set=[
            (
                X_valid,
                y_valid
            )
        ],

        callbacks=[
            lgb.early_stopping(
                50
            )
        ]
    )

    # -----------------------------------------------------
    # Validation
    # -----------------------------------------------------

    prediction = model.predict(
        X_valid
    )

    rmse = np.sqrt(
        mean_squared_error(
            y_valid,
            prediction
        )
    )

    mae = mean_absolute_error(
        y_valid,
        prediction
    )

    print()
    print(
        "=========================="
    )

    print(
        "LightGBM V4.1"
    )

    print(
        "=========================="
    )

    print(
        f"Validation RMSE: "
        f"{rmse:.6f}"
    )

    print(
        f"Validation MAE : "
        f"{mae:.6f}"
    )

    # -----------------------------------------------------
    # Feature Importance
    # -----------------------------------------------------

    importance = pd.DataFrame({

        "feature":
            FEATURE_COLUMNS,

        "importance":
            model.feature_importances_

    })

    importance = (
        importance
        .sort_values(
            "importance",
            ascending=False
        )
    )

    print()
    print(
        "Feature Importance"
    )

    print(
        importance.to_string(
            index=False
        )
    )

    return model


# =========================================================
# 最新預測
# =========================================================

def predict_latest(
    model,
    market_df
):

    print()
    print(
        "=========================="
    )

    print(
        "V4.1 Market Prediction"
    )

    print(
        "=========================="
    )

    prediction_data = []

    # -----------------------------------------------------
    # 每支股票分開處理
    # -----------------------------------------------------

    for symbol, stock_df in (
        market_df.groupby("symbol")
    ):

        stock_df = (
            stock_df
            .sort_values("date")
            .copy()
        )

        # -------------------------------------------------
        # 確保模型特徵都是數值
        # -------------------------------------------------

        for column in FEATURE_COLUMNS:

            stock_df[column] = pd.to_numeric(
                stock_df[column],
                errors="coerce"
            )

        # -------------------------------------------------
        # 找出特徵完整的資料
        # -------------------------------------------------

        valid_df = stock_df.dropna(
            subset=FEATURE_COLUMNS
        )

        if valid_df.empty:

            print(
                f"  -> Skip {symbol}: "
                f"no valid feature data"
            )

            continue

        # -------------------------------------------------
        # 最新一筆資料
        # -------------------------------------------------

        latest = valid_df.iloc[-1]

        # -------------------------------------------------
        # 建立預測資料
        # -------------------------------------------------

        X_latest = pd.DataFrame(
            [
                [
                    float(
                        latest[column]
                    )
                    for column in FEATURE_COLUMNS
                ]
            ],
            columns=FEATURE_COLUMNS
        )

        # -------------------------------------------------
        # LightGBM 預測
        # -------------------------------------------------

        predicted_return = model.predict(
            X_latest
        )[0]

        prediction_data.append({

            "symbol":
                symbol,

            "date":
                latest["date"],

            "close":
                float(
                    latest["close"]
                ),

            "predicted_return_20":
                float(
                    predicted_return
                )
        })

    # -----------------------------------------------------
    # 建立結果
    # -----------------------------------------------------

    result = pd.DataFrame(
        prediction_data
    )

    if result.empty:

        print(
            "No prediction result."
        )

        return result

    # -----------------------------------------------------
    # 最新日期
    # -----------------------------------------------------

    latest_date = result[
        "date"
    ].max()

    print(
        f"Date: "
        f"{latest_date.strftime('%Y-%m-%d')}"
    )

    # -----------------------------------------------------
    # 預測報酬排序
    # -----------------------------------------------------

    result = result.sort_values(
        "predicted_return_20",
        ascending=False
    ).reset_index(
        drop=True
    )

    # -----------------------------------------------------
    # Rank
    # -----------------------------------------------------

    result["rank"] = (
        result.index + 1
    )

    # -----------------------------------------------------
    # Top N
    # -----------------------------------------------------

    top_result = result.head(
        TOP_N
    )

    # =====================================================
    # 完整排名
    # =====================================================

    print()
    print(
        "=========================================="
    )

    print(
        "AI 全市場股票排名"
    )

    print(
        "=========================================="
    )

    print(
        f"{'Rank':<8}"
        f"{'Symbol':<10}"
        f"{'Close':>12}"
        f"{'Predicted Return':>20}"
    )

    print(
        "-" * 50
    )

    for _, row in result.iterrows():

        print(

            f"{int(row['rank']):<8}"

            f"{row['symbol']:<10}"

            f"{row['close']:>12.2f}"

            f"{row['predicted_return_20'] * 100:>18.2f}%"
        )

    # =====================================================
    # Top N
    # =====================================================

    print()
    print(
        "=========================================="
    )

    print(
        f"Top {TOP_N}"
    )

    print(
        "=========================================="
    )

    for _, row in top_result.iterrows():

        print(

            f"Rank {int(row['rank'])} | "

            f"{row['symbol']} | "

            f"{row['predicted_return_20'] * 100:+.2f}%"
        )

    return result


# =========================================================
# 匯出排名結果
# =========================================================

def save_ranking_csv(
    result
):

    if result.empty:
        return

    output_dir = os.path.join(
        BASE_DIR,
        "myapp",
        "ml",
        "output"
    )

    os.makedirs(
        output_dir,
        exist_ok=True
    )

    output_file = os.path.join(
        output_dir,
        "market_ranking.csv"
    )

    export_df = result[
        [
            "rank",
            "symbol",
            "date",
            "close",
            "predicted_return_20"
        ]
    ].copy()

    # -----------------------------------------------------
    # 股票代號固定為 4 碼
    # -----------------------------------------------------

    export_df["symbol"] = (
        export_df["symbol"]
        .astype(str)
        .str.zfill(4)
    )

    # -----------------------------------------------------
    # 預測報酬率轉成百分比
    # -----------------------------------------------------

    export_df["predicted_return_20"] = (
        export_df[
            "predicted_return_20"
        ] * 100
    )

    export_df.to_csv(
        output_file,
        index=False,
        encoding="utf-8-sig"
    )

    print()
    print(
        "Ranking CSV saved:"
    )

    print(
        output_file
    )


# =========================================================
# Main
# =========================================================

if __name__ == "__main__":

    print()
    print(
        "================================="
    )

    print(
        "V4.1 AI 全市場股票排名"
    )

    print(
        "================================="
    )

    # -----------------------------------------------------
    # 建立市場資料
    # -----------------------------------------------------

    market_df = (
        build_market_dataset()
    )

    if market_df.empty:

        print(
            "No market data."
        )

        sys.exit()

    print()
    print(
        "Market dataset:"
    )

    print(
        market_df[
            [
                "symbol",
                "date",
                "close",
                "future_return_20"
            ]
        ].head()
    )

    # -----------------------------------------------------
    # 訓練模型
    # -----------------------------------------------------

    model = train_model(
        market_df
    )

    # -----------------------------------------------------
    # 預測 + 排名
    # -----------------------------------------------------

    result = predict_latest(
        model,
        market_df
    )

    # -----------------------------------------------------
    # 儲存 CSV
    # -----------------------------------------------------

    save_ranking_csv(
        result
    )

    # -----------------------------------------------------
    # 完成
    # -----------------------------------------------------

    print()
    print(
        "================================="
    )

    print(
        "V4.1 training + ranking completed."
    )

    print(
        "================================="
    )