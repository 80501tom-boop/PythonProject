# -*- coding: utf-8 -*-
"""
Top-10 策略（49 檔選股池）與 0050 基準比較

功能：
1. 讀取 market_backtest.csv（0050 基準來自 bench_return_20）。
2. 讀取 market_strategy_detail.csv。
3. 比較 Top-10 策略與 0050 的實際報酬。
4. 輸出比較圖表 PNG、PDF 與 CSV。
5. 顯示中文統計摘要。

本次微修正：
- 圖表標題、座標軸與圖例使用英文。
- 移除遮擋折線的摘要框。
- 圖例移至圖表上方。
- 不修改原有報酬率計算方式。
"""

from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import MultipleLocator, FuncFormatter


# =====================================
# 路徑設定
# =====================================

BASE_DIR = Path(__file__).resolve().parents[1]

BACKTEST_FILE = (
    BASE_DIR
    / "myapp"
    / "ml"
    / "output"
    / "market_backtest.csv"
)

STRATEGY_DETAIL_FILE = (
    BASE_DIR
    / "myapp"
    / "ml"
    / "output"
    / "market_strategy_detail.csv"
)

REPORT_DIR = BASE_DIR / "scripts" / "reports"

PNG_FILE = REPORT_DIR / "top10_vs_0050.png"
PDF_FILE = REPORT_DIR / "top10_vs_0050.pdf"
CSV_FILE = REPORT_DIR / "top10_vs_0050.csv"


# =====================================
# 圖表設定
# =====================================

plt.rcParams["axes.unicode_minus"] = False


# =====================================
# 讀取及整理比較資料
# =====================================

def load_comparison_data():

    if not BACKTEST_FILE.exists():
        raise FileNotFoundError(
            f"找不到回測資料：{BACKTEST_FILE}"
        )

    if not STRATEGY_DETAIL_FILE.exists():
        raise FileNotFoundError(
            f"找不到策略明細：{STRATEGY_DETAIL_FILE}"
        )

    # 讀取原有回測資料
    backtest_df = pd.read_csv(BACKTEST_FILE)

    # 讀取 Top-10 策略明細
    strategy_df = pd.read_csv(STRATEGY_DETAIL_FILE)

    required_columns = {
        "date",
        "symbol",
        "actual_return_20",
    }

    # 檢查回測資料欄位（0050 基準來自 bench_return_20）
    missing_backtest = (
        required_columns | {"bench_return_20"}
    ) - set(backtest_df.columns)

    if missing_backtest:
        raise ValueError(
            "market_backtest.csv 缺少必要欄位："
            f"{sorted(missing_backtest)}"
        )

    # 檢查策略資料欄位
    missing_strategy = (
        required_columns - set(strategy_df.columns)
    )

    if missing_strategy:
        raise ValueError(
            "market_strategy_detail.csv 缺少必要欄位："
            f"{sorted(missing_strategy)}"
        )

    # 日期統一轉換格式
    backtest_df["date"] = pd.to_datetime(
        backtest_df["date"],
        errors="coerce",
    )

    strategy_df["date"] = pd.to_datetime(
        strategy_df["date"],
        errors="coerce",
    )

    # 報酬率轉換為數值
    backtest_df["actual_return_20"] = pd.to_numeric(
        backtest_df["actual_return_20"],
        errors="coerce",
    )

    backtest_df["bench_return_20"] = pd.to_numeric(
        backtest_df["bench_return_20"],
        errors="coerce",
    )

    strategy_df["actual_return_20"] = pd.to_numeric(
        strategy_df["actual_return_20"],
        errors="coerce",
    )

    # 移除必要資料缺失的列
    backtest_df = backtest_df.dropna(
        subset=["date", "symbol", "actual_return_20"]
    )

    strategy_df = strategy_df.dropna(
        subset=["date", "symbol", "actual_return_20"]
    )

    # 每個回測日期的 Top-10 平均實際報酬
    top5_returns = (
        strategy_df
        .groupby("date")["actual_return_20"]
        .mean()
        .rename("top5_avg_return")
    )

    # 每個回測日期的 0050 同期實際報酬（基準）
    market_returns = (
        backtest_df
        .dropna(subset=["bench_return_20"])
        .groupby("date")["bench_return_20"]
        .first()
        .rename("market_avg_return")
    )

    # 合併相同回測日期
    result = pd.concat(
        [top5_returns, market_returns],
        axis=1,
        join="inner",
    ).dropna()

    result = result.reset_index().sort_values("date")

    if result.empty:
        raise ValueError(
            "沒有可比較的共同回測日期，"
            "請確認兩份 CSV 的日期資料。"
        )

    # 超額報酬：Top-10 平均報酬減去 0050 報酬
    result["excess_return"] = (
        result["top5_avg_return"]
        - result["market_avg_return"]
    )

    return result, backtest_df



