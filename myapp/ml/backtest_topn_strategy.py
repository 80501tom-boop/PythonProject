# -*- coding: utf-8 -*-

"""
V5.4 - Top-N 股票選股策略回測

功能：
1. 讀取 market_backtest.csv
2. 每個回測日期依 predicted_return_20 由高到低排序
3. 選出 Top 5 股票
4. 計算 Top 5 預測平均報酬
5. 計算 Top 5 實際平均報酬
6. 計算全市場平均實際報酬
7. 計算策略超額報酬
8. 計算策略累積報酬
9. 計算市場累積報酬
10. 輸出：
       market_strategy_backtest.csv
       market_strategy_detail.csv
"""


import os
import pandas as pd
import numpy as np


# =========================================================
# 基本設定
# =========================================================

# 目前檔案所在位置：
# myapp/ml/backtest_topn_strategy.py
BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)


# =========================================================
# CSV 路徑
# =========================================================

INPUT_PATH = os.path.join(
    BASE_DIR,
    "output",
    "market_backtest.csv"
)


STRATEGY_OUTPUT_PATH = os.path.join(
    BASE_DIR,
    "output",
    "market_strategy_backtest.csv"
)


DETAIL_OUTPUT_PATH = os.path.join(
    BASE_DIR,
    "output",
    "market_strategy_detail.csv"
)


# =========================================================
# 策略設定
# =========================================================

TOP_N = 5


# =========================================================
# 顯示標題
# =========================================================

print()
print("=" * 70)
print("V5.4 - Top-N 股票選股策略回測")
print("=" * 70)

print()
print("輸入檔案：")
print(INPUT_PATH)

print()
print("Top-N：")
print(TOP_N)


# =========================================================
# 檢查輸入檔案
# =========================================================

if not os.path.exists(INPUT_PATH):

    print()
    print("❌ 找不到 market_backtest.csv")
    print()
    print("請確認檔案位於：")
    print(INPUT_PATH)

    raise SystemExit


# =========================================================
# 讀取資料
# =========================================================

print()
print("正在讀取回測資料...")


df = pd.read_csv(
    INPUT_PATH,
    dtype={
        "symbol": str
    }
)


if df.empty:

    print()
    print("❌ market_backtest.csv 沒有資料")

    raise SystemExit


print()
print(
    f"讀取完成，共 {len(df)} 筆資料"
)


# =========================================================
# 檢查必要欄位
# =========================================================

required_columns = [
    "date",
    "symbol",
    "predicted_return_20",
    "actual_return_20"
]


missing_columns = [
    column
    for column in required_columns
    if column not in df.columns
]


if missing_columns:

    print()
    print("❌ 缺少必要欄位：")

    for column in missing_columns:
        print(
            f"   - {column}"
        )

    print()
    print("目前 CSV 欄位：")

    for column in df.columns:
        print(
            f"   - {column}"
        )

    raise SystemExit


# =========================================================
# 股票代號
# =========================================================

df["symbol"] = (
    df["symbol"]
    .astype(str)
    .str.strip()
    .str.replace(
        ".0",
        "",
        regex=False
    )
    .str.zfill(4)
)


# =========================================================
# 日期
# =========================================================

df["date"] = pd.to_datetime(
    df["date"],
    errors="coerce"
)


# =========================================================
# 數值欄位
# =========================================================

numeric_columns = [
    "predicted_return_20",
    "actual_return_20"
]


if "rank" in df.columns:

    numeric_columns.append(
        "rank"
    )


if "close" in df.columns:

    numeric_columns.append(
        "close"
    )


if "prediction_error" in df.columns:

    numeric_columns.append(
        "prediction_error"
    )


for column in numeric_columns:

    df[column] = pd.to_numeric(
        df[column],
        errors="coerce"
    )


# =========================================================
# 移除無效資料
# =========================================================

before_count = len(df)


df = df.dropna(
    subset=[
        "date",
        "symbol",
        "predicted_return_20",
        "actual_return_20"
    ]
)


after_count = len(df)


if before_count != after_count:

    print()
    print(
        f"移除無效資料："
        f"{before_count - after_count} 筆"
    )


if df.empty:

    print()
    print("❌ 清理後沒有可用資料")

    raise SystemExit


# =========================================================
# 排序
# =========================================================

df = df.sort_values(
    [
        "date",
        "predicted_return_20"
    ],
    ascending=[
        True,
        False
    ]
).reset_index(
    drop=True
)


