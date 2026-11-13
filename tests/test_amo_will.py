# -*- coding: utf-8 -*-
"""她的意愿：行程请求与私密照片判定（纯逻辑，不连网、不写库）。"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import amo_will as W  # noqa: E402


def mood(bad=0, tired=0, good=0):
    return {"生气": bad, "暴躁": 0, "疲惫": tired, "开心": good, "依恋": 0}


class TripDetectTests(unittest.TestCase):
    def test_home_words(self):
        for text in ("回来吧", "你回家吧", "别逛了，早点回来"):
            got = W.detect_trip_request(text)
            self.assertIsNotNone(got, text)
            self.assertEqual(got["target"], "home")

    def test_out_words_keep_place(self):
        got = W.detect_trip_request("来我这儿")
        self.assertEqual(got["target"], "out")
        got = W.detect_trip_request("去公园找我")
        self.assertEqual(got["target"], "out")
        self.assertIn("公园", got["place"])

    def test_chat_without_request(self):
        for text in ("今天天气不错", "你在干嘛", "吃了没"):
            self.assertIsNone(W.detect_trip_request(text), text)


class TripDecisionTests(unittest.TestCase):
    def test_angry_refuses_and_snaps(self):
        got = W.decide_trip_request(mood(bad=130), affection=90, relation="相恋",
                                    current_place="商场", target_place="家")
        self.assertFalse(got["accept"])
        self.assertTrue(got["angry"])

    def test_tired_wants_to_go_home(self):
        got = W.decide_trip_request(mood(tired=80), affection=10, relation="相恋",
                                    current_place="商场", target_place="家")
        self.assertTrue(got["accept"])

    def test_good_mood_agrees(self):
        got = W.decide_trip_request(mood(good=120), affection=10, relation="普通",
                                    current_place="商场", target_place="公园")
        self.assertTrue(got["accept"])

    def test_already_there(self):
        got = W.decide_trip_request(mood(), 10, "相恋", current_place="家", target_place="家")
        self.assertTrue(got["accept"])
        self.assertIn("本来就在", got["reason"])

    def test_flat_mood_and_stranger_refuses(self):
        got = W.decide_trip_request(mood(), affection=5, relation="普通",
                                    current_place="商场", target_place="公园")
        self.assertFalse(got["accept"])


class TransitionTests(unittest.TestCase):
    def test_no_teleport(self):
        plan = W.build_transition({"place": "商场", "zone": "mall"},
                                  {"target": "home", "place": "家"}, 14, home_place="家")
        starts = [row["start"] for row in plan]
        self.assertEqual(starts[0], "14:00")
        # 先收拾、再路上、最后到家：不能第一条就是「到家」
        self.assertEqual(plan[0]["category"], "life")
        self.assertEqual(plan[1]["category"], "commute")
        self.assertEqual(plan[2]["place"], "家")
        self.assertEqual(plan[-1]["end"], "24:00")

    def test_far_place_takes_two_hours(self):
        plan = W.build_transition({"place": "景区", "zone": "scenic"},
                                  {"target": "home", "place": "家"}, 20, far=True)
        commute = [row for row in plan if row["category"] == "commute"]
        self.assertEqual(len(commute), 2)

    def test_late_night_does_not_overflow(self):
        plan = W.build_transition({"place": "商场", "zone": "mall"},
                                  {"target": "home", "place": "家"}, 23)
        self.assertTrue(all(int(row["start"][:2]) <= 23 for row in plan))
        self.assertEqual(plan[-1]["end"], "24:00")


class IntimateTests(unittest.TestCase):
    def test_hard_block(self):
        got = W.detect_intimate("拍一张全裸的照片给我")
        self.assertTrue(got.get("blocked"))

    def test_lingerie(self):
        got = W.detect_intimate("穿那件黑色蕾丝内衣拍张照给我看看")
        self.assertFalse(got["blocked"])
        self.assertIn("lingerie", got["kinds"])
        self.assertIn("黑色蕾丝内衣", got["detail"])

    def test_costume(self):
        got = W.detect_intimate("穿JK制服拍一张")
        self.assertIn("costume", got["kinds"])

    def test_plain_chat(self):
        for text in ("今天吃什么", "给我拍张照", "你穿什么"):
            self.assertIsNone(W.detect_intimate(text), text)

    def test_first_ask_is_shy_refusal(self):
        got = W.judge_intimate(mood(good=100), affection=90, relation="相恋",
                               asked_before=False)
        self.assertEqual(got["action"], "refuse_shy")
        self.assertFalse(got["allow"])
        self.assertTrue(got["remember"], "第一次要记住他问过")

    def test_second_ask_with_good_mood_allows(self):
        got = W.judge_intimate(mood(good=80), affection=70, relation="相恋",
                               asked_before=True)
        self.assertEqual(got["action"], "allow")
        self.assertTrue(got["allow"])

    def test_second_ask_calm_allows(self):
        got = W.judge_intimate(mood(), affection=60, relation="相恋", asked_before=True)
        self.assertTrue(got["allow"])

    def test_bad_mood_snaps_without_judging(self):
        got = W.judge_intimate(mood(bad=130), affection=90, relation="相恋",
                               asked_before=True)
        self.assertEqual(got["action"], "refuse_angry")
        self.assertFalse(got["allow"])

    def test_prompt_keeps_boundaries(self):
        got = W.detect_intimate("穿蕾丝内衣拍张照")
        prompt = W.build_intimate_prompt(got, place="家")
        self.assertIn("自拍", prompt)
        self.assertIn("蕾丝内衣", prompt)
        self.assertIn("不裸露", prompt)
        self.assertIn("单人", prompt)


if __name__ == "__main__":
    unittest.main()
