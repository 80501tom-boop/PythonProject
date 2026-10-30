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
from sklearn.metrics import mean_absolute_error, mean_squared_error

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

from myapp.models import PredictionHistory

from config import POOL_SYMBOLS, TOP_N, is_eligible

ADJUSTED_PATH = os.path.join(BASE_DIR, "adjusted_prices.csv")
_ADJUSTED_CACHE = {}
# ============================================================
# 基本設定
# ============================================================

LOOK_FORWARD = 20

MIN_DATA_LENGTH = 120

MODEL_VERSION = "V5.8-FORWARD"

VALID_RATIO = 0.2
MIN_VALID_SAMPLES = 200

MIN_AVG_VOLUME_20 = 100000
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

# 完整前瞻預測結果
OUTPUT_FILE = os.path.join(
    OUTPUT_DIR,
    "forward_prediction.csv"
)

# 相容既有 Django AI 排名頁
RANKING_FILE = os.path.join(
    OUTPUT_DIR,
    "market_ranking.csv"
)

MODEL_FILE = os.path.join(
    MODEL_DIR,
    "lightgbm_v5_8_forward.txt"
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
    "is_twse",
    "is_tpex",
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

def load_adjusted_prices(symbol):
    """讀取 adjust_prices.py 產生的還原收盤價（date, adj_close）。"""
    if not os.path.exists(ADJUSTED_PATH):
        raise FileNotFoundError(
            f"找不到 {ADJUSTED_PATH}，請先執行 scripts/adjust_prices.py"
        )

    if _ADJUSTED_CACHE.get("df") is None:
        adj = pd.read_csv(ADJUSTED_PATH, dtype={"symbol": str})
        adj["symbol"] = adj["symbol"].str.strip()
        adj["date"] = pd.to_datetime(adj["date"])
        _ADJUSTED_CACHE["df"] = adj

    adj = _ADJUSTED_CACHE["df"]
    return adj.loc[adj["symbol"] == symbol, ["date", "adj_close"]]


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

    df = df.merge(
        load_adjusted_prices(str(stock.symbol).strip()),
        on="date",
        how="left",
    )

    df = df.dropna(
        subset=[
            "date",
            "close",
            "adj_close",
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

    # 特徵與標籤使用還原收盤價；原始收盤價保留給輸出顯示
    df["close_raw"] = df["close"]
    df["close"] = df["adj_close"]

    # --------------------------------------------------------
    # 報酬率
    # --------------------------------------------------------
    df["return_1"] = df["close"].pct_change(1)
    df["return_5"] = df["close"].pct_change(5)
    df["return_20"] = df["close"].pct_change(20)

    # --------------------------------------------------------
    # 移動平均
    # --------------------------------------------------------
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()

    # --------------------------------------------------------
    # 均線乖離
    # --------------------------------------------------------
    df["ma5_ratio"] = df["close"] / df["ma5"] - 1
    df["ma20_ratio"] = df["close"] / df["ma20"] - 1
    df["ma60_ratio"] = df["close"] / df["ma60"] - 1

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------
    df["rsi"] = calculate_rsi(df["close"], 14)

    # --------------------------------------------------------
    # 成交量變化 / 均量比
    # --------------------------------------------------------
    df["volume_change"] = df["volume"].pct_change(1)
    volume_ma20 = df["volume"].rolling(20).mean()
    df["volume_ma20"] = volume_ma20
    df["volume_ratio"] = df["volume"] / volume_ma20

    # --------------------------------------------------------
    # 20日波動率
    # --------------------------------------------------------
    df["volatility_20"] = df["return_1"].rolling(20).std()

    # --------------------------------------------------------
    # 未來 LOOK_FORWARD 報酬與標籤終點日期
    # --------------------------------------------------------
    df["future_return_20"] = (
        df["close"].shift(-LOOK_FORWARD) / df["close"] - 1
    )
    df["future_date_20"] = df["date"].shift(-LOOK_FORWARD)

    df["close"] = df["close_raw"]
    df = df.drop(columns=["close_raw", "adj_close"])

    return df


# ============================================================
# 建立全市場資料
# ============================================================

def build_market_dataset():

    print()
    print("=" * 70)
    print("建立全市場資料")
    print("=" * 70)

    stocks = Stock.objects.filter(symbol__in=POOL_SYMBOLS)

    market_data = []
    stock_count = 0
    valid_count = 0
    low_liquidity_count = 0

    for stock in stocks:
        stock_count += 1

        try:
            df = get_stock_data(stock)

            if df is None:
                continue

            if len(df) < MIN_DATA_LENGTH:
                continue

            df = create_features(df)

            # -----------------------------
            # point-in-time：只保留首次納入日之後的列
            # -----------------------------
            symbol = str(stock.symbol).strip()
            df = df[
                df["date"].map(
                    lambda d: is_eligible(symbol, pd.Timestamp(d).date())
                )
            ]

            if df.empty:
                continue

            # -----------------------------
            # 流動性門檻：
            # 最新一天的 20 日平均成交量不足則略過
            # -----------------------------
            latest_volume_ma20 = pd.to_numeric(
                df["volume_ma20"].iloc[-1],
                errors="coerce"
            )

            if pd.isna(latest_volume_ma20) or latest_volume_ma20 < MIN_AVG_VOLUME_20:
                low_liquidity_count += 1
                continue

            # -----------------------------
            # 加入股票資訊與市場特徵
            # -----------------------------
            market_raw = str(getattr(stock, "market", "") or "").strip().upper()

            if market_raw in ("TWSE", "上市"):
                market_norm = "TWSE"
            elif market_raw in ("TPEX", "TPEx", "OTC", "上櫃"):
                market_norm = "TPEx"
            else:
                market_norm = "UNKNOWN"

            df["stock_id"] = stock.id
            df["symbol"] = str(stock.symbol).strip().zfill(4)
            df["stock_name"] = stock.name

            # 市場 one-hot 特徵（最小版）
            df["is_twse"] = 1 if market_norm == "TWSE" else 0
            df["is_tpex"] = 1 if market_norm == "TPEx" else 0

            market_data.append(df)
            valid_count += 1

        except Exception as e:
            print(f"股票 {stock.symbol} 處理失敗：{e}")
            continue

    if not market_data:
        return None

    market_df = pd.concat(market_data, ignore_index=True)

    market_df = market_df.sort_values(
        ["date", "symbol"]
    ).reset_index(drop=True)

    print(f"股票總數：{stock_count}")
    print(f"有效股票：{valid_count}")
    print(f"流動性不足略過：{low_liquidity_count}")
    print(f"資料總筆數：{len(market_df)}")
    print(
        f"資料日期："
        f"{market_df['date'].min().strftime('%Y-%m-%d')}"
        " ～ "
        f"{market_df['date'].max().strftime('%Y-%m-%d')}"
    )

    return market_df

def run_time_based_validation(train_df):
    """
    時間驗證：僅供監控，不改變最終模型的全資料訓練流程。

    訓練樣本日期與標籤終點都必須早於驗證起始日。
    此驗證不代表已完成獨立測試或投資組合回測。
    """
    if not 0 < VALID_RATIO < 1:
        raise ValueError("VALID_RATIO 必須介於 0 與 1 之間。")

    required_columns = FEATURE_COLUMNS + [
        "date",
        "future_date_20",
        "future_return_20",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in train_df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"驗證資料缺少欄位：{missing_columns}；"
            "請確認 create_features() 已建立 future_date_20。"
        )

    # --------------------------------------------------------
    # 1. 日期及數值清理
    # --------------------------------------------------------

    df = train_df.copy()

    for column in ["date", "future_date_20"]:
        df[column] = pd.to_datetime(
            df[column],
            errors="coerce",
        )

    numeric_columns = FEATURE_COLUMNS + ["future_return_20"]

    df[numeric_columns] = (
        df[numeric_columns]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
    )

    df = df.dropna(subset=required_columns).copy()

    # 正常的未來報酬標籤，終點必須晚於樣本日期。
    df = df.loc[
        df["future_date_20"] > df["date"]
    ].sort_values("date").reset_index(drop=True)

    if df.empty:
        print("驗證資料清理後為空，略過時間驗證。")
        return

    # --------------------------------------------------------
    # 2. 依不重複日期切分
    # --------------------------------------------------------

    unique_dates = (
        df["date"]
        .drop_duplicates()
        .sort_values()
        .reset_index(drop=True)
    )

    if len(unique_dates) < 30:
        print("有效交易日期少於 30 天，略過時間驗證。")
        return

    split_position = int(
        len(unique_dates) * (1 - VALID_RATIO)
    )
    split_position = max(
        1,
        min(split_position, len(unique_dates) - 1),
    )

    valid_start_date = unique_dates.iloc[split_position]

    # 關鍵：訓練標籤不得使用驗證期間的價格。
    train_part = df.loc[
        (df["date"] < valid_start_date)
        & (df["future_date_20"] < valid_start_date)
    ].copy()

    valid_part = df.loc[
        df["date"] >= valid_start_date
    ].copy()

    purged_count = int(
        (
            (df["date"] < valid_start_date)
            & (df["future_date_20"] >= valid_start_date)
        ).sum()
    )

    if (
        len(train_part) < MIN_VALID_SAMPLES
        or len(valid_part) < MIN_VALID_SAMPLES
    ):
        print(
            "時間切分後樣本不足，略過驗證。"
            f"訓練：{len(train_part)} 筆；"
            f"驗證：{len(valid_part)} 筆；"
            f"每組至少需要 {MIN_VALID_SAMPLES} 筆。"
        )
        return

    # 明確檢查時間邊界，避免未來修改時破壞隔離。
    if train_part["future_date_20"].max() >= valid_start_date:
        raise ValueError("訓練標籤終點進入驗證期間。")

    if train_part["date"].max() >= valid_part["date"].min():
        raise ValueError("訓練與驗證的樣本日期未正確隔離。")

    # --------------------------------------------------------
    # 3. 訓練獨立的驗證模型
    # --------------------------------------------------------

    X_train = train_part[FEATURE_COLUMNS]
    y_train = train_part["future_return_20"]

    X_valid = valid_part[FEATURE_COLUMNS]
    y_valid = valid_part["future_return_20"]

    eval_model = lgb.LGBMRegressor(
        objective="regression",
        n_estimators=300,
        learning_rate=0.03,
        num_leaves=31,
        max_depth=-1,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=-1,
        verbosity=-1,
    )

    eval_model.fit(X_train, y_train)
    predictions = eval_model.predict(X_valid)

    # --------------------------------------------------------
    # 4. 評估指標
    # --------------------------------------------------------

    # 訓練標籤採小數報酬；乘以 100 轉成百分點。
    mae_pp = mean_absolute_error(y_valid, predictions) * 100
    rmse_pp = (
        np.sqrt(mean_squared_error(y_valid, predictions)) * 100
    )

    actual = y_valid.to_numpy()
    predicted = np.asarray(predictions)

    # 實際報酬為 0 不計入方向準確率。
    nonzero_mask = actual != 0
    direction_count = int(nonzero_mask.sum())

    if direction_count > 0:
        direction_accuracy = float(
            np.mean(
                np.sign(predicted[nonzero_mask])
                == np.sign(actual[nonzero_mask])
            ) * 100
        )
    else:
        direction_accuracy = float("nan")

    # --------------------------------------------------------
    # 5. 輸出報告
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("時間驗證報告（僅供監控）")
    print("=" * 70)
    print(f"驗證起始日：{valid_start_date:%Y-%m-%d}")
    print(
        "訓練樣本日期："
        f"{train_part['date'].min():%Y-%m-%d} ～ "
        f"{train_part['date'].max():%Y-%m-%d}"
    )
    print(
        "訓練標籤最晚終點："
        f"{train_part['future_date_20'].max():%Y-%m-%d}"
    )
    print(
        "驗證樣本日期："
        f"{valid_part['date'].min():%Y-%m-%d} ～ "
        f"{valid_part['date'].max():%Y-%m-%d}"
    )
    print(f"因標籤跨界排除：{purged_count:,} 筆")
    print(f"訓練樣本：{len(X_train):,} 筆")
    print(f"驗證樣本：{len(X_valid):,} 筆")
    print(f"MAE：{mae_pp:.4f} 個百分點")
    print(f"RMSE：{rmse_pp:.4f} 個百分點")
    print(f"方向有效樣本：{direction_count:,} 筆")

    if np.isnan(direction_accuracy):
        print("方向準確率：N/A")
    else:
        print(f"方向準確率：{direction_accuracy:.2f}%")

    print("=" * 70)
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
        subset=FEATURE_COLUMNS + ["future_return_20", "future_date_20"]
    ).copy()

    if train_df.empty:

        raise ValueError(
            "沒有足夠的訓練資料。"
        )

    # --------------------------------------------------------
    # X / y（先做一致性清理）
    # --------------------------------------------------------

    train_df[FEATURE_COLUMNS] = (
        train_df[FEATURE_COLUMNS]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
    )

    train_df["future_return_20"] = pd.to_numeric(
        train_df["future_return_20"],
        errors="coerce"
    )

    train_df["future_date_20"] = pd.to_datetime(
        train_df["future_date_20"],
        errors="coerce"
    )

    train_df["date"] = pd.to_datetime(
        train_df["date"],
        errors="coerce"
    )

    train_df = train_df.dropna(
        subset=FEATURE_COLUMNS + ["future_return_20", "future_date_20", "date"]
    ).copy()

    # 基本合理性：約束標籤終點要晚於樣本日期
    train_df = train_df[
        train_df["future_date_20"] > train_df["date"]
    ].copy()
    
    # 與回測一致：排除極端 label 樣本（僅訓練）
    train_df = train_df[
        (train_df["future_return_20"] >= -0.5)
        & (train_df["future_return_20"] <= 1.5)
    ].copy()
    
    X = train_df[FEATURE_COLUMNS]
    y = train_df["future_return_20"]

    valid_mask = X.notna().all(axis=1) & y.notna()
    train_df = train_df.loc[valid_mask].copy()

    X = train_df[FEATURE_COLUMNS]
    y = train_df["future_return_20"]

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
    # 監控用時間驗證（不影響最終模型仍用全資料訓練）
    run_time_based_validation(train_df)
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

    # 並列對照：mom20 = 過去 20 日漲幅排名（僅作對照，不取代主排名）
    current_df["rank_mom20"] = (
        current_df["return_20"]
        .rank(ascending=False, method="first")
        .astype(int)
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


def save_prediction_history(result_df):
    """
    將當次完整前瞻預測結果保存至 MySQL（快照模式）。

    規則（嚴格不覆寫）：
    1) 同一天、同一檔、同一模型版本、同一 data_date 若不存在 -> 新增
    2) 若已存在 -> 一律略過（不覆寫，不修改）
       - 不論是否已評估，皆保留原始快照
    """

    if result_df.empty:
        print("沒有預測結果，不保存歷史紀錄。")
        return

    created_count = 0
    skipped_existing_count = 0

    for _, row in result_df.iterrows():
        prediction_date = pd.to_datetime(
            row["prediction_date"]
        ).date()

        data_date = pd.to_datetime(
            row["date"]
        ).date()

        symbol = str(row["symbol"]).strip().zfill(4)

        model_version = str(
            row.get("model_version", MODEL_VERSION)
        )

        defaults = {
            "stock_name": str(row.get("stock_name", "")),
            "close_price": round(float(row["close"]), 2),
            "predicted_return_20": round(
                float(row["predicted_return_20"]) * 100,
                4
            ),
            "rank": int(row["rank"]),
            "horizon": int(row.get("horizon", LOOK_FORWARD)),
        }

        _, created = PredictionHistory.objects.get_or_create(
            prediction_date=prediction_date,
            symbol=symbol,
            model_version=model_version,
            data_date=data_date,
            defaults=defaults
        )

        if created:
            created_count += 1
        else:
            skipped_existing_count += 1

    print()
    print("=" * 50)
    print("歷史預測紀錄保存完成（快照模式）")
    print(f"新增紀錄：{created_count} 筆")
    print(f"已存在略過：{skipped_existing_count} 筆")
    print("=" * 50)
# ============================================================
# 儲存 Forward Prediction
# ============================================================


def save_prediction(result_df):

    if result_df.empty:
        print("沒有預測結果，不輸出 CSV。")
        return

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    # =====================================================
    # A. 完整前瞻預測檔
    # =====================================================

    export_df = result_df[
        [
            "prediction_date",
            "symbol",
            "stock_name",
            "date",
            "close",
            "predicted_return_20",
            "rank",
            "rank_mom20",
            "return_20",
            "model_version",
            "horizon",
        ]
    ].copy()

    export_df["return_20"] = export_df["return_20"] * 100

    export_df["prediction_date"] = (
        pd.to_datetime(
            export_df["prediction_date"]
        ).dt.strftime("%Y-%m-%d")
    )

    export_df["date"] = (
        pd.to_datetime(
            export_df["date"]
        ).dt.strftime("%Y-%m-%d")
    )

    export_df = export_df.rename(
        columns={
            "date": "data_date",
            "close": "close_price",
        }
    )

    export_df["symbol"] = (
        export_df["symbol"]
        .astype(str)
        .str.strip()
        .str.zfill(4)
    )

    # 以百分比數值儲存，例如 3.5 代表 3.5%
    export_df["predicted_return_20"] = (
        export_df["predicted_return_20"] * 100
    )

    export_df.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8-sig",
    )

    # =====================================================
    # B. 相容既有 Django 排名頁的檔案
    # =====================================================

    ranking_df = export_df[
        [
            "rank",
            "symbol",
            "data_date",
            "close_price",
            "predicted_return_20",
        ]
    ].copy()

    ranking_df = ranking_df.rename(
        columns={
            "data_date": "date",
            "close_price": "close",
        }
    )

    ranking_df.to_csv(
        RANKING_FILE,
        index=False,
        encoding="utf-8-sig",
    )

    # =====================================================
    # C. 執行結果
    # =====================================================

    print()
    print("=" * 60)
    print("前瞻預測輸出完成")
    print("=" * 60)

    print(f"完整預測檔：{OUTPUT_FILE}")
    print(f"網站排名檔：{RANKING_FILE}")
    print(f"預測股票數：{len(export_df)}")

    print()
    print(f"Top {TOP_N}（LightGBM 主排名）：")

    print(
        ranking_df.head(TOP_N).to_string(
            index=False
        )
    )

    print()
    print(f"Top {TOP_N}（mom20 並列對照）：")

    print(
        export_df.sort_values("rank_mom20")[
            ["rank_mom20", "symbol", "stock_name", "close_price", "return_20"]
        ].head(TOP_N).to_string(index=False)
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
    
    # 5. 保存資料庫歷史預測紀錄
    save_prediction_history(result_df)
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