"""股票排名評估：簡單基準 vs LightGBM，walk-forward + 20 日 embargo。

資料：adjusted_prices.csv（還原收盤價）+ StockPrice（成交量）。
流程：
1. 特徵皆為截面排名，只使用當日及之前的資料。
2. 基準：全體等權、20 日動能、5 日反轉、低波動；模型：LightGBM（截面去中位數目標）。
3. 每 20 個交易日調倉一次，Top-5 / Top-10，扣除單邊 0.1% 與 0.3% 成本。
4. 最後 126 個交易日為保留期間（holdout），僅作最終報告，不用於調參。

用法：python scripts/evaluate_ranking.py
"""

import os
import sys

import django
import lightgbm as lgb
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

sys.path.append(BASE_DIR)

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "PythonProject.settings"
)

django.setup()

from myapp.models import Stock, StockPrice  # noqa: E402
from config import POOL_BY_SYMBOL, POOL_SYMBOLS  # noqa: E402


ADJUSTED_PATH = os.path.join(BASE_DIR, "adjusted_prices.csv")
OUTPUT_PATH = os.path.join(BASE_DIR, "myapp", "ml", "output", "ranking_evaluation.csv")

LOOK_FORWARD = 20
REBALANCE_STEP = 20
TOP_NS = (5, 10)
BUFFER_RANK = 15
COSTS_ONE_SIDE = (0.001, 0.003)
MIN_AVG_VOLUME_20 = 100000
DEV_START_INDEX = 252
HOLDOUT_DAYS = 126
RETRAIN_EVERY = 60
EMBARGO = LOOK_FORWARD
BOOTSTRAP_N = 2000
RANDOM_SEED = 42

FEATURES = ["mom5", "mom20", "mom60", "vol20", "volratio20"]

LGB_PARAMS = {
    "objective": "regression",
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_child_samples": 200,
    "reg_lambda": 5,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "verbose": -1,
    "seed": RANDOM_SEED,
}
N_ESTIMATORS = 300


# =========================================================
# 資料
# =========================================================

def load_panel():
    adj = pd.read_csv(ADJUSTED_PATH, dtype={"symbol": str})
    adj["symbol"] = adj["symbol"].str.strip()
    adj["date"] = pd.to_datetime(adj["date"])

    frames = []

    for stock in Stock.objects.filter(symbol__in=POOL_SYMBOLS):
        symbol = str(stock.symbol).strip()

        vol = pd.DataFrame(
            StockPrice.objects.filter(stock=stock).values("date", "volume")
        )

        if vol.empty:
            continue

        vol["date"] = pd.to_datetime(vol["date"])
        vol["volume"] = pd.to_numeric(vol["volume"], errors="coerce")

        prices = adj.loc[adj["symbol"] == symbol, ["date", "adj_close"]]

        df = prices.merge(vol, on="date", how="inner").dropna()
        df["symbol"] = symbol
        df["asset_type"] = POOL_BY_SYMBOL[symbol]["asset_type"]
        frames.append(df)

    return pd.concat(frames, ignore_index=True)


def build_panel(raw):
    p = raw.sort_values(["symbol", "date"]).reset_index(drop=True)
    g = p.groupby("symbol", group_keys=False)

    p["ret1"] = g["adj_close"].pct_change()
    p["mom5"] = g["adj_close"].pct_change(5)
    p["mom20"] = g["adj_close"].pct_change(20)
    p["mom60"] = g["adj_close"].pct_change(60)
    p["vol20"] = g["ret1"].transform(lambda s: s.rolling(20).std())
    p["vma20"] = g["volume"].transform(lambda s: s.rolling(20).mean())
    p["volratio20"] = p["volume"] / p["vma20"]
    p["liquid"] = p["vma20"] >= MIN_AVG_VOLUME_20

    p["fwd20"] = g["adj_close"].shift(-LOOK_FORWARD) / p["adj_close"] - 1

    p = p.sort_values(["date", "symbol"]).reset_index(drop=True)

    dates = sorted(p["date"].unique())
    index_map = {d: i for i, d in enumerate(dates)}
    p["date_idx"] = p["date"].map(index_map)

    # 截面百分位（只用當日資料）
    for col in FEATURES:
        p[f"{col}_cs"] = p.groupby("date")[col].rank(pct=True)

    # 截面目標：未來 20 日報酬減去當日中位數
    p["y"] = p["fwd20"] - p.groupby("date")["fwd20"].transform("median")

    return p, len(dates)


