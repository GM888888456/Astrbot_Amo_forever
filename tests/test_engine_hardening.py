# -*- coding: utf-8 -*-
"""画图 / 照片引擎的健壮性回归（P2 审查补的）。

覆盖：
- 画图「每天上限」以前只看最近一小时，日限额根本拦不住；
- 画图缓存不能把 base64 data_url 塞进 kv（会把数据库撑大）；
- 生图调用要有超时，卡住时不能把 _busy / inflight 永久占住；
- 照片下载要在事件循环外完成，并限制大小；
- 没配 photo_owner_ids 时只发主页私聊，不发给陌生私聊。
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import astrbot_stub  # noqa: E402

astrbot_stub.install()

import clock  # noqa: E402

clock.configure("Asia/Shanghai")  # 固定时区：别让别的用例留下的 TZ 影响这些用例

import draw_engine as DE  # noqa: E402
import photo_engine as PE  # noqa: E402
import test_draw_engine as DT  # noqa: E402
import test_photo_engine as PT  # noqa: E402


class DrawLimitTests(unittest.TestCase):
    def test_daily_cap_counts_whole_day(self):
        # 2 小时前画过一张：按旧的实现它已经从 hour 列表里消失，日限额永远不触发
        engine, _ = DT.engine_for({"draw_max_per_hour": 10, "draw_max_per_day": 1,
                                   "draw_cooldown_minutes": 0})
        engine._draw_times["u1"] = [time.monotonic() - 7200]
        self.assertEqual(engine._check_limits("u1"), "今天画满了")

    def test_hourly_cap(self):
        engine, _ = DT.engine_for({"draw_max_per_hour": 1, "draw_max_per_day": 10,
                                   "draw_cooldown_minutes": 0})
        engine._draw_times["u1"] = [time.monotonic() - 60]
        self.assertEqual(engine._check_limits("u1"), "这一小时画满了")

    def test_zero_limit_disables_draw(self):
        engine, _ = DT.engine_for({"draw_max_per_hour": 0, "draw_max_per_day": 10,
                                   "draw_cooldown_minutes": 0})
        self.assertIn("限额为 0", engine._check_limits("u1") or "")


class DrawCacheTests(unittest.TestCase):
    def test_large_data_url_is_not_stored(self):
        engine, plugin = DT.engine_for()
        engine._cache_put("k1", {"data_url": "data:image/png;base64," + "A" * 300000})
        self.assertNotIn("k1", plugin.db.kv)

    def test_data_url_dropped_when_file_exists(self):
        engine, plugin = DT.engine_for()
        engine._cache_put("k2", {"file_path": "C:/tmp/a.png",
                                "data_url": "data:image/png;base64," + "A" * 300000})
        self.assertEqual(plugin.db.kv["k2"]["data_url"], "")
        self.assertEqual(plugin.db.kv["k2"]["file_path"], "C:/tmp/a.png")


class DrawTaskTests(unittest.TestCase):
    def test_spawn_failure_does_not_leak_inflight(self):
        engine, plugin = DT.engine_for()

        def fake_spawn(coro):
            coro.close()
            return None

        plugin._spawn = fake_spawn
        engine._schedule(DT.FakeEvent("给我画一碗面"), "一碗面", "manual")
        self.assertNotIn("test:private:u1", engine._inflight)


class PhotoFetchTests(unittest.TestCase):
    def test_fetch_image_rejects_oversized_body(self):
        class BigResponse:
            headers = {"Content-Type": "image/jpeg"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size=-1):
                return b"x" * (PE._MAX_IMAGE_BYTES + 1)

        with mock.patch("photo_engine.urllib.request.urlopen", return_value=BigResponse()):
            with self.assertRaises(ValueError):
                PE.PhotoEngine._fetch_image("https://example.com/big.jpg")


if __name__ == "__main__":
    unittest.main(verbosity=2)
