# -*- coding: utf-8 -*-

"""
V5.9-MA200F - 空頭趨勢濾網策略（獨立版本）

規則與參數見 docs/BEAR_FILTER_PLAN.md，所有常數在看回測結果前已固定，不得為提高績效而修改。

做法：
1. 唯讀取用 V5.9 輸出（market_strategy_backtest.csv、market_strategy_detail.csv），
   選股、截尾、基準都與 V5.9 完全相同。
2. 在每個調倉日 t，只用 0050 在 t 日（含）以前的還原收盤價，判斷收盤是否低於 200 日均線。
3. 空頭訊號時持股比例降為 REDUCED_EXPOSURE，其餘為現金（報酬 0%）；暖機期不足 200 筆時維持滿倉。
4. 成本與最大回撤沿用 V5.9 的口徑。

輸出（不覆蓋 V5.9 任何檔案）：
    market_strategy_filtered_backtest.csv
    market_strategy_filtered_summary.csv
    market_strategy_filtered_groups.csv
"""

import os

import numpy as np
import pandas as pd

from myapp.ml.backtest_topn_strategy import (
    COST_ONE_WAY,
    DETAIL_FILE,
    OUTPUT_DIR,
    STRATEGY_FILE,
    TOP_N,
    calculate_max_drawdown,
    mean_ci95,
)

# ============================================================
# 固定參數（見 docs/BEAR_FILTER_PLAN.md，禁止依回測結果調整）
# ============================================================

VERSION = "V5.9-MA200F"
FILTER_SYMBOL = "0050"
MA_WINDOW = 200
REDUCED_EXPOSURE = 0.5
# 僅供敏感度報告，不取代主方案
SENSITIVITY_EXPOSURE = 0.0

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
ADJUSTED_PATH = os.path.join(PROJECT_ROOT, "adjusted_prices.csv")

FILTERED_BACKTEST_FILE = os.path.join(OUTPUT_DIR, "market_strategy_filtered_backtest.csv")
FILTERED_SUMMARY_FILE = os.path.join(OUTPUT_DIR, "market_strategy_filtered_summary.csv")
FILTERED_GROUPS_FILE = os.path.join(OUTPUT_DIR, "market_strategy_filtered_groups.csv")

# 依 0050 實際 20 日報酬（%）分組；左閉右開，最後一組含 5
GROUP_LABELS = ["<-5%", "-5%~0%", "0%~5%", ">5%"]


# ============================================================
# 濾網邏輯
# ============================================================

def compute_filter_signal(bench_df, as_of_date, window=MA_WINDOW):
    """
    回傳 as_of_date 當天的濾網訊號，只使用日期 <= as_of_date 的 0050 資料。

    bench_df 需有 date、adj_close。不足 window 筆時 available=False（不用部分均線）。
    收盤等於均線視為多頭。
    """
    as_of = pd.Timestamp(as_of_date)
    history = bench_df.loc[bench_df["date"] <= as_of].sort_values("date").tail(window)

    if len(history) < window:
        return {"available": False, "bear": False, "close": np.nan, "ma": np.nan}

    close = float(history["adj_close"].iloc[-1])
    ma = float(history["adj_close"].mean())

    return {"available": True, "bear": close < ma, "close": close, "ma": ma}


def exposure_for(signal, reduced_exposure=REDUCED_EXPOSURE):
    """空頭訊號才減碼；無訊號（暖機期）維持滿倉。"""
    return reduced_exposure if signal["available"] and signal["bear"] else 1.0


def assign_group(market_return):
    """依 0050 實際 20 日報酬（%）分組。"""
    if market_return < -5:
        return GROUP_LABELS[0]
    if market_return < 0:
        return GROUP_LABELS[1]
    if market_return <= 5:
        return GROUP_LABELS[2]
    return GROUP_LABELS[3]


def weight_change(prev_picks, prev_exposure, picks, exposure):
    """各檔等權重（持股比例 / TOP_N）下，買進加賣出的權重變動總和。"""
    prev_picks = prev_picks or set()
    prev_w = prev_exposure / TOP_N if prev_picks else 0.0
    new_w = exposure / TOP_N

    total = 0.0
    for symbol in prev_picks | picks:
        total += abs((new_w if symbol in picks else 0.0) - (prev_w if symbol in prev_picks else 0.0))

    return total


# ============================================================
# 逐期計算
# ============================================================

