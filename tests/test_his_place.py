# -*- coding: utf-8 -*-
"""记住他人在哪：说城市记城市，只说「在外地」也记，回来就清掉。

用户的抱怨：他说在外地，她总说「你在家」或者「你慢点开」。
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


class FakeDB:
    def __init__(self):
        self.kv = {}

    def kv_get(self, key, default=None):
        return self.kv.get(key, default)

    def kv_set(self, key, value):
        self.kv[key] = value


def make_plugin():
    plugin = object.__new__(amo_main.HumanCorePlugin)
    plugin.db = FakeDB()
    return plugin


class HisPlaceTests(unittest.TestCase):
    def test_city_is_remembered(self):
        plugin = make_plugin()
        plugin._track_his_place("我在温州呢，过两天回")
        self.assertEqual(plugin.db.kv["he_place"]["city"], "温州")
        self.assertTrue(plugin.db.kv["he_place"]["away"])

    def test_away_without_city(self):
        """「我在外地/出差」认不出城市，也得记住他不在家。"""
        plugin = make_plugin()
        plugin._track_his_place("我在外地出差，回不来")
        self.assertEqual(plugin.db.kv["he_place"]["city"], "")
        self.assertTrue(plugin.db.kv["he_place"]["away"])

    def test_home_resets(self):
        plugin = make_plugin()
        plugin._track_his_place("我在温州")
        plugin._track_his_place("我回来了")
        self.assertFalse(plugin.db.kv["he_place"]["away"])
        self.assertEqual(plugin.db.kv["he_place"]["city"], "东莞")

    def test_unrelated_text_does_nothing(self):
        plugin = make_plugin()
        plugin._track_his_place("今天好想吃酸菜鱼")
        self.assertEqual(plugin.db.kv, {})


if __name__ == "__main__":
    unittest.main()
