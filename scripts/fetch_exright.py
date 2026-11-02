# -*- coding: utf-8 -*-
"""
fetch_exright.py
功能：抓取上市（TWSE）與上櫃（TPEx）除權息計算結果，寫入 data/exright_fetched.csv，
供 adjust_prices.py 計算還原收盤價使用。

使用方式：
    python scripts/fetch_exright.py                       # 自動：從已抓取的最後日期前 35 天開始
    python scripts/fetch_exright.py --start 2025-01-01    # 指定起始日
    python scripts/fetch_exright.py --start 2025-01-01 --end 2026-11-02

注意：TPEX_URL 與上櫃欄位格式尚未經實際連線驗證，請先在本機測試。
"""
import argparse
import os
import re
from datetime import date, datetime, timedelta

import pandas as pd
import requests

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
FETCHED_PATH = os.path.join(BASE_DIR, "data", "exright_fetched.csv")

TWSE_URL = "https://www.twse.com.tw/rwd/zh/exRight/TWT49U"
TPEX_URL = "https://www.tpex.org.tw/www/zh-tw/bulletin/exRight"

HEADERS = {"User-Agent": "Mozilla/5.0"}
TIMEOUT = 30
COLUMNS = ["source", "symbol", "ex_date", "prev_close", "ref_price"]
DEFAULT_FIRST_START = date(2025, 1, 1)


def parse_roc_date(text):
    """支援「115年11月03日」與「115/11/03」兩種民國日期格式。"""
    parts = re.findall(r"\d+", str(text))
    if len(parts) < 3:
        return pd.NaT
    year, month, day = (int(x) for x in parts[:3])
    return pd.Timestamp(year=year + 1911, month=month, day=day)


def clean_code(text):
    return str(text).strip().strip('="').strip('"').strip()


def to_number(text):
    return pd.to_numeric(
        str(text).replace(",", "").strip(), errors="coerce"
    )


def month_ranges(start, end):
    """將日期區間切成每月一段，避免單次查詢過大。"""
    cur = start.replace(day=1)
    while cur <= end:
        nxt = (cur + timedelta(days=32)).replace(day=1)
        yield max(cur, start), min(nxt - timedelta(days=1), end)
        cur = nxt


def get_json(url, params):
    resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def fetch_twse(start, end):
    """上市：TWT49U 除權息計算結果，欄位名稱與本機 CSV 表頭相同。"""
    rows = []
    for s, e in month_ranges(start, end):
        payload = get_json(TWSE_URL, {
            "startDate": s.strftime("%Y%m%d"),
            "endDate": e.strftime("%Y%m%d"),
            "response": "json",
        })
        if not payload.get("data"):
            continue

        idx = {str(name).strip(): i for i, name in enumerate(payload["fields"])}
        for r in payload["data"]:
            rows.append({
                "source": "TWSE",
                "symbol": clean_code(r[idx["股票代號"]]),
                "ex_date": parse_roc_date(r[idx["資料日期"]]),
                "prev_close": to_number(r[idx["除權息前收盤價"]]),
                "ref_price": to_number(r[idx["除權息參考價"]]),
            })
    return pd.DataFrame(rows, columns=COLUMNS)


def fetch_tpex(start, end):
    """上櫃：除權息計算結果（格式待驗證，預期 tables[0] 內含 fields/data）。"""
    rows = []
    for s, e in month_ranges(start, end):
        payload = get_json(TPEX_URL, {
            "startDate": s.strftime("%Y/%m/%d"),
            "endDate": e.strftime("%Y/%m/%d"),
            "response": "json",
        })
        tables = payload.get("tables") or []
        if not tables or not tables[0].get("data"):
            continue

        table = tables[0]
        idx = {str(name).strip(): i for i, name in enumerate(table["fields"])}
        for r in table["data"]:
            rows.append({
                "source": "TPEx",
                "symbol": clean_code(r[idx["代號"]]),
                "ex_date": parse_roc_date(r[idx["除權息日期"]]),
                "prev_close": to_number(r[idx["除權息前收盤價"]]),
                "ref_price": to_number(r[idx["除權息參考價"]]),
            })
    return pd.DataFrame(rows, columns=COLUMNS)


def default_start():
    """已有抓取檔時回推 35 天重抓，確保除權息結果更新後能覆蓋。"""
    if os.path.exists(FETCHED_PATH):
        last = pd.read_csv(
            FETCHED_PATH, usecols=["ex_date"], parse_dates=["ex_date"]
        )["ex_date"].max()
        if pd.notna(last):
            return (last - timedelta(days=35)).date()
    return DEFAULT_FIRST_START


def save(new_df):
    """合併既有抓取結果，以 source + symbol + ex_date 去重後寫入。"""
    new_df = new_df.dropna(subset=["ex_date", "prev_close", "ref_price"])
    new_df = new_df[(new_df["prev_close"] > 0) & (new_df["ref_price"] > 0)]

    if os.path.exists(FETCHED_PATH):
        old = pd.read_csv(
            FETCHED_PATH, dtype={"symbol": str},
            parse_dates=["ex_date"], encoding="utf-8-sig",
        )
        new_df = pd.concat([old, new_df], ignore_index=True)

    new_df = new_df.drop_duplicates(
        subset=["source", "symbol", "ex_date"], keep="last"
    )
    new_df = new_df.sort_values(["ex_date", "symbol"]).reset_index(drop=True)
    new_df.to_csv(FETCHED_PATH, index=False, encoding="utf-8-sig")
    return len(new_df)


def fetch_latest(start=None, end=None):
    """抓取上市與上櫃除權息並寫入檔案，回傳寫入後的總筆數。"""
    start = start or default_start()
    end = end or date.today()
    if start > end:
        raise ValueError(f"起始日 {start} 晚於結束日 {end}")

    twse = fetch_twse(start, end)
    tpex = fetch_tpex(start, end)
    print(
        f"抓取除權息 {start} ~ {end}：上市 {len(twse)} 筆，上櫃 {len(tpex)} 筆"
    )

    total = save(pd.concat([twse, tpex], ignore_index=True))
    print(f"已寫入 {FETCHED_PATH}，共 {total} 筆")
    return total


def main():
    parser = argparse.ArgumentParser(description="抓取上市上櫃除權息資料")
    parser.add_argument("--start", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date())
    parser.add_argument("--end", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date())
    args = parser.parse_args()

    fetch_latest(args.start, args.end)


if __name__ == "__main__":
    main()
