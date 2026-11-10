"""day_types / schedule_change 的单元测试：不依赖 AstrBot，直接跑这两个模块。"""
import datetime
import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import day_types as DT
import schedule_change as SC


class DayTypeTests(unittest.TestCase):
    def test_defaults_load(self):
        types = DT.normalize_day_types(None)
        self.assertGreaterEqual(len(types), 6)
        names = [t["name"] for t in types]
        for want in ("上班日", "休息日", "外出日", "宅家日", "加班日", "摸鱼日"):
            self.assertIn(want, names)

    def test_weekend_only_weekend_types(self):
        types = DT.normalize_day_types(None)
        for seed in ("2026-11-14", "2026-11-15", "2026-11-21"):
            picked = DT.pick_day_type(types, True, seed)
            self.assertIn(picked["scope"], ("weekend", "any"))

    def test_weekday_excludes_weekend_types(self):
        types = DT.normalize_day_types(None)
        for seed in ("2026-11-11", "2026-11-12", "2026-11-13"):
            picked = DT.pick_day_type(types, False, seed)
            self.assertIn(picked["scope"], ("weekday", "any"))

    def test_same_seed_same_result(self):
        types = DT.normalize_day_types(None)
        a = DT.pick_day_type(types, True, "2026-11-14")
        b = DT.pick_day_type(types, True, "2026-11-14")
        self.assertEqual(a["id"], b["id"])

    def test_disabled_type_never_picked(self):
        types = DT.normalize_day_types([
            {"id": "only", "name": "唯一", "enabled": True, "weight": 1, "scope": "any"},
            {"id": "off", "name": "关掉的", "enabled": False, "weight": 99, "scope": "any"},
        ])
        for seed in ("a", "b", "c", "d", "e"):
            self.assertEqual(DT.pick_day_type(types, False, seed)["id"], "only")

    def test_all_disabled_falls_back(self):
        types = DT.normalize_day_types([
            {"id": "off", "name": "关掉的", "enabled": False, "weight": 1, "scope": "any"},
        ])
        picked = DT.pick_day_type(types, False, "x")
        self.assertEqual(picked["id"], "workday")


class ScheduleChangeTests(unittest.TestCase):
    NOW = datetime.datetime(2026, 11, 10, 18, 10)

    def _items(self):
        return [
            {"start": "17:00", "end": "18:30", "activity": "下班通勤", "place": "路上", "category": "commute"},
            {"start": "18:30", "end": "20:00", "activity": "吃晚饭", "place": "家", "category": "meal"},
            {"start": "20:00", "end": "22:30", "activity": "刷手机", "place": "家", "category": "rest"},
            {"start": "22:30", "end": "23:59", "activity": "睡觉", "place": "家", "category": "sleep"},
        ]

    def test_detect_pickup(self):
        c = SC.detect_schedule_change("我下班来接你")
        self.assertIsNotNone(c)
        self.assertIn("来接我", c["activity"])

    def test_detect_sleep(self):
        c = SC.detect_schedule_change("一起睡吧")
        self.assertEqual(c["category"], "sleep")

    def test_no_match_chat(self):
        self.assertIsNone(SC.detect_schedule_change("今天天气不错啊"))

    def test_apply_rewrites_current_slot(self):
        items = self._items()
        change = SC.detect_schedule_change("来接我")
        out = SC.apply_change(items, change, self.NOW)
        cur = out[0]
        self.assertEqual(cur["start"], "18:10")
        self.assertIn("来接我", cur["activity"])
        self.assertEqual(out[1]["activity"], "吃晚饭")

    def test_apply_does_not_mutate_input(self):
        items = self._items()
        before = [dict(x) for x in items]
        SC.apply_change(items, SC.detect_schedule_change("来接我"), self.NOW)
        self.assertEqual(items, before)

    def test_apply_sleep_merges_night(self):
        items = self._items()
        change = SC.detect_schedule_change("该睡了")
        out = SC.apply_change(items, change, self.NOW)
        self.assertEqual(out[0]["category"], "sleep")
        self.assertEqual(out[1]["activity"], "睡觉")
        self.assertEqual(out[1]["category"], "sleep")

    def test_apply_empty_items(self):
        self.assertEqual(SC.apply_change([], SC.detect_schedule_change("睡吧"), self.NOW), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
