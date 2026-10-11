
# -*- coding: utf-8 -*-
"""
Prediction Report - Predicted vs. Actual Returns

用途：
1. 讀取 Top-5 策略回測明細。
2. 計算 MAE、RMSE 與方向準確率。
3. 繪製預測報酬與實際報酬散佈圖。
4. 輸出 PNG 與 PDF 報告。

注意：
CSV 的 predicted_return_20、actual_return_20
已經是百分比數值，例如 23.7 代表 23.7%。
因此不可再乘以 100。
"""

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# ==================================================
# 1. 路徑設定
# ==================================================

# plot_prediction_report.py 位於 scripts 資料夾
# 往上一層取得專案根目錄
BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_FILE = (
    BASE_DIR
    / "myapp"
    / "ml"
    / "output"
    / "market_strategy_detail.csv"
)

OUTPUT_DIR = BASE_DIR / "scripts" / "reports"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PNG_FILE = OUTPUT_DIR / "prediction_vs_actual.png"
PDF_FILE = OUTPUT_DIR / "prediction_vs_actual.pdf"


# ==================================================
# 2. 圖表設定
# ==================================================

plt.rcParams["font.sans-serif"] = [
    "Microsoft JhengHei",
    "Arial",
]
plt.rcParams["axes.unicode_minus"] = False


# ==================================================
# 3. 讀取與檢查資料
# ==================================================

def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"找不到回測明細檔案：\n{INPUT_FILE}"
        )

    df = pd.read_csv(INPUT_FILE)

    required_columns = [
        "predicted_return_20",
        "actual_return_20",
    ]

    missing_columns = [
        col for col in required_columns
        if col not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"CSV 缺少必要欄位：{missing_columns}"
        )

    # 轉換為數值並排除無效資料
    for col in required_columns:
        df[col] = pd.to_numeric(
            df[col], errors="coerce"
        )

    df = df.dropna(subset=required_columns).copy()

    if df.empty:
        raise ValueError("沒有可用的預測與實際報酬資料。")

    # CSV 已是百分比數值，不可再乘以 100
    predicted = df["predicted_return_20"].to_numpy()
    actual = df["actual_return_20"].to_numpy()

    # ==================================================
    # 4. 計算評估指標
    # ==================================================

    errors = predicted - actual

    sample_size = len(df)

    # MAE、RMSE 單位為百分點（percentage points）
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors ** 2)))

    # 方向準確率：比較預測與實際報酬的正負方向
    # 排除實際報酬恰好為 0 的樣本
    nonzero_mask = actual != 0

    if np.any(nonzero_mask):
        direction_accuracy = float(
            np.mean(
                np.sign(predicted[nonzero_mask])
                == np.sign(actual[nonzero_mask])
            ) * 100
        )
    else:
        direction_accuracy = float("nan")

    # ==================================================
    # 5. 輸出評估結果
    # ==================================================

    print("=" * 48)
    print("Predicted vs. Actual Returns Report")
    print("=" * 48)
    print(f"Sample Size: {sample_size}")
    print(f"MAE: {mae:.2f} percentage points")
    print(f"RMSE: {rmse:.2f} percentage points")

    if np.isnan(direction_accuracy):
        print("Directional Accuracy: N/A")
    else:
        print(
            f"Directional Accuracy: "
            f"{direction_accuracy:.2f}%"
        )

    print("=" * 48)

    # ==================================================
    # 6. 繪製散佈圖
    # ==================================================

    fig, ax = plt.subplots(figsize=(8, 7))

    ax.scatter(
        predicted,
        actual,
        alpha=0.75,
        s=38,
        edgecolors="white",
        linewidths=0.4,
        label="Top-5 Selected Stocks",
    )

    # 理想預測線：預測值等於實際值
    min_value = float(
        min(np.min(predicted), np.min(actual))
    )
    max_value = float(
        max(np.max(predicted), np.max(actual))
    )

    # 留少量邊界，避免點貼在圖框上
    data_range = max_value - min_value
    padding = data_range * 0.05 if data_range > 0 else 1

    line_min = min_value - padding
    line_max = max_value + padding

    ax.plot(
        [line_min, line_max],
        [line_min, line_max],
        linestyle="--",
        linewidth=1.5,
        label="Ideal Prediction (y = x)",
    )

    ax.set_xlim(line_min, line_max)
    ax.set_ylim(line_min, line_max)

    ax.set_title(
        "Predicted vs. Actual Returns",
        fontsize=15,
        pad=14,
    )

    ax.set_xlabel("Predicted Return (%)", fontsize=11)
    ax.set_ylabel("Actual Return (%)", fontsize=11)

    # 標示誤差與樣本數；不將方向準確率當成主要成果
    metrics_text = (
        f"Sample Size: {sample_size}\n"
        f"MAE: {mae:.2f} pp\n"
        f"RMSE: {rmse:.2f} pp"
    )

    ax.text(
        0.03,
        0.97,
        metrics_text,
        transform=ax.transAxes,
        fontsize=10,
        verticalalignment="top",
        bbox={
            "boxstyle": "round,pad=0.5",
            "facecolor": "white",
            "alpha": 0.88,
        },
    )

    ax.grid(True, linestyle=":", alpha=0.4)
    ax.legend(loc="lower right")
    fig.tight_layout()

    # ==================================================
    # 7. 儲存 PNG 與 PDF
    # ==================================================

    fig.savefig(
        PNG_FILE,
        dpi=300,
        bbox_inches="tight",
    )

    fig.savefig(
        PDF_FILE,
        bbox_inches="tight",
    )

    plt.close(fig)

    print(f"PNG saved: {PNG_FILE}")
    print(f"PDF saved: {PDF_FILE}")


if __name__ == "__main__":
    main()
