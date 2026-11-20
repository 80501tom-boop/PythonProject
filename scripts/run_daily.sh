#!/usr/bin/env bash
# 每日前瞻追蹤流程（對應 README「前瞻追蹤（每日流程）」步驟 1–4）。
# 任一步驟失敗即停止；日誌寫入 logs/daily_YYYYmmdd.log。
# 可用 PYTHON 環境變數指定 Python 直譯器，例如 PYTHON=.venv/bin/python。

set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR" || exit 1

PYTHON="${PYTHON:-python}"
LOG_DIR="$REPO_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/daily_$(date +%Y%m%d).log"

if grep -q "每日流程結束" "$LOG_FILE" 2>/dev/null; then
    echo "今天已完成每日流程，略過：$LOG_FILE"
    exit 0
fi

run_step() {
    local name="$1"
    shift
    echo "[$(date '+%F %T')] 開始：$name" | tee -a "$LOG_FILE"
    if "$@" >>"$LOG_FILE" 2>&1; then
        echo "[$(date '+%F %T')] 完成：$name" | tee -a "$LOG_FILE"
    else
        local code=$?
        echo "[$(date '+%F %T')] 失敗：$name（exit $code），流程中止" | tee -a "$LOG_FILE"
        exit "$code"
    fi
}

echo "==== 每日流程開始 $(date '+%F %T') ====" >>"$LOG_FILE"

run_step "1 更新股價資料" "$PYTHON" scripts/import_history.py all
run_step "2 重新還原股價" "$PYTHON" scripts/adjust_prices.py
run_step "3 執行前瞻預測" "$PYTHON" myapp/ml/forward_prediction.py
run_step "4 評估到期紀錄" "$PYTHON" myapp/ml/evaluate_forward_predictions.py

echo "==== 每日流程結束 $(date '+%F %T') ====" >>"$LOG_FILE"
