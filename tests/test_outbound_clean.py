# -*- coding: utf-8 -*-
"""出站清理 + 旅游记账。

两件踩过的事：
1. 模型把 `<astrbot_execute_python>` 当正文输出 → 群里直接「爆代码」；
2. 出去玩不花钱 → 日程在景区、账本一分没动。
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


class PseudoTagTests(unittest.TestCase):
    def test_execute_python_block_is_removed(self):
        raw = "好呀\n<astrbot_execute_python>\n```python\nprint(1)\n```\n</astrbot_execute_python>"
        self.assertEqual(amo_main.strip_pseudo_tags(raw), "好呀")

    def test_plain_tag_only_text_becomes_empty(self):
        self.assertEqual(amo_main.strip_pseudo_tags("<astrbot_execute_python>"), "")
        self.assertEqual(amo_main.clean_reply("<astrbot_execute_python>"), "")

    def test_code_fence_removed_from_reply(self):
        self.assertEqual(amo_main.clean_reply("看这个```print(1)```呀"), "看这个呀")

    def test_normal_text_untouched(self):
        self.assertEqual(amo_main.strip_pseudo_tags("今天雾大得很"), "今天雾大得很")

    def test_voice_text_never_keeps_control_tags(self):
        self.assertEqual(amo_main._strip_voice_tags("<astrbot_execute_python>"), "")
        self.assertEqual(
            amo_main._strip_voice_tags('<astrbot_speak text="我爱你呀老公">'), "我爱你呀老公")
        self.assertEqual(amo_main._strip_voice_tags("<text>爱你呀</text>"), "爱你呀")


class FakeDB:
    def __init__(self):
        self.kv = {}

    def kv_get(self, key, default=None):
        return self.kv.get(key, default)

    def kv_set(self, key, value):
        self.kv[key] = value


class FakePlugin:
    """只提供 HumanState 记账要用的东西。"""

    def __init__(self, ok=True):
        self.db = FakeDB()
        self.charges = []
        self.ok = ok
        self.tasks = []

    def _spawn(self, coro):
        self.tasks.append(coro)
        return coro

    async def charge(self, amount, reason="", payee="", request_id="",
                     source="", detail="", uid=""):
        self.charges.append({"amount": amount, "reason": reason, "payee": payee,
                             "request_id": request_id, "source": source,
                             "detail": detail})
        return {"ok": self.ok, "balance": 123.45,
                "reason": "" if self.ok else "余额不足"}


def state_for(plugin):
    state = object.__new__(amo_main.HumanState)
    state.db = plugin.db
    state.p = plugin
    return state


class TravelBillingTests(unittest.TestCase):
    TRIP = {"city": "南阳", "kind": "solo"}

    def test_cost_is_deterministic_per_day(self):
        plugin = FakePlugin()
        state = state_for(plugin)
        first = state._trip_cost("南阳", TODAY)
        second = state._trip_cost("南阳", TODAY)
        self.assertEqual(first, second)
        self.assertGreater(first, 0)
        self.assertLess(first, 2000)

    def test_one_charge_per_day(self):
        plugin = FakePlugin()
        state = state_for(plugin)
        state._bill_trip(self.TRIP, TODAY)
        self.assertEqual(len(plugin.tasks), 1)
        import asyncio
        asyncio.run(plugin.tasks[0])
        self.assertEqual(len(plugin.charges), 1)
        charge = plugin.charges[0]
        self.assertEqual(charge["reason"], "旅游")
        self.assertEqual(charge["payee"], "南阳")
        self.assertEqual(charge["source"], "travel")
        self.assertIn(TODAY, charge["request_id"])

        # 同一天再走一遍日程同步，不许再扣一次
        state._bill_trip(self.TRIP, TODAY)
        self.assertEqual(plugin.tasks[1:], [])
        self.assertEqual(len(plugin.charges), 1)

    def test_failed_charge_is_retried_next_time(self):
        plugin = FakePlugin(ok=False)
        state = state_for(plugin)
        import asyncio
        state._bill_trip(self.TRIP, TODAY)
        asyncio.run(plugin.tasks[0])
        self.assertFalse(state.db.kv_get("travel_billed:travel:%s:南阳" % TODAY, ""))
        # 同一天下次同步还会再试（扣成功才记账，失败不留"已扣"标记）
        state._bill_trip(self.TRIP, TODAY)
        self.assertEqual(len(plugin.tasks), 2)
        asyncio.run(plugin.tasks[1])
        self.assertEqual(len(plugin.charges), 2)

    def test_no_city_means_no_charge(self):
        plugin = FakePlugin()
        state = state_for(plugin)
        state._bill_trip({}, TODAY)
        self.assertEqual(plugin.tasks, [])


if __name__ == "__main__":
    unittest.main()
