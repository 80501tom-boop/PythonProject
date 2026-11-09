# -*- coding: utf-8 -*-

"""新增股票後的背景抓取狀態（讀取 data/import_logs/<代號>.log）。"""

import os
import time
from datetime import datetime


HISTORY_START_YEAR = 2021
IMPORT_STALE_SECONDS = 60 * 60


def months_since_history_start(now=None):
    now = now or datetime.now()
    return (now.year - HISTORY_START_YEAR) * 12 + now.month


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