# =========================================================
# 顯示回測日期範圍
# =========================================================

min_date = df["date"].min()

max_date = df["date"].max()


print()
print(
    "回測日期："
    f"{min_date.strftime('%Y-%m-%d')}"
    " ～ "
    f"{max_date.strftime('%Y-%m-%d')}"
)


# =========================================================
# V5.4 Top-N 策略
# =========================================================

strategy_results = []

detail_results = []


all_dates = sorted(
    df["date"].dropna().unique()
)


print()
print(
    f"開始進行 Top-{TOP_N} 策略回測..."
)


for current_date in all_dates:

    # =====================================================
    # 取得當日資料
    # =====================================================

    daily = df[
        df["date"] == current_date
    ].copy()


    if daily.empty:

        continue


    # =====================================================
    # 按照 AI 預測報酬排序
    # =====================================================

    daily = daily.sort_values(
        "predicted_return_20",
        ascending=False
    )


    # =====================================================
    # 取 Top N
    # =====================================================

    top_n = daily.head(
        TOP_N
    ).copy()


    if top_n.empty:

        continue


    # =====================================================
    # Top-N 實際 / 預測平均報酬
    # =====================================================

    predicted_avg = (
        top_n[
            "predicted_return_20"
        ].mean()
    )


    actual_avg = (
        top_n[
            "actual_return_20"
        ].mean()
    )


    # =====================================================
    # 全市場平均實際報酬
    # =====================================================

    market_avg = (
        daily[
            "actual_return_20"
        ].mean()
    )


    # =====================================================
    # 超額報酬
    #
    # Top-N 實際報酬
    # -
    # 全市場平均實際報酬
    # =====================================================

    excess_return = (
        actual_avg
        -
        market_avg
    )


    # =====================================================
    # 記錄策略結果
    # =====================================================

    strategy_results.append({

        "date":
            current_date.strftime(
                "%Y-%m-%d"
            ),

        "top_n":
            len(top_n),

        "predicted_avg":
            round(
                float(
                    predicted_avg
                ),
                4
            ),

        "actual_avg":
            round(
                float(
                    actual_avg
                ),
                4
            ),

        "market_avg":
            round(
                float(
                    market_avg
                ),
                4
            ),

        "excess_return":
            round(
                float(
                    excess_return
                ),
                4
            )

    })


    # =====================================================
    # 記錄 Top-N 股票明細
    # =====================================================

    for rank_index, (_, row) in enumerate(
        top_n.iterrows(),
        start=1
    ):

        detail_row = {

            "date":
                current_date.strftime(
                    "%Y-%m-%d"
                ),

            "rank":
                rank_index,

            "symbol":
                row["symbol"],

            "predicted_return_20":
                round(
                    float(
                        row[
                            "predicted_return_20"
                        ]
                    ),
                    4
                ),

            "actual_return_20":
                round(
                    float(
                        row[
                            "actual_return_20"
                        ]
                    ),
                    4
                )

        }


        # ---------------------------------------------
        # 如果原始資料有股票名稱
        # ---------------------------------------------

        if "name" in row.index:

            detail_row["name"] = (
                row["name"]
            )


        # ---------------------------------------------
        # 如果原始資料有收盤價
        # ---------------------------------------------

        if "close" in row.index:

            if pd.notna(
                row["close"]
            ):

                detail_row["close"] = round(
                    float(
                        row["close"]
                    ),
                    2
                )


        # ---------------------------------------------
        # 如果原始資料有原始 Rank
        # ---------------------------------------------

        if "rank" in row.index:

            if pd.notna(
                row["rank"]
            ):

                detail_row[
                    "model_rank"
                ] = int(
                    row["rank"]
                )


        detail_results.append(
            detail_row
        )


# =========================================================
# 建立 DataFrame
# =========================================================

strategy_df = pd.DataFrame(
    strategy_results
)


detail_df = pd.DataFrame(
    detail_results
)


if strategy_df.empty:

    print()
    print("❌ 沒有產生任何策略結果")

    raise SystemExit


# =========================================================
# 日期排序
# =========================================================

strategy_df["date"] = pd.to_datetime(
    strategy_df["date"]
)


detail_df["date"] = pd.to_datetime(
    detail_df["date"]
)


strategy_df = strategy_df.sort_values(
    "date"
).reset_index(
    drop=True
)


