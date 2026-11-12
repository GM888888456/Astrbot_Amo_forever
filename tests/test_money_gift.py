# -*- coding: utf-8 -*-
"""他给她钱：认 [转账] / [红包] 两种模板，算借款。"""

from __future__ import annotations

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
        self.assertEqual(build()._parse_money_gift("[转账]500"), ("transfer", 500.0))

    def test_transfer_chinese_bracket(self):
        self.assertEqual(build()._parse_money_gift("【转账】500"), ("transfer", 500.0))

    def test_transfer_plain(self):
        self.assertEqual(build()._parse_money_gift("转账 1000"), ("transfer", 1000.0))

    def test_red_packet(self):
        self.assertEqual(build()._parse_money_gift("[红包]200"), ("red", 200.0))

    def test_wan_unit(self):
        self.assertEqual(build()._parse_money_gift("[转账]1万"), ("transfer", 10000.0))

    def test_decimal(self):
        self.assertEqual(build()._parse_money_gift("[红包]66.6"), ("red", 66.6))

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


if __name__ == "__main__":
    unittest.main()
