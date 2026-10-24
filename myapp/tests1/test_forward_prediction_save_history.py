# -*- coding: utf-8 -*-

from datetime import date
import pandas as pd

from django.test import TestCase
from django.utils import timezone

from myapp.models import PredictionHistory
from myapp.ml.forward_prediction import (
    save_prediction_history,
    MODEL_VERSION,
    LOOK_FORWARD,
)


class SavePredictionHistoryLockingTests(TestCase):
    """
    驗證 save_prediction_history 的三種行為：
    1) 新增不存在紀錄
    2) 覆寫未評估紀錄
    3) 鎖定已評估紀錄（不覆寫）
    """

    def test_create_when_not_exists(self):
        result_df = pd.DataFrame([
            {
                "prediction_date": "2026-10-22",
                "date": "2026-10-22",
                "symbol": "0050",
                "stock_name": "元大台灣50",
                "close": 200.12,
                "predicted_return_20": 0.052427,  # 小數，函式內會 *100
                "rank": 14,
                "model_version": MODEL_VERSION,
                "horizon": LOOK_FORWARD,
            }
        ])

        save_prediction_history(result_df)

        obj = PredictionHistory.objects.get(
            prediction_date=date(2026, 10, 22),
            data_date=date(2026, 10, 22),
            symbol="0050",
            model_version=MODEL_VERSION,
        )

        self.assertEqual(obj.rank, 14)
        self.assertEqual(obj.horizon, LOOK_FORWARD)
        self.assertAlmostEqual(float(obj.predicted_return_20), 5.2427, places=4)
        self.assertIsNone(obj.evaluated_at)
        self.assertIsNone(obj.actual_return_20)

    def test_update_when_not_evaluated(self):
        obj = PredictionHistory.objects.create(
            prediction_date=date(2026, 10, 22),
            data_date=date(2026, 10, 22),
            symbol="0050",
            model_version=MODEL_VERSION,
            stock_name="舊名稱",
            close_price=199.00,
            predicted_return_20=1.1111,
            rank=30,
            horizon=LOOK_FORWARD,
            evaluated_at=None,
            actual_return_20=None,
        )

        result_df = pd.DataFrame([
            {
                "prediction_date": "2026-10-22",
                "date": "2026-10-22",
                "symbol": "0050",
                "stock_name": "新名稱",
                "close": 210.55,
                "predicted_return_20": 0.031234,  # => 3.1234%
                "rank": 8,
                "model_version": MODEL_VERSION,
                "horizon": LOOK_FORWARD,
            }
        ])

        save_prediction_history(result_df)

        obj.refresh_from_db()
        self.assertEqual(obj.stock_name, "新名稱")
        self.assertAlmostEqual(float(obj.close_price), 210.55, places=2)
        self.assertAlmostEqual(float(obj.predicted_return_20), 3.1234, places=4)
        self.assertEqual(obj.rank, 8)
        self.assertEqual(obj.horizon, LOOK_FORWARD)

    def test_lock_when_already_evaluated(self):
        evaluated_time = timezone.now()

        obj = PredictionHistory.objects.create(
            prediction_date=date(2026, 10, 22),
            data_date=date(2026, 10, 22),
            symbol="0050",
            model_version=MODEL_VERSION,
            stock_name="已評估原值",
            close_price=188.88,
            predicted_return_20=9.9999,
            rank=1,
            horizon=LOOK_FORWARD,
            evaluated_at=evaluated_time,
            actual_return_20=2.3456,
        )

        result_df = pd.DataFrame([
            {
                "prediction_date": "2026-10-22",
                "date": "2026-10-22",
                "symbol": "0050",
                "stock_name": "不應覆寫",
                "close": 999.99,
                "predicted_return_20": 0.8888,  # => 88.88%
                "rank": 30,
                "model_version": MODEL_VERSION,
                "horizon": LOOK_FORWARD,
            }
        ])

        save_prediction_history(result_df)

        obj.refresh_from_db()
        # 應維持原值，不被覆寫
        self.assertEqual(obj.stock_name, "已評估原值")
        self.assertAlmostEqual(float(obj.close_price), 188.88, places=2)
        self.assertAlmostEqual(float(obj.predicted_return_20), 9.9999, places=4)
        self.assertEqual(obj.rank, 1)
        self.assertEqual(obj.horizon, LOOK_FORWARD)
        self.assertEqual(obj.evaluated_at, evaluated_time)
        self.assertAlmostEqual(float(obj.actual_return_20), 2.3456, places=4)