# -*- coding: utf-8 -*-
"""服装库：他添的衣服、日程从库里挑、说话换装。"""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import astrbot_stub  # noqa: E402

astrbot_stub.install()

import main as amo_main  # noqa: E402
import outfit_engine  # noqa: E402
import wardrobe as wardrobe_mod  # noqa: E402

DAY = "2026-11-11"


class FakeKV:
    def __init__(self):
        self.data = {}

    def kv_get(self, key, default=None):
        return self.data.get(key, default)

    def kv_set(self, key, value):
        self.data[key] = value

    def get_schedule(self, day):
        return []

    def save_schedule(self, day, items):
        pass


class FakePlugin:
    def __init__(self, tmp, gender="自动"):
        self.conf = {"outfit_gender": gender, "outfit_enable": True}
        self.logger = type("L", (), {"debug": staticmethod(lambda *a, **k: None)})()
        self.plugin_dir = tmp
        self.db = FakeKV()
        self.db.path = os.path.join(tmp, "amo.db")
        self.wardrobe = wardrobe_mod.Wardrobe(self)

    def cfg_bool(self, name, default=False):
        return bool(self.conf.get(name, default))

    def cfg_str(self, name, default=""):
        return str(self.conf.get(name, default))

    def cfg_int(self, name, default=0):
        return int(self.conf.get(name, default))


class WardrobeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.plugin = FakePlugin(self.tmp)
        self.store = self.plugin.wardrobe

    def test_add_and_list(self):
        item = self.store.add("米色针织开衫", scenes=["work", "out"])
        self.assertTrue(item.get("id"))
        self.assertEqual(len(self.store.items()), 1)

    def test_duplicate_merges(self):
        self.store.add("米色针织开衫")
        self.store.add("米色针织开衫", scenes=["home"])
        self.assertEqual(len(self.store.items()), 1)

    def test_scene_guess(self):
        self.assertIn("sleep", wardrobe_mod.guess_scenes("粉色睡裙"))
        self.assertIn("beach", wardrobe_mod.guess_scenes("黑色比基尼"))
        self.assertIn("work", wardrobe_mod.guess_scenes("西装套装"))

    def test_pool_filters_gender_and_scene(self):
        self.store.add("男款夹克", scenes=["out"], gender="男")
        self.store.add("女款外套", scenes=["out"], gender="女")
        self.assertEqual(self.store.pool("女", "out"), ["女款外套"])
        self.assertEqual(self.store.pool("男", "out"), ["男款夹克"])

    def test_match_text(self):
        self.store.add("米色针织开衫", scenes=["out"])
        hit = self.store.match_text("今天换上米色针织开衫吧")
        self.assertEqual(hit.get("name"), "米色针织开衫")

    def test_persist_to_disk(self):
        self.store.add("白色衬衫", scenes=["work"])
        again = wardrobe_mod.Wardrobe(self.plugin)
        self.assertEqual(len(again.items()), 1)


class OutfitFromWardrobeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.plugin = FakePlugin(self.tmp)
        self.engine = outfit_engine.OutfitEngine(self.plugin)

    def test_schedule_uses_wardrobe(self):
        self.plugin.wardrobe.add("藏青色西装套装", scenes=["work", "formal"])
        items = [{"start": "09:00", "end": "18:00", "activity": "上班",
                  "place": "公司", "category": "work"}]
        self.engine.assign(items, DAY)
        self.assertEqual(items[0]["outfit"], "藏青色西装套装")

    def test_empty_wardrobe_falls_back(self):
        items = [{"start": "09:00", "end": "18:00", "activity": "上班",
                  "place": "公司", "category": "work"}]
        self.engine.assign(items, DAY)
        self.assertTrue(items[0].get("outfit"))

    def test_override_from_hour(self):
        self.plugin.wardrobe.add("红色连衣裙", scenes=["casual", "out"])
        items = [
            {"start": "09:00", "end": "18:00", "activity": "上班",
             "place": "公司", "category": "work"},
            {"start": "19:00", "end": "21:00", "activity": "逛街",
             "place": "商场", "category": "play"},
        ]
        self.engine.assign(items, DAY)
        before = items[0]["outfit"]
        self.engine.change_outfit(DAY, "红色连衣裙", from_hour="19:00")
        self.engine.assign(items, DAY)
        self.assertEqual(items[0]["outfit"], before)      # 之前的时段不变
        self.assertEqual(items[1]["outfit"], "红色连衣裙")

    def test_override_survives_reassign(self):
        self.plugin.wardrobe.add("红色连衣裙", scenes=["out"])
        self.engine.change_outfit(DAY, "红色连衣裙", from_hour="00:00")
        items = [{"start": "19:00", "end": "21:00", "activity": "逛街",
                  "place": "商场", "category": "play"}]
        self.engine.assign(items, DAY)
        self.assertEqual(items[0]["outfit"], "红色连衣裙")


class OutfitCommandTests(unittest.TestCase):
    def test_detect_change_request(self):
        plugin = object.__new__(amo_main.HumanCorePlugin)
        self.assertEqual(plugin._outfit_change_request("换上那条红裙子吧"), "红裙子")
        self.assertEqual(plugin._outfit_change_request("今天穿白衬衫"), "白衬衫")
        self.assertEqual(plugin._outfit_change_request("今天吃什么"), "")

    def test_prefers_wardrobe_name(self):
        tmp = tempfile.mkdtemp()
        fake = FakePlugin(tmp)
        fake.wardrobe.add("米色针织开衫", scenes=["out"])
        plugin = object.__new__(amo_main.HumanCorePlugin)
        plugin.wardrobe = fake.wardrobe
        self.assertEqual(
            plugin._outfit_change_request("换上米色针织开衫好不好"), "米色针织开衫")


if __name__ == "__main__":
    unittest.main()