detail_df = detail_df.sort_values(
    [
        "date",
        "rank"
    ]
).reset_index(
    drop=True
)


# =========================================================
# 累積報酬
#
# 每一期：
#
# 1 + 報酬率 / 100
#
# 再累乘
# =========================================================

strategy_df[
    "cumulative_strategy"
] = (
    (
        1
        +
        strategy_df[
            "actual_avg"
        ] / 100
    )
    .cumprod()
    -
    1
) * 100


strategy_df[
    "cumulative_market"
] = (
    (
        1
        +
        strategy_df[
            "market_avg"
        ] / 100
    )
    .cumprod()
    -
    1
) * 100


# =========================================================
# 累積超額報酬
# =========================================================

strategy_df[
    "cumulative_excess"
] = (
    strategy_df[
        "cumulative_strategy"
    ]
    -
    strategy_df[
        "cumulative_market"
    ]
)


# =========================================================
# 四捨五入
# =========================================================

round_columns = [

    "predicted_avg",

    "actual_avg",

    "market_avg",

    "excess_return",

    "cumulative_strategy",

    "cumulative_market",

    "cumulative_excess"

]


for column in round_columns:

    strategy_df[column] = (
        strategy_df[column]
        .round(4)
    )


# =========================================================
# 日期轉回文字
# =========================================================

strategy_df["date"] = (
    strategy_df["date"]
    .dt.strftime(
        "%Y-%m-%d"
    )
)


detail_df["date"] = (
    detail_df["date"]
    .dt.strftime(
        "%Y-%m-%d"
    )
)


# =========================================================
# 建立 output 資料夾
# =========================================================

output_dir = os.path.dirname(
    STRATEGY_OUTPUT_PATH
)


os.makedirs(
    output_dir,
    exist_ok=True
)


# =========================================================
# 輸出策略結果
# =========================================================

strategy_df.to_csv(
    STRATEGY_OUTPUT_PATH,
    index=False,
    encoding="utf-8-sig"
)


# =========================================================
# 輸出股票明細
# =========================================================

detail_df.to_csv(
    DETAIL_OUTPUT_PATH,
    index=False,
    encoding="utf-8-sig"
)


# =========================================================
# 最終統計
# =========================================================

total_periods = len(
    strategy_df
)


final_strategy_return = (
    strategy_df[
        "cumulative_strategy"
    ].iloc[-1]
)


final_market_return = (
    strategy_df[
        "cumulative_market"
    ].iloc[-1]
)


final_excess_return = (
    strategy_df[
        "cumulative_excess"
    ].iloc[-1]
)


average_actual = (
    strategy_df[
        "actual_avg"
    ].mean()
)


average_market = (
    strategy_df[
        "market_avg"
    ].mean()
)


win_rate = (
    strategy_df[
        "actual_avg"
    ] > 0
).mean() * 100


outperform_rate = (
    strategy_df[
        "actual_avg"
    ]
    >
    strategy_df[
        "market_avg"
    ]
).mean() * 100


# =========================================================
# 完成
# =========================================================

print()
print("=" * 70)
print("V5.4 回測完成")
print("=" * 70)


print()
print("【回測期間】")

print(
    f"{min_date.strftime('%Y-%m-%d')}"
    " ～ "
    f"{max_date.strftime('%Y-%m-%d')}"
)


print()
print("【回測統計】")

print(
    f"回測期間數：{total_periods}"
)


print(
    f"Top-{TOP_N} 平均實際報酬："
    f"{average_actual:.2f}%"
)


print(
    f"全市場平均實際報酬："
    f"{average_market:.2f}%"
)


print(
    f"Top-{TOP_N} 正報酬比例："
    f"{win_rate:.2f}%"
)


print(
    f"Top-{TOP_N} 超越市場比例："
    f"{outperform_rate:.2f}%"
)


print()
print("【累積報酬】")

print(
    f"Top-{TOP_N} 策略："
    f"{final_strategy_return:.2f}%"
)


print(
    f"全市場："
    f"{final_market_return:.2f}%"
)


print(
    f"策略超額報酬："
    f"{final_excess_return:.2f}%"
)


print()
print("【輸出檔案】")

print(
    "策略結果："
)

print(
    STRATEGY_OUTPUT_PATH
)


print()
print(
    "選股明細："
)

print(
    DETAIL_OUTPUT_PATH
)


print()
print("=" * 70)
print("V5.4 完成")
print("=" * 70)