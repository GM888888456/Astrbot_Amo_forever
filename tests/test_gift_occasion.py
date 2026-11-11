# -*- coding: utf-8 -*-
"""礼物：节日/生日/旅游索要小礼物 + 提及礼物时检索来历。"""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import astrbot_stub  # noqa: E402

astrbot_stub.install()

import gift_engine  # noqa: E402


class FakeDB:
    def __init__(self, path):
        self.path = path
        self.kv = {}

    def list_profiles(self, limit=20):
        return self.profiles

    profiles = []


class FakeState:
    def __init__(self, activity):
        self.activity = activity
        self.weather = {}

    def current_activity(self):
        return dict(self.activity)


class FakePlugin:
    def __init__(self, tmp, activity=None, birthday=""):
        self.db = FakeDB(os.path.join(tmp, "amo.db"))
        self.state = FakeState(activity or {"activity": "在家", "place": "家"})
        self.plugin_dir = tmp
        self.conf = {"gift_enable": True, "gift_birthday": birthday}

    def cfg_bool(self, name, default=False):
        return bool(self.conf.get(name, default))

    def cfg_int(self, name, default=0):
        return int(self.conf.get(name, default))

    def cfg_float(self, name, default=0.0):
        return float(self.conf.get(name, default))

    def cfg_str(self, name, default=""):
        return str(self.conf.get(name, default))


def make(activity=None, birthday=""):
    tmp = tempfile.mkdtemp()
    plugin = FakePlugin(tmp, activity=activity, birthday=birthday)
    engine = gift_engine.GiftEngine(plugin)
    return engine


class OccasionTests(unittest.TestCase):
    def test_birthday_from_config(self):
        engine = make(birthday="11-11")
        occasion = engine.occasion_now()
        if occasion:
            self.assertEqual(occasion["kind"], "birthday")

    def test_travel_detected(self):
        engine = make(activity={"activity": "在古镇逛", "place": "古镇", "zone": "scenic"})
        self.assertEqual(engine.occasion_now().get("kind"), "travel")

    def test_plain_day_has_no_occasion(self):
        engine = make(activity={"activity": "上班", "place": "公司", "zone": "office"})
        self.assertEqual(engine.occasion_now(), {})

    def test_no_occasion_means_no_hint(self):
        engine = make(activity={"activity": "上班", "place": "公司", "zone": "office"})
        parts = []
        engine._maybe_occasion_hint("umo", parts)
        self.assertEqual(parts, [])

    def test_occasion_hint_once_per_day(self):
        engine = make(activity={"activity": "在古镇逛", "place": "古镇", "zone": "scenic"})
        first = []
        engine._maybe_occasion_hint("umo", first)
        second = []
        engine._maybe_occasion_hint("umo", second)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])


class ProvenanceTests(unittest.TestCase):
    def test_recall_gift_when_mentioned(self):
        engine = make()
        engine.add_gift("米色围巾", raw="天冷了给你买了条围巾", place="商场")
        text = engine.gift_provenance("你那条米色围巾呢")
        self.assertIn("米色围巾", text)
        self.assertIn("商场", text)

    def test_no_gift_no_text(self):
        engine = make()
        self.assertEqual(engine.gift_provenance("今天天气不错"), "")


if __name__ == "__main__":
    unittest.main()
