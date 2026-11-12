# -*- coding: utf-8 -*-

"""新增股票後的背景抓取狀態（讀取 data/import_logs/<代號>.log）。"""

import os
import time
from datetime import datetime


HISTORY_START_YEAR = 2021
IMPORT_STALE_SECONDS = 60 * 60
BATCH_LOCK_NAME = "batch.lock"
BATCH_MAX_SIZE = 20


def months_since_history_start(now=None):
    now = now or datetime.now()
    return (now.year - HISTORY_START_YEAR) * 12 + now.month


STAGE_LABELS = {
    "歷史股價抓取": "歷史股價抓取中",
    "adjust_prices.py": "還原股價計算中",
    "forward_prediction.py": "前瞻預測計算中",
}


def import_stage(symbol, base_dir):
    """回傳 pipeline 目前執行的步驟文字；尚未開始或無紀錄時回傳 None。"""
    log_path = os.path.join(str(base_dir), "data", "import_logs", f"{symbol}.log")

    if not os.path.isfile(log_path):
        return None

    with open(log_path, encoding="utf-8", errors="replace") as f:
        steps = [
            line.split(">>> 執行 ", 1)[1].strip()
            for line in f
            if ">>> 執行 " in line
        ]

    if not steps:
        return None

    return STAGE_LABELS.get(steps[-1], steps[-1])


def running_imports(base_dir, now=None):
    """回傳目前仍在匯入歷史股價的股票代號（尚未進入還原股價或前瞻預測階段）。"""
    log_dir = os.path.join(str(base_dir), "data", "import_logs")

    if not os.path.isdir(log_dir):
        return []

    running = []
    for name in os.listdir(log_dir):
        if not name.endswith(".log"):
            continue
        symbol = name[:-4]
        if import_status(symbol, base_dir, now) != "抓取中":
            continue
        stage = import_stage(symbol, base_dir)
        if stage in (None, STAGE_LABELS["歷史股價抓取"]):
            running.append(symbol)

    return sorted(running)


def batch_lock_path(base_dir):
    return os.path.join(str(base_dir), "data", "import_logs", BATCH_LOCK_NAME)


def batch_symbols(base_dir, now=None):
    """回傳批量執行中的代號清單；無執行或鎖檔過期（程序已中斷）則回傳空清單。"""
    path = batch_lock_path(base_dir)

    if not os.path.isfile(path):
        return []

    now = now or time.time()
    if now - os.path.getmtime(path) >= IMPORT_STALE_SECONDS:
        return []

    with open(path, encoding="utf-8") as f:
        return [s.strip() for s in f.read().split(",") if s.strip()]


def import_status(symbol, base_dir, now=None):
    """回傳 None / 抓取中 / 完成 / 失敗 / 可能已中止。"""
    log_path = os.path.join(str(base_dir), "data", "import_logs", f"{symbol}.log")

    if not os.path.isfile(log_path):
        return None

    with open(log_path, encoding="utf-8", errors="replace") as f:
        text = f.read()

    if "新增股票流程完成" in text:
        return "完成"

    if "新增股票流程失敗" in text or "匯入未完全成功" in text:
        return "失敗"

    now = now or time.time()
    if now - os.path.getmtime(log_path) < IMPORT_STALE_SECONDS:
        return "抓取中"

    return "可能已中止"
