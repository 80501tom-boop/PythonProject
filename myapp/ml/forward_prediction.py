# -*- coding: utf-8 -*-

"""
STOCK AI - Forward Prediction

功能：
1. 讀取 Django Stock / StockPrice 資料
2. 建立與 V5.1 相同的技術特徵
3. 建立 future_return_20 作為訓練目標
4. 使用所有「已經知道未來20日結果」的歷史資料訓練 LightGBM
5. 找出目前最新交易日
6. 使用最新交易日的特徵預測未來20個交易日報酬
7. 全市場排序
8. 建立 Top-N 股票排名
9. 儲存 LightGBM 模型
10. 輸出 forward_prediction.csv

注意：
本程式是 Forward Prediction，不是歷史回測。

例如：
2026-10-06 最新資料
        ↓
使用截至目前已知的歷史資料訓練
        ↓
預測 2026-10-06 之後的 20 個交易日

目前尚不知道 actual_return_20，
因此不會在本程式中計算實際報酬。
"""

import os
import sys

import django
import pandas as pd
import numpy as np
import lightgbm as lgb


# ============================================================
# Django 設定
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

sys.path.insert(
    0,
    BASE_DIR
)

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "PythonProject.settings"
)

django.setup()


# ============================================================
# Django Models
# ============================================================

from myapp.models import Stock, StockPrice


# ============================================================
# 基本設定
# ============================================================

LOOK_FORWARD = 20

MIN_DATA_LENGTH = 120

TOP_N = 5

MODEL_VERSION = "V5.7-FORWARD"


# ============================================================
# 輸出資料夾
# ============================================================

OUTPUT_DIR = os.path.join(
    os.path.dirname(
        os.path.abspath(__file__)
    ),
    "output"
)

MODEL_DIR = os.path.join(
    os.path.dirname(
        os.path.abspath(__file__)
    ),
    "models"
)


os.makedirs(
    OUTPUT_DIR,
    exist_ok=True
)

os.makedirs(
    MODEL_DIR,
    exist_ok=True
)


# ============================================================
# 輸出檔案
# ============================================================

OUTPUT_FILE = os.path.join(
    OUTPUT_DIR,
    "forward_prediction.csv"
)


MODEL_FILE = os.path.join(
    MODEL_DIR,
    "lightgbm_v5_7_forward.txt"
)


# ============================================================
# Features
#
# 必須與 V5.1 保持一致
# ============================================================

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


# ============================================================
# Console 顯示設定
# ============================================================

pd.set_option(
    "display.width",
    180
)

pd.set_option(
    "display.max_columns",
    30
)

pd.set_option(
    "display.float_format",
    lambda x: f"{x:.4f}"
)


# ============================================================
# RSI
# ============================================================

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
        avg_gain
        /
        avg_loss.replace(
            0,
            np.nan
        )
    )

    rsi = (
        100
        -
        (
            100
            /
            (
                1 + rs
            )
        )
    )

    return rsi


# ============================================================
# 股票資料
# ============================================================

def get_stock_data(stock):

    prices = StockPrice.objects.filter(
        stock=stock
    ).order_by(
        "date"
    ).values(
        "date",
        "close_price",
        "volume"
    )

    df = pd.DataFrame(
        prices
    )

    if df.empty:
        return None

    df["date"] = pd.to_datetime(
        df["date"],
        errors="coerce"
    )

    df["close"] = pd.to_numeric(
        df["close_price"],
        errors="coerce"
    )

    df["volume"] = pd.to_numeric(
        df["volume"],
        errors="coerce"
    )

    df = df.dropna(
        subset=[
            "date",
            "close",
            "volume"
        ]
    )

    df = df.sort_values(
        "date"
    ).reset_index(
        drop=True
    )

    return df

# ============================================================
# 建立 Features
#
# 與 V5.1 相同
# ============================================================

