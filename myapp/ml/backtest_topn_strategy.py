# -*- coding: utf-8 -*-

"""
V5.8 - Top-N 股票選股策略回測

功能：
1. 讀取 market_backtest.csv
2. 每個回測日期依 predicted_return_20 由高到低排序
3. 選出 Top-N 股票（預設 Top-5）
4. 計算 Top-N 預測平均報酬
5. 計算 Top-N 實際平均報酬
6. 計算全市場平均實際報酬
7. 計算 Top-N 相對於市場的超額報酬
8. 計算正報酬比例
9. 計算超越市場比例
10. 計算預測方向正確率（排除 actual_return_20 = 0）
11. 計算最佳／最差回測期間
12. 最大回撤改為 N/A（不誤導）
13. 不將重疊的 20 日報酬直接複利
14. prediction_error 定義統一為：
    actual_return_20 - predicted_return_20
15. 輸出：
    - market_strategy_backtest.csv
    - market_strategy_detail.csv
    - market_strategy_summary.csv

版本差異：

V5.6：
    將每一期 actual_return_20 直接進行複利，
    但不同回測日期的 20 日 forward return 具有高度重疊，
    容易產生失真的累積報酬。

V5.7：
    移除重疊報酬直接複利的累積績效呈現，
    改以平均實際報酬、超額報酬、正報酬比例、
    超越市場比例、方向正確率、最佳/最差期間做評估。

V5.8：
    1) prediction_error 定義統一為 actual - predicted，
       與 evaluate_forward_predictions.py 一致。
    2) 最大回撤在目前資料結構下改為 N/A，
       避免將重疊 forward return 誤解為可交易淨值路徑。

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
    計算最大回撤（目前停用版）。

    為避免誤導，本函式在「重疊 forward return」資料下不計算 MDD，
    一律回傳 NaN。未來若提供「日頻、可交易、非重疊」策略淨值序列，
    再啟用正式 MDD 計算。

    參數：
        returns: 可迭代報酬序列（目前僅做基本檢查）

    回傳：
        float("nan")
    """
    if returns is None:
        return float("nan")

    try:
        series = pd.Series(returns, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
    except Exception:
        return float("nan")

    if series.empty:
        return float("nan")

    # 目前資料型態不適合嚴謹計算 MDD，先回傳 N/A 對應值
    return float("nan")


# ============================================================
# 主程式
# ============================================================

def main():

    print()
    print("=" * 70)
    print("V5.8 - Top-N 股票選股策略回測")
    print("=" * 70)
    print()

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    if not os.path.exists(INPUT_FILE):
        print(
            f"錯誤：找不到輸入檔案：\n{INPUT_FILE}"
        )
        return

    try:
        df = pd.read_csv(INPUT_FILE)
    except Exception as e:
        print(f"讀取 market_backtest.csv 失敗：{e}")
        return

    print(f"讀取完成，共 {len(df)} 筆資料")

    required_columns = [
        "date",
        "symbol",
        "predicted_return_20",
        "actual_return_20",
    ]

    missing_columns = [
        col for col in required_columns
        if col not in df.columns
    ]

    if missing_columns:
        print(
            "錯誤：market_backtest.csv 缺少欄位："
            + ", ".join(missing_columns)
        )
        return

    df["date"] = pd.to_datetime(
        df["date"],
        errors="coerce"
    )

    df["symbol"] = normalize_symbol(df["symbol"])

    df["predicted_return_20"] = pd.to_numeric(
        df["predicted_return_20"],
        errors="coerce"
    )
    df["actual_return_20"] = pd.to_numeric(
        df["actual_return_20"],
        errors="coerce"
    )

    df = df.dropna(
        subset=[
            "date",
            "symbol",
            "predicted_return_20",
            "actual_return_20",
        ]
    ).copy()

    df = df.sort_values(
        ["date", "predicted_return_20"],
        ascending=[True, False]
    ).reset_index(drop=True)

    backtest_dates = sorted(df["date"].unique())

    if not backtest_dates:
        print("錯誤：沒有有效的回測日期。")
        return

    print(
        "回測日期："
        f"{pd.Timestamp(backtest_dates[0]).strftime('%Y-%m-%d')}"
        " ～ "
        f"{pd.Timestamp(backtest_dates[-1]).strftime('%Y-%m-%d')}"
    )
    print(f"開始進行 Top-{TOP_N} 策略回測...")
    print()

    strategy_results = []
    detail_results = []

    for backtest_date in backtest_dates:
        current_df = df[df["date"] == backtest_date].copy()

        if current_df.empty:
            continue

        current_df = current_df.sort_values(
            "predicted_return_20",
            ascending=False
        ).reset_index(drop=True)

        current_df["rank"] = current_df.index + 1

        top_df = current_df.head(TOP_N).copy()

        if top_df.empty:
            continue

        predicted_avg = float(top_df["predicted_return_20"].mean())
        actual_avg = float(top_df["actual_return_20"].mean())
        market_avg = float(current_df["actual_return_20"].mean())
        excess_return = actual_avg - market_avg

        positive_rate = float(
            (top_df["actual_return_20"] > 0).mean() * 100
        )

        outperform_market = actual_avg > market_avg

        actual_series = pd.to_numeric(
            top_df["actual_return_20"],
            errors="coerce"
        )
        pred_series = pd.to_numeric(
            top_df["predicted_return_20"],
            errors="coerce"
        )

        direction_df = pd.DataFrame({
            "actual": actual_series,
            "pred": pred_series,
        }).dropna()

        direction_df = direction_df[
            direction_df["actual"] != 0
        ]

        if direction_df.empty:
            direction_accuracy = np.nan
        else:
            direction_accuracy = float(
                (
                    np.sign(direction_df["pred"])
                    == np.sign(direction_df["actual"])
                ).mean() * 100
            )

        strategy_results.append({
            "date": pd.Timestamp(backtest_date).strftime("%Y-%m-%d"),
            "top_n": TOP_N,
            "predicted_avg": predicted_avg,
            "actual_avg": actual_avg,
            "market_avg": market_avg,
            "excess_return": excess_return,
            "positive_rate": positive_rate,
            "outperform_market": int(outperform_market),
            "direction_accuracy": direction_accuracy,
        })

        for _, stock in top_df.iterrows():
            detail_results.append({
                "date": pd.Timestamp(backtest_date).strftime("%Y-%m-%d"),
                "rank": int(stock["rank"]),
                "symbol": str(stock["symbol"]).zfill(4),
                "predicted_return_20": float(stock["predicted_return_20"]),
                "actual_return_20": float(stock["actual_return_20"]),
                "prediction_error": float(
                    stock["actual_return_20"] - stock["predicted_return_20"]
                ),
            })

    strategy_df = pd.DataFrame(strategy_results)
    detail_df = pd.DataFrame(detail_results)

    if strategy_df.empty:
        print("錯誤：沒有產生策略回測結果。")
        return

    strategy_df["date"] = pd.to_datetime(strategy_df["date"])
    strategy_df = strategy_df.sort_values("date").reset_index(drop=True)

    detail_df["date"] = pd.to_datetime(detail_df["date"])
    detail_df = detail_df.sort_values(
        ["date", "rank"]
    ).reset_index(drop=True)

    max_drawdown = calculate_max_drawdown(strategy_df["actual_avg"])

    average_excess = float(strategy_df["excess_return"].mean())
    average_actual = float(strategy_df["actual_avg"].mean())
    average_market = float(strategy_df["market_avg"].mean())

    positive_return_rate = float(
        (strategy_df["actual_avg"] > 0).mean() * 100
    )

    outperform_rate = float(
        strategy_df["outperform_market"].mean() * 100
    )

    valid_direction = pd.to_numeric(
        strategy_df["direction_accuracy"],
        errors="coerce"
    ).dropna()

    average_direction_accuracy = (
        float(valid_direction.mean())
        if not valid_direction.empty
        else float("nan")
    )

    best_row = strategy_df.loc[strategy_df["actual_avg"].idxmax()]
    best_date = pd.Timestamp(best_row["date"]).strftime("%Y-%m-%d")
    best_return = float(best_row["actual_avg"])

    worst_row = strategy_df.loc[strategy_df["actual_avg"].idxmin()]
    worst_date = pd.Timestamp(worst_row["date"]).strftime("%Y-%m-%d")
    worst_return = float(worst_row["actual_avg"])

    start_date = strategy_df["date"].min()
    end_date = strategy_df["date"].max()
    backtest_periods = len(strategy_df)

    max_drawdown_value = (
        "N/A"
        if pd.isna(max_drawdown)
        else round(float(max_drawdown), 4)
    )

    summary_df = pd.DataFrame([{
        "version": "V5.8",
        "top_n": TOP_N,
        "backtest_periods": backtest_periods,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "average_actual": average_actual,
        "average_market": average_market,
        "average_excess": average_excess,
        "positive_return_rate": positive_return_rate,
        "outperform_rate": outperform_rate,
        "direction_accuracy": average_direction_accuracy,
        "max_drawdown": max_drawdown_value,
        "best_date": best_date,
        "best_return": best_return,
        "worst_date": worst_date,
        "worst_return": worst_return,
    }])

    strategy_export = strategy_df.copy()
    strategy_export["date"] = strategy_export["date"].dt.strftime("%Y-%m-%d")

    detail_export = detail_df.copy()
    detail_export["date"] = detail_export["date"].dt.strftime("%Y-%m-%d")

    strategy_export.to_csv(
        STRATEGY_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    detail_export.to_csv(
        DETAIL_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    summary_df.to_csv(
        SUMMARY_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    print()
    print("【回測統計】")
    print(f"回測期間數：{backtest_periods}")
    print(f"Top-{TOP_N} 平均實際報酬：{average_actual:.2f}%")
    print(f"全市場平均實際報酬：{average_market:.2f}%")
    print(f"平均超額報酬：{average_excess:.2f}%")
    print(f"Top-{TOP_N} 正報酬比例：{positive_return_rate:.2f}%")
    print(f"Top-{TOP_N} 超越市場比例：{outperform_rate:.2f}%")
    print(f"預測方向正確率：{average_direction_accuracy:.2f}%")

    print()
    print("【V5.8 策略績效分析】")
    print(f"平均超額報酬：{average_excess:.2f}%")

    if pd.isna(max_drawdown):
        print("最大回撤：N/A（重疊 forward return 不直接計算）")
    else:
        print(f"最大回撤：{max_drawdown:.2f}%")

    print(f"最佳回測期間：{best_date} ({best_return:.2f}%)")
    print(f"最差回測期間：{worst_date} ({worst_return:.2f}%)")
    print(f"預測方向正確率：{average_direction_accuracy:.2f}%")

    print()
    print("【V5.8 回測說明】")
    print("本版本不再計算重疊 20 日報酬的累積複利績效。")
    print("actual_return_20 僅用於評估模型的未來 20 日報酬預測與選股能力。")
    print("因此不再輸出 V5.6 的1153.97% 類型累積報酬。")

    print()
    print("【輸出檔案】")
    print("策略結果：")
    print(STRATEGY_FILE)
    print()
    print("選股明細：")
    print(DETAIL_FILE)
    print()
    print("V5.8 績效摘要：")
    print(SUMMARY_FILE)

    print()
    print("V5.8 完成")
    print("=" * 70)


# ============================================================
# 程式進入點
# ============================================================

if __name__ == "__main__":

    main()