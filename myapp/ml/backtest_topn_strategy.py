# -*- coding: utf-8 -*-

"""
V5.7 - Top-N 股票選股策略回測

功能：
1. 讀取 market_backtest.csv
2. 每個回測日期依 predicted_return_20 由高到低排序
3. 選出 Top-5 股票
4. 計算 Top-5 預測平均報酬
5. 計算 Top-5 實際平均報酬
6. 計算全市場平均實際報酬
7. 計算 Top-5 相對於市場的超額報酬
8. 計算正報酬比例
9. 計算超越市場比例
10. 計算預測方向正確率
11. 計算最佳／最差回測期間
12. 計算最大回撤
13. 不再將重疊的 20 日報酬直接複利
14. 輸出：
    - market_strategy_backtest.csv
    - market_strategy_detail.csv
    - market_strategy_summary.csv

V5.7 主要修正：

V5.6：
    將每一期 actual_return_20 直接進行複利，
    但不同回測日期的 20 日 forward return
    具有高度重疊，因此容易產生失真的累積報酬。

V5.7：
    移除這種累積報酬計算。

    改以：
    - 平均實際報酬
    - 平均超額報酬
    - 正報酬比例
    - 超越市場比例
    - 預測方向正確率
    - 最大回撤
    - 最佳／最差期間

    作為策略績效指標。

注意：
    actual_return_20 是未來 20 個交易日的 forward return，
    用於模型預測能力與選股能力評估。

    本版本不將重疊的 20 日 forward return
    宣稱為可直接複利的投資組合累積報酬。
"""

import os
import pandas as pd
import numpy as np


# ============================================================
# 基本設定
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

OUTPUT_DIR = os.path.join(
    BASE_DIR,
    "output"
)


INPUT_FILE = os.path.join(
    OUTPUT_DIR,
    "market_backtest.csv"
)


STRATEGY_FILE = os.path.join(
    OUTPUT_DIR,
    "market_strategy_backtest.csv"
)


DETAIL_FILE = os.path.join(
    OUTPUT_DIR,
    "market_strategy_detail.csv"
)


SUMMARY_FILE = os.path.join(
    OUTPUT_DIR,
    "market_strategy_summary.csv"
)


# ============================================================
# 策略設定
# ============================================================

TOP_N = 5


# ============================================================
# 輸出格式
# ============================================================