def create_features(df):

    df = df.copy()

    # --------------------------------------------------------
    # 報酬率
    # --------------------------------------------------------

    df["return_1"] = (
        df["close"].pct_change(1)
    )

    df["return_5"] = (
        df["close"].pct_change(5)
    )

    df["return_20"] = (
        df["close"].pct_change(20)
    )

    # --------------------------------------------------------
    # 移動平均
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # 均線乖離
    # --------------------------------------------------------

    df["ma5_ratio"] = (
        df["close"]
        /
        df["ma5"]
        - 1
    )

    df["ma20_ratio"] = (
        df["close"]
        /
        df["ma20"]
        - 1
    )

    df["ma60_ratio"] = (
        df["close"]
        /
        df["ma60"]
        - 1
    )

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    df["rsi"] = calculate_rsi(
        df["close"],
        14
    )

    # --------------------------------------------------------
    # 成交量變化
    # --------------------------------------------------------

    df["volume_change"] = (
        df["volume"]
        .pct_change(1)
    )

    # --------------------------------------------------------
    # 成交量相對20日均量
    # --------------------------------------------------------

    volume_ma20 = (
        df["volume"]
        .rolling(20)
        .mean()
    )

    df["volume_ratio"] = (
        df["volume"]
        /
        volume_ma20
    )

    # --------------------------------------------------------
    # 20日波動率
    # --------------------------------------------------------

    df["volatility_20"] = (
        df["return_1"]
        .rolling(20)
        .std()
    )

    # --------------------------------------------------------
    # 未來20交易日報酬
    #
    # 只有歷史資料可以取得這個值。
    #
    # 最新資料的 future_return_20
    # 會自然變成 NaN。
    # --------------------------------------------------------

    df["future_return_20"] = (
        df["close"].shift(
            -LOOK_FORWARD
        )
        /
        df["close"]
        - 1
    )

    return df


# ============================================================
# 建立全市場資料
# ============================================================

def build_market_dataset():

    print()
    print("=" * 70)
    print("建立全市場資料")
    print("=" * 70)

    stocks = Stock.objects.all()

    market_data = []

    stock_count = 0

    valid_count = 0

    for stock in stocks:

        stock_count += 1

        try:

            df = get_stock_data(
                stock
            )

            if df is None:
                continue

            if len(df) < MIN_DATA_LENGTH:
                continue

            df = create_features(
                df
            )

            # ------------------------------------------------
            # 加入股票資訊
            # ------------------------------------------------

            df["stock_id"] = stock.id

            df["symbol"] = str(
                stock.symbol
            ).strip().zfill(4)

            df["stock_name"] = (
                stock.name
            )

            market_data.append(
                df
            )

            valid_count += 1

        except Exception as e:

            print(
                f"股票 {stock.symbol} "
                f"處理失敗：{e}"
            )

            continue

    if not market_data:

        return None

    market_df = pd.concat(
        market_data,
        ignore_index=True
    )

    market_df = market_df.sort_values(
        [
            "date",
            "symbol"
        ]
    ).reset_index(
        drop=True
    )

    print(
        f"股票總數：{stock_count}"
    )

    print(
        f"有效股票：{valid_count}"
    )

    print(
        f"資料總筆數：{len(market_df)}"
    )

    print(
        f"資料日期："
        f"{market_df['date'].min().strftime('%Y-%m-%d')}"
        " ～ "
        f"{market_df['date'].max().strftime('%Y-%m-%d')}"
    )

    return market_df


# ============================================================
# 建立最終模型
# ============================================================

