# -*- coding: utf-8 -*-

"""
adjust_prices.py

功能：依除權息資料計算還原收盤價，輸出 adjusted_prices.csv。

還原方式：
    除權息日 d 的調整因子 f_d = 除權息參考價 / 除權息前收盤價
    某日 t 的還原收盤價 = 收盤價 × Π(f_d)，其中 d > t 的所有除權息日

資料來源：
1. 上市：TWT49U 除權息計算結果（cp950 編碼，第 1 行為標題）
2. 上櫃：櫃買中心除權息資訊（cp950 編碼，前 2 行為標題）

使用方式（預設讀取 data/ 內的除權息檔，無需參數）：
    python scripts/adjust_prices.py

資料檔：
    data/twse_exright_2021_2026.csv：上市（TWT49U，cp950）
    data/tpex_exright_2021_2026.csv：上櫃（櫃買中心，cp950）

輸出：
    adjusted_prices.csv：symbol, date, close, adj_close, factor
    dividend_events.csv：每筆除權息事件與資料庫收盤價的核對結果
"""

import argparse
import os
import sys
import re

import django
import pandas as pd


BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "PythonProject.settings"
)

django.setup()

from myapp.models import StockPrice
from config import POOL_SYMBOLS


DATA_DIR = os.path.join(BASE_DIR, "data")
TWSE_DEFAULT = os.path.join(DATA_DIR, "twse_exright_2021_2026.csv")
TPEX_DEFAULT = os.path.join(DATA_DIR, "tpex_exright_2021_2026.csv")
MANUAL_DEFAULT = os.path.join(DATA_DIR, "manual_events.csv")

ADJUSTED_PATH = os.path.join(BASE_DIR, "adjusted_prices.csv")
EVENTS_PATH = os.path.join(BASE_DIR, "dividend_events.csv")

# 除權息前收盤價與資料庫前一交易日收盤價的允許差異
PREV_CLOSE_TOLERANCE = 0.01


def parse_roc_date(text):
    """支援「110年01月05日」與「110/01/05」兩種民國日期格式。"""
    match = re.match(r"\s*(\d{2,3})[年/](\d{1,2})[月/](\d{1,2})", str(text))
    if not match:
        return pd.NaT

    year, month, day = (int(x) for x in match.groups())
    return pd.Timestamp(year=year + 1911, month=month, day=day)


def clean_code(text):
    """去除 TWT49U 的 ="0050" 格式與尾端空白。"""
    text = str(text).strip()
    text = re.sub(r'^="?', "", text)
    text = text.rstrip('"').strip()
    return text


def to_number(text):
    return pd.to_numeric(
        str(text).replace(",", "").strip(), errors="coerce"
    )


def load_twse(path):
    df = pd.read_csv(path, encoding="cp950", skiprows=1, dtype=str)

    events = pd.DataFrame({
        "symbol": df["股票代號"].map(clean_code),
        "ex_date": df["資料日期"].map(parse_roc_date),
        "prev_close": df["除權息前收盤價"].map(to_number),
        "ref_price": df["除權息參考價"].map(to_number),
    })
    events["source"] = "TWSE"
    return events


def load_tpex(path):
    df = pd.read_csv(path, encoding="cp950", skiprows=2, dtype=str)

    events = pd.DataFrame({
        "symbol": df["代號"].map(clean_code),
        "ex_date": df["除權息日期"].map(parse_roc_date),
        "prev_close": df["除權息前收盤價"].map(to_number),
        "ref_price": df["除權息參考價"].map(to_number),
    })
    events["source"] = "TPEx"
    return events


def load_manual(path):
    """讀取人工登錄的分割等事件；factor 留空者不套用，回傳待確認清單。"""
    if not os.path.exists(path):
        return pd.DataFrame(), []

    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    pending = df[df["factor"].str.strip() == ""]
    applied = df[df["factor"].str.strip() != ""]

    events = pd.DataFrame({
        "symbol": applied["symbol"].str.strip(),
        "ex_date": pd.to_datetime(applied["ex_date"].str.strip()),
        "prev_close": float("nan"),
        "ref_price": float("nan"),
        "source": "MANUAL",
        "factor": applied["factor"].astype(float),
    })
    pending_list = [
        f"{r.symbol} {r.ex_date}" for r in pending.itertuples(index=False)
    ]
    return events, pending_list


def load_prices():
    rows = StockPrice.objects.filter(
        stock__symbol__in=POOL_SYMBOLS
    ).values_list(
        "stock__symbol", "date", "close_price"
    )

    df = pd.DataFrame(list(rows), columns=["symbol", "date", "close"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])

    return df.sort_values(["symbol", "date"]).reset_index(drop=True)


