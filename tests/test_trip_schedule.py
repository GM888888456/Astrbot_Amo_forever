# -*- coding: utf-8 -*-
"""出行日程一致性：人在旅游，日程就不能写着「家」。

踩过的坑：11:02 出行覆盖层写好了南阳，11:05 插件重启后走「已有日程」那条早退分支，
生成/重建没有再过一遍溢出层，于是下午 11:00-20:00 全是「休息 / 家」，
她聊天说在南阳逛恐龙园，日程却在家躺尸。
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import astrbot_stub  # noqa: E402

astrbot_stub.install()

import main as amo_main  # noqa: E402

TODAY = "2026-11-13"


class FakeDB:
    def __init__(self, kv=None):
        self.kv = dict(kv or {})
        self.saved = []

    def kv_get(self, key, default=None):
        return self.kv.get(key, default)

    def kv_set(self, key, value):
        self.kv[key] = value

    def save_schedule(self, day, items):
        self.saved.append((day, len(items)))


def make_plugin(kv=None, cfg=None, hour=14):
    state = object.__new__(amo_main.HumanState)
    state.db = FakeDB(kv)
    state.config = dict(cfg or {"city_travel_schedule": True})
    state.schedule = {}
    state.calls = []
    state.hour = hour
    amo_main._now = lambda: type("T", (), {"hour": state.hour})()

    def fake_travel_overlay(city=None):
        state.calls.append(("travel", city))
        state.schedule[TODAY] = [
            {"start": "%02d:00" % h, "end": "%02d:00" % (h + 1),
             "activity": "逛恐龙园", "place": "%s·恐龙园" % city, "category": "play"}
            for h in range(11, 21)
        ]
        state.db.save_schedule(TODAY, state.schedule[TODAY])
        return True

    def fake_return_overlay(city=None, until=21):
        state.calls.append(("return", city, until))
        state.schedule[TODAY] = [
            {"start": "%02d:00" % h, "end": "%02d:00" % (h + 1),
             "activity": "在%s逛，晚上回" % city, "place": city, "category": "play"}
            for h in range(11, int(until))
        ] + [
            {"start": "%02d:00" % h, "end": "%02d:00" % (h + 1),
             "activity": "到家缓一会儿", "place": "家", "category": "rest"}
            for h in range(int(until), 24)
        ]
        state.db.save_schedule(TODAY, state.schedule[TODAY])
        return True

    state.apply_travel_overlay = fake_travel_overlay
    state.apply_return_overlay = fake_return_overlay

    def cfg_bool(key, default=False):
        value = state.config.get(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on", "是")

    state.p = type("P", (), {"cfg_bool": staticmethod(cfg_bool)})()
    return state


SOLO = {"city": "南阳", "day": TODAY, "return_day": TODAY, "return_hour": 21,
        "phase": "applied", "spots": ["南阳市西峡伏牛山老骨岭"]}


class ActiveTripTests(unittest.TestCase):
    def test_solo_trip_today(self):
        state = make_plugin({"wander_trip": SOLO})
        trip = state._active_trip(TODAY)
        self.assertIsNotNone(trip)
        self.assertEqual(trip["city"], "南阳")
        self.assertEqual(trip["kind"], "solo")
        self.assertEqual(trip["return_hour"], 21)

    def test_follow_trip_shape(self):
        state = make_plugin({"travel": {"city": "南阳", "start_day": TODAY,
                                        "return_day": "2026-11-15", "phase": "touring"}})
        trip = state._active_trip(TODAY)
        self.assertEqual(trip["kind"], "follow")
        self.assertEqual(trip["return_day"], "2026-11-15")

    def test_out_of_range_and_cancelled_are_not_trips(self):
        state = make_plugin({"wander_trip": dict(SOLO, day="2026-11-20",
                                                  return_day="2026-11-20")})
        self.assertIsNone(state._active_trip(TODAY))
        state = make_plugin({"wander_trip": dict(SOLO, phase="cancelled")})
        self.assertIsNone(state._active_trip(TODAY))
        state = make_plugin({"wander_trip": {}})
        self.assertIsNone(state._active_trip(TODAY))


class SyncScheduleTests(unittest.TestCase):
    def test_same_day_trip_uses_return_overlay(self):
        """一天来回：白天在南阳，21:00 之后才回。"""
        state = make_plugin({"wander_trip": SOLO}, hour=14)
        items = [{"start": "10:00", "activity": "休息", "place": "家"}]
        out = state._sync_trip_schedule(items, TODAY)
        self.assertEqual(state.calls, [("return", "南阳", 21)])
        by_hour = {item["start"]: item for item in out}
        self.assertTrue(by_hour["14:00"]["place"].startswith("南阳"))
        self.assertEqual(by_hour["23:00"]["place"], "家")
        self.assertTrue(state.db.saved)

    def test_multi_day_trip_uses_travel_overlay(self):
        state = make_plugin({"travel": {"city": "南阳", "start_day": "2026-11-12",
                                        "return_day": "2026-11-15", "phase": "touring"}},
                             hour=14)
        out = state._sync_trip_schedule([], TODAY)
        self.assertEqual(state.calls, [("travel", "南阳")])
        by_hour = {item["start"]: item for item in out}
        self.assertTrue(by_hour["14:00"]["place"].startswith("南阳"))
        self.assertEqual(by_hour["14:00"]["activity"], "逛恐龙园")

    def test_after_return_hour_leaves_schedule_alone(self):
        state = make_plugin({"wander_trip": SOLO}, hour=22)
        items = [{"start": "22:00", "activity": "到家", "place": "家"}]
        self.assertEqual(state._sync_trip_schedule(items, TODAY), items)
        self.assertEqual(state.calls, [])

    def test_no_trip_means_no_change(self):
        state = make_plugin({})
        items = [{"start": "22:00", "activity": "睡觉", "place": "家"}]
        self.assertEqual(state._sync_trip_schedule(items, TODAY), items)
        self.assertEqual(state.calls, [])

    def test_config_switch_off_respects_owner(self):
        state = make_plugin({"wander_trip": SOLO}, cfg={"city_travel_schedule": False})
        self.assertEqual(state._sync_trip_schedule([], TODAY), [])
        self.assertEqual(state.calls, [])

    def test_overlay_failure_does_not_break_chat(self):
        state = make_plugin({"wander_trip": SOLO})

        def boom(city=None, until=21):
            raise RuntimeError("挂了")

        state.apply_return_overlay = boom
        items = [{"start": "14:00", "activity": "休息", "place": "家"}]
        self.assertEqual(state._sync_trip_schedule(items, TODAY), items)


class DayTypeTests(unittest.TestCase):
    def test_trip_forces_outing_day_type(self):
        """在外面旅游就不该抽到「宅家日」。"""
        state = make_plugin({"wander_trip": SOLO})
        state._day_types = lambda: [
            {"id": "homebody", "name": "宅家日", "scope": "any", "weight": 1.0},
            {"id": "outing", "name": "外出日", "scope": "any", "weight": 1.0,
             "guide": "在外面逛"},
        ]
        import day_types

        picked = state._today_day_type(TODAY)
        self.assertEqual(picked["id"], "outing")
        self.assertEqual(state.db.kv_get("day_type_" + TODAY)["id"], "outing")
        self.assertTrue(hasattr(day_types, "pick_day_type"))

    def test_no_trip_keeps_picked_day_type(self):
        state = make_plugin({})
        state._day_types = lambda: [
            {"id": "homebody", "name": "宅家日", "scope": "any", "weight": 1.0},
            {"id": "outing", "name": "外出日", "scope": "any", "weight": 1.0},
        ]
        picked = state._today_day_type(TODAY)
        self.assertIn(picked["id"], ("homebody", "outing"))


if __name__ == "__main__":
    unittest.main()
