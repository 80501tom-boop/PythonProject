"""抓取股票池個股的歷史月營收（FinMind），輸出 myapp/ml/output/monthly_revenue.csv。

欄位說明：
- revenue_year / revenue_month：營收所屬月份（例如 2019 年 12 月營收）。
- announce_date：FinMind 的 date 欄位，為營收公布月的 1 日。
- available_date：本腳本保守推算的可用日（公布月 11 日，晚於法定 10 日公告期限），
  評估時只能使用 available_date 當日（含）之前的營收，避免偷看未來。

用法：python scripts/fetch_monthly_revenue.py
選用：環境變數 FINMIND_TOKEN（沒有也可抓取，但額度較低）。
"""

import os
import sys
import time

import pandas as pd
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from config import STOCK_POOL  # noqa: E402

API_URL = "https://api.finmindtrade.com/api/v4/data"
DATASET = "TaiwanStockMonthRevenue"
START_DATE = "2018-01-01"
OUTPUT_PATH = os.path.join(BASE_DIR, "myapp", "ml", "output", "monthly_revenue.csv")


def fetch_symbol(symbol, token=None):
    params = {"dataset": DATASET, "data_id": symbol, "start_date": START_DATE}
    if token:
        params["token"] = token

    resp = requests.get(API_URL, params=params, timeout=30)
    resp.raise_for_status()
    payload = resp.json()

    if payload.get("status") != 200:
        raise RuntimeError(f"{symbol}: {payload.get('msg')}")

    return pd.DataFrame(payload.get("data", []))


def main():
    token = os.environ.get("FINMIND_TOKEN")
    symbols = [p["symbol"] for p in STOCK_POOL if p["asset_type"] == "STOCK"]

    frames = []
    failed = []

    for symbol in symbols:
        try:
            df = fetch_symbol(symbol, token)
        except Exception as exc:  # noqa: BLE001
            failed.append((symbol, str(exc)))
            continue

        if df.empty:
            failed.append((symbol, "無資料"))
            continue

        frames.append(df)
        time.sleep(0.3)

    if not frames:
        raise SystemExit("沒有任何營收資料，請檢查網路或 FINMIND_TOKEN")

    raw = pd.concat(frames, ignore_index=True)
    out = pd.DataFrame({
        "symbol": raw["stock_id"].astype(str).str.strip(),
        "revenue_year": raw["revenue_year"].astype(int),
        "revenue_month": raw["revenue_month"].astype(int),
        "revenue": pd.to_numeric(raw["revenue"], errors="coerce"),
        "announce_date": pd.to_datetime(raw["date"]),
    })
    out["available_date"] = out["announce_date"] + pd.Timedelta(days=10)
    out = out.dropna(subset=["revenue"]).sort_values(["symbol", "revenue_year", "revenue_month"])

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    out.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    print(f"成功：{out['symbol'].nunique()} 檔，共 {len(out)} 筆")
    print(f"期間：{out['revenue_year'].min()}/{out['revenue_month'].min()} ～ "
          f"{out['revenue_year'].max()}/{out['revenue_month'].max()}")
    if failed:
        print(f"失敗：{failed}")
    print(f"輸出：{OUTPUT_PATH}")


if __name__ == "__main__":
    main()
