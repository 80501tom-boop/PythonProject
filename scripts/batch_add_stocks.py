# -*- coding: utf-8 -*-

"""
新增股票執行器（網頁單檔與批量共用）：依序抓歷史股價，檔與檔之間暫停，避免 API 限流。

流程：
1. 代號已存在 Stock 則更新（import_history.py 增量），否則抓取完整歷史（--months）
2. 狀態寫入 data/import_logs/batch.lock，每檔的輸出寫入 data/import_logs/<代號>.log
3. 新股抓取失敗則移除紀錄，其餘繼續
4. 全部抓完後，只執行一次 adjust_prices.py 與 forward_prediction.py
5. 結果寫入 data/import_logs/batch_last.json，首頁顯示

用法：
    python scripts/batch_add_stocks.py 3443 2887 8046 --pause 45
    python scripts/batch_add_stocks.py 3443,2887 --months 71
"""

import os
import subprocess
import sys
import time

import django


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

from myapp.import_status import months_since_history_start  # noqa: E402
from myapp.models import Stock, StockPrice  # noqa: E402
from myapp.stock_queue import (  # noqa: E402
    MAX_BATCH_SIZE,
    lock_path,
    lookup_stock,
    normalize_symbols,
    save_stock,
    write_last_results,
    write_queue_results,
)


LOG_DIR = os.path.join(BASE_DIR, "data", "import_logs")
DEFAULT_PAUSE_SECONDS = 45
COOLDOWN_SECONDS = 240
MAX_CONSECUTIVE_LIMITS = 2
RATE_LIMIT_MARK = "428 Client Error"

FINAL_STEPS = [
    ("adjust_prices.py", "scripts/adjust_prices.py"),
    ("forward_prediction.py", "myapp/ml/forward_prediction.py"),
]

FINAL_STAGE_LABELS = {
    "adjust_prices.py": "還原股價計算中",
    "forward_prediction.py": "前瞻預測計算中",
}


def parse_args(argv):
    pause = DEFAULT_PAUSE_SECONDS
    months = months_since_history_start()
    symbols = []

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--pause":
            pause = int(argv[i + 1])
            i += 2
            continue
        if arg == "--months":
            months = int(argv[i + 1])
            i += 2
            continue
        symbols.extend(
            s.strip().split(".")[0].zfill(4)
            for s in arg.replace(",", " ").split()
            if s.strip()
        )
        i += 1

    symbols = list(dict.fromkeys(symbols))

    if not symbols:
        sys.exit("用法：python scripts/batch_add_stocks.py 代號 [代號…] [--pause 秒] [--months 月數]")

    if len(symbols) > MAX_BATCH_SIZE:
        sys.exit(f"一次最多 {MAX_BATCH_SIZE} 檔，目前 {len(symbols)} 檔")

    return symbols, months, pause


def parse_args(argv):
    pause = DEFAULT_PAUSE_SECONDS
    months = months_since_history_start()
    raw = []

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--pause":
            pause = int(argv[i + 1])
            i += 2
            continue
        if arg == "--months":
            months = int(argv[i + 1])
            i += 2
            continue
        raw.append(arg)
        i += 1

    symbols = normalize_symbols(raw)

    if not symbols:
        sys.exit("用法：python scripts/batch_add_stocks.py 代號 [代號…] [--pause 秒] [--months 月數]")

    if len(symbols) > MAX_BATCH_SIZE:
        sys.exit(f"一次最多 {MAX_BATCH_SIZE} 檔，目前 {len(symbols)} 檔")

    return symbols, months, pause


def append_log(symbol, text):
    with open(os.path.join(LOG_DIR, f"{symbol}.log"), "a", encoding="utf-8") as f:
        f.write(text + "\n")


def run_history_step(symbol, months):
    """months 為 None 時做增量更新（import_history.py 單代號模式），否則抓完整歷史。"""
    log_path = os.path.join(LOG_DIR, f"{symbol}.log")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    args = [sys.executable, os.path.join(BASE_DIR, "scripts", "import_history.py"), symbol]
    if months is not None:
        args += ["--months", str(months)]

    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write(">>> 執行 歷史股價抓取\n")
        log_file.flush()
        result = subprocess.run(
            args,
            cwd=BASE_DIR,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
        )

    with open(log_path, encoding="utf-8", errors="replace") as f:
        limited = RATE_LIMIT_MARK in f.read()

    return result.returncode == 0, limited


