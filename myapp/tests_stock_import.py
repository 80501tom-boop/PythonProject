# -*- coding: utf-8 -*-

import importlib
import os
import sys
import tempfile
import types
from datetime import datetime
from unittest import mock

import pandas as pd
from django.test import SimpleTestCase

from myapp.import_status import (
    HISTORY_START_YEAR,
    IMPORT_STALE_SECONDS,
    import_stage,
    import_status,
    months_since_history_start,
    running_imports,
)
from myapp.stock_queue import (
    QUEUE_STALE_SECONDS,
    last_results,
    lock_path,
    normalize_symbols,
    queue_results,
    write_last_results,
    write_queue_results,
)


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


class StockQueueTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.tmp.name, "data", "import_logs"))
        self.base = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_lock_returns_none(self):
        self.assertIsNone(queue_results(self.base))

    def test_fresh_lock_returns_statuses(self):
        write_queue_results(self.base, {"2330": "處理中", "2317": "等待中"})
        self.assertEqual(
            queue_results(self.base), {"2330": "處理中", "2317": "等待中"}
        )

    def test_stale_lock_is_ignored(self):
        write_queue_results(self.base, {"2330": "處理中"})
        path = lock_path(self.base)
        old = os.path.getmtime(path) - QUEUE_STALE_SECONDS - 10
        os.utime(path, (old, old))
        self.assertIsNone(queue_results(self.base))

    def test_last_results_round_trip(self):
        self.assertIsNone(last_results(self.base))
        write_last_results(self.base, {"2330": "完成"})
        self.assertEqual(last_results(self.base)["results"], {"2330": "完成"})

    def test_normalize_symbols_dedupes_and_pads(self):
        self.assertEqual(
            normalize_symbols(["2330, 50 2330，2317.TW"]),
            ["2330", "0050", "2317"],
        )

    def test_normalize_symbols_rejects_non_digits(self):
        with self.assertRaises(ValueError):
            normalize_symbols(["23A0"])



class BearFilterTests(SimpleTestCase):
    """空頭濾網（V5.9-MA200F）：訊號邏輯、無未來資料、成本。"""

    @staticmethod
    def _bench(values, start="2024-01-01"):
        dates = pd.bdate_range(start, periods=len(values))
        return pd.DataFrame({"date": dates, "adj_close": values})

    def _signal(self, bench, day):
        from myapp.ml.backtest_filtered_strategy import compute_filter_signal
        return compute_filter_signal(bench, day)

    def test_below_ma_is_bear_and_halves_exposure(self):
        from myapp.ml.backtest_filtered_strategy import exposure_for
        bench = self._bench([100.0] * 199 + [90.0])
        signal = self._signal(bench, bench["date"].iloc[-1])
        self.assertTrue(signal["bear"])
        self.assertEqual(exposure_for(signal), 0.5)

    def test_equal_to_ma_is_bull(self):
        bench = self._bench([100.0] * 200)
        signal = self._signal(bench, bench["date"].iloc[-1])
        self.assertTrue(signal["available"])
        self.assertFalse(signal["bear"])

    def test_warmup_has_no_signal_and_full_exposure(self):
        from myapp.ml.backtest_filtered_strategy import exposure_for
        bench = self._bench([100.0] * 150 + [10.0])
        signal = self._signal(bench, bench["date"].iloc[-1])
        self.assertFalse(signal["available"])
        self.assertEqual(exposure_for(signal), 1.0)

    def test_signal_ignores_future_prices(self):
        bench = self._bench([100.0] * 260)
        day = bench["date"].iloc[230]
        before = self._signal(bench, day)
        crashed = bench.copy()
        crashed.loc[crashed["date"] > day, "adj_close"] = 1.0
        after = self._signal(crashed, day)
        self.assertEqual(before, after)

    def test_includes_as_of_day_close(self):
        bench = self._bench([100.0] * 230 + [50.0] + [100.0] * 5)
        day = bench["date"].iloc[230]
        self.assertTrue(self._signal(bench, day)["bear"])

    def test_missing_as_of_day_uses_previous_row(self):
        bench = self._bench([100.0] * 230)
        sunday = bench["date"].iloc[-1] + pd.Timedelta(days=2)
        signal = self._signal(bench, sunday)
        self.assertEqual(signal["close"], 100.0)

    def test_group_boundaries(self):
        from myapp.ml.backtest_filtered_strategy import GROUP_LABELS, assign_group
        self.assertEqual(
            [assign_group(x) for x in (-5.01, -5, 0, 5, 5.01)],
            [GROUP_LABELS[0], GROUP_LABELS[1], GROUP_LABELS[2], GROUP_LABELS[2], GROUP_LABELS[3]],
        )

    def test_cost_matches_v59_when_fully_invested(self):
        from myapp.ml.backtest_filtered_strategy import weight_change
        a, b = set("ABCDEFGHIJ"), set("ABCDEFGHKL")
        # V5.9：換手 20% -> 單邊 0.1% × 2 × 0.2；首期買進 1.0
        self.assertAlmostEqual(weight_change(None, 1.0, a, 1.0), 1.0)
        self.assertAlmostEqual(weight_change(a, 1.0, b, 1.0), 0.4)

    def test_cost_when_cutting_exposure_with_same_picks(self):
        from myapp.ml.backtest_filtered_strategy import weight_change
        a = set("ABCDEFGHIJ")
        self.assertAlmostEqual(weight_change(a, 1.0, a, 0.5), 0.5)

    def test_full_exposure_period_matches_v59(self):
        from myapp.ml.backtest_filtered_strategy import build_filtered_periods
        dates = pd.to_datetime(["2024-01-02", "2024-02-01"])
        picks = {dates[0]: set("ABCDEFGHIJ"), dates[1]: set("ABCDEFGHKL")}
        strategy = pd.DataFrame({
            "date": dates,
            "actual_avg": [3.0, -2.0],
            "market_avg": [1.0, 0.5],
            "turnover": [1.0, 0.2],
            "excess_return_net": [3.0 - 1.0 - 0.1, -2.0 - 0.5 - 0.04],
            "rank_ic": [0.1, 0.2],
            "direction_accuracy": [60.0, 50.0],
        })
        bench = self._bench([100.0] * 10)  # 暖機期：不減碼
        result = build_filtered_periods(strategy, picks, bench)
        self.assertEqual(list(result["exposure"]), [1.0, 1.0])
        for got, expected in zip(result["excess_return_net"], strategy["excess_return_net"]):
            self.assertAlmostEqual(got, expected)
