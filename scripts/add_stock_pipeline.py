# -*- coding: utf-8 -*-

"""
網頁新增股票後的背景流程：

1. 抓取歷史股價（import_history.py）
2. 成功 → 重算還原價（adjust_prices.py）→ 重跑前瞻預測（forward_prediction.py）
3. 失敗 → 移除剛建立的 Stock 紀錄，避免股票池缺股價導致後續流程中止

用法：python scripts/add_stock_pipeline.py 2330 71
"""

import os
import subprocess
import sys

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

from myapp.models import Stock  # noqa: E402


STEPS = [
    ("adjust_prices.py", "scripts/adjust_prices.py"),
    ("forward_prediction.py", "myapp/ml/forward_prediction.py"),
]


def run_step(label, rel_path, extra_args=()):
    print(f"\n>>> 執行 {label}", flush=True)

    result = subprocess.run(
        [sys.executable, os.path.join(BASE_DIR, rel_path), *extra_args],
        cwd=BASE_DIR,
    )

    return result.returncode == 0


def remove_failed_stock(symbol):
    stock = Stock.objects.filter(symbol=symbol).first()

    if stock is not None:
        stock.delete()
        print(f"已移除 {symbol} 的股票紀錄（含部分股價），股票池保持不變")


def main():
    if len(sys.argv) < 3:
        sys.exit("用法：python scripts/add_stock_pipeline.py 代號 月數")

    symbol = sys.argv[1]
    months = sys.argv[2]

    ok = run_step(
        "歷史股價抓取",
        "scripts/import_history.py",
        [symbol, "--months", months],
    )

    if not ok:
        remove_failed_stock(symbol)
        print("新增股票流程失敗：歷史股價抓取未成功", flush=True)
        sys.exit(1)

    for label, rel_path in STEPS:
        if not run_step(label, rel_path):
            print(f"新增股票流程失敗：{label} 執行失敗", flush=True)
            sys.exit(1)

    print("\n新增股票流程完成", flush=True)


if __name__ == "__main__":
    main()