def run_final_steps(symbols, env, results):
    """全部股票共用一次還原價與前瞻預測；同時更新佇列狀態供首頁與股票頁顯示目前步驟。"""
    for label, rel_path in FINAL_STEPS:
        print(f"\n>>> 執行 {label}", flush=True)
        for symbol in symbols:
            results[symbol] = f"處理中（{FINAL_STAGE_LABELS[label]}）"
        write_queue_results(BASE_DIR, results)
        for symbol in symbols:
            append_log(symbol, f">>> 執行 {label}")
        result = subprocess.run(
            [sys.executable, os.path.join(BASE_DIR, rel_path)],
            cwd=BASE_DIR,
            env=env,
        )
        if result.returncode != 0:
            return label
    return None


def main():
    symbols, months, pause = parse_args(sys.argv[1:])
    os.makedirs(LOG_DIR, exist_ok=True)

    results = {s: "等待中" for s in symbols}
    ready = []
    consecutive_limits = 0
    stopped = False

    write_queue_results(BASE_DIR, results)
    try:
        for index, symbol in enumerate(symbols):
            if stopped:
                results[symbol] = "未處理（限流停止）"
                continue

            print(f"\n{'=' * 60}\n[{index + 1}/{len(symbols)}] 開始 {symbol}\n{'=' * 60}", flush=True)
            results[symbol] = "處理中"
            write_queue_results(BASE_DIR, results)

            stock = Stock.objects.filter(symbol=symbol).first()
            if stock is None:
                info = lookup_stock(symbol)
                if info is None:
                    results[symbol] = "找不到代號"
                    write_queue_results(BASE_DIR, results)
                    print(f"{symbol} 找不到股票代號，略過", flush=True)
                    continue
                stock = save_stock(symbol, info)

            had_history = StockPrice.objects.filter(stock=stock).exists()
            ok, limited = run_history_step(symbol, None if had_history else months)

            if ok:
                results[symbol] = "歷史已抓取"
                ready.append(symbol)
            else:
                results[symbol] = "失敗"
                if not had_history:
                    Stock.objects.filter(symbol=symbol).delete()
                    append_log(symbol, "新增股票流程失敗：歷史股價抓取未成功")
                else:
                    append_log(symbol, "新增股票流程失敗：歷史股價更新未成功")
                print(f"{symbol} 抓取失敗", flush=True)

            write_queue_results(BASE_DIR, results)

            consecutive_limits = consecutive_limits + 1 if limited else 0
            if consecutive_limits >= MAX_CONSECUTIVE_LIMITS:
                stopped = True
                print(
                    f"連續 {consecutive_limits} 檔遇到 428 限流，停止；"
                    "未處理的股票稍後可重新送出",
                    flush=True,
                )
            elif limited:
                print(f"遇到限流，冷卻 {COOLDOWN_SECONDS} 秒", flush=True)
                time.sleep(COOLDOWN_SECONDS)
            elif index < len(symbols) - 1:
                print(f"{pause} 秒後開始下一檔", flush=True)
                time.sleep(pause)

        if ready:
            env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
            failed_step = run_final_steps(ready, env, results)
            for symbol in ready:
                if failed_step:
                    results[symbol] = f"失敗（{failed_step}）"
                    append_log(symbol, f"新增股票流程失敗：{failed_step} 執行失敗")
                else:
                    results[symbol] = "完成"
                    append_log(symbol, "新增股票流程完成")
    finally:
        for symbol, status in list(results.items()):
            if status in ("等待中", "處理中"):
                results[symbol] = "未完成"
            if results[symbol].startswith("未處理") or results[symbol] == "未完成":
                if not StockPrice.objects.filter(symbol=symbol).exists():
                    Stock.objects.filter(symbol=symbol).delete()
        write_last_results(BASE_DIR, results)
        if os.path.exists(lock_path(BASE_DIR)):
            os.remove(lock_path(BASE_DIR))

    print("\n新增結束", flush=True)
    for symbol, status in results.items():
        print(f"{symbol}：{status}", flush=True)


if __name__ == "__main__":
    main()
