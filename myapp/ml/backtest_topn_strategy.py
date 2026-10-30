# -*- coding: utf-8 -*-

"""
V5.9 - Top-N 股票選股策略回測

功能：
1. 讀取 market_backtest.csv
2. 每個回測日期依 predicted_return_20 由高到低排序
3. 選出 Top-N 股票（預設 Top-10）
4. 計算 Top-N 預測平均報酬
5. 計算 Top-N 實際平均報酬
6. 計算全市場平均實際報酬
7. 計算 Top-N 相對於市場的超額報酬
8. 計算正報酬比例
9. 計算超越市場比例
10. 計算預測方向正確率（排除 actual_return_20 = 0）
11. 計算最佳／最差回測期間
12. 最大回撤維持 N/A（避免重疊 forward return 誤導）
13. 不將重疊的 20 日報酬直接複利
14. prediction_error 定義統一為：
    actual_return_20 - predicted_return_20
15. 額外診斷：
    - 每期 Rank IC（Spearman）
    - 每期前半部勝率（Top half hit rate）
16. 輸出：
    - market_strategy_backtest.csv
    - market_strategy_detail.csv
    - market_strategy_summary.csv
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

TOP_N = 10


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


def calculate_max_drawdown(returns):
    """
    計算最大回撤（目前停用版）。

    為避免誤導，本函式在「重疊 forward return」資料下不計算 MDD，
    一律回傳 NaN。
    """
    if returns is None:
        return float("nan")

    try:
        series = (
            pd.Series(returns, dtype="float64")
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
        )
    except Exception:
        return float("nan")

    if series.empty:
        return float("nan")

    return float("nan")


def validate_backtest_input(df, top_n):
    """
    嚴格檢查輸入資料，避免先刪資料再選股造成偏差。
    """
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
        raise ValueError(
            "market_backtest.csv 缺少欄位："
            + ", ".join(missing_columns)
        )

    invalid_mask = df[required_columns].isna().any(axis=1)

    for col in ["predicted_return_20", "actual_return_20"]:
        invalid_mask |= ~np.isfinite(df[col])

    invalid_mask |= df["symbol"].astype(str).str.strip().str.lower().isin(
        ["", "nan", "none", "<na>"]
    )

    if invalid_mask.any():
        sample = df.loc[invalid_mask, required_columns].head(10)
        raise ValueError(
            "輸入資料含缺值、無限值或無效代號，已停止。\n"
            + sample.to_string(index=False)
        )

    duplicate_mask = df.duplicated(
        subset=["date", "symbol"],
        keep=False
    )

    if duplicate_mask.any():
        sample = df.loc[duplicate_mask, required_columns].head(10)
        raise ValueError(
            "發現同日同股重複資料，已停止。\n"
            + sample.to_string(index=False)
        )

    counts = df.groupby("date")["symbol"].nunique()
    insufficient = counts[counts < top_n]

    if not insufficient.empty:
        raise ValueError(
            f"部分日期股票數不足 TOP_N={top_n}：\n"
            + insufficient.to_string()
        )


def calc_rank_ic(current_df):
    """
    橫截面 Spearman Rank IC：
    predicted 越高，actual 是否越高。
    """
    x = pd.to_numeric(
        current_df["predicted_return_20"],
        errors="coerce"
    )
    y = pd.to_numeric(
        current_df["actual_return_20"],
        errors="coerce"
    )

    valid = (
        x.notna()
        & y.notna()
        & np.isfinite(x)
        & np.isfinite(y)
    )

    if valid.sum() < 3:
        return float("nan")

    rank_x = x[valid].rank(method="average")
    rank_y = y[valid].rank(method="average")

    if rank_x.nunique() < 2 or rank_y.nunique() < 2:
        return float("nan")

    corr = rank_x.corr(rank_y, method="pearson")

    if pd.isna(corr):
        return float("nan")

    return float(corr)


# ============================================================
# 主程式
# ============================================================

def run_mom20_benchmark(df):
    """並列對照：以 return_20（過去 20 日漲幅）取 Top-N，與 ML 主排名同日期比較。"""
    if "return_20" not in df.columns:
        return None

    rows = []

    for backtest_date, current_df in df.groupby("date"):
        current_df = current_df.dropna(subset=["return_20"])

        if len(current_df) < TOP_N:
            continue

        top_df = current_df.sort_values(
            "return_20", ascending=False
        ).head(TOP_N)

        actual_avg = float(top_df["actual_return_20"].mean())
        market_avg = float(current_df["actual_return_20"].mean())

        rows.append({
            "date": pd.Timestamp(backtest_date).strftime("%Y-%m-%d"),
            "actual_avg": actual_avg,
            "market_avg": market_avg,
            "excess_return": actual_avg - market_avg,
            "positive_rate": float((top_df["actual_return_20"] > 0).mean() * 100),
            "outperform_market": int(actual_avg > market_avg),
        })

    if not rows:
        return None

    return pd.DataFrame(rows)


def main():

    print()
    print("=" * 70)
    print("V5.9 - Top-N 股票選股策略回測")
    print("=" * 70)
    print()

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    if not os.path.exists(INPUT_FILE):
        print(f"錯誤：找不到輸入檔案：\n{INPUT_FILE}")
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

    try:
        validate_backtest_input(df, TOP_N)
    except ValueError as exc:
        print(f"錯誤：{exc}")
        return

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
    top_half_hit_list = []

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

        rank_ic = calc_rank_ic(current_df)

        half_n = max(1, len(current_df) // 2)
        top_half = current_df.head(half_n)
        top_half_hit = float(
            (top_half["actual_return_20"] > 0).mean() * 100
        )
        top_half_hit_list.append(top_half_hit)

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
            "rank_ic": rank_ic,
            "top_half_hit_rate": top_half_hit,
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

    mom20_df = run_mom20_benchmark(df)

    if mom20_df is not None:
        mom20_path = os.path.join(OUTPUT_DIR, "market_strategy_mom20_benchmark.csv")
        mom20_df.to_csv(mom20_path, index=False, encoding="utf-8-sig")
        print()
        print(f"【mom20 並列對照】（期數 {len(mom20_df)}）")
        print(f"Top-{TOP_N} 平均超額報酬：{mom20_df['excess_return'].mean():.2f}%")
        print(f"超越市場比例：{mom20_df['outperform_market'].mean() * 100:.2f}%")
        print(f"正報酬比例：{mom20_df['positive_rate'].mean():.2f}%")
        print(f"輸出：{mom20_path}")

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

    rank_ic_series = pd.to_numeric(
        strategy_df["rank_ic"],
        errors="coerce"
    ).dropna()

    average_rank_ic = (
        float(rank_ic_series.mean())
        if not rank_ic_series.empty
        else float("nan")
    )

    top_half_hit_rate = (
        float(np.mean(top_half_hit_list))
        if top_half_hit_list
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
        "version": "V5.9",
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
        "average_rank_ic": average_rank_ic,
        "top_half_hit_rate": top_half_hit_rate,
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
    print(f"平均 RankIC：{average_rank_ic:.4f}")
    print(f"前半部勝率：{top_half_hit_rate:.2f}%")

    print()
    print("【V5.9 策略績效分析】")
    print(f"平均超額報酬：{average_excess:.2f}%")

    if pd.isna(max_drawdown):
        print("最大回撤：N/A（重疊 forward return 不直接計算）")
    else:
        print(f"最大回撤：{max_drawdown:.2f}%")

    print(f"最佳回測期間：{best_date} ({best_return:.2f}%)")
    print(f"最差回測期間：{worst_date} ({worst_return:.2f}%)")
    print(f"預測方向正確率：{average_direction_accuracy:.2f}%")

    print()
    print("【V5.9 回測說明】")
    print("本版本不再計算重疊 20 日報酬的累積複利績效。")
    print("actual_return_20 僅用於評估模型的未來 20 日報酬預測與選股能力。")
    print("因此不再輸出 V5.6 的累積報酬型指標。")

    print()
    print("【輸出檔案】")
    print("策略結果：")
    print(STRATEGY_FILE)
    print()
    print("選股明細：")
    print(DETAIL_FILE)
    print()
    print("V5.9 績效摘要：")
    print(SUMMARY_FILE)

    print()
    print("V5.9 完成")
    print("=" * 70)


# ============================================================
# 程式進入點
# ============================================================

if __name__ == "__main__":
    main()