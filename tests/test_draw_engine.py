# -*- coding: utf-8 -*-
"""画图引擎单测（不连真实 AstrBot / 不花钱）。"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import astrbot_stub  # noqa: E402

astrbot_stub.install()

from draw_engine import (  # noqa: E402
    DEFAULT_EXPLICIT_KEYWORDS,
    DrawEngine,
    clean_explicit_prompt,
    clean_topic_prompt,
)


class FakeDB:
    def __init__(self):
        self.profiles = {}
        self.messages = {}
        self.by_uid = {}
        self.kv = {}

    def kv_get(self, key, default=None):
        return self.kv.get(key, default)

    def kv_set(self, key, value):
        self.kv[key] = value

    def messages_by_uid(self, uid, limit=20):
        return self.by_uid.get(str(uid), [])[-max(1, int(limit)):]

    def get_profile(self, uid):
        return self.profiles.get(str(uid), {})

    def recent_messages(self, umo, limit=8):
        return self.messages.get(str(umo), [])[-max(1, int(limit)):]


class FakeContext:
    def __init__(self, omni=None):
        self.omni = omni

    def get_registered_star(self, name):
        if self.omni is None:
            return None

        class Meta:
            star_cls = self.omni

        return Meta()


class FakeOmni:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def generate_images_for_plugin(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            return {"success": False, "message": "没配节点", "images": []}
        return {"success": True, "images": [{"file_path": "C:/tmp/x.png", "image_url": "C:/tmp/x.png",
                                             "url": "https://example.com/x.png"}]}


class FakeState:
    def __init__(self, place="公园", activity="散步"):
        self.place = place
        self.activity = activity

    def current_activity(self):
        return {"place": self.place, "activity": self.activity, "zone": "scenic"}


class FakePhoto:
    def outfit_today(self):
        return "米色针织衫配牛仔裤"


class FakePlugin:
    def __init__(self, cfg=None, omni=None):
        self.config = dict(cfg or {})
        self.db = FakeDB()
        self.context = FakeContext(omni)
        self.photo = FakePhoto()
        self.admin_uids = set()
        self.tasks = []
        self.image_prompts = []
        self.image_fail = False

    async def _image_bytes(self, prompt, umo="", uid="", selfie=None):
        """生图插件替身：终端只拿字节，出图/额度都在插件那边。"""
        self.image_prompts.append(prompt)
        self.image_selfie = selfie
        if self.image_fail:
            return None
        return b"\x89PNG"

    def _image_plugin(self):
        return self

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
        return event.uid

    def _is_admin(self, event):
        return bool(getattr(event, "admin", False))

    def _spawn(self, coro):
        self.tasks.append(coro)
        return coro


class FakeEvent:
    def __init__(self, text, uid="u1", private=True, umo="test:private:u1"):
        self.message_str = text
        self.uid = uid
        self.private = private
        self.unified_msg_origin = umo
        self.sent = []

    def is_private_chat(self):
        return self.private

    async def send(self, chain):
        self.sent.append(chain)


BASE_CFG = {
    "draw_enable": True,
    "draw_trigger_mode": "both",
    "draw_owner_ids": "u1",
    "draw_cooldown_minutes": 0,
    "draw_max_per_hour": 10,
    "draw_max_per_day": 10,
    "draw_delay_seconds": 0,
    "draw_prompt_max_chars": 80,
    "photo_prompt_prefix": "二次元插画，动漫风格，生活感，",
}


def engine_for(cfg=None, omni=None):
    merged = dict(BASE_CFG)
    merged.update(cfg or {})
    plugin = FakePlugin(merged, omni if omni is not None else FakeOmni())
    return DrawEngine(plugin), plugin


class CleanTests(unittest.TestCase):
    def test_explicit_prompt_strips_request_words(self):
        self.assertEqual(clean_explicit_prompt("给我画一碗牛肉面"), "一碗牛肉面")
        self.assertEqual(clean_explicit_prompt("拍张照片"), "照片")

    def test_topic_prompt_strips_tail(self):
        self.assertEqual(clean_topic_prompt("面条吧", 80), "面条")
        self.assertEqual(clean_topic_prompt("今天中午吃了牛肉面，好吃！", 80), "今天中午吃了牛肉面，好吃")


class DecideTests(unittest.TestCase):
    def test_explicit_hit(self):
        engine, _ = engine_for()
        plan = engine.decide(FakeEvent("给我画一碗牛肉面"), "好呀")
        self.assertIsNotNone(plan)
        self.assertIn("一碗牛肉面", plan["prompt"])
        self.assertFalse(plan.get("selfie"))

    def test_explicit_without_subject_uses_previous_bot_line(self):
        engine, plugin = engine_for()
        event = FakeEvent("拍照给我看看")
        plugin.db.messages[event.unified_msg_origin] = [
            {"role": "user", "content": "今天中午吃了啥呀"},
            {"role": "bot", "content": "今天中午吃了牛肉面"},
        ]
        plan = engine.decide(event, "好呀")
        self.assertIsNotNone(plan)
        self.assertIn("牛肉面", plan["prompt"])

    def test_topic_hit_uses_reply(self):
        engine, _ = engine_for()
        plan = engine.decide(FakeEvent("晚上吃啥"), "面条吧")
        self.assertIsNotNone(plan)
        self.assertIn("面条", plan["prompt"])

    def test_no_hit(self):
        engine, _ = engine_for()
        self.assertIsNone(engine.decide(FakeEvent("今天上班好累"), "抱抱"))

    def test_group_skipped(self):
        engine, _ = engine_for()
        self.assertIsNone(engine.decide(FakeEvent("给我画一碗面", private=False), "好"))

    def test_non_owner_skipped(self):
        engine, _ = engine_for()
        event = FakeEvent("给我画一碗面", uid="other")
        self.assertIsNone(engine.decide(event, "好"))

    def test_selfie_request_uses_selfie_prompt(self):
        engine, _ = engine_for()
        plan = engine.decide(FakeEvent("发张自拍"), "好呀")
        self.assertIsNotNone(plan)
        self.assertTrue(plan["prompt"].startswith("自拍"))
        self.assertIn("前置", plan["prompt"])
        self.assertIn("穿着", plan["prompt"])
        self.assertIn("米色针织衫", plan["prompt"])

    def test_selfie_uses_previous_line_as_subject(self):
        engine, plugin = engine_for()
        event = FakeEvent("发张自拍")
        plugin.db.messages[event.unified_msg_origin] = [
            {"role": "bot", "content": "今天穿了新裙子"},
        ]
        plan = engine.decide(event, "好呀")
        self.assertIsNotNone(plan)
        self.assertIn("新裙子", plan["prompt"])
        self.assertTrue(plan["prompt"].startswith("自拍"))

    def test_same_question_cross_platform_uses_shared_last_line(self):
        engine, plugin = engine_for()
        plugin.db.by_uid["u1"] = [{"role": "bot", "content": "今天中午吃了牛肉面"}]
        qq = FakeEvent("拍照给我看看", umo="aiocqhttp:private:u1")
        lark = FakeEvent("拍照给我看看", umo="lark:private:u1")
        first = engine.decide(qq, "好呀")
        second = engine.decide(lark, "好呀")
        self.assertIsNotNone(first)
        self.assertIn("牛肉面", first["prompt"])
        self.assertEqual(first["prompt"], second["prompt"])

    def test_explicit_skipped_when_reply_already_drawing(self):
        engine, _ = engine_for()
        self.assertIsNone(engine.decide(FakeEvent("拍照给我看看"), "稍等，这就给你画"))

    def test_cooldown_skips_second(self):
        engine, _ = engine_for({"draw_cooldown_minutes": 30})
        event = FakeEvent("给我画一碗面")
        self.assertIsNotNone(engine.decide(event, "好"))
        engine._last_draw[event.uid] = __import__("time").monotonic()
        self.assertIsNone(engine.decide(event, "好"))


class RunTests(unittest.TestCase):
    def test_dry_run_does_not_call_model(self):
        omni = FakeOmni()
        engine, plugin = engine_for({"draw_dry_run": True}, omni)
        event = FakeEvent("给我画一碗面")
        engine.maybe_after_reply(event, "好呀")
        self.assertEqual(len(plugin.tasks), 1)
        asyncio.run(plugin.tasks[0])
        self.assertEqual(plugin.image_prompts, [])
        self.assertEqual(event.sent, [])

    def test_success_sends_image(self):
        omni = FakeOmni()
        engine, plugin = engine_for({}, omni)
        event = FakeEvent("给我画一碗面")
        engine.maybe_after_reply(event, "好呀")
        asyncio.run(plugin.tasks[0])
        self.assertEqual(len(plugin.image_prompts), 1)
        self.assertIn("一碗面", plugin.image_prompts[0])
        self.assertEqual(len(event.sent), 1)
        self.assertEqual(len(event.sent[0].chain), 1)

    def test_failure_does_not_raise(self):
        engine, plugin = engine_for({})
        plugin.image_fail = True
        event = FakeEvent("给我画一碗面")
        engine.maybe_after_reply(event, "好呀")
        asyncio.run(plugin.tasks[0])
        self.assertEqual(event.sent, [])

    def test_missing_image_plugin_does_not_raise(self):
        engine, plugin = engine_for({}, None)
        plugin._image_bytes = None
        event = FakeEvent("给我画一碗面")
        engine.maybe_after_reply(event, "好呀")
        asyncio.run(plugin.tasks[0])
        self.assertEqual(event.sent, [])

    def test_wants_photo_for_explicit_request(self):
        engine, _ = engine_for()
        self.assertTrue(engine.wants_photo(FakeEvent("拍照给我看看")))

    def test_wants_photo_false_for_topic_mode(self):
        engine, _ = engine_for({"draw_trigger_mode": "topic"})
        self.assertFalse(engine.wants_photo(FakeEvent("拍照给我看看")))

    def test_location_question_uses_current_schedule_place(self):
        engine, plugin = engine_for()
        plugin.state = FakeState(place="公司", activity="加班")
        plan = engine.decide(FakeEvent("你在公园吗？拍照给我看看"), "不在呀，我在公司加班呢")
        self.assertIsNotNone(plan)
        self.assertIn("公司", plan["prompt"])
        self.assertNotIn("公园", plan["prompt"])

    def test_location_question_at_park_uses_park_scene(self):
        engine, plugin = engine_for()
        plugin.state = FakeState(place="公园", activity="散步")
        plan = engine.decide(FakeEvent("你在公园吗？拍照给我看看"), "在呀")
        self.assertIsNotNone(plan)
        self.assertIn("公园", plan["prompt"])
        self.assertIn("散步", plan["prompt"])
        self.assertTrue(plan.get("selfie"))

    def test_extra_scene_keywords_from_config(self):
        engine, _ = engine_for({"draw_scene_keywords": "鸽子,风筝"})
        keywords = engine._scene_keywords("在公园喂鸽子")
        self.assertIn("鸽子", keywords)
        self.assertIn("公园", keywords)

    def test_residual_detail_changes_cache_key(self):
        engine, _ = engine_for()
        kws1 = engine._scene_keywords("在公园喂鸽子")
        kws2 = engine._scene_keywords("在公园喂鸭子")
        self.assertEqual(kws1, kws2)
        r1 = engine._scene_residual("在公园喂鸽子", kws1)
        r2 = engine._scene_residual("在公园喂鸭子", kws2)
        self.assertTrue(r1 and r2)
        self.assertNotEqual(
            engine._cache_key("p1", kws1, False, r1),
            engine._cache_key("p2", kws2, False, r2),
        )

    def test_residual_empty_for_plain_scene(self):
        engine, _ = engine_for()
        keywords = engine._scene_keywords("在公园散步")
        self.assertEqual(engine._scene_residual("在公园散步", keywords), "")

    def test_vague_questions_share_scene_cache(self):
        omni = FakeOmni()
        engine, plugin = engine_for({"draw_cooldown_minutes": 30}, omni)
        plugin.db.by_uid["u1"] = [{"role": "bot", "content": "在公园散步呢"}]
        qq = FakeEvent("你在公园吗？拍照给我看看", umo="aiocqhttp:private:u1")
        engine.maybe_after_reply(qq, "在呀")
        asyncio.run(plugin.tasks.pop(0))
        lark = FakeEvent("公园玩的开心吗？拍给我看看", umo="lark:private:u1")
        plan = engine.decide(lark, "开心呀")
        self.assertIsNotNone(plan)
        self.assertEqual(plan["reason"], "cache")

    def test_new_detail_in_same_scene_regenerates(self):
        omni = FakeOmni()
        engine, plugin = engine_for({"draw_cooldown_minutes": 0}, omni)
        plugin.db.by_uid["u1"] = [{"role": "bot", "content": "在公园散步呢"}]
        engine.maybe_after_reply(FakeEvent("你在公园吗？拍照给我看看"), "在呀")
        asyncio.run(plugin.tasks.pop(0))
        plugin.db.by_uid["u1"] = [{"role": "bot", "content": "在公园看到狗狗，跟狗狗玩"}]
        engine._last_prompt.clear()
        engine.maybe_after_reply(FakeEvent("公园在干吗？拍给我看看"), "在跟狗狗玩呢")
        asyncio.run(plugin.tasks.pop(0))
        self.assertEqual(len(plugin.image_prompts), 2)

    def test_same_prompt_reuses_image_across_platforms(self):
        omni = FakeOmni()
        engine, plugin = engine_for({"draw_cooldown_minutes": 30}, omni)
        qq = FakeEvent("给我画一碗面", umo="aiocqhttp:private:u1")
        engine.maybe_after_reply(qq, "好呀")
        asyncio.run(plugin.tasks.pop(0))
        self.assertEqual(len(plugin.image_prompts), 1)

        lark = FakeEvent("给我画一碗面", umo="lark:private:u1")
        plan = engine.decide(lark, "好呀")
        self.assertIsNotNone(plan)
        self.assertEqual(plan["reason"], "cache")
        engine.maybe_after_reply(lark, "好呀")
        asyncio.run(plugin.tasks.pop(0))
        self.assertEqual(len(plugin.image_prompts), 1)      # 没重新生成
        self.assertEqual(len(lark.sent), 1)       # 但在飞书那边发了同一张
        self.assertEqual(len(qq.sent), 1)

    def test_different_prompt_regenerates(self):
        omni = FakeOmni()
        engine, plugin = engine_for({"draw_cooldown_minutes": 0}, omni)
        engine.maybe_after_reply(FakeEvent("给我画一碗面"), "好呀")
        asyncio.run(plugin.tasks.pop(0))
        engine.maybe_after_reply(FakeEvent("给我画一只猫"), "好呀")
        asyncio.run(plugin.tasks.pop(0))
        self.assertEqual(len(plugin.image_prompts), 2)

    def test_cache_can_be_disabled(self):
        omni = FakeOmni()
        engine, plugin = engine_for({"draw_cooldown_minutes": 0, "draw_cache_minutes": 0}, omni)
        engine.maybe_after_reply(FakeEvent("给我画一碗面"), "好呀")
        asyncio.run(plugin.tasks.pop(0))
        engine._last_prompt.clear()  # 绕过 120 秒同句去重，专门验证缓存开关
        engine.maybe_after_reply(FakeEvent("给我画一碗面"), "好呀")
        asyncio.run(plugin.tasks.pop(0))
        self.assertEqual(len(plugin.image_prompts), 2)

    def test_status_text(self):
        engine, _ = engine_for()
        text = engine.status_text()
        self.assertIn("画图", text)

    def test_manual_without_text_returns_diagnostics(self):
        engine, _ = engine_for()
        text = engine.manual(FakeEvent(""), "")
        self.assertIn("画图", text)
        self.assertIn("上次错误", text)

    def test_diagnostics_reports_last_error(self):
        engine, _ = engine_for()
        engine._last_error = "节点 401"
        self.assertIn("节点 401", engine.diagnostics())

    def test_manual_disabled(self):
        engine, _ = engine_for({"draw_enable": False})
        self.assertIn("没开", engine.manual(FakeEvent("一碗面"), "一碗面"))


class PhotoAskTests(unittest.TestCase):
    """明着要照片：要认得出来，而且不吃普通冷却。"""

    def test_photo_ask_words(self):
        engine, _ = engine_for()
        self.assertTrue(engine._is_photo_ask("老婆吃的啥，能不能拍给我看看"))
        self.assertTrue(engine._is_photo_ask("拍照给我"))
        self.assertFalse(engine._is_photo_ask("给我画一碗牛肉面"))

    def test_photo_ask_ignores_cooldown(self):
        engine, _ = engine_for({"draw_cooldown_minutes": 30})
        event = FakeEvent("能不能拍给我看看")
        self.assertIsNotNone(engine.decide(event, "好呀"))
        engine._last_draw[event.uid] = __import__("time").monotonic()
        self.assertIsNotNone(engine.decide(event, "好呀"))

    def test_topic_draw_still_respects_cooldown(self):
        engine, _ = engine_for({"draw_cooldown_minutes": 30})
        event = FakeEvent("晚上吃啥")
        self.assertIsNotNone(engine.decide(event, "面条吧"))
        engine._last_draw[event.uid] = __import__("time").monotonic()
        self.assertIsNone(engine.decide(event, "面条吧"))

    def test_vague_photo_ask_falls_back_to_previous_line(self):
        engine, plugin = engine_for()
        event = FakeEvent("老婆吃的啥，能不能拍给我看看")
        plugin.db.by_uid["u1"] = [{"role": "bot", "content": "今天中午吃了牛肉面"}]
        plan = engine.decide(event, "好呀")
        self.assertIsNotNone(plan)
        self.assertTrue(plan["prompt"].startswith("自拍"))
        self.assertIn("牛肉面", plan["prompt"])


class FallbackTests(unittest.TestCase):
    """没装万象画卷时改走生图插件，别一张都出不来。"""

    def test_missing_omni_falls_back_to_image_plugin(self):
        engine, plugin = engine_for({}, None)
        plugin.context.omni = None
        prompts = []

        async def fake_bytes(prompt, umo="", uid="", selfie=None):
            prompts.append(prompt)
            return b"\x89PNG"

        plugin._image_bytes = fake_bytes
        event = FakeEvent("给我画一碗面")
        engine.maybe_after_reply(event, "好呀")
        asyncio.run(plugin.tasks[0])
        self.assertEqual(len(prompts), 1)
        self.assertIn("一碗面", prompts[0])
        self.assertEqual(len(event.sent), 1)


if __name__ == "__main__":
    unittest.main()