def build_events(twse_path, tpex_path, symbols, manual_path=MANUAL_DEFAULT):
    events = pd.concat(
        [load_twse(twse_path), load_tpex(tpex_path)],
        ignore_index=True,
    )

    events = events[events["symbol"].isin(symbols)]
    events = events.dropna(subset=["ex_date", "prev_close", "ref_price"])
    events = events[(events["prev_close"] > 0) & (events["ref_price"] > 0)]

    events = events.drop_duplicates(subset=["symbol", "ex_date"])
    events["factor"] = events["ref_price"] / events["prev_close"]

    manual, pending = load_manual(manual_path)
    manual = manual[manual["symbol"].isin(symbols)]
    exchange_keys = set(zip(events["symbol"], events["ex_date"]))
    dup = [
        (s, d) for s, d in zip(manual["symbol"], manual["ex_date"])
        if (s, d) in exchange_keys
    ]
    if dup:
        print(f"警告：人工事件與交易所事件重複，已忽略人工項目：{dup}")
        manual = manual[
            [(s, d) not in exchange_keys
             for s, d in zip(manual["symbol"], manual["ex_date"])]
        ]
    if pending:
        print(f"警告：以下人工事件待確認，未套用：{pending}")

    events = pd.concat([events, manual], ignore_index=True)

    return events.sort_values(["symbol", "ex_date"]).reset_index(drop=True)


def check_events(events, prices):
    """核對每筆除權息前收盤價與資料庫前一交易日收盤價。"""
    results = []

    for row in events.itertuples(index=False):
        if row.source == "MANUAL":
            results.append(0.0)
            continue

        sdf = prices[
            (prices["symbol"] == row.symbol)
            & (prices["date"] < row.ex_date)
        ]

        if sdf.empty:
            results.append(None)
            continue

        db_prev = sdf.iloc[-1]["close"]
        diff = abs(db_prev - row.prev_close) / row.prev_close
        results.append(diff)

    events = events.copy()
    events["db_prev_diff"] = results
    events["prev_close_ok"] = events["db_prev_diff"].apply(
        lambda d: d is not None and d <= PREV_CLOSE_TOLERANCE
    ) | (events["source"] == "MANUAL")
    return events


def adjust(prices, events):
    """逐檔計算還原收盤價：比該日晚的所有除權息因子相乘。"""
    out = []

    for symbol, sdf in prices.groupby("symbol", sort=False):
        ev = events[events["symbol"] == symbol]

        factors = []
        for date in sdf["date"]:
            later = ev[ev["ex_date"] > date]
            factors.append(float(later["factor"].prod()) if len(later) else 1.0)

        sdf = sdf.copy()
        sdf["factor"] = factors
        sdf["adj_close"] = sdf["close"] * sdf["factor"]
        out.append(sdf)

    return pd.concat(out, ignore_index=True)


def validate_example(adjusted):
    """2882 於 2026-06-30 除息，還原後 2026-06-29 應接近參考價 98.00。"""
    row = adjusted[
        (adjusted["symbol"] == "2882")
        & (adjusted["date"] == pd.Timestamp("2026-06-29"))
    ]

    if row.empty:
        print("驗證略過：2882 缺少 2026-06-29 資料")
        return

    adj = row.iloc[0]["adj_close"]
    print(f"驗證 2882 2026-06-29：還原收盤 {adj:.2f}（預期約 98.00）")


def main():
    parser = argparse.ArgumentParser(description="計算還原收盤價")
    parser.add_argument(
        "--twse", default=TWSE_DEFAULT,
        help="上市除權息 CSV 路徑（預設 data/twse_exright_2021_2026.csv）",
    )
    parser.add_argument(
        "--tpex", default=TPEX_DEFAULT,
        help="上櫃除權息 CSV 路徑（預設 data/tpex_exright_2021_2026.csv）",
    )
    args = parser.parse_args()

    prices = load_prices()
    symbols = set(prices["symbol"].unique())

    events = build_events(args.twse, args.tpex, symbols)
    events = check_events(events, prices)

    adjusted = adjust(prices, events)
    adjusted.to_csv(ADJUSTED_PATH, index=False, encoding="utf-8-sig")
    events.to_csv(EVENTS_PATH, index=False, encoding="utf-8-sig")

    total = len(events)
    ok = int(events["prev_close_ok"].sum())
    print(f"股票數：{len(symbols)}　除權息事件：{total}　核對通過：{ok}")

    mismatch = events[~events["prev_close_ok"]]
    if not mismatch.empty:
        print(f"核對未通過 {len(mismatch)} 筆，請檢查 dividend_events.csv")

    validate_example(adjusted)
    print(f"已輸出：{ADJUSTED_PATH}")
    print(f"已輸出：{EVENTS_PATH}")


if __name__ == "__main__":
    main()
