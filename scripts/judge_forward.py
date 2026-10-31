# -*- coding: utf-8 -*-
"""
前瞻 Top-10 判斷工具（依已鎖定的三段式標準）

標準：
- 前瞻期間需 >= 12 個月（365 天），否則只顯示累積狀況，不下結論。
- 每 20 個交易日取一次非重疊的調倉樣本。
- 淨超額 = Top-10 平均 20 日實際報酬 - 0050 同期報酬 - 換手成本（單邊 0.1%）。
- 成功：95% CI 下界 > 0；失敗：95% CI 上界 < 0；其餘為未定。

執行（於 repo 根目錄，Windows PowerShell）：
    python scripts/judge_forward.py
"""

import os
import sys
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parents[1]

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

MODEL_VERSION = "V5.8-FORWARD"
BENCH_SYMBOL = "0050"
TOP_N = 10
HORIZON = 20
REBALANCE_STEP = 20
COST_ONE_SIDE = 0.001
MIN_SPAN_DAYS = 365
BOOTSTRAP_N = 2000
RANDOM_SEED = 42


def select_nonoverlap_dates(dates, step=REBALANCE_STEP):
    """從已排序的信號日中，每 step 個交易日取一個（避免重疊樣本）。"""
    kept = []
    for i in range(0, len(dates), step):
        kept.append(dates[i])
    return kept


def bootstrap_ci(values, n=BOOTSTRAP_N):
    rng = np.random.default_rng(RANDOM_SEED)
    values = np.asarray(values, dtype=float)
    means = [rng.choice(values, size=len(values), replace=True).mean() for _ in range(n)]
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def judge(net_excess, span_days):
    """回傳 (判定, 平均淨超額, CI 下界, CI 上界)。"""
    if len(net_excess) == 0:
        return "無樣本", np.nan, np.nan, np.nan

    mean = float(np.mean(net_excess))
    low, high = bootstrap_ci(net_excess)

    if span_days < MIN_SPAN_DAYS:
        return "資料不足（前瞻未滿 12 個月）", mean, low, high
    if low > 0:
        return "成功", mean, low, high
    if high < 0:
        return "失敗", mean, low, high
    return "未定（繼續累積，不調參）", mean, low, high


def build_samples(basket_returns, bench_returns, baskets):
    """
    basket_returns：每個調倉日 Top-10 的平均 20 日報酬（小數）
    bench_returns ：每個調倉日 0050 的 20 日報酬（小數）
    baskets       ：每個調倉日的 Top-10 股票代號集合（依日期排序）
    回傳每次調倉的淨超額（已扣除單邊成本換手）。
    """
    net = []
    prev = None
    for ret, bench, picks in zip(basket_returns, bench_returns, baskets):
        if prev is None:
            turnover = 1.0
        else:
            turnover = 1 - len(picks & prev) / TOP_N
        net.append(ret - bench - turnover * 2 * COST_ONE_SIDE)
        prev = picks
    return net


def main():
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "PythonProject.settings")
    django.setup()

    from myapp.models import PredictionHistory, StockPrice, Stock

    records = list(
        PredictionHistory.objects.filter(
            model_version=MODEL_VERSION,
            rank__lte=TOP_N,
            horizon=HORIZON,
            actual_return_20__isnull=False,
        ).values("data_date", "symbol", "actual_return_20")
    )

    if not records:
        print(f"找不到已完成評估的 {MODEL_VERSION} 紀錄（Top-{TOP_N}）。")
        return

    by_date = {}
    for r in records:
        by_date.setdefault(r["data_date"], []).append(r)

    all_dates = sorted(by_date)
    sample_dates = select_nonoverlap_dates(all_dates)

    bench = Stock.objects.filter(symbol=BENCH_SYMBOL).first()
    if bench is None:
        print(f"找不到基準 {BENCH_SYMBOL} 的 Stock 資料。")
        return

    basket_returns, bench_returns, baskets = [], [], []
    for d in sample_dates:
        rows = by_date[d]
        basket_returns.append(
            float(np.mean([float(r["actual_return_20"]) for r in rows])) / 100
        )
        base = StockPrice.objects.filter(stock=bench, date=d).values_list("close_price", flat=True).first()
        fwd = list(
            StockPrice.objects.filter(stock=bench, date__gt=d, close_price__gt=0)
            .order_by("date").values_list("close_price", flat=True)[:HORIZON]
        )
        if base is None or len(fwd) < HORIZON:
            print(f"[略過] {d}：0050 價格不足")
            basket_returns.pop()
            continue
        bench_returns.append(float(fwd[-1]) / float(base) - 1)
        baskets.append({r["symbol"] for r in rows})

    net = build_samples(basket_returns, bench_returns, baskets)
    span_days = (sample_dates[-1] - sample_dates[0]).days if len(sample_dates) > 1 else 0

    verdict, mean, low, high = judge(net, span_days)

    print("=" * 60)
    print(f"前瞻判斷（{MODEL_VERSION}，Top-{TOP_N}，基準 {BENCH_SYMBOL}）")
    print("=" * 60)
    print(f"信號日（全部）：{len(all_dates)} 天　非重疊樣本：{len(net)} 次")
    print(f"涵蓋期間：{sample_dates[0] if sample_dates else '-'} ～ {sample_dates[-1] if sample_dates else '-'}（{span_days} 天）")
    print(f"平均淨超額（扣成本）：{mean * 100:+.2f}%")
    print(f"95% CI：[{low * 100:+.2f}%, {high * 100:+.2f}%]")
    print(f"判定：{verdict}")


if __name__ == "__main__":
    main()
