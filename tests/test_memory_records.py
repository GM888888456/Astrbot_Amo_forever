# -*- coding: utf-8 -*-
"""记忆里要留下「他今天干了什么」和「她发过什么图」。

两条都必须走事件记忆（7 天降权、14 天删除），不能变成永久事实。
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
    def __init__(self):
        self.kv = {}

    def kv_get(self, key, default=None):
        return self.kv.get(key, default)

    def kv_set(self, key, value):
        self.kv[key] = value

    def chat_history(self, uid, limit=200):
        return []


class FakeLLM:
    def __init__(self, reply="他去了南阳恐龙园。他晚上吃了烩面。"):
        self.reply = reply
        self.calls = []

    async def chat_raw(self, umo, system, prompt, contexts=None, kind="other"):
        self.calls.append({"umol": umo, "system": system, "prompt": prompt, "kind": kind})
        return self.reply


class FakePlugin:
    pass


def make_plugin(messages=None, reply=None, hour=23, minute=30):
    plugin = object.__new__(amo_main.HumanCorePlugin)
    plugin.config = {}
    plugin.db = FakeDB()
    plugin.llm = FakeLLM(reply) if reply is not None else FakeLLM()
    plugin._primary_uid = lambda: "u1"
    plugin._first_private_umo = lambda: "umo1"
    plugin._last_umo = "umo1"
    plugin._data_bot_id = lambda: "bot"
    plugin.memories = []

    async def fake_data_call(name, bot_id, **kwargs):
        return {"messages": messages or []}

    async def fake_write(uid, content, kind="fact", tier=1, scope="private", group_id=""):
        plugin.memories.append({"uid": uid, "content": content, "kind": kind,
                                "tier": tier, "scope": scope})
        return True

    plugin._data_call = fake_data_call
    plugin._write_memory_checked = fake_write

    amo_main._now = lambda: types.SimpleNamespace(hour=hour, minute=minute,
                                                  strftime=lambda fmt: TODAY)
    return plugin


MESSAGES = [
    {"role": "user", "content": "今天去了恐龙园，人多得要命"},
    {"role": "bot", "content": "好玩吗"},
    {"role": "user", "content": "晚上吃了烩面"},
    {"role": "user", "content": "明天一早就回贵阳"},
]


class HisDayDigestTests(unittest.TestCase):
    def test_writes_his_day_as_event_memory(self):
        import asyncio
        plugin = make_plugin(MESSAGES)
        asyncio.run(plugin._maybe_his_day_digest())
        self.assertEqual(len(plugin.memories), 1)
        row = plugin.memories[0]
        self.assertEqual(row["kind"], "his_day", "必须走事件记忆，才会 7 天降权 14 天删除")
        self.assertEqual(row["tier"], 0)
        self.assertEqual(row["uid"], "u1")
        self.assertIn(TODAY, row["content"])
        self.assertIn("他去了南阳", row["content"])

    def test_guard_prevents_duplicate(self):
        import asyncio
        plugin = make_plugin(MESSAGES)
        plugin.db.kv["his_digest:" + TODAY] = TODAY
        asyncio.run(plugin._maybe_his_day_digest())
        self.assertEqual(plugin.memories, [])

    def test_too_few_messages_does_nothing(self):
        import asyncio
        plugin = make_plugin(MESSAGES[:2])
        asyncio.run(plugin._maybe_his_day_digest())
        self.assertEqual(plugin.memories, [])

    def test_before_schedule_hour_does_nothing(self):
        import asyncio
        plugin = make_plugin(MESSAGES, hour=20)
        asyncio.run(plugin._maybe_his_day_digest())
        self.assertEqual(plugin.memories, [])

    def test_empty_summary_is_not_written(self):
        import asyncio
        plugin = make_plugin(MESSAGES, reply="今天没说什么")
        asyncio.run(plugin._maybe_his_day_digest())
        self.assertEqual(plugin.memories, [])


class PhotoRecordTests(unittest.TestCase):
    def test_photo_memory_is_event(self):
        import asyncio
        plugin = make_plugin()
        scene = {"place": "南阳·恐龙园", "activity": "自己出门逛"}
        asyncio.run(plugin._remember_photo("umo1", "自拍，户外", scene, label="自拍"))
        self.assertEqual(len(plugin.memories), 1)
        row = plugin.memories[0]
        self.assertEqual(row["kind"], "photo_record")
        self.assertEqual(row["tier"], 0)
        self.assertIn("南阳·恐龙园", row["content"])
        self.assertIn("自拍", row["content"])

    def test_photo_memory_without_scene(self):
        import asyncio
        plugin = make_plugin()
        asyncio.run(plugin._remember_photo("umo1", "画了一碗面", None, label="照片"))
        self.assertIn("给他发了一张照片", plugin.memories[0]["content"])


if __name__ == "__main__":
    unittest.main()
