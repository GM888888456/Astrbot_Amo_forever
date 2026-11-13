# -*- coding: utf-8 -*-
"""日程里不许凭空出现他：他只能出现在聊天里。

用户的原话：把他加进她的日程、他在外地却生成「他在陪她」，这很可怕。
只有聊天确认他今天在场（`his_present_day`）才允许。
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


def make_state(kv=None, home="南明区·小窝"):
    state = object.__new__(amo_main.HumanState)
    state.db = FakeDB(kv)
    state.schedule_profile = {"home": home}
    state.p = types.SimpleNamespace(cfg_str=lambda key, default="": default)
    amo_main.today_str = lambda *a, **k: TODAY
    return state


class HisPresenceTests(unittest.TestCase):
    def test_activity_with_him_is_rewritten(self):
        state = make_state()
        items = [
            {"start": "09:00", "end": "10:00", "activity": "跟他一起出门，先去恐龙园",
             "place": "南阳·恐龙园", "category": "play"},
            {"start": "17:00", "end": "18:00", "activity": "回酒店等他忙完",
             "place": "南阳·酒店房间", "category": "rest"},
            {"start": "00:00", "end": "07:00", "activity": "在他电脑里睡着",
             "place": "他桌面上", "category": "sleep"},
        ]
        out = state._strip_his_presence(items, TODAY)
        for row in out:
            self.assertNotIn("他", row["activity"], row)
            self.assertNotIn("阿墨", row["activity"], row)
            self.assertNotIn("他", row["place"], row)
        self.assertIn("自己出门", out[0]["activity"])
        self.assertIn("南明区·小窝", out[2]["place"], "他的桌面要换回她自己的家")

    def test_chat_confirmed_presence_is_kept(self):
        state = make_state({"his_present_day": TODAY})
        items = [{"start": "20:00", "end": "21:00", "activity": "他来找我，一起吃饭",
                  "place": "家", "category": "meal"}]
        out = state._strip_his_presence(items, TODAY)
        self.assertIn("他来找我", out[0]["activity"])

    def test_other_day_presence_does_not_leak(self):
        state = make_state({"his_present_day": "2026-11-10"})
        items = [{"start": "20:00", "end": "21:00", "activity": "他在家陪我",
                  "place": "家", "category": "rest"}]
        out = state._strip_his_presence(items, TODAY)
        self.assertNotIn("他", out[0]["activity"])

    def test_empty_and_non_dict_items_pass_through(self):
        state = make_state()
        self.assertEqual(state._strip_his_presence([], TODAY), [])
        items = ["x", {"start": "09:00", "end": "10:00", "activity": "上班",
                       "place": "公司", "category": "work"}]
        out = state._strip_his_presence(items, TODAY)
        self.assertEqual(out[0], "x")
        self.assertEqual(out[1]["activity"], "上班")

    def test_home_name_prefers_profile(self):
        self.assertEqual(make_state()._home_name(), "南明区·小窝")

    def test_home_name_never_empty(self):
        state = make_state(home="")
        self.assertEqual(state._home_name(), "家")


if __name__ == "__main__":
    unittest.main()
