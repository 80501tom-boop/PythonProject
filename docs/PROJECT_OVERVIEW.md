# 專題總覽（維護手冊）

本文件整理專題架構、流程、檔案與重要決策，供日後維護與優化使用。
研究結論與限制見 `README.md`。

---

## 1. 專題目標

台股 Top-N 選股系統：以 LightGBM 預測未來 20 日報酬，每日排名並做前瞻追蹤，
同時以回測、mom20 動能對照、0050 基準評估是否有超額報酬。

---

## 2. 架構

| 層 | 位置 | 說明 |
|---|---|---|
| Django 入口 | `manage.py`、`PythonProject/settings.py`、`PythonProject/urls.py` | 設定與路由 |
| 網頁路由 | `myapp/urls.py` → `myapp/views.py` | 每個頁面與「執行」按鈕對應一個 view |
| 模板 | `templates/stocks/*.html`、`templates/stocks/partials/navbar.html` | 網頁介面 |
| 資料庫 | `myapp/models.py`（`Stock`、`StockPrice`、`PredictionHistory`） | 股票清單、每日股價、前瞻紀錄 |
| 股票池 | `config.py` | 由資料庫 `Stock` 表讀取，網頁新增或刪除即同步 |
| 腳本 | `scripts/`、`myapp/ml/` | 資料抓取、還原價、模型、回測、評估 |
| 舊版程式 | `nouse/` | 開發期間的實驗，無程式引用，保留未刪 |

網頁透過 `subprocess` 呼叫腳本（前瞻預測、還原價、前瞻評估、全部更新）。

---

## 3. 每日流程（順序不可亂）

1. `python scripts/import_history.py all`：更新股價到資料庫。失敗即停止。
2. `python scripts/adjust_prices.py`：重算還原價。股價缺漏或落後、或還原價不完整時中止，不覆寫舊檔。
3. `python myapp/ml/forward_prediction.py`：前瞻預測，寫入 `forward_prediction.csv` 與資料庫。
4. `python myapp/ml/evaluate_forward_predictions.py`：到期紀錄評估（以還原價計算實際報酬）。
5. `python scripts/judge_forward.py`（選做）：超額報酬與 95% CI 判斷，不存檔。

網頁新增股票流程（`scripts/add_stock_pipeline.py`）：
匯入 2021/1/1 起（或上市櫃起始）股價 → 重算還原價 → 重跑前瞻。匯入失敗會刪除該股紀錄。

---

## 4. 檔案說明

### 4.1 Python 腳本

| 檔案 | 功能 |
|---|---|
| `config.py` | 股票池（從資料庫讀取）、`TOP_N`、`USE_POOL_START`、`is_eligible` |
| `scripts/import_history.py` | 從證交所／櫃買抓股價寫入資料庫，CLI：`<symbol> --months N` 或 `all` |
| `scripts/fetch_exright.py` | 抓取最新除權息，累加到 `data/exright_fetched.csv` |
| `scripts/adjust_prices.py` | 產生還原價與事件，含寫入前檢查 |
| `scripts/fetch_monthly_revenue.py` | 抓月營收（輸出路徑未逐一核對，修改前請先確認） |
| `scripts/add_stock_pipeline.py` | 網頁新增股票的背景流程 |
| `myapp/import_status.py` | 歷史資料抓取狀態判斷（進行中／完成／失敗） |
| `myapp/ml/forward_prediction.py` | 前瞻預測、排名、mom20 並列對照 |
| `myapp/ml/evaluate_forward_predictions.py` | 前瞻評估，寫入資料庫 |
| `myapp/ml/backtest_market_model.py` | ML 回測，逐日與每 5 交易日取樣 |
| `myapp/ml/backtest_topn_strategy.py` | Top-N 策略回測，28 日曆天非重疊調倉，含 mom20 對照 |
| `scripts/evaluate_ranking.py` | 穩健性比較：IC、5 日反轉、低波動、mom20、混合分數 |
| `scripts/judge_forward.py` | 前瞻判斷：淨超額、bootstrap CI、三段式標準 |
| `scripts/plot_*.py` | 報告圖表 |
| `myapp/tests_stock_import.py` | 新增股票流程與還原價檢查的測試（13 項） |

### 4.2 CSV

**輸入（`data/`，進版控）**

| 檔案 | 欄位／內容 | 用途 |
|---|---|---|
| `twse_exright_2021_2026.csv` | 上市除權息原始資料（CP950） | `adjust_prices.py` 讀取 |
| `tpex_exright_2021_2026.csv` | 上櫃除權息原始資料（CP950） | 同上 |
| `manual_events.csv` | `symbol, ex_date, factor, note` | 手動事件，例如 0050 的 1 拆 4 |
| `pool_history.csv` | `symbol, asset_type, market, pool_start, source` | 股票類型與市場；納入日僅在 `USE_POOL_START=True` 時使用 |

**快取（`data/`，不進版控）**

| 檔案 | 欄位 | 用途 |
|---|---|---|
| `exright_fetched.csv` | `source, symbol, ex_date, prev_close, ref_price` | 增量抓取的除權息累積檔 |

**根目錄（不進版控）**

| 檔案 | 產生者 | 用途 |
|---|---|---|
| `adjusted_prices.csv` | `adjust_prices.py` | 還原收盤價，所有模型與評估的依據 |
| `dividend_events.csv` | `adjust_prices.py` | 合併後的除權息事件 |