def train_final_model(
    market_df
):

    print()
    print("=" * 70)
    print("訓練 Forward Prediction 最終模型")
    print("=" * 70)

    # --------------------------------------------------------
    # 只有 future_return_20 已知的資料
    # 才能拿來訓練
    # --------------------------------------------------------

    train_df = market_df.dropna(
        subset=
        FEATURE_COLUMNS
        +
        [
            "future_return_20"
        ]
    ).copy()

    if train_df.empty:

        raise ValueError(
            "沒有足夠的訓練資料。"
        )

    # --------------------------------------------------------
    # X / y
    # --------------------------------------------------------

    X = train_df[
        FEATURE_COLUMNS
    ].apply(
        pd.to_numeric,
        errors="coerce"
    )

    y = pd.to_numeric(
        train_df[
            "future_return_20"
        ],
        errors="coerce"
    )

    # --------------------------------------------------------
    # 再次清理
    # --------------------------------------------------------

    valid_mask = (
        X.notna().all(
            axis=1
        )
        &
        y.notna()
    )

    X = X.loc[
        valid_mask
    ]

    y = y.loc[
        valid_mask
    ]

    if len(X) == 0:

        raise ValueError(
            "清理後沒有有效訓練資料。"
        )

    # --------------------------------------------------------
    # 建立模型
    #
    # 與 V5.1 相同
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # 訓練
    # --------------------------------------------------------

    print(
        f"訓練資料筆數：{len(X):,}"
    )

    print(
        f"Features 數量：{len(FEATURE_COLUMNS)}"
    )

    print()

    print(
        "開始訓練 LightGBM..."
    )

    model.fit(
        X,
        y
    )

    # --------------------------------------------------------
    # 儲存模型
    # --------------------------------------------------------

    model.booster_.save_model(
        MODEL_FILE
    )

    print()

    print(
        "模型訓練完成"
    )

    print(
        f"模型檔案：{MODEL_FILE}"
    )

    return model


# ============================================================
# Forward Prediction
# ============================================================

def predict_latest(
    model,
    market_df
):

    print()
    print("=" * 70)
    print("開始 Forward Prediction")
    print("=" * 70)

    # --------------------------------------------------------
    # 找出市場最新交易日
    # --------------------------------------------------------

    latest_date = (
        market_df["date"].max()
    )

    print(
        "最新市場交易日："
        f"{latest_date.strftime('%Y-%m-%d')}"
    )

    # --------------------------------------------------------
    # 只取最新交易日
    # --------------------------------------------------------

    current_df = market_df[
        market_df["date"]
        ==
        latest_date
    ].copy()

    if current_df.empty:

        raise ValueError(
            "找不到最新交易日資料。"
        )

    original_count = len(
        current_df
    )

    # --------------------------------------------------------
    # Features
    # --------------------------------------------------------

    X = current_df[
        FEATURE_COLUMNS
    ].apply(
        pd.to_numeric,
        errors="coerce"
    )

    # --------------------------------------------------------
    # 移除 Feature 不完整股票
    # --------------------------------------------------------

    valid_mask = (
        X.notna().all(
            axis=1
        )
    )

    current_df = (
        current_df.loc[
            valid_mask
        ].copy()
    )

    X = X.loc[
        valid_mask
    ]

    if current_df.empty:

        raise ValueError(
            "最新交易日沒有有效的 Features。"
        )

    # --------------------------------------------------------
    # 預測
    # --------------------------------------------------------

    predictions = model.predict(
        X
    )

    current_df[
        "predicted_return_20"
    ] = predictions

    # --------------------------------------------------------
    # 排序
    # --------------------------------------------------------

    current_df = current_df.sort_values(
        "predicted_return_20",
        ascending=False
    ).reset_index(
        drop=True
    )

    # --------------------------------------------------------
    # Rank
    # --------------------------------------------------------

    current_df["rank"] = (
        current_df.index + 1
    )

    # --------------------------------------------------------
    # Prediction 日期
    # --------------------------------------------------------

    current_df[
        "prediction_date"
    ] = latest_date

    # --------------------------------------------------------
    # 模型資訊
    # --------------------------------------------------------

    current_df[
        "model_version"
    ] = MODEL_VERSION

    current_df[
        "horizon"
    ] = LOOK_FORWARD

    # --------------------------------------------------------
    # 顯示資訊
    # --------------------------------------------------------

    print(
        f"最新市場股票數："
        f"{original_count}"
    )

    print(
        f"成功預測股票數："
        f"{len(current_df)}"
    )

    print()

    print(
        f"Top-{TOP_N} 預測結果："
    )

    print()

    display_columns = [

        "rank",

        "symbol",

        "stock_name",

        "close",

        "predicted_return_20",

    ]

    display_df = (
        current_df[
            display_columns
        ]
        .head(TOP_N)
        .copy()
    )

    display_df[
        "predicted_return_20"
    ] = (
        display_df[
            "predicted_return_20"
        ]
        * 100
    )

    display_df = display_df.rename(
        columns={
            "close": "close_price",
            "predicted_return_20":
                "predicted_return_20_%"
        }
    )

    print(
        display_df.to_string(
            index=False
        )
    )

    return current_df


