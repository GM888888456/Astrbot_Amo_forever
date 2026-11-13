# -*- coding: utf-8 -*-
"""他给她钱：认 [转账] / [红包] 两种模板，算借款。"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import astrbot_stub  # noqa: E402

astrbot_stub.install()

import main as M  # noqa: E402


def build():
    obj = object.__new__(M.HumanCorePlugin)
    obj.state = type("S", (), {"finance": {"balance": 0}})()
    return obj


class ParseTests(unittest.TestCase):
    def test_transfer_bracket(self):
        self.assertEqual(build()._parse_money_gift("[转账]500"), ("transfer", 500.0, "CNY"))

    def test_transfer_chinese_bracket(self):
        self.assertEqual(build()._parse_money_gift("【转账】500"), ("transfer", 500.0, "CNY"))

    def test_transfer_plain(self):
        self.assertEqual(build()._parse_money_gift("转账 1000"), ("transfer", 1000.0, "CNY"))

    def test_red_packet(self):
        self.assertEqual(build()._parse_money_gift("[红包]200"), ("red", 200.0, "CNY"))

    def test_wan_unit(self):
        self.assertEqual(build()._parse_money_gift("[转账]1万"), ("transfer", 10000.0, "CNY"))

    def test_decimal(self):
        self.assertEqual(build()._parse_money_gift("[红包]66.6"), ("red", 66.6, "CNY"))

    def test_transfer_with_currency(self):
        self.assertEqual(build()._parse_money_gift("[转账]100 USD"),
                         ("transfer", 100.0, "USD"))
        self.assertEqual(build()._parse_money_gift("[转账] 500 元"),
                         ("transfer", 500.0, "CNY"))

    def test_red_with_currency(self):
        self.assertEqual(build()._parse_money_gift("[红包]200 港币"),
                         ("red", 200.0, "HKD"))

    def test_wan_with_currency(self):
        self.assertEqual(build()._parse_money_gift("[转账]1万美金"),
                         ("transfer", 10000.0, "USD"))

    def test_not_money(self):
        self.assertIsNone(build()._parse_money_gift("转账给我转点钱"))
        self.assertIsNone(build()._parse_money_gift("今天天气不错"))

    def test_borrow_line_when_broke(self):
        obj = build()
        obj._finance = lambda: type("F", (), {"borrow_info": lambda self: {"owed": 300.0}})()
        line = obj._borrow_line(can_ask=True)
        self.assertIn("没钱", line)
        self.assertIn("红包", line)
        self.assertIn("300", line)

    def test_no_borrow_line_when_has_cash(self):
        obj = build()
        obj.state.finance = {"balance": 5000}
        self.assertEqual(obj._borrow_line(can_ask=True), "")


class FakeDB:
    def __init__(self):
        self.kv = {}

    def kv_get(self, key, default=None):
        return self.kv.get(key, default)

    def kv_set(self, key, value):
        self.kv[key] = value


def with_gift(amount=7150.0, owed=7150.0):
    obj = build()
    obj.db = FakeDB()
    obj._finance = lambda: type("F", (), {"money_gift": lambda self: {
        "amount": amount, "channel": "transfer", "owed": owed, "seconds": 10}})()
    return obj


class GiftLineTests(unittest.TestCase):
    def test_gift_is_for_eating_well(self):
        text = with_gift()._gift_line()
        self.assertIn("吃好的", text)

    def test_gift_line_does_not_dictate_a_fixed_sentence(self):
        """以前上下文里写死「老公今天怎么对我这么好啊」，模型就每笔都复读。"""
        text = with_gift()._gift_line()
        self.assertNotIn("怎么对我这么好", text)
        self.assertIn("这轮的反应", text)
        self.assertIn("别套用", text)

    def test_gift_line_style_changes_between_gifts(self):
        obj = with_gift()
        first = obj._gift_line()
        second = obj._gift_line()
        self.assertNotEqual(first, second)


class GiftReplyVarietyTests(unittest.TestCase):
    def test_canned_line_is_gone(self):
        for template in M.HumanCorePlugin.GIFT_REPLIES + M.HumanCorePlugin.GIFT_REPLIES_BIG:
            self.assertNotIn("怎么对我这么好", template)

    def test_replies_do_not_repeat_the_previous_one(self):
        obj = with_gift()
        seen = set()
        last = None
        for _ in range(12):
            text = obj._warm_gift_reply("转账", 200.0, 800.0)
            self.assertNotEqual(text, last)
            last = text
            seen.add(text)
        self.assertGreaterEqual(len(seen), 5)

    def test_big_amount_uses_big_pool(self):
        obj = with_gift()
        text = obj._warm_gift_reply("转账", 5000.0, 5000.0)
        pool = [t.format(kind="转账", amt="5000", owed=5000.0)
                for t in M.HumanCorePlugin.GIFT_REPLIES_BIG]
        self.assertIn(text, pool)


class PrivateOnlyTests(unittest.TestCase):
    def test_group_message_ignored(self):
        obj = build()
        event = type("E", (), {"is_private_chat": lambda self: False})()
        self.assertFalse(asyncio.run(obj._handle_money_gift(event, "[转账]500")))


if __name__ == "__main__":
    unittest.main()
