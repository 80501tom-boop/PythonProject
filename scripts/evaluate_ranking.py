"""股票排名評估：簡單基準 vs LightGBM，walk-forward + 20 日 embargo。

資料：adjusted_prices.csv（還原收盤價）+ StockPrice（成交量）。
流程：
1. 特徵皆為截面排名，只使用當日及之前的資料。
2. 基準：20 日動能、5 日反轉、低波動；模型：LightGBM（截面去中位數目標）；混合：ML 與 mom20 排名等權平均。
   ML 超參數只在開發期以時間序列分割（含 embargo）選擇。
3. 每 20 個交易日調倉一次（另做每 40 日敏感度），Top-5 / Top-10，扣除單邊 0.1% 與 0.3% 成本。
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
PAIRED_OUTPUT_PATH = os.path.join(BASE_DIR, "myapp", "ml", "output", "ranking_paired_compare.csv")
SCOPE_OUTPUT_PATH = os.path.join(BASE_DIR, "myapp", "ml", "output", "ranking_scope_compare.csv")
REVENUE_PATH = os.path.join(BASE_DIR, "myapp", "ml", "output", "monthly_revenue.csv")

LOOK_FORWARD = 20
BENCHMARK_SYMBOL = "0050"
REBALANCE_STEP = 20
TOP_NS = (5, 10)
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
RIDGE_ALPHA = 1.0
TUNE_SPLITS = 4
TUNE_GRID = [
    {"num_leaves": nl, "min_child_samples": mc}
    for nl in (7, 15, 31)
    for mc in (100, 200, 400)
]
SENSITIVITY_STEP = 40


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

    # 基準為 0050 的未來 20 日報酬；0050 不參與選股候選
    bench = p.loc[p["symbol"] == BENCHMARK_SYMBOL, ["date", "fwd20"]].rename(
        columns={"fwd20": "bench20"}
    )
    p = p[p["symbol"] != BENCHMARK_SYMBOL].merge(bench, on="date", how="left")

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
# 營收特徵缺值（ETF 或無營收）以中性 0.5 補，避免 LightGBM 把「缺值」學成 ETF 指標
REV_FEATURES = ["rev_yoy_f", "rev_mom_f"]
REV_MODEL_FEATURES = ML_FEATURES + REV_FEATURES


def train_model(panel, train_end_idx, params=None, features=None):
    features = features or ML_FEATURES
    train = panel[
        panel["liquid"]
        & panel["y"].notna()
        & (panel["date_idx"] + LOOK_FORWARD <= train_end_idx)
    ]

    model = lgb.train(
        params or LGB_PARAMS,
        lgb.Dataset(train[features], label=train["y"]),
        num_boost_round=N_ESTIMATORS,
    )
    return model


def add_ml_scores(panel, start_idx, end_idx, params=None, col="ml", features=None):
    """walk-forward：每 RETRAIN_EVERY 日重訓一次，訓練資料只用標籤已結束且超過 embargo 的列。"""
    features = features or ML_FEATURES
    panel[col] = np.nan

    chunk_start = start_idx

    while chunk_start <= end_idx:
        chunk_end = min(chunk_start + RETRAIN_EVERY - 1, end_idx)
        model = train_model(panel, chunk_start - EMBARGO - 1, params, features)

        mask = panel["date_idx"].between(chunk_start, chunk_end)
        panel.loc[mask, col] = model.predict(panel.loc[mask, features])

        chunk_start = chunk_end + 1

    panel[f"{col}_cs"] = panel.groupby("date")[col].rank(pct=True)

    return panel


def train_ridge(panel, train_end_idx):
    """線性基準：與 LightGBM 相同的訓練列與 embargo，α 固定不調參。"""
    train = panel[
        panel["liquid"]
        & panel["y"].notna()
        & (panel["date_idx"] + LOOK_FORWARD <= train_end_idx)
    ].dropna(subset=ML_FEATURES)

    X = train[ML_FEATURES].to_numpy(dtype=float)
    y = train["y"].to_numpy(dtype=float)
    x_mean = X.mean(axis=0)
    y_mean = y.mean()
    Xc = X - x_mean

    coef = np.linalg.solve(
        Xc.T @ Xc + RIDGE_ALPHA * np.eye(Xc.shape[1]),
        Xc.T @ (y - y_mean),
    )
    return coef, x_mean, y_mean


def add_ridge_scores(panel, start_idx, end_idx, col="ridge"):
    """walk-forward Ridge：每 RETRAIN_EVERY 日重訓一次；缺值特徵以中位數 0.5 補。"""
    panel[col] = np.nan

    chunk_start = start_idx

    while chunk_start <= end_idx:
        chunk_end = min(chunk_start + RETRAIN_EVERY - 1, end_idx)
        coef, x_mean, y_mean = train_ridge(panel, chunk_start - EMBARGO - 1)

        mask = panel["date_idx"].between(chunk_start, chunk_end)
        X = panel.loc[mask, ML_FEATURES].fillna(0.5).to_numpy(dtype=float)
        panel.loc[mask, col] = (X - x_mean) @ coef + y_mean

        chunk_start = chunk_end + 1

    panel[f"{col}_cs"] = panel.groupby("date")[col].rank(pct=True)

    return panel


def add_revenue_features(panel):
    """月營收年增率／月增率，依公開日（available_date）對齊：每個交易日只用當日前已公布的最新營收。"""
    if not os.path.exists(REVENUE_PATH):
        raise SystemExit(f"找不到 {REVENUE_PATH}，請先執行 scripts/fetch_monthly_revenue.py")

    rev = pd.read_csv(REVENUE_PATH, dtype={"symbol": str}, parse_dates=["available_date"])
    rev["symbol"] = rev["symbol"].str.strip()
    rev = rev.sort_values(["symbol", "revenue_year", "revenue_month"]).reset_index(drop=True)

    key = rev.set_index(["symbol", "revenue_year", "revenue_month"])["revenue"]
    y, m = rev["revenue_year"], rev["revenue_month"]
    prev_y_rev = key.reindex(pd.MultiIndex.from_arrays([rev["symbol"], y - 1, m])).to_numpy()
    prev_m_year = np.where(m == 1, y - 1, y)
    prev_m_month = np.where(m == 1, 12, m - 1)
    prev_m_rev = key.reindex(
        pd.MultiIndex.from_arrays([rev["symbol"], prev_m_year, prev_m_month])
    ).to_numpy()

    rev["rev_yoy"] = (rev["revenue"] / prev_y_rev - 1).replace([np.inf, -np.inf], np.nan)
    rev["rev_mom"] = (rev["revenue"] / prev_m_rev - 1).replace([np.inf, -np.inf], np.nan)

    left = panel[["date", "symbol"]].reset_index().sort_values("date")
    right = rev[["symbol", "available_date", "rev_yoy", "rev_mom"]].sort_values("available_date")
    merged = pd.merge_asof(
        left, right, left_on="date", right_on="available_date",
        by="symbol", direction="backward",
    ).set_index("index").reindex(panel.index)

    panel["rev_yoy"] = merged["rev_yoy"]
    panel["rev_mom"] = merged["rev_mom"]
    panel["rev_yoy_cs"] = panel.groupby("date")["rev_yoy"].rank(pct=True)
    panel["rev_mom_cs"] = panel.groupby("date")["rev_mom"].rank(pct=True)
    panel["rev_yoy_f"] = panel["rev_yoy_cs"].fillna(0.5)
    panel["rev_mom_f"] = panel["rev_mom_cs"].fillna(0.5)

    return panel


def tune_params(panel, dev_start, dev_end):
    """只在開發期內做時間序列分割（含 embargo）選超參數，保留期不參與。"""
    upto = panel[panel["date_idx"] <= dev_end]
    edges = np.linspace(dev_start, dev_end + 1, TUNE_SPLITS + 2).astype(int)

    rows = []

    for combo in TUNE_GRID:
        params = {**LGB_PARAMS, **combo}
        fold_ics = []

        for k in range(1, TUNE_SPLITS + 1):
            val_start, val_end = edges[k], edges[k + 1] - 1
            model = train_model(upto, val_start - EMBARGO - 1, params)

            val = upto[upto["date_idx"].between(val_start, val_end)].copy()
            val["_p"] = model.predict(val[ML_FEATURES])
            ic = daily_ic(val, "_p", pd.Series(True, index=val.index))
            fold_ics.append(ic.mean())

        rows.append({**combo, "cv_IC_mean": np.nanmean(fold_ics)})

    result = pd.DataFrame(rows).sort_values("cv_IC_mean", ascending=False)
    best = result.iloc[0]
    best_params = {
        **LGB_PARAMS,
        "num_leaves": int(best["num_leaves"]),
        "min_child_samples": int(best["min_child_samples"]),
    }
    return best_params, result


# =========================================================
# 評估
# =========================================================

def select_top(scores, n):
    """純排名選股：取分數最高的前 n 檔。"""
    return list(scores.sort_values(ascending=False).index[:n])


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


def evaluate_strategy(panel, score_col, idx_start, idx_end, top_n, step=REBALANCE_STEP):
    """回傳每次調倉的淨超額報酬、換手率、毛報酬與 ETF 佔比。"""
    dates = sorted(panel["date_idx"].unique())
    rebalance_idx = [
        i for i in range(idx_start, idx_end + 1, step)
    ]

    records = []
    prev = []

    for ridx in rebalance_idx:
        snap = panel[
            (panel["date_idx"] == ridx)
            & panel["liquid"]
            & panel["fwd20"].notna()
            & panel["bench20"].notna()
            & panel[score_col].notna()
        ].set_index("symbol")

        if len(snap) < top_n + 2:
            continue

        picks = select_top(snap[score_col], top_n)
        turnover = 1 - len(set(picks) & set(prev)) / top_n if prev else 1.0

        gross = snap.loc[picks, "fwd20"].mean()
        bench = snap["bench20"].iloc[0]
        decile = max(1, int(round(len(snap) * 0.1)))
        bottom = snap["fwd20"].nsmallest(decile).mean()
        top_decile = snap["fwd20"].nlargest(decile).mean()

        rec = {
            "date": dates[ridx],
            "gross": gross,
            "bench": bench,
            "spread": top_decile - bottom,
            "turnover": turnover,
            "beat_market": float(gross > bench),
            "positive": float(gross > 0),
            "etf_share": snap.loc[picks, "asset_type"].eq("ETF").mean(),
        }

        for cost in COSTS_ONE_SIDE:
            net = gross - turnover * 2 * cost
            rec[f"excess_net_{cost}"] = net - bench

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
        "beat_market_rate": rec["beat_market"].mean() if len(rec) else np.nan,
        "positive_rate": rec["positive"].mean() if len(rec) else np.nan,
        "etf_share": rec["etf_share"].mean() if len(rec) else np.nan,
    }

    for cost in COSTS_ONE_SIDE:
        col = f"excess_net_{cost}"
        vals = rec[col].values if len(rec) else np.array([])
        lo, hi = bootstrap_ci(vals)
        summary[f"excess_{cost}"] = vals.mean() if len(vals) else np.nan
        summary[f"ci_low_{cost}"] = lo
        summary[f"ci_high_{cost}"] = hi

    return summary


def run_period(panel, label, idx_start, idx_end, step=REBALANCE_STEP, names=None):
    results = []

    strategies = {
        "mom20": panel["mom20_cs"],
        "rev5": 1 - panel["mom5_cs"],
        "lowvol": 1 - panel["vol20_cs"],
        "ml": panel["ml"],
        "blend": panel["blend"],
    }
    if "ridge" in panel.columns:
        strategies["ridge"] = panel["ridge"]
    if "ml_rev" in panel.columns:
        strategies["ml_rev"] = panel["ml_rev"]
        # 單一營收因子（只有個股有營收，ETF 自動排除）
        strategies["rev_yoy"] = panel["rev_yoy_cs"]
    if "ml_tuned" in panel.columns:
        strategies["ml_tuned"] = panel["ml_tuned"]
        strategies["blend_tuned"] = panel["blend_tuned"]

    for name, score in strategies.items():
        if names and name not in names:
            continue

        panel["_score"] = score
        date_mask = panel["date_idx"].between(idx_start, idx_end)
        ic = daily_ic(panel, "_score", date_mask)

        for top_n in TOP_NS:
            rec = evaluate_strategy(panel, "_score", idx_start, idx_end, top_n, step)
            row = summarize(name, top_n, ic, rec)
            row["period"] = label
            row["rebalance_step"] = step
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


def scope_compare(panel, idx_start, idx_end, score_cols):
    """比較選股範圍：混合 Top-10、只選個股 Top-10、只選 ETF Top-3；同一分數、同一調倉日。"""
    scopes = [
        ("mixed_top10", None, 10),
        ("stock_only_top10", "STOCK", 10),
        ("etf_only_top3", "ETF", 3),
    ]
    summary_rows = []
    paired_rows = []

    for score_name, col in score_cols.items():
        panel["_s"] = panel[col]
        recs = {}

        for scope, asset, top_n in scopes:
            sub = panel if asset is None else panel[panel["asset_type"] == asset].copy()
            rec = evaluate_strategy(sub, "_s", idx_start, idx_end, top_n)
            recs[scope] = rec
            row = {"score": score_name, "scope": scope, "top_n": top_n,
                   "n_rebalance": len(rec)}
            row["excess_0.001"] = rec["excess_net_0.001"].mean()
            lo, hi = bootstrap_ci(rec["excess_net_0.001"].values)
            row["ci_low_0.001"] = lo
            row["ci_high_0.001"] = hi
            row["turnover"] = rec["turnover"].mean()
            row["etf_share"] = rec["etf_share"].mean()
            summary_rows.append(row)

        for scope in ("stock_only_top10", "etf_only_top3"):
            merged = recs["mixed_top10"][["date", "excess_net_0.001"]].merge(
                recs[scope][["date", "excess_net_0.001"]], on="date", suffixes=("_mixed", "_other")
            )
            diff = merged["excess_net_0.001_other"] - merged["excess_net_0.001_mixed"]
            lo, hi = bootstrap_ci(diff.values)
            paired_rows.append({
                "score": score_name,
                "compare": f"{scope}_minus_mixed",
                "n": len(diff),
                "mean": diff.mean(),
                "ci_low": lo,
                "ci_high": hi,
            })

    return summary_rows, paired_rows


def paired_compare(panel, idx_start, idx_end, col_a, col_b, label):
    """同一日期配對比較兩個分數：每日 IC 差與 Top-10 淨超額差，附 bootstrap 信賴區間。"""
    rows = []

    panel["_a"] = panel[col_a]
    panel["_b"] = panel[col_b]
    date_mask = panel["date_idx"].between(idx_start, idx_end)
    ic_a = daily_ic(panel, "_a", date_mask)
    ic_b = daily_ic(panel, "_b", date_mask)
    ic_diff = (ic_a - ic_b).dropna()
    lo, hi = bootstrap_ci(ic_diff.values)
    rows.append({
        "compare": label,
        "metric": "daily_IC_diff",
        "n": len(ic_diff),
        "mean": ic_diff.mean(),
        "ci_low": lo,
        "ci_high": hi,
    })

    rec_a = evaluate_strategy(panel, "_a", idx_start, idx_end, 10)
    rec_b = evaluate_strategy(panel, "_b", idx_start, idx_end, 10)
    merged = rec_a[["date", "gross", "bench"]].merge(
        rec_b[["date", "gross", "bench"]], on="date", suffixes=("_a", "_b")
    )
    diff = (merged["gross_a"] - merged["bench_a"]) - (merged["gross_b"] - merged["bench_b"])
    lo, hi = bootstrap_ci(diff.values)
    rows.append({
        "compare": label,
        "metric": "top10_excess_gross_diff",
        "n": len(diff),
        "mean": diff.mean(),
        "ci_low": lo,
        "ci_high": hi,
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

    tuned_params, tune_table = tune_params(panel, DEV_START_INDEX, dev_end)
    print()
    print("超參數搜尋（僅開發期，時間序列分割＋embargo，依 cv_IC_mean 排序）：")
    print(tune_table.round(4).to_string(index=False))
    print(f"選定：num_leaves={tuned_params['num_leaves']}, min_child_samples={tuned_params['min_child_samples']}")

    panel = add_ml_scores(
        panel, DEV_START_INDEX, n_dates - LOOK_FORWARD - 1,
        params=tuned_params, col="ml_tuned",
    )
    # 混合分數：ML 截面百分位與 mom20 截面百分位等權平均
    panel["blend"] = (panel["ml_cs"] + panel["mom20_cs"]) / 2
    panel["blend_tuned"] = (panel["ml_tuned_cs"] + panel["mom20_cs"]) / 2

    panel = add_ridge_scores(panel, DEV_START_INDEX, n_dates - LOOK_FORWARD - 1)

    # 營收模型沿用開發期選定的超參數，不重新調參
    panel = add_revenue_features(panel)
    panel = add_ml_scores(
        panel, DEV_START_INDEX, n_dates - LOOK_FORWARD - 1,
        params=tuned_params, col="ml_rev", features=REV_MODEL_FEATURES,
    )

    full_end = n_dates - LOOK_FORWARD - 1

    results = []
    # 完整期間（約 51 次調倉）為主要判斷依據；保留期僅作檢查
    results += run_period(panel, "full", DEV_START_INDEX, full_end)
    results += run_period(panel, "dev", DEV_START_INDEX, dev_end)
    results += run_period(panel, "holdout", holdout_start, full_end)

    # 換股頻率敏感度：每 40 日調倉，檢查換手降低時準確率是否跟著下降
    results += run_period(
        panel, "full", DEV_START_INDEX, full_end,
        step=SENSITIVITY_STEP, names=["mom20", "ml", "blend", "ml_tuned", "blend_tuned"],
    )

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
    print("配對比較（完整期間，正值代表前者較好）：")
    pair_rows = []
    for col_a, col_b, label in [
        ("ml", "mom20_cs", "ml_vs_mom20"),
        ("blend", "mom20_cs", "blend_vs_mom20"),
        ("ml_tuned", "ml", "ml_tuned_vs_ml"),
        ("ridge", "ml", "ridge_vs_ml"),
        ("ridge", "mom20_cs", "ridge_vs_mom20"),
        ("ml_rev", "ml_tuned", "ml_rev_vs_ml_tuned"),
    ]:
        pair_rows += paired_compare(panel, DEV_START_INDEX, full_end, col_a, col_b, label)
    pair = pd.DataFrame(pair_rows)
    print(pair.round(4).to_string(index=False))
    pair.to_csv(PAIRED_OUTPUT_PATH, index=False, encoding="utf-8-sig")

    print()
    print("選股範圍比較（完整期間，0050 為基準，扣單邊 0.1% 成本）：")
    scope_rows, scope_pairs = scope_compare(
        panel, DEV_START_INDEX, full_end,
        {"ml_tuned": "ml_tuned", "mom20": "mom20_cs"},
    )
    scope_df = pd.DataFrame(scope_rows)
    print(scope_df.round(4).to_string(index=False))
    print()
    print("與混合選股的配對差（正值代表該範圍較好）：")
    scope_pair_df = pd.DataFrame(scope_pairs)
    print(scope_pair_df.round(4).to_string(index=False))
    scope_df.to_csv(SCOPE_OUTPUT_PATH, index=False, encoding="utf-8-sig")

    print()
    print(f"輸出：{OUTPUT_PATH}")


if __name__ == "__main__":
    main()
