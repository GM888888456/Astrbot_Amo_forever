# -*- coding: utf-8 -*-
"""出行期间的状态回落：日程没落地时也不能说自己在「家」。

踩过的坑：出行覆盖层没落到日程上（重启走「已有日程」早退、刚重建、日程还没生成），
`current_activity()` 就退到硬编码的「家/公司」，于是她聊天说在南阳逛恐龙园、
状态和照片场景却写着家——比没有状态更糟。
"""

import os
import sys
import types
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

    def kv_get(self, key, default=None):
        return self.kv.get(key, default)

    def kv_set(self, key, value):
        self.kv[key] = value

    def save_schedule(self, day, items):
        pass


SOLO = {"city": "南阳", "day": TODAY, "return_day": TODAY, "return_hour": 21,
        "phase": "applied", "spots": ["南阳市西峡伏牛山老界岭·恐龙遗址园旅游区"]}


class ActivityFallbackTests(unittest.TestCase):
    def setUp(self):
        self._saved = {name: getattr(amo_main, name) for name in ("today_str", "minutes_now", "_now")}
        amo_main.today_str = lambda *a, **k: TODAY
        amo_main.minutes_now = lambda *a, **k: 14 * 60

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(amo_main, name, value)

    def state(self, kv, hour=14):
        state = object.__new__(amo_main.HumanState)
        state.db = FakeDB(kv)
        state.schedule = {}
        amo_main._now = lambda *a, **k: types.SimpleNamespace(hour=hour)
        return state

    def test_trip_without_schedule_stays_out(self):
        """日程是空的（还没生成/刚重建），但只要在出行中，状态就得在外面。"""
        act = self.state({"wander_trip": SOLO}).current_activity()
        self.assertIn("南阳", act["place"])
        self.assertNotIn("家", act["place"])
        self.assertEqual(act["zone"], "hotel")

    def test_follow_trip_also_counts(self):
        travel = {"city": "南阳", "start_day": TODAY, "return_day": "2026-11-15",
                  "phase": "touring"}
        act = self.state({"travel": travel}).current_activity()
        self.assertIn("南阳", act["place"])

    def test_after_return_hour_goes_back_to_home(self):
        """21 点回家了，就不能还挂着南阳。"""
        act = self.state({"wander_trip": SOLO}, hour=22).current_activity()
        self.assertEqual(act["place"], "家")

    def test_no_trip_keeps_the_old_fallback(self):
        """没有出行时，回落规则一个字不变：白天公司、晚上家。"""
        self.assertEqual(self.state({}, hour=14).current_activity()["place"], "公司")
        self.assertEqual(self.state({}, hour=20).current_activity()["place"], "家")

    def test_schedule_wins_over_trip_placeholder(self):
        state = self.state({"wander_trip": SOLO})
        state.schedule = {TODAY: [{"start": "13:00", "end": "15:00", "activity": "逛恐龙园",
                                   "place": "南阳·恐龙遗址园", "category": "play"}]}
        act = state.current_activity()
        self.assertEqual(act["place"], "南阳·恐龙遗址园")
        self.assertEqual(act["activity"], "逛恐龙园")

    def test_state_on_trip_helper_is_safe_without_db(self):
        state = object.__new__(amo_main.HumanState)
        self.assertFalse(state._state_on_trip())
        state.db = FakeDB({"wander_trip": SOLO})
        self.assertTrue(state._state_on_trip())


if __name__ == "__main__":
    unittest.main()