pd.set_option(
    "display.width",
    160
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
# 工具函式
# ============================================================

def normalize_symbol(series):
    """
    統一股票代號格式。

    例如：
        50      -> 0050
        2330    -> 2330
        0050.0  -> 0050
    """

    return (
        series
        .astype(str)
        .str.replace(
            ".0",
            "",
            regex=False
        )
        .str.strip()
        .str.zfill(4)
    )


# ============================================================
# 計算最大回撤
# ============================================================

def calculate_max_drawdown(returns):
    """
    使用每期 Top-N 實際報酬計算策略回撤。

    注意：
    這裡不是用原本 V5.6 的重疊累積報酬。

    而是建立一條「描述性績效序列」，
    用來觀察策略報酬的高低點與回撤。

    returns：
        每一期的 actual_avg，
        單位為百分比。

    回傳：
        最大回撤百分比
    """

    if returns is None:
        return 0.0

    returns = pd.Series(
        returns,
        dtype=float
    ).dropna()

    if returns.empty:
        return 0.0

    # --------------------------------------------------------
    # 建立描述性績效指數
    #
    # 每一期以：
    # 1 + return
    #
    # 建立績效序列。
    #
    # 這個值只用來分析 drawdown，
    # 不作為投資組合累積報酬對外宣稱。
    # --------------------------------------------------------

    index = (
        1
        + returns / 100
    ).cumprod()

    running_max = index.cummax()

    drawdown = (
        index / running_max - 1
    ) * 100

    return float(
        drawdown.min()
    )


# ============================================================
# 主程式
# ============================================================

def main():

    print()
    print("=" * 70)
    print("V5.7 - Top-N 股票選股策略回測")
    print("=" * 70)
    print()


    # ========================================================
    # 建立輸出資料夾
    # ========================================================

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )


    # ========================================================
    # 檢查輸入檔案
    # ========================================================

    if not os.path.exists(INPUT_FILE):

        print(
            f"錯誤：找不到輸入檔案：\n{INPUT_FILE}"
        )

        return


    # ========================================================
    # 讀取資料
    # ========================================================

    try:

        df = pd.read_csv(
            INPUT_FILE
        )

    except Exception as e:

        print(
            f"讀取 market_backtest.csv 失敗：{e}"
        )

        return


    print(
        f"讀取完成，共 {len(df)} 筆資料"
    )


    # ========================================================
    # 檢查必要欄位
    # ========================================================

    required_columns = [
        "date",
        "symbol",
        "predicted_return_20",
        "actual_return_20",
    ]


    missing_columns = [
        col
        for col in required_columns
        if col not in df.columns
    ]


    if missing_columns:

        print(
            "錯誤：market_backtest.csv 缺少欄位："
            + ", ".join(missing_columns)
        )

        return


    # ========================================================
    # 日期處理
    # ========================================================

    df["date"] = pd.to_datetime(
        df["date"],
        errors="coerce"
    )


    # ========================================================
    # 股票代號
    # ========================================================

    df["symbol"] = normalize_symbol(
        df["symbol"]
    )


    # ========================================================
    # 數值欄位
    # ========================================================

    df["predicted_return_20"] = pd.to_numeric(
        df["predicted_return_20"],
        errors="coerce"
    )


    df["actual_return_20"] = pd.to_numeric(
        df["actual_return_20"],
        errors="coerce"
    )


    # ========================================================
    # 移除無效資料
    # ========================================================

    df = df.dropna(
        subset=[
            "date",
            "symbol",
            "predicted_return_20",
            "actual_return_20",
        ]
    ).copy()


    # ========================================================
    # 日期排序
    # ========================================================

    df = df.sort_values(
        [
            "date",
            "predicted_return_20",
        ],
        ascending=[
            True,
            False,
        ]
    ).reset_index(
        drop=True
    )


    # ========================================================
    # 回測日期
    # ========================================================

    backtest_dates = sorted(
        df["date"].unique()
    )


    if not backtest_dates:

        print(
            "錯誤：沒有有效的回測日期。"
        )

        return


    print(
        "回測日期："
        f"{pd.Timestamp(backtest_dates[0]).strftime('%Y-%m-%d')}"
        " ～ "
        f"{pd.Timestamp(backtest_dates[-1]).strftime('%Y-%m-%d')}"
    )


    print(
        f"開始進行 Top-{TOP_N} 策略回測..."
    )

    print()


    # ========================================================
    # 儲存結果
    # ========================================================

    strategy_results = []

    detail_results = []


    # ========================================================
    # 每個日期進行回測
    # ========================================================

    for backtest_date in backtest_dates:

        current_df = df[
            df["date"] == backtest_date
        ].copy()


        if current_df.empty:
            continue


        # ====================================================
        # 預測報酬排序
        # ====================================================

        current_df = current_df.sort_values(
            "predicted_return_20",
            ascending=False
        ).reset_index(
            drop=True
        )


        # ====================================================
        # 建立 Rank
        # ====================================================

        current_df["rank"] = (
            current_df.index + 1
        )


        # ====================================================
        # Top-N
        # ====================================================

        top_df = current_df.head(
            TOP_N
        ).copy()


        if top_df.empty:
            continue


        # ====================================================
        # Top-N 預測平均
        # ====================================================

        predicted_avg = float(
            top_df[
                "predicted_return_20"
            ].mean()
        )


        # ====================================================
        # Top-N 實際平均
        # ====================================================

        actual_avg = float(
            top_df[
                "actual_return_20"
            ].mean()
        )


        # ====================================================
        # 全市場平均
        # ====================================================

        market_avg = float(
            current_df[
                "actual_return_20"
            ].mean()
        )


        # ====================================================
        # 超額報酬
        #
        # Top-N - 全市場
        # ====================================================

        excess_return = (
            actual_avg
            - market_avg
        )


        # ====================================================
        # Top-N 正報酬比例
        # ====================================================

        positive_rate = float(
            (
                top_df[
                    "actual_return_20"
                ] > 0
            ).mean()
            * 100
        )


        # ====================================================
        # Top-N 超越市場比例
        #
        # 這裡使用：
        #
        # actual_avg > market_avg
        #
        # 判斷該回測期間是否超越市場。
        # ====================================================

        outperform_market = (
            actual_avg > market_avg
        )


        # ====================================================
        # 預測方向正確率
        #
        # predicted > 0 且 actual > 0
        # 或
        # predicted < 0 且 actual < 0
        #
        # 判斷模型方向是否一致。
        # ====================================================

        predicted_direction = (
            top_df[
                "predicted_return_20"
            ] >= 0
        )


        actual_direction = (
            top_df[
                "actual_return_20"
            ] >= 0
        )


        direction_accuracy = float(
            (
                predicted_direction
                == actual_direction
            ).mean()
            * 100
        )


        # ====================================================
        # 策略結果
        # ====================================================

        strategy_results.append({

            "date":
                pd.Timestamp(
                    backtest_date
                ).strftime(
                    "%Y-%m-%d"
                ),

            "top_n":
                TOP_N,

            "predicted_avg":
                predicted_avg,

            "actual_avg":
                actual_avg,

            "market_avg":
                market_avg,

            "excess_return":
                excess_return,

            "positive_rate":
                positive_rate,

            "outperform_market":
                int(
                    outperform_market
                ),

            "direction_accuracy":
                direction_accuracy,

        })


        # ====================================================
        # Top-N 明細
        # ====================================================

        for _, stock in top_df.iterrows():

            detail_results.append({

                "date":
                    pd.Timestamp(
                        backtest_date
                    ).strftime(
                        "%Y-%m-%d"
                    ),

                "rank":
                    int(
                        stock["rank"]
                    ),

                "symbol":
                    str(
                        stock["symbol"]
                    ).zfill(4),

                "predicted_return_20":
                    float(
                        stock[
                            "predicted_return_20"
                        ]
                    ),

                "actual_return_20":
                    float(
                        stock[
                            "actual_return_20"
                        ]
                    ),

                "prediction_error":
                    float(
                        stock[
                            "predicted_return_20"
                        ]
                        -
                        stock[
                            "actual_return_20"
                        ]
                    ),

            })


    # ========================================================
    # 轉 DataFrame
    # ========================================================

    strategy_df = pd.DataFrame(
        strategy_results
    )


    detail_df = pd.DataFrame(
        detail_results
    )


    if strategy_df.empty:

        print(
            "錯誤：沒有產生策略回測結果。"
        )

        return


    # ========================================================
    # 日期排序
    # ========================================================

    strategy_df["date"] = pd.to_datetime(
        strategy_df["date"]
    )


    strategy_df = strategy_df.sort_values(
        "date"
    ).reset_index(
        drop=True
    )


    detail_df["date"] = pd.to_datetime(
        detail_df["date"]
    )


    detail_df = detail_df.sort_values(
        [
            "date",
            "rank",
        ]
    ).reset_index(
        drop=True
    )


    # ========================================================
    # V5.7 最大回撤
    # ========================================================

    max_drawdown = calculate_max_drawdown(
        strategy_df[
            "actual_avg"
        ]
    )


    # ========================================================
    # 平均超額報酬
    # ========================================================

    average_excess = float(
        strategy_df[
            "excess_return"
        ].mean()
    )


    # ========================================================
    # 平均 Top-N 實際報酬
    # ========================================================

    average_actual = float(
        strategy_df[
            "actual_avg"
        ].mean()
    )


    # ========================================================
    # 平均市場實際報酬
    # ========================================================

    average_market = float(
        strategy_df[
            "market_avg"
        ].mean()
    )


    # ========================================================
    # Top-N 正報酬比例
    # ========================================================

    positive_return_rate = float(
        (
            strategy_df[
                "actual_avg"
            ] > 0
        ).mean()
        * 100
    )


    # ========================================================
    # 超越市場比例
    # ========================================================

    outperform_rate = float(
        strategy_df[
            "outperform_market"
        ].mean()
        * 100
    )


    # ========================================================
    # 平均預測方向正確率
    # ========================================================

    average_direction_accuracy = float(
        strategy_df[
            "direction_accuracy"
        ].mean()
    )


    # ========================================================
    # 最佳回測期間
    # ========================================================

    best_row = strategy_df.loc[
        strategy_df[
            "actual_avg"
        ].idxmax()
    ]


    best_date = (
        pd.Timestamp(
            best_row["date"]
        ).strftime(
            "%Y-%m-%d"
        )
    )


    best_return = float(
        best_row[
            "actual_avg"
        ]
    )


    # ========================================================
    # 最差回測期間
    # ========================================================

    worst_row = strategy_df.loc[
        strategy_df[
            "actual_avg"
        ].idxmin()
    ]


    worst_date = (
        pd.Timestamp(
            worst_row["date"]
        ).strftime(
            "%Y-%m-%d"
        )
    )


    worst_return = float(
        worst_row[
            "actual_avg"
        ]
    )


    # ========================================================
    # 回測期間
    # ========================================================

    start_date = (
        strategy_df[
            "date"
        ].min()
    )


    end_date = (
        strategy_df[
            "date"
        ].max()
    )


    # ========================================================
    # 回測日期數
    # ========================================================

    backtest_periods = len(
        strategy_df
    )


    # ========================================================
    # V5.7 Summary
    # ========================================================

    summary_df = pd.DataFrame([{

        "version":
            "V5.7",

        "top_n":
            TOP_N,

        "backtest_periods":
            backtest_periods,

        "start_date":
            start_date.strftime(
                "%Y-%m-%d"
            ),

        "end_date":
            end_date.strftime(
                "%Y-%m-%d"
            ),

        "average_actual":
            average_actual,

        "average_market":
            average_market,

        "average_excess":
            average_excess,

        "positive_return_rate":
            positive_return_rate,

        "outperform_rate":
            outperform_rate,

        "direction_accuracy":
            average_direction_accuracy,

        "max_drawdown":
            max_drawdown,

        "best_date":
            best_date,

        "best_return":
            best_return,

        "worst_date":
            worst_date,

        "worst_return":
            worst_return,

    }])


    # ========================================================
    # 輸出前處理
    # ========================================================

    strategy_export = strategy_df.copy()


    strategy_export["date"] = (
        strategy_export["date"]
        .dt.strftime(
            "%Y-%m-%d"
        )
    )


    detail_export = detail_df.copy()


    detail_export["date"] = (
        detail_export["date"]
        .dt.strftime(
            "%Y-%m-%d"
        )
    )


    # ========================================================
    # 輸出策略結果
    # ========================================================

    strategy_export.to_csv(
        STRATEGY_FILE,
        index=False,
        encoding="utf-8-sig"
    )


    # ========================================================
    # 輸出 Top-N 明細
    # ========================================================

    detail_export.to_csv(
        DETAIL_FILE,
        index=False,
        encoding="utf-8-sig"
    )


    # ========================================================
    # 輸出 V5.7 Summary
    # ========================================================

    summary_df.to_csv(
        SUMMARY_FILE,
        index=False,
        encoding="utf-8-sig"
    )


    # ========================================================
    # Console Summary
    # ========================================================

    print()
    print("【回測統計】")

    print(
        f"回測期間數："
        f"{backtest_periods}"
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
        f"平均超額報酬："
        f"{average_excess:.2f}%"
    )

    print(
        f"Top-{TOP_N} 正報酬比例："
        f"{positive_return_rate:.2f}%"
    )

    print(
        f"Top-{TOP_N} 超越市場比例："
        f"{outperform_rate:.2f}%"
    )

    print(
        f"預測方向正確率："
        f"{average_direction_accuracy:.2f}%"
    )


    # ========================================================
    # V5.7 績效分析
    # ========================================================

    print()
    print("【V5.7 策略績效分析】")

    print(
        f"平均超額報酬："
        f"{average_excess:.2f}%"
    )

    print(
        f"最大回撤："
        f"{max_drawdown:.2f}%"
    )

    print(
        f"最佳回測期間："
        f"{best_date} "
        f"({best_return:.2f}%)"
    )

    print(
        f"最差回測期間："
        f"{worst_date} "
        f"({worst_return:.2f}%)"
    )

    print(
        f"預測方向正確率："
        f"{average_direction_accuracy:.2f}%"
    )


    # ========================================================
    # 注意事項
    # ========================================================

    print()
    print("【V5.7 回測說明】")

    print(
        "本版本不再計算重疊 20 日報酬的累積複利績效。"
    )

    print(
        "actual_return_20 僅用於評估模型的"
        "未來 20 日報酬預測與選股能力。"
    )

    print(
        "因此不再輸出 V5.6 的"
        "1153.97% 類型累積報酬。"
    )


    # ========================================================
    # 輸出檔案
    # ========================================================

    print()
    print("【輸出檔案】")

    print(
        "策略結果："
    )

    print(
        STRATEGY_FILE
    )

    print()

    print(
        "選股明細："
    )

    print(
        DETAIL_FILE
    )

    print()

    print(
        "V5.7 績效摘要："
    )

    print(
        SUMMARY_FILE
    )


    print()
    print(
        "V5.7 完成"
    )

    print("=" * 70)


# ============================================================
# 程式進入點
# ============================================================

if __name__ == "__main__":

    main()