# =========================================================
# 模型
# =========================================================

ML_FEATURES = [f"{c}_cs" for c in FEATURES]


def train_model(panel, train_end_idx):
    train = panel[
        panel["liquid"]
        & panel["y"].notna()
        & (panel["date_idx"] + LOOK_FORWARD <= train_end_idx)
    ]

    model = lgb.train(
        LGB_PARAMS,
        lgb.Dataset(train[ML_FEATURES], label=train["y"]),
        num_boost_round=N_ESTIMATORS,
    )
    return model


def add_ml_scores(panel, start_idx, end_idx):
    """walk-forward：每 RETRAIN_EVERY 日重訓一次，訓練資料只用標籤已結束且超過 embargo 的列。"""
    panel["ml"] = np.nan

    chunk_start = start_idx

    while chunk_start <= end_idx:
        chunk_end = min(chunk_start + RETRAIN_EVERY - 1, end_idx)
        model = train_model(panel, chunk_start - EMBARGO - 1)

        mask = panel["date_idx"].between(chunk_start, chunk_end)
        panel.loc[mask, "ml"] = model.predict(panel.loc[mask, ML_FEATURES])

        chunk_start = chunk_end + 1

    return panel


# =========================================================
# 評估
# =========================================================

def select_top(scores, n, prev_holdings):
    """Top-N 加緩衝區：前一期持股若仍在前 BUFFER_RANK 名則續留。"""
    ranked = scores.sort_values(ascending=False)
    rank_pos = {sym: i + 1 for i, sym in enumerate(ranked.index)}

    keep = [
        s for s in prev_holdings
        if s in rank_pos and rank_pos[s] <= BUFFER_RANK
    ][:n]

    picks = keep[:]

    for sym in ranked.index:
        if len(picks) >= n:
            break
        if sym not in picks:
            picks.append(sym)

    return picks


def bootstrap_ci(values, n=BOOTSTRAP_N):
    rng = np.random.default_rng(RANDOM_SEED)
    values = np.asarray(values, dtype=float)

    if len(values) == 0:
        return (np.nan, np.nan)

    means = [
        rng.choice(values, size=len(values), replace=True).mean()
        for _ in range(n)
    ]

    return (np.percentile(means, 2.5), np.percentile(means, 97.5))


def daily_ic(panel, score_col, date_mask, min_names=10):
    rows = panel[date_mask & panel[score_col].notna() & panel["liquid"] & panel["fwd20"].notna()]

    ics = {}

    for d, grp in rows.groupby("date"):
        if len(grp) < min_names:
            continue
        ics[d] = grp[score_col].rank().corr(grp["fwd20"].rank())

    return pd.Series(ics, dtype=float)


def evaluate_strategy(panel, score_col, idx_start, idx_end, top_n):
    """回傳每次調倉的淨超額報酬、換手率與毛報酬。"""
    dates = sorted(panel["date_idx"].unique())
    rebalance_idx = [
        i for i in range(idx_start, idx_end + 1, REBALANCE_STEP)
    ]

    records = []
    prev = []

    for ridx in rebalance_idx:
        snap = panel[
            (panel["date_idx"] == ridx)
            & panel["liquid"]
            & panel["fwd20"].notna()
            & panel[score_col].notna()
        ].set_index("symbol")

        if len(snap) < top_n + 2:
            continue

        picks = select_top(snap[score_col], top_n, prev)
        turnover = 1 - len(set(picks) & set(prev)) / top_n if prev else 1.0

        gross = snap.loc[picks, "fwd20"].mean()
        ew = snap["fwd20"].mean()
        decile = max(1, int(round(len(snap) * 0.1)))
        bottom = snap["fwd20"].nsmallest(decile).mean()
        top_decile = snap["fwd20"].nlargest(decile).mean()

        rec = {
            "date": dates[ridx],
            "gross": gross,
            "ew": ew,
            "spread": top_decile - bottom,
            "turnover": turnover,
        }

        for cost in COSTS_ONE_SIDE:
            net = gross - turnover * 2 * cost
            rec[f"excess_net_{cost}"] = net - ew

        records.append(rec)
        prev = picks

    return pd.DataFrame(records)