def build_filtered_periods(strategy_df, picks_by_date, bench_df, reduced_exposure=REDUCED_EXPOSURE):
    """
    strategy_df：V5.9 逐期結果（date、actual_avg、market_avg、turnover、…）。
    picks_by_date：{Timestamp: set(symbol)}。
    """
    rows = []
    prev_picks = None
    prev_exposure = 1.0
    cost_pct = COST_ONE_WAY * 100

    for _, row in strategy_df.sort_values("date").iterrows():
        date = pd.Timestamp(row["date"])
        picks = picks_by_date[date]
        signal = compute_filter_signal(bench_df, date)
        exposure = exposure_for(signal, reduced_exposure)

        change = weight_change(prev_picks, prev_exposure, picks, exposure)
        cost = change * cost_pct

        # 回撤口徑與 V5.9 相同：首期以 turnover=1 計雙邊成本
        dd_cost = 2 * exposure * cost_pct if prev_picks is None else cost

        gross = exposure * float(row["actual_avg"])
        net = gross - cost

        rows.append({
            "date": date,
            "filter_available": int(signal["available"]),
            "bear_signal": int(signal["bear"]),
            "bench_close": signal["close"],
            "bench_ma": signal["ma"],
            "exposure": exposure,
            "market_avg": float(row["market_avg"]),
            "v59_actual_avg": float(row["actual_avg"]),
            "v59_excess_net": float(row["excess_return_net"]),
            "v59_net_period": float(row["actual_avg"]) - float(row["turnover"]) * 2 * cost_pct,
            "actual_avg": gross,
            "net_return": net,
            "excess_return": gross - float(row["market_avg"]),
            "excess_return_net": net - float(row["market_avg"]),
            "cost": cost,
            "dd_net_period": gross - dd_cost,
            "rank_ic": row["rank_ic"],
            "direction_accuracy": row["direction_accuracy"],
            "group": assign_group(float(row["market_avg"])),
        })

        prev_picks = picks
        prev_exposure = exposure

    return pd.DataFrame(rows)


# ============================================================
# 統計
# ============================================================

def count_switches(period_df):
    """有訊號期間內，多空狀態改變的次數。"""
    state = period_df.loc[period_df["filter_available"] == 1, "bear_signal"]
    return int((state.diff().fillna(0) != 0).sum())


def group_stats(period_df, key, label):
    """單一分組的 V5.9 與濾網對照。"""
    diff = period_df["excess_return_net"] - period_df["v59_excess_net"]
    diff_mean, diff_low, diff_high = mean_ci95(diff)

    return {
        "group_by": key,
        "group": label,
        "periods": len(period_df),
        "bear_signal_periods": int(period_df["bear_signal"].sum()),
        "avg_exposure": float(period_df["exposure"].mean()),
        "v59_avg_return": float(period_df["v59_actual_avg"].mean()),
        "filtered_avg_return": float(period_df["actual_avg"].mean()),
        "v59_excess_net": float(period_df["v59_excess_net"].mean()),
        "filtered_excess_net": float(period_df["excess_return_net"].mean()),
        "diff_excess_net": diff_mean,
        "diff_ci_low": diff_low,
        "diff_ci_high": diff_high,
        "rank_ic": float(pd.to_numeric(period_df["rank_ic"], errors="coerce").mean()),
        "direction_accuracy": float(
            pd.to_numeric(period_df["direction_accuracy"], errors="coerce").mean()
        ),
        "v59_max_drawdown_net": calculate_max_drawdown(period_df["v59_net_period"]),
        "filtered_max_drawdown_net": calculate_max_drawdown(period_df["dd_net_period"]),
    }


def build_group_table(period_df, variant):
    """依 0050 實際 20 日報酬分組，以及依事前訊號分組。"""
    rows = []

    for label in GROUP_LABELS:
        subset = period_df[period_df["group"] == label]
        if not subset.empty:
            rows.append(group_stats(subset, "market_20d_return", label))

    available = period_df[period_df["filter_available"] == 1]
    for flag, label in [(0, "訊號多頭"), (1, "訊號空頭")]:
        subset = available[available["bear_signal"] == flag]
        if not subset.empty:
            rows.append(group_stats(subset, "signal", label))

    rows.append(group_stats(period_df, "all", "全部"))

    table = pd.DataFrame(rows)
    table.insert(0, "variant", variant)
    return table


