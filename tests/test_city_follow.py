from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from city_follow import (  # noqa: E402
    compose_block,
    detect_city,
    pick_spots,
    travel_action,
    travel_block,
    travel_events,
    travel_to_events,
)


class DetectCityTests(unittest.TestCase):
    """只认「我在X / 我到X / 我回X」，别的说法一律不触发。"""

    def test_wo_zai(self) -> None:
        cases = {
            "我在清远": "清远",
            "我在广州": "广州",
            "我还在广州": "广州",
            "我人在清远": "清远",
            "我在广州出差": "广州",
            "我在东莞上班": "东莞",
            "我在东莞东城": "东莞",
        }
        for text, expected in cases.items():
            hit = detect_city(text)
            self.assertIsNotNone(hit, text)
            self.assertEqual(hit["name"], expected, text)

    def test_wo_dao(self) -> None:
        cases = {
            "我到广州了": "广州",
            "我到清远了，马上到": "清远",
            "我刚到深圳": "深圳",
        }
        for text, expected in cases.items():
            hit = detect_city(text)
            self.assertIsNotNone(hit, text)
            self.assertEqual(hit["name"], expected, text)

    def test_wo_hui(self) -> None:
        cases = {
            "我回东莞": "东莞",
            "我回东莞了": "东莞",
            "我回清远啦": "清远",
            "我准备回清远": "清远",
        }
        for text, expected in cases.items():
            hit = detect_city(text)
            self.assertIsNotNone(hit, text)
            self.assertEqual(hit["name"], expected, text)

    def test_district_keeps_city(self) -> None:
        hit = detect_city("我在深圳南山")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["name"], "深圳南山")
        self.assertEqual(hit["id"], "101280604")
        hit = detect_city("我在清远清城区")
        self.assertEqual(hit["name"], "清远清城区")
        self.assertEqual(hit["id"], "101281309")
        hit = detect_city("我在清城区", prefer_city="清远")
        self.assertEqual(hit["name"], "清远清城区")
        hit = detect_city("我在白云区", prefer_city="广州")
        self.assertEqual(hit["name"], "广州白云区")
        self.assertIsNone(detect_city("我在白云区"))

    def test_not_a_city(self) -> None:
        for text in (
            "我在等公交",
            "我在开会",
            "我在家",
            "我在公司加班",
            "我在想广州",
            "我回老家",
            "我到了",
            "我到家了",
            "他说他在广州",
            "明天我去广州",
            "广州那边下雨了",
            "我在北京路吃饭",
            "我在广州路",
            "我在南山",  # 重名，不猜
            "",
        ):
            self.assertIsNone(detect_city(text), text)


