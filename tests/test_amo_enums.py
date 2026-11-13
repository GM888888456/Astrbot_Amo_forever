# -*- coding: utf-8 -*-
"""枚举的值必须和旧字符串一模一样：换了类型，不换语义。"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from amo_enums import (  # noqa: E402
    MOOD_KEYS,
    ActivityCategory,
    MoodKey,
    SceneZone,
    coerce,
    value_of,
)


class ValueTests(unittest.TestCase):
    def test_mood_values_unchanged(self):
        self.assertEqual(
            MOOD_KEYS,
            ("开心", "平静", "郁闷", "生气", "暴躁", "委屈", "疲惫", "焦虑", "兴奋", "依恋"),
        )
        self.assertEqual(MoodKey.ANGRY.value, "生气")

    def test_str_returns_value_not_member(self):
        self.assertEqual(str(MoodKey.ANGRY), "生气")
        self.assertEqual("%s" % MoodKey.HAPPY, "开心")
        self.assertEqual(f"{MoodKey.CALM}", "平静")

    def test_equals_plain_string(self):
        self.assertEqual(MoodKey.ANGRY, "生气")
        self.assertIn(MoodKey.ANGRY, ("生气", "暴躁"))

    def test_category_and_zone_values(self):
        self.assertEqual(ActivityCategory.SLEEP.value, "sleep")
        self.assertEqual(ActivityCategory.COMMUTE.value, "commute")
        self.assertEqual(SceneZone.SCENIC.value, "scenic")
        self.assertEqual(SceneZone.RESTAURANT.value, "restaurant")


class CoerceTests(unittest.TestCase):
    def test_accepts_old_strings(self):
        self.assertIs(coerce(MoodKey, "生气"), MoodKey.ANGRY)
        self.assertIs(coerce(ActivityCategory, "sleep"), ActivityCategory.SLEEP)

    def test_accepts_enum(self):
        self.assertIs(coerce(MoodKey, MoodKey.HAPPY), MoodKey.HAPPY)

    def test_unknown_returns_default(self):
        self.assertIs(coerce(ActivityCategory, "Sleep", default="rest"),
                      ActivityCategory.REST)
        self.assertIsNone(coerce(ActivityCategory, "???"))

    def test_dirty_value_does_not_raise(self):
        # 历史脏数据不能把链路打挂：能修的修（去掉空格），修不了的退回默认值
        self.assertEqual(value_of(ActivityCategory, " sleep ", default=""), "sleep")
        self.assertEqual(value_of(ActivityCategory, "Sleep", default="rest"), "rest")
        self.assertEqual(value_of(SceneZone, "景区", default="street"), "street")


if __name__ == "__main__":
    unittest.main()
