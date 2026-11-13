# -*- coding: utf-8 -*-
"""他喊她回来/去别处：她自己掂量愿不愿意，愿意就先走过去再改日程。

不要钱——那 100 是赞助开发者做功能的，不是游戏里的打赏。
"""

import asyncio
import datetime
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
    def __init__(self):
        self.kv = {}
        self.saved = {}

    def kv_get(self, key, default=None):
        return self.kv.get(key, default)

    def kv_set(self, key, value):
        self.kv[key] = value

    def get_schedule(self, day):
        return self.saved.get(day, [])

    def save_schedule(self, day, items):
        self.saved[day] = items


class FakeEvent:
    def __init__(self, text, private=True):
        self.message_str = text
        self.unified_msg_origin = "umo"
        self._private = private
        self.stopped = False

    def is_private_chat(self):
        return self._private

    def stop_event(self):
        self.stopped = True

    def get_sender_id(self):
        return "u1"


class FakeState:
    def __init__(self, mood, items):
        self.schedule = {TODAY: items}
        self._mood = mood

    def snapshot(self):
        return {"mood": self._mood}


ITEMS = [
    {"start": "15:00", "end": "16:00", "activity": "在景区逛", "place": "南阳·恐龙园", "category": "play"},
    {"start": "16:00", "end": "17:00", "activity": "找家咖啡店坐坐", "place": "南阳·咖啡店", "category": "rest"},
]


def make_plugin(mood=None, items=None):
    p = object.__new__(amo_main.HumanCorePlugin)
    p.config = {}
    p.db = FakeDB()
    p.db.saved[TODAY] = list(items or ITEMS)
    p.state = FakeState(mood or {"平静": 60}, list(items or ITEMS))
    p.memories = []

    async def send(umo, text):
        p.last_reply = text

    async def remember(uid, content, kind="fact", tier=1, scope="private", group_id=""):
        p.memories.append({"content": content, "kind": kind})

    p.context = types.SimpleNamespace(send_message=send)
    p._primary_uid = lambda: "u1"
    p._write_memory_checked = remember
    am = amo_main
    am._clock_now = lambda: datetime.datetime(2026, 11, 13, 15, 20)
    am.today_str = lambda *a, **k: TODAY
    return p


class UserMoveTests(unittest.TestCase):
    def test_good_mood_accepts_and_adds_a_walk_segment(self):
        p = make_plugin({"平静": 60, "开心": 65})
        event = FakeEvent("回来吧")
        handled = asyncio.run(p._maybe_user_move(event, "回来吧"))
        self.assertTrue(handled)
        self.assertTrue(event.stopped)
        rows = p.state.schedule[TODAY]
        roads = [r for r in rows if r.get("place") == "路上"]
        self.assertTrue(roads, "中间要有在路上的一段")
        self.assertTrue(any(r.get("place") == "家" for r in rows), "到了之后要在家")
        self.assertTrue(any("路上" in str(r.get("activity")) or "分钟" in p.last_reply
                            for r in rows))
        self.assertTrue(p.memories and p.memories[0]["kind"] == "event")

    def test_bad_mood_refuses_without_touching_schedule(self):
        p = make_plugin({"生气": 80, "暴躁": 60})
        before = [dict(x) for x in p.state.schedule[TODAY]]
        event = FakeEvent("回来吧")
        handled = asyncio.run(p._maybe_user_move(event, "回来吧"))
        self.assertTrue(handled)
        self.assertEqual(p.state.schedule[TODAY], before, "心情差就不改日程")
        self.assertIn("不去", p.last_reply)
        self.assertTrue(p.memories)

    def test_not_a_move_request_is_ignored(self):
        p = make_plugin()
        event = FakeEvent("今天天气不错")
        self.assertFalse(asyncio.run(p._maybe_user_move(event, "今天天气不错")))

    def test_group_chat_is_ignored(self):
        p = make_plugin()
        event = FakeEvent("回来吧", private=False)
        self.assertFalse(asyncio.run(p._maybe_user_move(event, "回来吧")))


if __name__ == "__main__":
    unittest.main()
