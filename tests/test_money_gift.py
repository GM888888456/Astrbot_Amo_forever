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
        line = obj._borrow_line()
        self.assertIn("没钱", line)
        self.assertIn("红包", line)
        self.assertIn("300", line)

    def test_no_borrow_line_when_has_cash(self):
        obj = build()
        obj.state.finance = {"balance": 5000}
        self.assertEqual(obj._borrow_line(), "")


class PrivateOnlyTests(unittest.TestCase):
    def test_group_message_ignored(self):
        obj = build()
        event = type("E", (), {"is_private_chat": lambda self: False})()
        self.assertFalse(asyncio.run(obj._handle_money_gift(event, "[转账]500")))


if __name__ == "__main__":
    unittest.main()
