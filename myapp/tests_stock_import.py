# -*- coding: utf-8 -*-

import importlib
import os
import sys
import tempfile
import types
from datetime import datetime
from unittest import mock

import pandas as pd
from django.test import SimpleTestCase, TestCase

from myapp.import_status import (
    HISTORY_START_YEAR,
    IMPORT_STALE_SECONDS,
    batch_lock_path,
    batch_symbols,
    import_stage,
    import_status,
    months_since_history_start,
    running_imports,
)
from myapp.models import Stock


class ImportStatusTests(SimpleTestCase):
    """背景抓取狀態：依 data/import_logs/<代號>.log 判斷。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base_dir = self._tmp.name
        self.log_dir = os.path.join(self.base_dir, "data", "import_logs")
        os.makedirs(self.log_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_log(self, text, age_seconds=0):
        path = os.path.join(self.log_dir, "2330.log")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        mtime = datetime.now().timestamp() - age_seconds
        os.utime(path, (mtime, mtime))

    def test_no_log_returns_none(self):
        self.assertIsNone(import_status("2330", self.base_dir))

    def test_stage_reports_latest_pipeline_step(self):
        self._write_log(
            "\n>>> 執行 歷史股價抓取\n匯入完成：2330\n"
            "\n>>> 執行 adjust_prices.py\n"
        )
        self.assertEqual(
            import_stage("2330", self.base_dir), "還原股價計算中"
        )

    def test_stage_none_without_log(self):
        self.assertIsNone(import_stage("9999", self.base_dir))

    def test_pipeline_complete_marker_returns_done(self):
        self._write_log("匯入完成：2330\n新增股票流程完成\n")
        self.assertEqual(import_status("2330", self.base_dir), "完成")

    def test_import_failure_returns_failed(self):
        self._write_log("匯入未完全成功：2330；失敗月份：202101\n新增股票流程失敗")
        self.assertEqual(import_status("2330", self.base_dir), "失敗")

    def test_recent_log_without_marker_returns_in_progress(self):
        self._write_log("開始背景抓取 2330\n取得 202101 行情...\n", age_seconds=10)
        self.assertEqual(import_status("2330", self.base_dir), "抓取中")

    def test_running_imports_lists_only_in_progress(self):
        self._write_log("取得 202101 行情...\n", age_seconds=10)
        done_path = os.path.join(self.log_dir, "2317.log")
        with open(done_path, "w", encoding="utf-8") as f:
            f.write("新增股票流程完成\n")
        self.assertEqual(running_imports(self.base_dir), ["2330"])

    def test_running_imports_ignores_adjust_and_forward_stages(self):
        self._write_log(
            ">>> 執行 歷史股價抓取\n>>> 執行 adjust_prices.py\n",
            age_seconds=10,
        )
        self.assertEqual(running_imports(self.base_dir), [])

    def test_stale_log_without_marker_returns_stopped(self):
        self._write_log(
            "取得 202101 行情...\n",
            age_seconds=IMPORT_STALE_SECONDS + 60,
        )
        self.assertEqual(import_status("2330", self.base_dir), "可能已中止")


class MonthsSinceHistoryStartTests(SimpleTestCase):

    def test_counts_from_january_of_start_year(self):
        self.assertEqual(
            months_since_history_start(datetime(HISTORY_START_YEAR, 1, 15)), 1
        )

    def test_november_2026_is_71_months(self):
        self.assertEqual(months_since_history_start(datetime(2026, 11, 9)), 71)


def _load_adjust_prices():
    """adjust_prices 匯入時會載入 config（需資料庫），測試時以假的股票池取代。"""
    stub = types.SimpleNamespace(POOL_SYMBOLS=[])
    with mock.patch.dict(sys.modules, {"config": stub}):
        sys.modules.pop("scripts.adjust_prices", None)
        return importlib.import_module("scripts.adjust_prices")


class FindIncompleteAdjustedTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.adjust_prices = _load_adjust_prices()

    def _frames(self, adj_values):
        prices = pd.DataFrame({
            "symbol": ["2330", "2330", "0050", "0050"],
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"] * 2),
        })
        adjusted = prices.copy()
        adjusted["adj_close"] = adj_values
        return prices, adjusted

    def test_complete_adjusted_prices_pass(self):
        prices, adjusted = self._frames([1.0, 2.0, 3.0, 4.0])
        self.assertEqual(
            self.adjust_prices.find_incomplete_adjusted(prices, adjusted), []
        )

    def test_missing_adjusted_value_is_reported(self):
        prices, adjusted = self._frames([1.0, None, 3.0, 4.0])
        self.assertEqual(
            self.adjust_prices.find_incomplete_adjusted(prices, adjusted),
            ["2330"],
        )

    def test_missing_rows_are_reported(self):
        prices, adjusted = self._frames([1.0, 2.0, 3.0, 4.0])
        adjusted = adjusted[adjusted["symbol"] != "0050"]
        self.assertEqual(
            self.adjust_prices.find_incomplete_adjusted(prices, adjusted),
            ["0050"],
        )


class AddStockPipelineTests(TestCase):
    """新增股票流程：抓取失敗要移除紀錄，且不再執行後續步驟。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        sys.modules.pop("scripts.add_stock_pipeline", None)
        cls.pipeline = importlib.import_module("scripts.add_stock_pipeline")

    def _run_main(self, results):
        calls = []

        def fake_run_step(label, rel_path, extra_args=()):
            calls.append(label)
            return results[label]

        argv = ["add_stock_pipeline.py", "9999", "71"]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(self.pipeline, "run_step", side_effect=fake_run_step):
            try:
                self.pipeline.main()
                code = 0
            except SystemExit as e:
                code = e.code
        return calls, code

    def test_import_failure_removes_stock_and_stops(self):
        Stock.objects.create(symbol="9999", name="測試", market="TWSE")

        calls, code = self._run_main({"歷史股價抓取": False})

        self.assertEqual(calls, ["歷史股價抓取"])
        self.assertEqual(code, 1)
        self.assertFalse(Stock.objects.filter(symbol="9999").exists())

    def test_adjust_failure_keeps_stock_and_skips_forward(self):
        Stock.objects.create(symbol="9999", name="測試", market="TWSE")

        calls, code = self._run_main({
            "歷史股價抓取": True,
            "adjust_prices.py": False,
            "forward_prediction.py": True,
        })

        self.assertEqual(calls, ["歷史股價抓取", "adjust_prices.py"])
        self.assertEqual(code, 1)
        self.assertTrue(Stock.objects.filter(symbol="9999").exists())

    def test_all_steps_success_runs_everything(self):
        calls, code = self._run_main({
            "歷史股價抓取": True,
            "adjust_prices.py": True,
            "forward_prediction.py": True,
        })

        self.assertEqual(
            calls, ["歷史股價抓取", "adjust_prices.py", "forward_prediction.py"]
        )
        self.assertEqual(code, 0)


class BatchSymbolsTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.tmp.name, "data", "import_logs"))
        self.base = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_lock_returns_empty(self):
        self.assertEqual(batch_symbols(self.base), [])

    def test_fresh_lock_returns_symbols(self):
        with open(batch_lock_path(self.base), "w", encoding="utf-8") as f:
            f.write("2330,2317")
        self.assertEqual(batch_symbols(self.base), ["2330", "2317"])

    def test_stale_lock_is_ignored(self):
        path = batch_lock_path(self.base)
        with open(path, "w", encoding="utf-8") as f:
            f.write("2330")
        old = os.path.getmtime(path) - IMPORT_STALE_SECONDS - 10
        os.utime(path, (old, old))
        self.assertEqual(batch_symbols(self.base), [])
