# -*- coding: utf-8 -*-
"""24 小时峰谷条：分段覆盖整天，工作日 9-12 / 14-18 是高峰，周末全空闲。"""

import datetime
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import astrbot_stub  # noqa: E402

astrbot_stub.install()

import main as amo_main  # noqa: E402


class UsageClockTests(unittest.TestCase):
    def test_segments_cover_the_whole_day(self):
        clock = amo_main.usage_clock(datetime.datetime(2026, 11, 13, 10, 30))
        self.assertEqual(clock["segments"][0]["from"], 0)
        self.assertEqual(clock["segments"][-1]["to"], 24 * 60)
        total = sum(seg["to"] - seg["from"] for seg in clock["segments"])
        self.assertEqual(total, 24 * 60)

    def test_weekday_peak_windows(self):
        clock = amo_main.usage_clock(datetime.datetime(2026, 11, 13, 10, 30))  # 周五
        peaks = [(seg["from"], seg["to"]) for seg in clock["segments"] if seg["peak"]]
        self.assertIn((9 * 60, 12 * 60), peaks)
        self.assertIn((14 * 60, 18 * 60), peaks)
        self.assertTrue(clock["now_peak"], "10:30 应该是高峰价")

    def test_weekend_is_all_idle(self):
        clock = amo_main.usage_clock(datetime.datetime(2026, 11, 14, 10, 30))  # 周六
        self.assertFalse(any(seg["peak"] for seg in clock["segments"]))
        self.assertFalse(clock["now_peak"])

    def test_now_minute_and_note(self):
        clock = amo_main.usage_clock(datetime.datetime(2026, 11, 13, 8, 5))
        self.assertEqual(clock["now_minute"], 8 * 60 + 5)
        self.assertFalse(clock["now_peak"], "8:05 是空闲价")
        self.assertIn("高峰", clock["note"])


if __name__ == "__main__":
    unittest.main()