def summarize(name, top_n, ic_series, rec):
    summary = {
        "strategy": name,
        "top_n": top_n,
        "IC_mean": ic_series.mean() if len(ic_series) else np.nan,
        "IC_IR": (
            ic_series.mean() / ic_series.std()
            if len(ic_series) > 1 and ic_series.std() > 0 else np.nan
        ),
        "n_rebalance": len(rec),
        "turnover": rec["turnover"].mean() if len(rec) else np.nan,
        "spread_mean": rec["spread"].mean() if len(rec) else np.nan,
    }

    for cost in COSTS_ONE_SIDE:
        col = f"excess_net_{cost}"
        vals = rec[col].values if len(rec) else np.array([])
        lo, hi = bootstrap_ci(vals)
        summary[f"excess_{cost}"] = vals.mean() if len(vals) else np.nan
        summary[f"ci_low_{cost}"] = lo
        summary[f"ci_high_{cost}"] = hi

    return summary


def run_period(panel, label, idx_start, idx_end):
    results = []

    strategies = {
        "mom20": panel["mom20_cs"],
        "rev5": 1 - panel["mom5_cs"],
        "lowvol": 1 - panel["vol20_cs"],
        "ml": panel["ml"],
    }

    for name, score in strategies.items():
        panel["_score"] = score
        date_mask = panel["date_idx"].between(idx_start, idx_end)
        ic = daily_ic(panel, "_score", date_mask)

        for top_n in TOP_NS:
            rec = evaluate_strategy(panel, "_score", idx_start, idx_end, top_n)
            row = summarize(name, top_n, ic, rec)
            row["period"] = label
            results.append(row)

    return results


def ic_by_asset_type(panel, idx_start, idx_end):
    rows = []

    for asset in ["ETF", "STOCK"]:
        sub = panel[panel["asset_type"] == asset].copy()
        sub["_score"] = sub["ml"]
        date_mask = sub["date_idx"].between(idx_start, idx_end)
        # ETF 檔數少，截面最少門檻降為 3；樣本不足時 n_days 會顯示
        ic = daily_ic(sub, "_score", date_mask, min_names=3 if asset == "ETF" else 10)
        rows.append({
            "asset_type": asset,
            "n_days": len(ic),
            "ml_IC_mean": ic.mean() if len(ic) else np.nan,
            "ml_IC_IR": ic.mean() / ic.std() if len(ic) > 1 and ic.std() > 0 else np.nan,
        })

    return rows


def main():
    raw = load_panel()
    panel, n_dates = build_panel(raw)

    holdout_start = n_dates - HOLDOUT_DAYS
    dev_end = holdout_start - LOOK_FORWARD - 1

    print("=" * 70)
    print("Ranking Evaluation：walk-forward")
    print("=" * 70)
    print(f"股票數：{panel['symbol'].nunique()}　交易日數：{n_dates}")
    print(f"開發期：index {DEV_START_INDEX} ～ {dev_end}")
    print(f"保留期：index {holdout_start} ～ {n_dates - LOOK_FORWARD - 1}")

    panel = add_ml_scores(panel, DEV_START_INDEX, n_dates - LOOK_FORWARD - 1)

    results = []
    results += run_period(panel, "dev", DEV_START_INDEX, dev_end)
    results += run_period(panel, "holdout", holdout_start, n_dates - LOOK_FORWARD - 1)

    out = pd.DataFrame(results)
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    out.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 30)
    print()
    print(out.round(4).to_string(index=False))

    print()
    print("ML 依資產類型的 IC（開發期＋保留期合併）：")
    print(pd.DataFrame(ic_by_asset_type(panel, DEV_START_INDEX, n_dates - LOOK_FORWARD - 1)).round(4).to_string(index=False))

    print()
    print(f"輸出：{OUTPUT_PATH}")


if __name__ == "__main__":
    main()
