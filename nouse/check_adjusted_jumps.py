"""檢查還原收盤價是否仍有單日大幅跳動（應已由除權息與人工分割因子消除）。

讀取 adjusted_prices.csv（由 adjust_prices.py 產生），逐檔計算 adj_close 日報酬，
列出絕對值超過門檻的日期。
"""
import argparse
import os

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADJUSTED_PATH = os.path.join(BASE_DIR, "adjusted_prices.csv")
THRESHOLD = 0.20


def find_jumps(df, threshold=THRESHOLD):
    df = df.sort_values(["symbol", "date"]).copy()
    df["ret"] = df.groupby("symbol")["adj_close"].pct_change()
    return df[df["ret"].abs() > threshold][["symbol", "date", "close", "adj_close", "ret"]]


def main():
    parser = argparse.ArgumentParser(description="檢查還原收盤價的單日大幅跳動")
    parser.add_argument("--path", default=ADJUSTED_PATH)
    parser.add_argument("--threshold", type=float, default=THRESHOLD)
    args = parser.parse_args()

    df = pd.read_csv(args.path, parse_dates=["date"])
    jumps = find_jumps(df, args.threshold)

    if jumps.empty:
        print(f"還原序列無單日超過 {args.threshold:.0%} 的跳動")
        return

    print(f"仍有 {len(jumps)} 筆跳動：")
    print(jumps.to_string(index=False))


if __name__ == "__main__":
    main()