# ==================================================
# 繪製圖表
# ==================================================

def plot_comparison(result):

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    dates = result["date"]
    top5 = result["top5_avg_return"]
    market = result["market_avg_return"]

    fig, ax = plt.subplots(figsize=(11, 5.8))

    ax.plot(
        dates,
        top5,
        marker="o",
        markersize=3,
        linewidth=1.8,
        label="Top-10 Strategy",
    )

    ax.plot(
        dates,
        market,
        marker="s",
        markersize=3,
        linewidth=1.5,
        label="0050 Benchmark",
    )

    ax.axhline(
        0,
        linewidth=0.8,
        linestyle="--",
        color="gray",
    )

    ax.set_title(
        "Top-10 Strategy (49-Stock Pool) vs. 0050",
        fontsize=15,
        pad=14,
    )

    ax.set_xlabel("Backtest Date", fontsize=11)

    ax.set_ylabel(
        "Actual Return (%)",
        fontsize=10,
        labelpad=8,
    )

    ax.grid(
        True,
        linestyle="--",
        alpha=0.3,
    )

    # 圖例
    ax.legend(
        loc="best",
        fontsize=9,
        frameon=False,
    )

    # 顯示更詳細的日期，最多約 10 個刻度
    import matplotlib.dates as mdates

    ax.xaxis.set_major_locator(
        mdates.AutoDateLocator(
            minticks=6,
            maxticks=10,
        )
    )

    ax.xaxis.set_major_formatter(
        mdates.DateFormatter("%Y-%m-%d")
    )

    plt.setp(
        ax.get_xticklabels(),
        rotation=35,
        ha="right",
        fontsize=9,
    )

    fig.tight_layout()

    fig.savefig(
        PNG_FILE,
        dpi=220,
        bbox_inches="tight",
    )

    fig.savefig(
        PDF_FILE,
        bbox_inches="tight",
    )

    plt.close(fig)

    print(f"PNG 圖表已輸出：{PNG_FILE}")
    print(f"PDF 圖表已輸出：{PDF_FILE}")



# =====================================
# 顯示中文統計摘要
# =====================================

def print_summary(result, backtest_df):

    top5_mean = result["top5_avg_return"].mean()
    market_mean = result["market_avg_return"].mean()

    excess_mean = (
        top5_mean - market_mean
    )

    outperform_ratio = (
        result["excess_return"] > 0
    ).mean() * 100

    stock_counts = (
        backtest_df
        .groupby("date")["symbol"]
        .nunique()
    )

    print("\n各回測日期的股票數量：")
    print(stock_counts.value_counts().sort_index())

    print("\n========== Top-10 與股票基準比較 ==========")
    print(f"比較日期數：{len(result)}")
    print(f"Top-10 平均報酬：{top5_mean:.2f}%")
    print(f"0050 基準平均報酬：{market_mean:.2f}%")
    print(f"平均超額報酬：{excess_mean:+.2f} 個百分點")
    print(
        "報酬高於基準的回測日期比例："
        f"{outperform_ratio:.2f}%"
    )
    print("==========================================\n")


# =====================================
# 主程式
# =====================================

def main():

    print("開始比較 Top-10 策略與 0050 基準...")

    result, backtest_df = load_comparison_data()

    # 輸出比較資料
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    result.to_csv(
        CSV_FILE,
        index=False,
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )

    # 繪製圖表
    plot_comparison(result)

    # 顯示中文統計結果
    print_summary(result, backtest_df)

    print(f"比較資料已輸出：{CSV_FILE}")
    print("完成：Top-10 與 0050 基準比較。")


if __name__ == "__main__":
    main()