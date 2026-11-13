# -*- coding: utf-8 -*-
"""中央集权：判定只在终端，挂载插件只执行。

这里盯两件事：
1. 群聊放行策略（真 @ 才画）是终端本地判的，不看挂载插件的脸色；
2. 换装指令由终端判、终端说，挂载插件只给造型。
"""

import asyncio
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
from draw_engine import DrawEngine  # noqa: E402


class FakeDB:
    def __init__(self):
        self.kv = {}

    def kv_get(self, key, default=None):
        return self.kv.get(key, default)

    def kv_set(self, key, value):
        self.kv[key] = value

    def get_profile(self, uid):
        return {}

    def messages_by_uid(self, uid, limit=20):
        return []

    def recent_messages(self, umo, limit=8):
        return []


class FakeContext:
    def get_registered_star(self, name):
        return None


class FakePhoto:
    def outfit_today(self):
        return ""


class FakePlugin:
    """画图引擎要的那一小撮插件接口。"""

    def __init__(self, cfg):
        self.config = dict(cfg)
        self.db = FakeDB()
        self.context = FakeContext()
        self.photo = FakePhoto()

    def cfg_bool(self, key, default=False):
        value = self.config.get(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on", "是")

    def cfg_int(self, key, default=0):
        try:
            return int(self.config.get(key, default))
        except Exception:
            return default

    def cfg_float(self, key, default=0.0):
        try:
            return float(self.config.get(key, default))
        except Exception:
            return default

    def cfg_str(self, key, default=""):
        return str(self.config.get(key, default))

    def _canonical_uid(self, event):
        return getattr(event, "uid", "u1")

    def _spawn(self, coro):
        coro.close()
        return None


BASE_CFG = {
    "draw_enable": True,
    "draw_trigger_mode": "both",
    "draw_owner_ids": "u1",
    "draw_cooldown_minutes": 0,
    "draw_max_per_hour": 10,
    "draw_max_per_day": 10,
    "draw_delay_seconds": 0,
    "draw_prompt_max_chars": 80,
}


class At:
    """假 At 组件；_is_at_me 只认类名和 qq。"""

    def __init__(self, qq):
        self.qq = qq


class FakeEvent:
    def __init__(self, text="拍张照", private=True, at=False, self_id="bot1", uid="u1"):
        self.message_str = text
        self.uid = uid
        self.private = private
        self.self_id = self_id
        self.unified_msg_origin = "test:private:u1" if private else "test:group:g1"
        self.message_obj = types.SimpleNamespace(message=[At(self_id if at else "someone")])
        self.stopped = False
        self.sent = []

    def is_private_chat(self):
        return self.private

    def get_self_id(self):
        return self.self_id

    def stop_event(self):
        self.stopped = True


def engine_for(**cfg):
    merged = dict(BASE_CFG)
    merged.update(cfg)
    return DrawEngine(FakePlugin(merged))


class GroupGateTests(unittest.TestCase):
    """群聊只在真 @ 时放行，判定完全在终端本地。"""

    def test_private_chat_always_allowed(self):
        engine = engine_for()
        self.assertTrue(engine.wants_photo(FakeEvent(private=True)))

    def test_group_needs_real_at_by_default(self):
        engine = engine_for()
        self.assertTrue(engine.wants_photo(FakeEvent(private=False, at=True)))
        self.assertFalse(engine.wants_photo(FakeEvent(private=False, at=False)))

    def test_group_mode_off_blocks_even_at(self):
        engine = engine_for(draw_group_mode="off")
        self.assertFalse(engine.wants_photo(FakeEvent(private=False, at=True)))

    def test_group_mode_any_allows_without_at(self):
        engine = engine_for(draw_group_mode="any")
        self.assertTrue(engine.wants_photo(FakeEvent(private=False, at=False)))

    def test_legacy_private_only_key_no_longer_blocks_group_at(self):
        """老键 draw_private_only 不该再把群聊 @ 挡掉（线上行为等价迁移）。"""
        engine = engine_for(draw_private_only=True)
        self.assertTrue(engine.wants_photo(FakeEvent(private=False, at=True)))

    def test_decide_also_uses_the_same_gate(self):
        engine = engine_for()
        self.assertIsNone(engine.decide(FakeEvent(private=False, at=False), "在干嘛呀"))
        plan = engine.decide(FakeEvent(private=False, at=True), "在干嘛呀")
        self.assertIsNotNone(plan)


class FakeImageMount:
    def __init__(self, look="米色针织开衫配浅蓝牛仔裤", explode=False):
        self.look = look
        self.explode = explode
        self.calls = []

    def change_outfit_for(self, reason=""):
        self.calls.append(reason)
        if self.explode:
            raise RuntimeError("挂载炸了")
        return self.look


class SendCtx:
    def __init__(self):
        self.sent = []

    async def send_message(self, umo, chain):
        self.sent.append((umo, chain))


def outfit_plugin(image=None):
    plugin = object.__new__(amo_main.HumanCorePlugin)
    plugin.context = SendCtx()
    plugin._command_prefixes = lambda: []
    plugin._image_plugin = lambda: image
    return plugin


class OutfitDirectiveTests(unittest.TestCase):
    """换装：终端判、终端说，挂载只负责给造型。"""

    def test_command_changes_outfit_and_replies(self):
        image = FakeImageMount()
        plugin = outfit_plugin(image)
        event = FakeEvent(text="换一套衣服")
        handled = asyncio.run(plugin._maybe_change_outfit(event, "换一套衣服"))
        self.assertTrue(handled)
        self.assertEqual(image.calls, ["Amo 换装指令"])
        self.assertEqual(plugin.context.sent[0][1], "换好了：米色针织开衫配浅蓝牛仔裤")
        self.assertTrue(event.stopped)

    def test_chat_mentioning_outfit_is_not_a_command(self):
        plugin = outfit_plugin(FakeImageMount())
        for text in ("我想换一套衣服再出门", "换衣服的话穿哪件", "换好了"):
            self.assertFalse(asyncio.run(plugin._maybe_change_outfit(FakeEvent(text=text), text)))
        self.assertEqual(plugin.context.sent, [])

    def test_wake_prefix_is_stripped(self):
        plugin = outfit_plugin(FakeImageMount())
        plugin._command_prefixes = lambda: ["晓沫"]
        self.assertTrue(asyncio.run(plugin._maybe_change_outfit(FakeEvent(text="晓沫换衣服"), "晓沫换衣服")))

    def test_no_mount_means_no_claim(self):
        """挂载不在时不许假装换好了。"""
        plugin = outfit_plugin(None)
        self.assertFalse(asyncio.run(plugin._maybe_change_outfit(FakeEvent(text="换衣服"), "换衣服")))
        self.assertEqual(plugin.context.sent, [])

    def test_mount_failure_is_not_reported_as_success(self):
        plugin = outfit_plugin(FakeImageMount(explode=True))
        self.assertFalse(asyncio.run(plugin._maybe_change_outfit(FakeEvent(text="换衣服"), "换衣服")))
        self.assertEqual(plugin.context.sent, [])


if __name__ == "__main__":
    unittest.main()