class ComposeBlockTests(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertEqual(compose_block(""), "")
        self.assertEqual(compose_block(None), "")

    def test_block(self) -> None:
        text = compose_block("清远")
        self.assertIn("清远", text)
        self.assertIn("我这边", text)


class WiringTests(unittest.TestCase):
    """main.py 接了这三个入口；schema 里有开关。"""

    def test_main_wiring(self) -> None:
        src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
        self.assertIn("detect_city as _city_detect", src)
        self.assertIn("compose_block as _city_block", src)
        self.assertIn("_city_detect(text, prefer_city", src)
        self.assertIn('_city_block(self.db.kv_get("his_city"', src)
        self.assertIn("_maybe_follow_city", src)
        self.assertIn("_switch_weather_city", src)

    def test_schema_flags(self) -> None:
        with open(os.path.join(ROOT, "_conf_schema.json"), encoding="utf-8") as fh:
            schema = json.load(fh)
        self.assertTrue(schema["city_follow_enabled"]["default"])
        self.assertTrue(schema["city_follow_weather"]["default"])

    def test_travel_wiring(self) -> None:
        src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
        self.assertIn("apply_travel_overlay", src)
        self.assertIn("_city_travel_events", src)
        self.assertIn("_city_travel_action", src)
        self.assertIn("clear_diaries_from", src)


class TravelToTests(unittest.TestCase):
    def test_journey_then_tour(self) -> None:
        spots = [{"name": "黄腾峡", "city": "清远", "area": "清城区", "projects": ["漂流"]}]
        items = travel_to_events("清远", 9, spots=spots, seed="2026-11-10")
        starts = {item["start"]: item for item in items}
        self.assertIn("09:00", starts)
        self.assertIn("坐", starts["09:00"]["activity"])
        self.assertIn("2 小时", starts["10:00"]["activity"])
        self.assertIn("到了", starts["11:00"]["activity"])
        self.assertTrue(any("黄腾峡" in item["place"] for item in items))
        self.assertIn("07:00", starts)  # 早出发会补起床

    def test_early_start_no_duplicate(self) -> None:
        for start in (0, 7, 8, 9, 19, 21):
            items = travel_to_events("清远", start, spots=[], seed="d")
            starts = [item["start"] for item in items]
            self.assertEqual(len(starts), len(set(starts)), start)

    def test_late_arrival_goes_hotel(self) -> None:
        items = travel_to_events("清远", 21, spots=[], seed="d")
        by_start = {item["start"]: item for item in items}
        self.assertIn("酒店", by_start["23:00"]["place"])

    def test_daytime_start_keeps_no_morning(self) -> None:
        items = travel_to_events("清远", 19, spots=[], seed="d")
        self.assertEqual(items[0]["start"], "19:00")


class TravelEventsTests(unittest.TestCase):
    """出行覆盖层：不上班、地点带城市、从指定小时起。"""

    def test_full_day(self) -> None:
        items = travel_events("清远", 0, spots=[])
        self.assertEqual(len(items), 24)
        self.assertEqual(items[0]["start"], "00:00")
        self.assertEqual(items[-1]["end"], "24:00")
        self.assertNotIn("office", {item["zone"] for item in items})
        self.assertNotIn("work", {item["category"] for item in items})
        self.assertTrue(all(item["place"].startswith("清远") for item in items))

    def test_real_spots(self) -> None:
        spots = [
            {"name": "黄腾峡", "city": "清远", "area": "清城区", "projects": ["漂流"]},
            {"name": "古龙峡", "city": "清远", "area": "清新区", "projects": ["玻璃大峡谷"]},
        ]
        items = travel_events("清远", 9, weekday=False, spots=spots)
        places = [i["place"] for i in items]
        self.assertTrue(any("黄腾峡" in p for p in places))
        self.assertTrue(any("古龙峡" in p for p in places))

    def test_no_spots_no_fake_names(self) -> None:
        items = travel_events("清远", 9, weekday=False, spots=[])
        places = [i["place"] for i in items]
        self.assertFalse(any("黄腾峡" in p or "古龙峡" in p for p in places))
        self.assertTrue(any("清远·街头" in p or "清远·公园" in p for p in places))

    def test_until_hour(self) -> None:
        items = travel_events("清远", 0, spots=[], until_hour=12)
        self.assertEqual(len(items), 12)
        self.assertEqual(items[-1]["start"], "11:00")
        items = travel_events("清远", from_hour=12, spots=[])
        self.assertEqual(items[0]["start"], "12:00")

    def test_from_hour(self) -> None:
        items = travel_events("清远", 18)
        self.assertEqual(len(items), 6)
        self.assertEqual(items[0]["start"], "18:00")
        self.assertEqual(items[-1]["start"], "23:00")

    def test_home_variant(self) -> None:
        items = travel_events("东莞", 20, home=True)
        self.assertEqual(len(items), 4)
        # 宅家模板只写她自己的家，不再把「他桌面上」当地点（他只能出现在聊天里）
        self.assertTrue(all(item["place"] == "家" for item in items))
        self.assertFalse(any("他" in str(item.get("activity") or "") for item in items))

    def test_travel_action(self) -> None:
        self.assertEqual(travel_action("清远", False), "enter")
        self.assertEqual(travel_action("清远", True), "enter")
        self.assertEqual(travel_action("东莞", False), "none")
        self.assertEqual(travel_action("东莞", True), "exit")
        self.assertEqual(travel_action("", True), "none")

    def test_bad_from_hour(self) -> None:
        self.assertEqual(len(travel_events("清远", "bad")), 24)

    def test_weekday_vs_weekend(self) -> None:
        work = travel_events("清远", 8, weekday=True)
        self.assertTrue(any("请了假" in i["activity"] for i in work))
        weekend = travel_events("清远", 8, weekday=False)
        self.assertFalse(any("请了假" in i["activity"] for i in weekend))
        self.assertEqual(len(work), len(weekend))

    def test_travel_block(self) -> None:
        text = travel_block("拉萨")
        self.assertIn("拉萨", text)
        self.assertIn("旅游", text)
        self.assertIn("周末", text)
        self.assertIn("请了假", travel_block("拉萨", weekday=True))
        self.assertIn("别编", text)
        self.assertEqual(travel_block(""), "")

    def test_travel_block_with_spots(self) -> None:
        spots = [{"name": "黄腾峡", "city": "清远", "area": "清城区", "projects": ["漂流"]}]
        text = travel_block("清远", weekday=True, spots=spots)
        self.assertIn("黄腾峡", text)
        self.assertIn("真实景点", text)


class PickSpotsTests(unittest.TestCase):
    def test_city_filter_and_stability(self) -> None:
        all_spots = [
            {"name": "黄腾峡", "city": "清远", "area": "清城区", "projects": ["漂流"]},
            {"name": "古龙峡", "city": "清远", "area": "清新区", "projects": ["玻璃大峡谷"]},
            {"name": "故宫博物院", "city": "北京", "area": "东城区", "projects": ["太和殿"]},
        ]
        got = pick_spots(all_spots, "清远", "2026-11-09")
        self.assertEqual(len(got), 2)
        self.assertEqual(got, pick_spots(all_spots, "清远", "2026-11-09"))
        self.assertEqual(pick_spots(all_spots, "拉萨", "2026-11-09"), [])
        self.assertEqual(pick_spots(all_spots, "清远市", "2026-11-09"), got)


if __name__ == "__main__":
    unittest.main()
