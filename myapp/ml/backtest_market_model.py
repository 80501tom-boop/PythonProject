# -*- coding: utf-8 -*-

"""
V5.1 AI 全市場歷史回測

功能：
1. 取得股票歷史資料
2. 建立技術指標
3. 建立未來 20 交易日報酬
4. 使用歷史日期以前的資料訓練 LightGBM
5. 預測該日期每支股票未來 20 日報酬
6. 依預測報酬進行排名
7. 選出 Top N
8. 計算實際未來 20 日報酬
9. 比較預測報酬與實際報酬
10. 匯出 CSV
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

# 每隔幾個交易日做一次回測
# 1 = 每個交易日
# 5 = 每 5 個交易日
BACKTEST_STEP = 5

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

    df = df.rename(
        columns={
            "open_price": "open",
            "high_price": "high",
            "low_price": "low",
            "close_price": "close",
        }
    )

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

    # 報酬率

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

    # 移動平均

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

    # MA 比率

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

    # RSI

    df["rsi"] = calculate_rsi(
        df["close"],
        14
    )

    # 成交量變化

    df["volume_change"] = (
        df["volume"]
        .pct_change(1)
    )

    # 成交量比例

    volume_ma20 = (
        df["volume"]
        .rolling(20)
        .mean()
    )

    df["volume_ratio"] = (
        df["volume"] /
        volume_ma20
    )

    # 波動率

    df["volatility_20"] = (
        df["return_1"]
        .rolling(20)
        .std()
    )

    # 未來 20 日實際報酬

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
            str(stock.symbol)
            .zfill(4)
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
# 單次回測
# =========================================================

def run_single_backtest(
    market_df,
    backtest_date
):

    print()
    print(
        "=========================================="
    )

    print(
        f"Backtest Date: "
        f"{backtest_date.strftime('%Y-%m-%d')}"
    )

    print(
        "=========================================="
    )

    # -----------------------------------------------------
    # 訓練資料
    # -----------------------------------------------------

    train_df = market_df[
        market_df["date"] < backtest_date
    ].copy()

    train_df = train_df.dropna(
        subset=
        FEATURE_COLUMNS +
        ["future_return_20"]
    )

    train_df = train_df.sort_values(
        "date"
    )

    if len(train_df) < 100:

        print(
            "  -> Skip: "
            "training data too small"
        )

        return pd.DataFrame()

    # -----------------------------------------------------
    # 建立模型
    # -----------------------------------------------------

    X_train = train_df[
        FEATURE_COLUMNS
    ]

    y_train = train_df[
        "future_return_20"
    ]

    model = lgb.LGBMRegressor(

        objective="regression",

        n_estimators=300,

        learning_rate=0.03,

        num_leaves=31,

        max_depth=-1,

        subsample=0.8,

        colsample_bytree=0.8,

        random_state=42,

        n_jobs=-1,

        verbosity=-1
    )

    model.fit(
        X_train,
        y_train
    )

    # -----------------------------------------------------
    # 找出回測日期的股票資料
    # -----------------------------------------------------

    current_df = market_df[
        market_df["date"] == backtest_date
    ].copy()

    current_df = current_df.dropna(
        subset=FEATURE_COLUMNS
    )

    if current_df.empty:

        print(
            "  -> No valid stocks"
        )

        return pd.DataFrame()

    # -----------------------------------------------------
    # 預測
    # -----------------------------------------------------

    X_current = current_df[
        FEATURE_COLUMNS
    ].copy()

    for column in FEATURE_COLUMNS:

        X_current[column] = pd.to_numeric(
            X_current[column],
            errors="coerce"
        )

    current_df["predicted_return_20"] = (
        model.predict(
            X_current
        )
    )

    # -----------------------------------------------------
    # 排名
    # -----------------------------------------------------

    current_df = current_df.sort_values(
        "predicted_return_20",
        ascending=False
    ).reset_index(
        drop=True
    )

    current_df["rank"] = (
        current_df.index + 1
    )

    # -----------------------------------------------------
    # Top N
    # -----------------------------------------------------

    top_result = current_df.head(
        TOP_N
    ).copy()

    # -----------------------------------------------------
    # 實際報酬
    # -----------------------------------------------------

    top_result["actual_return_20"] = (
        top_result[
            "future_return_20"
        ]
    )

    # -----------------------------------------------------
    # 預測誤差
    # -----------------------------------------------------

    top_result["prediction_error"] = (
        top_result[
            "actual_return_20"
        ]
        -
        top_result[
            "predicted_return_20"
        ]
    )

    # -----------------------------------------------------
    # 顯示
    # -----------------------------------------------------

    print()

    print(
        f"{'Rank':<8}"
        f"{'Symbol':<10}"
        f"{'Predicted':>15}"
        f"{'Actual':>15}"
    )

    print(
        "-" * 48
    )

    for _, row in top_result.iterrows():

        print(

            f"{int(row['rank']):<8}"

            f"{str(row['symbol']).zfill(4):<10}"

            f"{row['predicted_return_20'] * 100:>13.2f}%"

            f"{row['actual_return_20'] * 100:>13.2f}%"
        )

    return top_result[
        [
            "date",
            "rank",
            "symbol",
            "close",
            "predicted_return_20",
            "actual_return_20",
            "prediction_error",
        ]
    ]


# =========================================================
# 執行完整回測
# =========================================================

def run_backtest(
    market_df
):

    valid_dates = (
        market_df["date"]
        .drop_duplicates()
        .sort_values()
        .tolist()
    )

    # 前面需要足夠資料訓練
    # 最後 20 日不能當回測日期
    if len(valid_dates) <= 140:

        raise ValueError(
            "Not enough historical dates "
            "for backtest."
        )

    # -----------------------------------------------------
    # 從中後段開始回測
    # -----------------------------------------------------

    start_index = 120

    end_index = (
        len(valid_dates)
        - LOOK_FORWARD
    )

    backtest_dates = valid_dates[
        start_index:end_index:BACKTEST_STEP
    ]

    print()
    print(
        "=========================================="
    )

    print(
        "V5.1 Historical Backtest"
    )

    print(
        "=========================================="
    )

    print(
        f"Backtest dates: "
        f"{len(backtest_dates)}"
    )

    all_results = []

    for backtest_date in backtest_dates:

        result = run_single_backtest(
            market_df,
            backtest_date
        )

        if not result.empty:

            all_results.append(
                result
            )

    if not all_results:

        return pd.DataFrame()

    result_df = pd.concat(
        all_results,
        ignore_index=True
    )

    return result_df


# =========================================================
# 回測統計
# =========================================================

def print_backtest_summary(
    result_df
):

    if result_df.empty:

        return

    # -----------------------------------------------------
    # 每次 Top N 的平均實際報酬
    # -----------------------------------------------------

    average_actual_return = (
        result_df[
            "actual_return_20"
        ].mean()
    )

    average_predicted_return = (
        result_df[
            "predicted_return_20"
        ].mean()
    )

    average_error = (
        result_df[
            "prediction_error"
        ].mean()
    )

    # -----------------------------------------------------
    # 正報酬比例
    # -----------------------------------------------------

    positive_ratio = (
        (
            result_df[
                "actual_return_20"
            ] > 0
        ).mean()
    )

    # -----------------------------------------------------
    # MAE
    # -----------------------------------------------------

    mae = mean_absolute_error(

        result_df[
            "actual_return_20"
        ],

        result_df[
            "predicted_return_20"
        ]
    )

    # -----------------------------------------------------
    # RMSE
    # -----------------------------------------------------

    rmse = np.sqrt(
        mean_squared_error(

            result_df[
                "actual_return_20"
            ],

            result_df[
                "predicted_return_20"
            ]
        )
    )

    print()
    print(
        "=========================================="
    )

    print(
        "V5.1 Backtest Summary"
    )

    print(
        "=========================================="
    )

    print(
        f"Backtest samples : "
        f"{len(result_df)}"
    )

    print(
        f"Average predicted: "
        f"{average_predicted_return * 100:.2f}%"
    )

    print(
        f"Average actual   : "
        f"{average_actual_return * 100:.2f}%"
    )

    print(
        f"Average error    : "
        f"{average_error * 100:.2f}%"
    )

    print(
        f"Positive return  : "
        f"{positive_ratio * 100:.2f}%"
    )

    print(
        f"MAE              : "
        f"{mae:.6f}"
    )

    print(
        f"RMSE             : "
        f"{rmse:.6f}"
    )


# =========================================================
# 匯出 CSV
# =========================================================

def save_backtest_csv(
    result_df
):

    if result_df.empty:

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
        "market_backtest.csv"
    )

    export_df = result_df.copy()

    export_df["symbol"] = (
        export_df["symbol"]
        .astype(str)
        .str.zfill(4)
    )

    export_df[
        "predicted_return_20"
    ] *= 100

    export_df[
        "actual_return_20"
    ] *= 100

    export_df[
        "prediction_error"
    ] *= 100

    export_df.to_csv(
        output_file,
        index=False,
        encoding="utf-8-sig"
    )

    print()
    print(
        "Backtest CSV saved:"
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
        "V5.1 AI 全市場歷史回測"
    )

    print(
        "================================="
    )

    # -----------------------------------------------------
    # 建立資料
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
        f"Rows: "
        f"{len(market_df)}"
    )

    print(
        f"Stocks: "
        f"{market_df['symbol'].nunique()}"
    )

    print(
        f"Date: "
        f"{market_df['date'].min().strftime('%Y-%m-%d')}"
        f" ~ "
        f"{market_df['date'].max().strftime('%Y-%m-%d')}"
    )

    # -----------------------------------------------------
    # 執行回測
    # -----------------------------------------------------

    result_df = run_backtest(
        market_df
    )

    if result_df.empty:

        print(
            "No backtest result."
        )

        sys.exit()

    # -----------------------------------------------------
    # 統計
    # -----------------------------------------------------

    print_backtest_summary(
        result_df
    )

    # -----------------------------------------------------
    # 儲存
    # -----------------------------------------------------

    save_backtest_csv(
        result_df
    )

    # -----------------------------------------------------
    # 完成
    # -----------------------------------------------------

    print()
    print(
        "================================="
    )

    print(
        "V5.1 backtest completed."
    )

    print(
        "================================="
    )