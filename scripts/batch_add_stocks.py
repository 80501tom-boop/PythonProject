# -*- coding: utf-8 -*-

"""
批量新增股票：依序抓歷史股價，檔與檔之間暫停，避免 API 限流。

流程：
1. 逐檔建立 Stock 紀錄（名稱取自 TWSE 清單，找不到則留空）
2. 逐檔執行 import_history.py，輸出寫入 data/import_logs/<代號>.log
   （網頁狀態框可直接讀取）
3. 失敗的股票移除紀錄，其餘繼續
4. 全部抓完後，只執行一次 adjust_prices.py 與 forward_prediction.py

用法：
    python scripts/batch_add_stocks.py 3443 2887 8046 --pause 120
    python scripts/batch_add_stocks.py 3443,2887 --months 71
"""

import os
import subprocess
import sys
import time

import django
import requests


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
from myapp.models import Stock  # noqa: E402


LOG_DIR = os.path.join(BASE_DIR, "data", "import_logs")
TWSE_LIST_URL = (
    "https://openapi.twse.com.tw/"
    "v1/exchangeReport/STOCK_DAY_ALL"
)
DEFAULT_PAUSE_SECONDS = 120

FINAL_STEPS = [
    ("adjust_prices.py", "scripts/adjust_prices.py"),
    ("forward_prediction.py", "myapp/ml/forward_prediction.py"),
]


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

    if not symbols:
        sys.exit("用法：python scripts/batch_add_stocks.py 代號 [代號…] [--pause 秒] [--months 月數]")

    return symbols, months, pause


def load_twse_names():
    try:
        response = requests.get(TWSE_LIST_URL, timeout=10)
        response.raise_for_status()
        return {
            str(item.get("Code", "")).strip().zfill(4): str(item.get("Name", "")).strip()
            for item in response.json()
        }
    except Exception as e:
        print(f"無法取得 TWSE 股票名稱（將留空）：{e}", flush=True)
        return {}


def ensure_stock(symbol, names):
    stock = Stock.objects.filter(symbol=symbol).first()
    if stock is not None:
        return stock

    if symbol in names:
        return Stock.objects.create(symbol=symbol, name=names[symbol], market="TWSE")

    return Stock.objects.create(symbol=symbol, name="", market="")


def append_log(symbol, text):
    with open(os.path.join(LOG_DIR, f"{symbol}.log"), "a", encoding="utf-8") as f:
        f.write(text + "\n")


def import_one(symbol, months):
    """依序抓單檔歷史股價，輸出寫入該股的 log 檔。"""
    log_path = os.path.join(LOG_DIR, f"{symbol}.log")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}

    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write(">>> 執行 歷史股價抓取\n")
        log_file.flush()
        result = subprocess.run(
            [sys.executable, os.path.join(BASE_DIR, "scripts", "import_history.py"),
             symbol, "--months", str(months)],
            cwd=BASE_DIR,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
        )

    return result.returncode == 0


def run_final_steps(symbols, env):
    """全部股票共用一次還原價與前瞻預測；同步寫入各股 log 供狀態框顯示步驟。"""
    for label, rel_path in FINAL_STEPS:
        print(f"\n>>> 執行 {label}", flush=True)
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
    names = load_twse_names()

    succeeded = []
    failed = []

    for index, symbol in enumerate(symbols):
        print(f"\n{'=' * 60}\n[{index + 1}/{len(symbols)}] 開始 {symbol}\n{'=' * 60}", flush=True)

        ensure_stock(symbol, names)

        if import_one(symbol, months):
            succeeded.append(symbol)
        else:
            failed.append(symbol)
            Stock.objects.filter(symbol=symbol).delete()
            append_log(symbol, "新增股票流程失敗：歷史股價抓取未成功")
            print(f"{symbol} 抓取失敗，已移除紀錄，繼續下一檔", flush=True)

        if index < len(symbols) - 1:
            print(f"暫停 {pause} 秒後繼續…", flush=True)
            time.sleep(pause)

    if succeeded:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        failed_step = run_final_steps(succeeded, env)
        for symbol in succeeded:
            if failed_step:
                append_log(symbol, f"新增股票流程失敗：{failed_step} 執行失敗")
            else:
                append_log(symbol, "新增股票流程完成")

    print("\n批量新增結束", flush=True)
    print(f"成功：{', '.join(succeeded) or '無'}", flush=True)
    print(f"失敗：{', '.join(failed) or '無'}", flush=True)


if __name__ == "__main__":
    main()
