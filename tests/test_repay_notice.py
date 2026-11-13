# -*- coding: utf-8 -*-
"""9.3.4：还款要在聊天里看得见，格式 [还款]金额。"""

from __future__ import annotations

import asyncio
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import astrbot_stub  # noqa: E402

astrbot_stub.install()

import main as M  # noqa: E402


class FakeDB:
    def __init__(self):
        self.kv = {}

    def kv_get(self, key, default=None):
        return self.kv.get(key, default)

    def kv_set(self, key, value):
        self.kv[key] = value


class FakeEvent:
    def __init__(self, umo="qq:private:10001", private=True):
        self.unified_msg_origin = umo
        self._private = private

    def is_private_chat(self):
        return self._private


def build(paid=500.0, remaining=2300.0):
    obj = object.__new__(M.HumanCorePlugin)
    obj.db = FakeDB()
    obj.state = types.SimpleNamespace(finance={}, invest={})
    obj._last_umo = "qq:private:10001"
    sent = []

    class Ctx:
        async def send_message(self, umo, text):
            sent.append((umo, text))

    obj.context = Ctx()
    obj.sent = sent
    obj._finance = lambda: types.SimpleNamespace(
        repay=lambda amount, notify=True: {"ok": True, "paid": paid,
                                          "remaining": remaining},
        money_repay=lambda: {"amount": paid, "remaining": remaining,
                             "seconds": 5, "ts": 100.0},
        snapshot=lambda refresh=False: {"balance": 0, "savings": 0, "invest": {}},
    )
    return obj


class RepayTextTests(unittest.TestCase):
    def test_bracket_format(self):
        text = build()._repay_message(500.0, 2300.0)
        self.assertTrue(text.startswith("[还款]500\n"))
        self.assertIn("还欠你 2300", text)

    def test_decimal_kept(self):
        self.assertTrue(build()._repay_message(124.5, 10).startswith("[还款]124.5"))

    def test_paid_off(self):
        text = build()._repay_message(500.0, 0)
        self.assertIn("还清", text)

    def test_nothing_paid(self):
        self.assertEqual(build()._repay_message(0, 100), "")


class ToolSendsMessageTests(unittest.TestCase):
    def test_amo_repay_sends_bracket_line(self):
        obj = build()
        out = asyncio.run(obj.amo_repay(FakeEvent(), 500.0))
        self.assertEqual(len(obj.sent), 1)
        umo, text = obj.sent[0]
        self.assertEqual(umo, "qq:private:10001")
        self.assertIn("[还款]500", text)
        self.assertIn("不用再报", out)

    def test_group_call_goes_to_private(self):
        obj = build()
        asyncio.run(obj.amo_repay(FakeEvent(umo="qq:group:1", private=False), 500.0))
        self.assertEqual(obj.sent[0][0], "qq:private:10001")

    def test_notify_repay_same_format(self):
        obj = build()
        asyncio.run(obj.notify_repay(500.0, 2300.0))
        self.assertEqual(len(obj.sent), 1)
        self.assertTrue(obj.sent[0][1].startswith("[还款]500\n"))


if __name__ == "__main__":
    unittest.main()