# ============================================================
# 儲存 Forward Prediction
# ============================================================

def save_prediction(
    result_df
):

    # --------------------------------------------------------
    # 選擇輸出欄位
    # --------------------------------------------------------

    export_df = result_df[
        [
            "prediction_date",

            "symbol",

            "stock_name",

            "date",

            "close",

            "predicted_return_20",

            "rank",

            "model_version",

            "horizon",

        ]
    ].copy()

    # --------------------------------------------------------
    # 日期
    # --------------------------------------------------------

    export_df[
        "prediction_date"
    ] = pd.to_datetime(
        export_df[
            "prediction_date"
        ]
    ).dt.strftime(
        "%Y-%m-%d"
    )

    export_df[
        "date"
    ] = pd.to_datetime(
        export_df[
            "date"
        ]
    ).dt.strftime(
        "%Y-%m-%d"
    )

    # --------------------------------------------------------
    # 命名
    # --------------------------------------------------------

    export_df = export_df.rename(
        columns={
            "date":
                "data_date",

            "close":
                "close_price",
        }
    )

    # --------------------------------------------------------
    # 預測報酬轉百分比
    #
    # 例如：
    # 0.0832
    # →
    # 8.32
    # --------------------------------------------------------

    export_df[
        "predicted_return_20"
    ] = (
        export_df[
            "predicted_return_20"
        ]
        * 100
    )

    # --------------------------------------------------------
    # 儲存
    # --------------------------------------------------------

    export_df.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    print()
    print("=" * 70)
    print("Forward Prediction 輸出完成")
    print("=" * 70)

    print(
        f"輸出檔案：{OUTPUT_FILE}"
    )

    print(
        f"預測股票數：{len(export_df)}"
    )

    print(
        f"Top-{TOP_N} 已建立"
    )


# ============================================================
# 主程式
# ============================================================

def main():

    print()
    print("=" * 70)
    print("STOCK AI - Forward Prediction")
    print("=" * 70)

    print()
    print(
        "功能：最新資料 → 未來20交易日 → 全市場排名"
    )

    print(
        f"模型版本：{MODEL_VERSION}"
    )

    print(
        f"預測期間：未來 {LOOK_FORWARD} 個交易日"
    )

    # ========================================================
    # 1. 建立全市場資料
    # ========================================================

    market_df = build_market_dataset()

    if market_df is None:

        print(
            "錯誤：無法建立市場資料。"
        )

        return

    # ========================================================
    # 2. 訓練最終模型
    # ========================================================

    model = train_final_model(
        market_df
    )

    # ========================================================
    # 3. 最新資料 Forward Prediction
    # ========================================================

    result_df = predict_latest(
        model,
        market_df
    )

    # ========================================================
    # 4. 儲存 CSV
    # ========================================================

    save_prediction(
        result_df
    )

    # ========================================================
    # 完成
    # ========================================================

    print()
    print("=" * 70)
    print("Forward Prediction 完成")
    print("=" * 70)

    print()
    print(
        "流程："
    )

    print(
        "最新資料"
        " → "
        "LightGBM"
        " → "
        "未來20交易日"
        " → "
        "全市場排名"
        " → "
        f"Top-{TOP_N}"
    )

    print()

    print(
        "注意："
    )

    print(
        "目前的 actual_return_20 尚未知道，"
        "因此本結果屬於 Forward Prediction，"
        "不是歷史回測結果。"
    )

    print()

    print(
        f"模型：{MODEL_FILE}"
    )

    print(
        f"預測結果：{OUTPUT_FILE}"
    )

    print()


# ============================================================
# 程式進入點
# ============================================================

if __name__ == "__main__":

    main()