def build_summary_row(period_df, variant, reduced_exposure):
    diff = period_df["excess_return_net"] - period_df["v59_excess_net"]
    diff_mean, diff_low, diff_high = mean_ci95(diff)
    _, ci_low, ci_high = mean_ci95(period_df["excess_return_net"])

    return {
        "version": VERSION,
        "variant": variant,
        "reduced_exposure": reduced_exposure,
        "backtest_periods": len(period_df),
        "start_date": period_df["date"].min().strftime("%Y-%m-%d"),
        "end_date": period_df["date"].max().strftime("%Y-%m-%d"),
        "warmup_periods": int((period_df["filter_available"] == 0).sum()),
        "bear_signal_periods": int(period_df["bear_signal"].sum()),
        "signal_switches": count_switches(period_df),
        "average_exposure": float(period_df["exposure"].mean()),
        "average_actual": float(period_df["actual_avg"].mean()),
        "average_market": float(period_df["market_avg"].mean()),
        "average_excess_net": float(period_df["excess_return_net"].mean()),
        "excess_net_ci_low": ci_low,
        "excess_net_ci_high": ci_high,
        "v59_average_excess_net": float(period_df["v59_excess_net"].mean()),
        "diff_excess_net": diff_mean,
        "diff_ci_low": diff_low,
        "diff_ci_high": diff_high,
        "max_drawdown": calculate_max_drawdown(period_df["actual_avg"]),
        "max_drawdown_net": calculate_max_drawdown(period_df["dd_net_period"]),
        "v59_max_drawdown": calculate_max_drawdown(period_df["v59_actual_avg"]),
        "v59_max_drawdown_net": calculate_max_drawdown(period_df["v59_net_period"]),
    }


# ============================================================
# 輸入輸出
# ============================================================

def load_inputs():
    for path in (STRATEGY_FILE, DETAIL_FILE, ADJUSTED_PATH):
        if not os.path.exists(path):
            raise FileNotFoundError(f"找不到必要輸入檔：{path}")

    strategy_df = pd.read_csv(STRATEGY_FILE)
    strategy_df["date"] = pd.to_datetime(strategy_df["date"])

    detail_df = pd.read_csv(DETAIL_FILE, dtype={"symbol": str})
    detail_df["date"] = pd.to_datetime(detail_df["date"])
    picks_by_date = {
        date: set(group["symbol"].str.zfill(4))
        for date, group in detail_df.groupby("date")
    }

    adjusted = pd.read_csv(ADJUSTED_PATH, dtype={"symbol": str})
    adjusted["symbol"] = adjusted["symbol"].str.strip()
    adjusted["date"] = pd.to_datetime(adjusted["date"])
    bench_df = adjusted.loc[
        adjusted["symbol"] == FILTER_SYMBOL, ["date", "adj_close"]
    ].sort_values("date")

    if bench_df.empty:
        raise ValueError(f"adjusted_prices.csv 沒有 {FILTER_SYMBOL} 的資料")

    missing = set(strategy_df["date"]) - set(picks_by_date)
    if missing:
        raise ValueError(f"選股明細缺少調倉日：{sorted(missing)[:3]}")

    return strategy_df, picks_by_date, bench_df


def main():
    strategy_df, picks_by_date, bench_df = load_inputs()

    variants = [
        ("main", REDUCED_EXPOSURE),
        ("sensitivity_cash", SENSITIVITY_EXPOSURE),
    ]

    period_tables, summary_rows, group_tables = [], [], []

    for variant, exposure in variants:
        period_df = build_filtered_periods(strategy_df, picks_by_date, bench_df, exposure)
        summary_rows.append(build_summary_row(period_df, variant, exposure))
        group_tables.append(build_group_table(period_df, variant))
        export = period_df.copy()
        export.insert(0, "variant", variant)
        export["date"] = export["date"].dt.strftime("%Y-%m-%d")
        period_tables.append(export)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    pd.concat(period_tables).to_csv(FILTERED_BACKTEST_FILE, index=False, encoding="utf-8-sig")
    pd.DataFrame(summary_rows).to_csv(FILTERED_SUMMARY_FILE, index=False, encoding="utf-8-sig")
    groups = pd.concat(group_tables)
    groups.to_csv(FILTERED_GROUPS_FILE, index=False, encoding="utf-8-sig")

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 30)
    pd.set_option("display.float_format", lambda x: f"{x:.3f}")
    print(f"{VERSION} 完成（參數已固定：MA{MA_WINDOW}，空頭持股 {REDUCED_EXPOSURE:.0%}）")
    print(pd.DataFrame(summary_rows).T)
    print(groups[groups["variant"] == "main"].drop(columns="variant").to_string(index=False))
    print("樣本少、期間自相關、存活者偏差，結果請謹慎解讀，勿據此調整參數。")


if __name__ == "__main__":
    main()
