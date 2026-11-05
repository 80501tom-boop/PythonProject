# nouse（開發中使用、目前未使用的檔案）

以下檔案在開發過程中曾經使用，但目前沒有被網頁、其他程式或 README 流程引用。

| 檔案 | 原位置 | 原用途 | 未使用原因 |
|------|--------|--------|------------|
| `train_market_model.py` | `myapp/ml/` | V4.1 舊版模型與排名 | 已由 `forward_prediction.py`（V5.8）取代，且會覆寫 `market_ranking.csv` |
| `backtest_market_model_baseline.py` | `myapp/ml/` | 基準比較版本（baseline v10） | 僅作比較紀錄，未被引用 |
| `update_stock.py` | `scripts/` | 更新股價 | 功能已由 `scripts/import_history.py` 取代 |
| `test_twse.py` | `scripts/` | 測試 TWSE API | 開發期間的臨時測試 |
| `check_adjusted_jumps.py` | `scripts/` | 檢查還原價單日大幅跳動 | 開發期間的診斷工具 |
| `check_price_gaps.py` | `scripts/` | 檢查股價缺漏與異常 | 開發期間的診斷工具 |

注意事項：
- 移入後，`train_market_model.py` 與 `backtest_market_model_baseline.py` 的 `BASE_DIR` 推算路徑會改變，若要重新執行，需先調整路徑。
- 若確認不再需要，可直接刪除，Git 歷史會保留紀錄。
