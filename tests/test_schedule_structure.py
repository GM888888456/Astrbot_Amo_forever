# -*- coding: utf-8 -*-
"""日程结构的自洽性：加班要晚走、痛经不是发烧、活动词库分时段。"""

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import schedule_engine as se  # noqa: E402


def _engine():
    return se.ScheduleEngine.__new__(se.ScheduleEngine)


def _ctx(**kwargs):
    ctx = {
        "home": "市区·家",
        "workplace": "市区·写字楼",
        "car": "",
        "has_car": False,
        "city": "东莞",
        "world": {"occupation": "普通上班族", "workplace": "市区·写字楼"},
        "yesterday": {},
        "health": {"sick": False},
        "period": {"pain": 0},
        "event": {"kind": "none"},
        "meta": {"rest": False, "holiday_days": 0},
    }
    ctx.update(kwargs)
    return ctx


class WorkdayOvertimeTests(unittest.TestCase):
    def test_overtime_moves_the_evening_into_the_office(self):
        engine = _engine()
        segments = engine._workday_segments(_ctx(event={"kind": "overtime", "effects": {"疲惫": 10}}), overtime=True)
        evening = [seg for seg in segments if seg["start"] in ("18:00", "19:00", "20:00")]
        self.assertEqual(len(evening), 3)
        for seg in evening:
            self.assertEqual(seg["zone"], "office")
            self.assertEqual(seg["category"], "work")
        self.assertEqual(segments[-1]["end"], "24:00")

    def test_normal_day_still_leaves_at_six(self):
        engine = _engine()
        segments = engine._workday_segments(_ctx(), overtime=False)
        at_six = [seg for seg in segments if seg["start"] == "18:00"][0]
        self.assertEqual(at_six["zone"], "road")


class PeriodRestTests(unittest.TestCase):
    def test_period_pain_uses_warm_water_not_medicine(self):
        engine = _engine()
        segments = engine._rest_segments(_ctx(period={"pain": 9}))
        text = "".join(seg["activity"] for seg in segments)
        self.assertIn("热水袋", text)
        self.assertNotIn("吃药", text)
        self.assertNotIn("量体温", text)

    def test_tired_health_is_not_a_sick_day(self):
        engine = _engine()
        segments = engine._rest_segments(_ctx(health={"sick": False, "status": "疲惫"}))
        text = "".join(seg["activity"] for seg in segments)
        self.assertNotIn("吃药", text)

    def test_real_sickness_still_uses_the_sick_day(self):
        engine = _engine()
        segments = engine._rest_segments(_ctx(health={"sick": True, "status": "感冒"}))
        text = "".join(seg["activity"] for seg in segments)
        self.assertIn("吃药", text)


class ActivityBankTests(unittest.TestCase):
    def test_breakfast_hour_uses_breakfast_bank(self):
        engine = _engine()
        item = {"zone": "home", "category": "meal", "activity": "起床吃早餐"}
        for seed in range(30):
            activity = engine._activity_for(item, _ctx(), 8, random.Random(seed), "")
            self.assertIn(activity, se.BREAKFAST_BANK, activity)

    def test_late_night_life_uses_night_bank(self):
        engine = _engine()
        item = {"zone": "home", "category": "life", "activity": "洗澡护肤"}
        for seed in range(30):
            activity = engine._activity_for(item, _ctx(), 22, random.Random(seed), "")
            self.assertIn(activity, se.NIGHT_LIFE_BANK, activity)

    def test_overtime_hour_at_office_is_work_not_sofa(self):
        engine = _engine()
        item = {"zone": "office", "category": "work", "activity": "上班"}
        for seed in range(30):
            activity = engine._activity_for(item, _ctx(), 19, random.Random(seed), "")
            self.assertIn(activity, se.OFFICE_WORK_BANK, activity)


if __name__ == "__main__":
    unittest.main()
