# -*- coding: utf-8 -*-
"""她嘴上说还款、实际没调 amo_repay：终端按那句话真扣。

用户的抱怨：「她说先还你多少多少，但金融并没有进行扣款」。
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

PLUGIN = amo_main.HumanCorePlugin


class AmountParseTests(unittest.TestCase):
    def test_arabic(self):
        self.assertEqual(PLUGIN._parse_amount("2000"), 2000.0)

    def test_chinese(self):
        self.assertEqual(PLUGIN._parse_amount("两千"), 2000.0)
        self.assertEqual(PLUGIN._parse_amount("一万"), 10000.0)

    def test_colloquial(self):
        """「一千二」是 1200，不是 1002。"""
        self.assertEqual(PLUGIN._parse_amount("一千二"), 1200.0)

    def test_unit_suffix(self):
        self.assertEqual(PLUGIN._parse_amount("五百块"), 500.0)

    def test_garbage(self):
        self.assertEqual(PLUGIN._parse_amount(""), 0.0)
        self.assertEqual(PLUGIN._parse_amount("好多"), 0.0)


class PromiseRegexTests(unittest.TestCase):
    def test_immediate_promise(self):
        m = PLUGIN.REPAY_PROMISE_RE.search("钱先还你两千，剩下的慢慢来。")
        self.assertIsNotNone(m)
        self.assertEqual(PLUGIN._parse_amount(m.group(1)), 2000.0)

    def test_arabic_promise(self):
        m = PLUGIN.REPAY_PROMISE_RE.search("先还你 500 块")
        self.assertEqual(PLUGIN._parse_amount(m.group(1)), 500.0)

    def test_later_promise_is_not_a_charge(self):
        """「回头还你两千」是以后的事，不能现在就扣。"""
        self.assertIsNone(PLUGIN.REPAY_PROMISE_RE.search("回头还你两千"))

    def test_small_talk_is_below_threshold(self):
        m = PLUGIN.REPAY_PROMISE_RE.search("还你一下")
        self.assertIsNotNone(m)
        self.assertLess(PLUGIN._parse_amount(m.group(1)), 50)


if __name__ == "__main__":
    unittest.main()
