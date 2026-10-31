# 台股選股排行專題（49 檔 vs 0050）

## 研究問題

以 49 檔股票池建立 AI 選股排行，每期買進預測報酬最高的 Top-10，檢驗其績效是否優於 0050 同期報酬。

## 方法與版本

| 版本 | 檔案 | 角色 |
|---|---|---|
| V5.1 | `myapp/ml/backtest_market_model.py` | 底層模型：12 個技術特徵的 LightGBM，產生每檔股票的預測報酬 |
| V5.9 | `myapp/ml/backtest_topn_strategy.py` | **主結果**：在 V5.1 預測上做 Top-10 選股與績效計算 |
| V5.8-FORWARD | `myapp/ml/forward_prediction.py` | 每日前瞻預測，供網站展示與長期驗證 |
| 穩健性佐證 | `scripts/evaluate_ranking.py` | 獨立評估：5 個橫斷面特徵、walk-forward、20 日 embargo、保留期、bootstrap CI |

股票池與基準定義於 `config.py`，0050 為基準、不納入選股。

## 主要結果（V5.9，Top-10 vs 0050）

- 回測期間：2021-08 至 2026-09，共 64 個非重疊調倉期（約每 28 天一次）。
- Top-10 平均 20 日實際報酬 3.88%，0050 同期 2.35%，毛超額 +1.53 個百分點。
- 扣除單邊 0.1% 交易成本後，淨超額 +1.42%，95% CI [-0.06%, +2.89%]，CI 跨越 0。
- 64% 的期間優於 0050。
- 最大回撤（以各期報酬複利計算）：毛報酬 -28.34%，扣成本 -29.15%。

圖表與資料：`scripts/reports/top10_vs_0050.{png,pdf,csv}`，由 `scripts/plot_top5_market_comparison.py` 產生。

## 結論

1. Top-10 相對 0050 的淨超額為正，但 95% CI 下界略低於 0，未達統計顯著水準。
2. 穩健性評估（`evaluate_ranking.py`）顯示，LightGBM 相對簡單動能基準（mom20）的 IC 差異，95% CI 包含 0。因此目前不能宣稱 ML 模型明顯優於動能選股。
3. 績效波動大：最大回撤接近 -30%，策略風險需與 0050 一併考量。

## 前瞻追蹤（每日流程）

1. 更新股價資料，確保有當天收盤價。
2. 執行前瞻預測：`python myapp/ml/forward_prediction.py`，或網頁「執行前瞻預測」。同一交易日重跑不會重複寫入。
3. 評估到期紀錄：`python myapp/ml/evaluate_forward_predictions.py`，或網頁「評估歷史預測績效」。
4. 判斷（選做）：`python scripts/judge_forward.py`，只在需要看超額與 CI 時執行，結果不存檔。

注意：不要因短期結果調整模型或參數。判斷以 12 個月以上的前瞻為準。

## 限制

- 樣本僅 64 期，統計檢定力有限。
- 回撤與超額均以歷史回測計算；交易成本採單邊 0.1% 固定假設，未模擬滑價。
- `evaluate_ranking.py` 目前未套用 `config.is_eligible` 的上市時點規則，須在引用前修正。
- 網頁顯示最大回撤需重新執行 V5.9 回測，產生含 `max_drawdown_net` 的 summary CSV。

## 版本標示

回測層統一為 V5.9，前瞻為 V5.8-FORWARD。`V5.1` 為模型特徵版本，`V6.x` 為網頁與評估腳本的開發標示。
