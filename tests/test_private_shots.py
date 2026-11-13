# -*- coding: utf-8 -*-
"""私密照片：判定、提示词边界、每天上限。"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from private_shots import (  # noqa: E402
    BOUNDARY,
    NEGATIVE,
    GlamourState,
    Verdict,
    build_prompt,
    decide,
    detect_outfit,
    detect_pose,
    wants_private_shot,
)


class DetectTests(unittest.TestCase):
    def test_needs_outfit_and_shot_word(self):
        self.assertTrue(wants_private_shot("穿黑色蕾丝内衣拍张照"))
        self.assertTrue(wants_private_shot("拍一张穿制服的照片"))
        self.assertFalse(wants_private_shot("今天吃什么"))
        self.assertFalse(wants_private_shot("内衣洗了没"))

    def test_outfit_and_pose(self):
        self.assertEqual(detect_outfit("穿黑色蕾丝内衣拍张照"), "内衣")
        self.assertIn("躺", detect_pose("躺拍一张"))
        self.assertEqual(detect_pose("随便说说话"), "")


class DecisionTests(unittest.TestCase):
    def test_first_time_is_shy(self):
        self.assertIs(decide(GlamourState.NONE.value, 10, 40, 0), Verdict.SHY)

    def test_second_time_grants(self):
        self.assertIs(decide(GlamourState.SHY_REFUSED.value, 10, 40, 0), Verdict.GRANT)

    def test_bad_mood_scolds_without_judging(self):
        self.assertIs(decide(GlamourState.SHY_REFUSED.value, 80, 10, 0), Verdict.SCOLD)
        self.assertIs(decide(GlamourState.NONE.value, 90, 20, 0), Verdict.SCOLD)

    def test_daily_cap(self):
        self.assertIs(decide(GlamourState.GRANTED.value, 10, 40, 2, 2), Verdict.BUSY)

    def test_unknown_state_behaves_like_first_time(self):
        self.assertIs(decide("???", 10, 40, 0), Verdict.SHY)


class PromptTests(unittest.TestCase):
    def test_boundary_and_negative_always_present(self):
        prompt = build_prompt("黑色蕾丝内衣", "侧躺在床沿", "酒店房间")
        self.assertIn("不露点", prompt)
        self.assertIn("不出现性行为", prompt)
        self.assertIn("explicit", prompt)
        for word in ("黑色蕾丝内衣", "侧躺在床沿", "酒店房间"):
            self.assertIn(word, prompt)

    def test_no_outfit_still_safe(self):
        prompt = build_prompt("", "", "")
        self.assertIn(BOUNDARY[:6], prompt)
        self.assertIn("nude", NEGATIVE)


if __name__ == "__main__":
    unittest.main()
