# -*- coding: utf-8 -*-
"""照片辅助单测：只剩「今日穿搭」和「图片落地」。

主动分享、场景概率、万象画卷人设/模板那一整套已经搬到终端判定 + 生图插件出图，
这里不再测它们，只保证被复用的两个能力不坏。
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import astrbot_stub  # noqa: E402

astrbot_stub.install()

from photo_engine import OUTFIT_POOL, PhotoEngine  # noqa: E402


class FakeDB:
    def __init__(self, path=""):
        self.kv = {}
        self.path = path

    def kv_get(self, key, default=None):
        return self.kv.get(key, default)

    def kv_set(self, key, value):
        self.kv[key] = value


class FakeState:
    def __init__(self, temp=20):
        self.weather = {"temp": temp}


class FakePlugin:
    def __init__(self, path="", temp=20, cfg=None):
        self.db = FakeDB(path)
        self.state = FakeState(temp)
        self.config = dict(cfg or {})
        self.plugin_dir = ""

    def cfg_bool(self, key, default=False):
        value = self.config.get(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on", "是")


def engine(path="", temp=20, cfg=None):
    return PhotoEngine(FakePlugin(path, temp, cfg))


class OutfitTests(unittest.TestCase):
    def test_same_day_same_outfit(self):
        e = engine()
        self.assertEqual(e.outfit_today(), e.outfit_today())
        self.assertIn(e.outfit_today(), OUTFIT_POOL)

    def test_outfit_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "amo.db")
            first = engine(db_path).outfit_today()
            again = engine(db_path).outfit_today()
            self.assertEqual(first, again)

    def test_cold_weather_adds_coat(self):
        self.assertIn("大衣", engine(temp=5).outfit_today())

    def test_hot_weather_is_light(self):
        self.assertIn("清爽", engine(temp=31).outfit_today())

    def test_enabled_defaults_on(self):
        self.assertTrue(engine().enabled)
        self.assertFalse(engine(cfg={"photo_enable": False}).enabled)


class LocalizeTests(unittest.TestCase):
    def test_data_url_passes_through(self):
        e = engine()
        item = {"data_url": "data:image/png;base64,AAA"}
        self.assertIs(asyncio.run(e._localize(item)), item)

    def test_existing_file_passes_through(self):
        e = engine()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
            path = fh.name
        try:
            item = {"file_path": path}
            self.assertIs(asyncio.run(e._localize(item)), item)
        finally:
            os.unlink(path)

    def test_non_http_untouched(self):
        e = engine()
        item = {"url": "C:/tmp/p.png"}
        self.assertIs(asyncio.run(e._localize(item)), item)

    def test_download_failure_returns_original(self):
        e = engine()

        async def boom(url):
            raise OSError("图床挂了")

        e._fetch_image = lambda url: (_ for _ in ()).throw(OSError("图床挂了"))
        item = {"url": "https://example.invalid/p.png"}
        out = asyncio.run(e._localize(item))
        self.assertIs(out, item)

    def test_cache_dir_is_inside_plugin_data(self):
        e = engine(path="/opt/astrbot_data/plugin_data/Astrbot_Amo_forever/amo.db")
        self.assertTrue(e._cache_dir().endswith("photo_cache"))


if __name__ == "__main__":
    unittest.main()
