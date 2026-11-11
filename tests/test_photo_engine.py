# -*- coding: utf-8 -*-
"""照片分享引擎单测（不连真实 AstrBot / 不花钱）。"""

from __future__ import annotations

import asyncio
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import astrbot_stub  # noqa: E402

astrbot_stub.install()

from photo_engine import PhotoEngine  # noqa: E402


class FakeDB:
    def __init__(self):
        self.kv = {}
        self.profiles = [{"uid": "u1", "relation": "相恋", "private_umo": "test:private:u1"}]

    def kv_get(self, key, default=None):
        return self.kv.get(key, default)

    def kv_set(self, key, value):
        self.kv[key] = value

    def proactive_profiles(self, limit=50):
        return list(self.profiles)


class FakeState:
    def __init__(self):
        self.activity = {"activity": "在家休息", "place": "家", "zone": "home", "category": "life"}

    def current_activity(self):
        return dict(self.activity)


class FakeGift:
    def worn_text(self):
        return "米色针织衫"


class FakeOmni:
    def __init__(self, fail=False, selfie_ready=True):
        self.calls = []
        self.fail = fail
        cfg = type("Cfg", (), {"persona_ref_image": "ref.png" if selfie_ready else "", "persona_base_prompt": ""})
        self.plugin_config = cfg()

    async def generate_images_for_plugin(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            return {"success": False, "message": "失败", "images": []}
        return {"success": True, "images": [{"file_path": "C:/tmp/p.png"}]}


class FakeContext:
    def __init__(self, omni=None):
        self.omni = omni
        self.sent = []

    def get_registered_star(self, name):
        if self.omni is None:
            return None

        class Meta:
            star_cls = self.omni

        return Meta()

    async def send_message(self, umo, chain):
        self.sent.append((umo, chain))
        return True


class FakePlugin:
    def __init__(self, cfg=None, omni=None):
        self.config = dict(cfg or {})
        self.db = FakeDB()
        self.state = FakeState()
        self.gift = FakeGift()
        self.context = FakeContext(omni)
        self.admin_uids = set()
        self.plugin_dir = tempfile.mkdtemp(prefix="amo-tpl-")
        self.tasks = []

    def _spawn(self, coro):
        self.tasks.append(coro)
        return coro

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

    def cfg_str(self, key, default=""):
        return str(self.config.get(key, default))

    def _pick_proactive_umo(self, profile):
        return profile.get("private_umo") or "test:private:u1"


BASE = {
    "photo_enable": True,
    # 免打扰时段在测试里关掉：不然别的用例改过全局时区/时钟时，
    # 「现在」可能落进 23:00-07:00，整批照片用例会跟着飘
    "photo_quiet_hours": "",
    "photo_travel_prob": 100,
    "photo_shopping_prob": 0,
    "photo_weekend_prob": 0,
    "photo_daily_prob": 0,
    "photo_outfit_prob": 100,
    "photo_selfie_ratio": 0,
    "photo_daily_cap": 4,
    "photo_delay": 0,
}


def engine_for(cfg=None, omni=None):
    merged = dict(BASE)
    merged.update(cfg or {})
    plugin = FakePlugin(merged, omni if omni is not None else FakeOmni())
    return PhotoEngine(plugin), plugin


def run_tick(engine, plugin):
    asyncio.run(engine.tick())
    while plugin.tasks:
        asyncio.run(plugin.tasks.pop(0))


class PhotoTests(unittest.TestCase):
    def setUp(self):
        self._random = random.random
        random.random = lambda: 0.0  # 必中

    def tearDown(self):
        random.random = self._random

    def test_travel_sends_scene(self):
        engine, plugin = engine_for()
        plugin.state.activity = {"activity": "逛景区", "place": "西湖", "zone": "scenic", "category": "travel"}
        run_tick(engine, plugin)
        self.assertEqual(len(plugin.context.sent), 1)
        self.assertEqual(plugin.context.sent[0][0], "test:private:u1")
        self.assertEqual(len(plugin.context.omni.calls), 1)
        self.assertNotIn("mode", plugin.context.omni.calls[0])

    def test_prob_zero_does_not_send(self):
        engine, plugin = engine_for({"photo_travel_prob": 0})
        plugin.state.activity = {"activity": "逛景区", "place": "西湖", "zone": "scenic", "category": "travel"}
        run_tick(engine, plugin)
        self.assertEqual(plugin.context.sent, [])

    def test_outfit_is_always_selfie(self):
        engine, plugin = engine_for({"photo_selfie_ratio": 0})
        engine._now_parts = lambda: (0, 8 * 60)  # 周一 08:00
        plugin.state.activity = {"activity": "出门上班", "place": "小区门口", "zone": "road", "category": "commute"}
        engine._last_check = 0
        run_tick(engine, plugin)
        self.assertEqual(len(plugin.context.sent), 1)
        self.assertEqual(plugin.context.omni.calls[0].get("mode"), "selfie")

    def test_daily_cap_blocks(self):
        engine, plugin = engine_for()
        plugin.state.activity = {"activity": "逛景区", "place": "西湖", "zone": "scenic", "category": "travel"}
        key = engine._count_key(__import__("photo_engine").today_str())
        plugin.db.kv[key] = 4
        run_tick(engine, plugin)
        self.assertEqual(plugin.context.sent, [])

    def test_roll_once_per_day(self):
        engine, plugin = engine_for()
        plugin.state.activity = {"activity": "逛景区", "place": "西湖", "zone": "scenic", "category": "travel"}
        run_tick(engine, plugin)
        engine._last_check = 0
        run_tick(engine, plugin)
        self.assertEqual(len(plugin.context.sent), 1)

    def test_owner_ids_mismatch_sends_nothing(self):
        engine, plugin = engine_for({"photo_owner_ids": "999"})
        plugin.state.activity = {"activity": "逛景区", "place": "西湖", "zone": "scenic", "category": "travel"}
        run_tick(engine, plugin)
        self.assertEqual(plugin.context.sent, [])

    def test_clean_place_sanitizes(self):
        self.assertEqual(PhotoEngine._clean_place("他桌面上"), "家里")
        self.assertEqual(PhotoEngine._clean_place("西湖"), "西湖")

    def test_smart_prompt_recognizes_photo_request(self):
        engine, _ = engine_for()
        engine._recent_place = lambda: "公园"
        text = engine.smart_prompt("拍照给我看看")
        self.assertIn("公园", text)
        self.assertIn("自拍", text)
        self.assertIn(engine.outfit_today(), text)

    def test_smart_prompt_keeps_explicit_scene(self):
        engine, _ = engine_for()
        text = engine.smart_prompt("在公园和狗狗玩拍照")
        self.assertEqual(text, "在公园和狗狗玩拍照")

    def test_generate_prompt_includes_today_outfit(self):
        engine, _ = engine_for()
        captured = {}

        async def fake_custom(prompt, refs=None):
            captured["prompt"] = prompt
            return None

        engine.generate_custom = fake_custom
        asyncio.run(engine.generate_prompt("在公园和狗狗玩"))
        self.assertIn("穿着", captured["prompt"])
        self.assertIn(engine.outfit_today(), captured["prompt"])

    def test_generate_prompt_keeps_user_outfit(self):
        engine, _ = engine_for()
        captured = {}

        async def fake_custom(prompt, refs=None):
            captured["prompt"] = prompt
            return None

        engine.generate_custom = fake_custom
        asyncio.run(engine.generate_prompt("穿着红色连衣裙在公园"))
        self.assertNotIn(engine.outfit_today(), captured["prompt"])

    def test_template_map_recovers_by_filename(self):
        engine, _ = engine_for()
        root = engine.template_dir()
        for view in ("front", "side", "full"):
            with open(os.path.join(root, "amo_persona_%s.png" % view), "wb") as handle:
                handle.write(b"x")
        mapped = engine._template_map()
        self.assertEqual(set(mapped), {"front", "side", "full"})

    def test_adopt_local_template(self):
        engine, _ = engine_for()
        source = os.path.join(engine.template_dir(), "source.png")
        with open(source, "wb") as handle:
            handle.write(b"\x89PNG\r\n\x1a\n")
        message = asyncio.run(engine.adopt_persona(source, "side"))
        self.assertTrue(message.startswith("✅"))
        self.assertIn("side", engine._template_map())
        self.assertTrue(os.path.exists(engine._template_map()["side"]))

    def test_template_dir_defaults_inside_plugin(self):
        engine, _ = engine_for()
        info = engine.template_info()
        self.assertTrue(info["root"].replace("\\", "/").endswith("/templates"))
        self.assertTrue(info["inside_plugin"])

    def test_outfit_today_is_stable(self):
        engine, _ = engine_for()
        first = engine.outfit_today()
        second = engine.outfit_today()
        self.assertEqual(first, second)
        self.assertTrue(first)

    def test_outfit_persists_across_engine_instances(self):
        engine, plugin = engine_for()
        first = engine.outfit_today()
        second_engine = PhotoEngine(plugin)
        self.assertEqual(second_engine.outfit_today(), first)

    def test_selfie_prompt_uses_today_outfit(self):
        engine, plugin = engine_for()
        plugin.state.activity = {"activity": "在咖啡馆坐坐", "place": "咖啡馆", "zone": "mall", "category": "life"}
        outfit = engine.outfit_today()
        prompt = engine._selfie_prompt_for("daily", "", plugin.state.activity)
        self.assertIn(outfit, prompt)
        self.assertIn("咖啡馆", prompt)

    def test_status_text(self):
        engine, _ = engine_for()
        text = engine.status_text()
        self.assertIn("照片", text)
        self.assertIn("旅游", text)

    def test_busy_blocks_second_tick(self):
        engine, plugin = engine_for()
        plugin.state.activity = {"activity": "逛景区", "place": "西湖", "zone": "scenic", "category": "travel"}
        engine._busy = True
        run_tick(engine, plugin)
        self.assertEqual(plugin.tasks, [])

    def test_missing_omni_no_crash(self):
        engine, plugin = engine_for()
        plugin.context.omni = None
        plugin.state.activity = {"activity": "逛景区", "place": "西湖", "zone": "scenic", "category": "travel"}
        run_tick(engine, plugin)
        self.assertEqual(plugin.context.sent, [])

    def test_share_now_disabled(self):
        engine, plugin = engine_for({"photo_enable": False})
        msg = asyncio.run(engine.share_now("daily"))
        self.assertIn("没开", msg)

    def test_selfie_failure_falls_back_to_scene(self):
        omni = FakeOmni(fail=True)
        engine, plugin = engine_for({"photo_selfie_ratio": 100}, omni)
        plugin.state.activity = {"activity": "逛景区", "place": "西湖", "zone": "scenic", "category": "travel"}
        run_tick(engine, plugin)
        self.assertGreaterEqual(len(omni.calls), 1)
        self.assertEqual(plugin.context.sent, [])

    def test_selfie_ready_accepts_new_omni_personas(self):
        """新版万象画卷把形象放在 plugin_config.personas 里，不能判成「没有」。"""

        class Profile:
            ref_images = ["templates/amo_persona_front.png"]
            persona_base_prompt = ""

        class NewOmni(FakeOmni):
            def __init__(self):
                super().__init__()
                self.plugin_config = type("Cfg", (), {
                    "persona_ref_image": "",
                    "persona_base_prompt": "",
                    "personas": [Profile()],
                    "persona_config": "",
                })()

        engine, _ = engine_for()
        self.assertTrue(engine._selfie_ready(NewOmni()))

    def test_selfie_ready_accepts_persona_config_json(self):
        import json as _json

        class JsonOmni(FakeOmni):
            def __init__(self):
                super().__init__()
                self.plugin_config = type("Cfg", (), {
                    "persona_ref_image": "",
                    "persona_base_prompt": "",
                    "personas": [],
                    "persona_config": _json.dumps({
                        "active_persona_id": "amo",
                        "profiles": [{"id": "amo", "persona_base_prompt": "同一个女孩"}],
                    }),
                })()

        engine, _ = engine_for()
        self.assertTrue(engine._selfie_ready(JsonOmni()))

    def test_selfie_ready_falls_back_to_own_templates(self):
        engine, plugin = engine_for()
        tpl = os.path.join(plugin.plugin_dir, "templates")
        os.makedirs(tpl, exist_ok=True)
        open(os.path.join(tpl, "amo_persona_front.png"), "wb").write(b"x")

        class BareOmni(FakeOmni):
            def __init__(self):
                super().__init__()
                self.plugin_config = type("Cfg", (), {
                    "persona_ref_image": "", "persona_base_prompt": "",
                    "personas": [], "persona_config": "",
                })()

        self.assertTrue(engine._selfie_ready(BareOmni()))

    def test_selfie_ready_false_when_nothing_configured(self):
        class BareOmni(FakeOmni):
            def __init__(self):
                super().__init__()
                self.plugin_config = type("Cfg", (), {
                    "persona_ref_image": "", "persona_base_prompt": "",
                    "personas": [], "persona_config": "",
                })()

        engine, _ = engine_for()
        self.assertFalse(engine._selfie_ready(BareOmni()))


if __name__ == "__main__":
    unittest.main()