**輸出（`myapp/ml/output/`，不進版控）**

| 檔案 | 產生者 | 網頁頁面 |
|---|---|---|
| `forward_prediction.csv` | `forward_prediction.py` | 歷史預測 |
| `market_ranking.csv` | `forward_prediction.py` | AI 選股排名 |
| `market_backtest.csv` | `backtest_market_model.py` | 回測結果 |
| `market_strategy_backtest.csv`、`market_strategy_detail.csv`、`market_strategy_summary.csv` | `backtest_topn_strategy.py` | 策略回測 |
| `market_strategy_mom20_benchmark.csv` | `backtest_topn_strategy.py` | mom20 對照 |
| `ranking_evaluation.csv`、`ranking_paired_compare.csv`、`ranking_scope_compare.csv`、`ranking_yearly.csv` | `evaluate_ranking.py` | 穩健性比較 |
| `monthly_revenue.csv` | `fetch_monthly_revenue.py` | 月營收 |

**報告（進版控）**

- `scripts/reports/top10_vs_0050.csv`：Top-10 與 0050 的逐期超額報酬，供圖表使用。

### 4.3 網頁頁面

| 網址 | view | 資料來源 |
|---|---|---|
| `/` | `index` | 資料庫、排名摘要 |
| `/add-stock/` | `add_stock` | 寫入資料庫並啟動背景流程 |
| `/stock/<代號>/` | `stock_detail` | 資料庫股價、狀態橫幅 |
| `/market-ranking/` | `market_ranking` | `market_ranking.csv` |
| `/prediction-history/` | `prediction_history` | `forward_prediction.csv`、資料庫 |
| `/prediction-performance/` | `prediction_performance` | 資料庫 |
| `/market-backtest/` | `market_backtest` | `market_backtest.csv` |
| `/market-strategy/` | `market_strategy` | `market_strategy_*.csv` |
| `/run-adjust-prices/`、`/run-forward-prediction/`、`/run-forward-evaluation/`、`/run-update-all-stocks/` | 對應 view | 以 subprocess 執行腳本 |

---

## 5. 重要決策（請勿無故改動）

| 項目 | 決策 | 原因 |
|---|---|---|
| 價格口徑 | 模型與評估都用還原價 | 高股息 ETF 除息會造成假性下跌 |
| 流動性過濾 | 逐日過濾 | 避免用最新一天決定整檔納入（前視偏誤） |
| 0050 | 不列入候選，只作基準 | 避免基準同時當選股標的 |
| ETF | 保留在股票池 | 使用者決定維持現狀；前瞻 Top-10 僅 1–2 檔 ETF |
| 非重疊取樣 | 28 日曆天 | 與回測一致，不因交易日不連續而失真 |
| 股票池 | 來自資料庫 | 網頁新增即加入模型，不需改程式 |
| 空股票池 | 警告，不中斷 | 讓測試資料庫可以啟動 |
| 還原價檢查 | 不完整即中止 | 避免用錯誤資料排名 |
| 前瞻紀錄 | 同日同檔同版本不重寫 | 保證前瞻紀錄不被事後改寫 |

---

## 6. 已知限制

- **存活者偏誤**：股票池是現在的名單回溯，會高估超額報酬。無法以程式修正，需歷史成分股資料。
- **樣本數少**：前瞻期數有限，信賴區間寬（見 `judge_forward.py` 輸出）。
- **等權對 0050**：基準與策略的比較不考慮風險調整。
- **交易成本**：回測以 `COST_ONE_WAY = 0.001` 單邊計算（`backtest_topn_strategy.py:76`），未模擬滑價。
- **還原價範圍**：減資、分割、增資是否完整涵蓋，尚未確認。
- **股票池變動**：新增股票後，模型與排名會改變，之前的回測結果不再直接可比。
- **漏跑**：漏跑的前瞻無法事後補回，只影響樣本數。

---

## 7. 維護指令

```
# 測試（新增股票流程、還原價檢查）
python manage.py test myapp.tests_stock_import -v 2

# 每日流程
python scripts/import_history.py all
python scripts/adjust_prices.py
python myapp/ml/forward_prediction.py
python myapp/ml/evaluate_forward_predictions.py
python scripts/judge_forward.py
```

---

## 8. 近期修改紀錄（主要）

| commit | 內容 |
|---|---|
| `4f5a2c4` | judge 取樣改為 28 日曆天 |
| `78b8591` | 新增股票開始匯入時顯示訊息；README 補充自動新增說明 |
| `cc0264e` | 股票池為空時改為警告 |
| `c11032c` | 抓取狀態與還原價檢查拆出模組，新增 13 項測試 |
| `f48c897` | 新增股票後自動重算與重跑前瞻；還原價檢查 |
| `dc0dcc0`、`a2f443d`、`0f45a99` | 新增股票背景匯入與狀態橫幅 |
| `40259dd`、`1b442fc` | 股票池改由資料庫讀取 |
| `4f41a9d` | 還原價用於前瞻評估與基準；修正流動性前視偏誤 |

---

## 9. 維護建議

- 改動還原價或股票池前，先確認 `adjusted_prices.csv` 與資料庫一致。
- 新增佐證方法時，放在 `scripts/evaluate_ranking.py` 比較，避免改動主排名。
- `nouse/` 可在確認後刪除，目前無程式引用。
- 修改模型特徵前，先確認 `FEATURE_COLUMNS` 在 `forward_prediction.py` 與回測保持一致。
