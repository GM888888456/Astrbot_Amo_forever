# -*- coding: utf-8 -*-
"""9.3.2：钱要算储蓄；缺钱只在私聊跟恋人开口，群里绝不跟人要钱。"""

from __future__ import annotations

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


def build(finance=None, owed=0.0, invest=None):
    obj = object.__new__(M.HumanCorePlugin)
    obj.state = types.SimpleNamespace(
        finance=finance if finance is not None else {},
        invest=invest if invest is not None else {},
    )
    obj._finance = lambda: types.SimpleNamespace(
        borrow_info=lambda: {"owed": owed},
        money_gift=lambda: {"amount": 100.0, "channel": "transfer",
                            "owed": owed, "seconds": 5},
        money_repay=lambda: {"amount": 50.0, "remaining": owed, "seconds": 5},
    )
    return obj


class MoneyPoolTests(unittest.TestCase):
    def test_money_line_counts_savings(self):
        obj = build(finance={"balance": 0.0, "savings": 25213.74})
        text = obj._money_line()
        self.assertIn("¥0", text)
        self.assertIn("25214", text)
        self.assertIn("合计", text)

    def test_money_line_says_do_not_beg_when_savings_enough(self):
        obj = build(finance={"balance": 0.0, "savings": 25000.0})
        text = obj._money_line()
        self.assertIn("并不缺钱", text)
        self.assertIn("别跟任何人开口要钱", text)

    def test_money_line_silent_when_cash_is_fine(self):
        obj = build(finance={"balance": 8000.0, "savings": 25000.0})
        text = obj._money_line()
        self.assertNotIn("并不缺钱", text)


class SyncTests(unittest.TestCase):
    """金融快照同步必须把储蓄一起带进来，否则「有存款」还是会说成「没钱」。"""

    def test_sync_finance_keeps_savings(self):
        obj = object.__new__(M.HumanCorePlugin)
        obj.state = types.SimpleNamespace(finance={}, invest={})
        snap = {"balance": 10.0, "savings": 25000.0, "fixed_total": 0, "anxiety": 0,
                "owed_to_user": 0, "month_spent": 0, "invest": {}}
        obj._finance = lambda: types.SimpleNamespace(snapshot=lambda refresh=False: snap)
        obj._sync_finance()
        self.assertEqual(obj.state.finance["savings"], 25000.0)
        self.assertEqual(obj.state.finance["total"], 25010.0)
        self.assertIn("¥25010", obj._money_line())


class ScopeTests(unittest.TestCase):
    """缺钱只在「私聊 + 恋人」才提；有储蓄不许哭穷。"""

    def test_borrow_line_requires_private_lover(self):
        obj = build(finance={"balance": 0.0, "savings": 0.0}, owed=300.0)
        self.assertEqual(obj._borrow_line(), "")
        self.assertEqual(obj._borrow_line(can_ask=False), "")
        self.assertIn("没钱", obj._borrow_line(can_ask=True))

    def test_borrow_line_when_savings_cover(self):
        obj = build(finance={"balance": 0.0, "savings": 20000.0})
        self.assertEqual(obj._borrow_line(can_ask=True), "")

    def test_debt_line_needs_private_lover(self):
        obj = build(owed=800.0)
        self.assertEqual(obj._debt_line(), "")
        self.assertIn("欠他", obj._debt_line(can_ask=True))

    def test_leek_money_branch_in_group_does_not_beg(self):
        obj = build(finance={"balance": 0.0, "savings": 0.0},
                    invest={"stance": "overconfident", "leek": {"kind": "no_money"}})
        group_text = " ".join(obj._leek_lines(can_ask_money=False))
        self.assertIn("别跟任何人开口要钱", group_text)
        self.assertNotIn("转点", group_text)
        lover_text = " ".join(obj._leek_lines(can_ask_money=True))
        self.assertIn("转点", lover_text)

    def test_sick_line_money_hint_by_scope(self):
        snap = {"health": {"sick": True, "status": "感冒", "note": "嗓子疼"}}
        group_text = build()._sick_line(snap, can_ask_money=False)
        self.assertIn("别跟人借钱", group_text)
        lover_text = build()._sick_line(snap, can_ask_money=True)
        self.assertIn("等他转钱", lover_text)

    def test_gift_and_repay_are_private_only(self):
        obj = build(owed=100.0)
        self.assertEqual(obj._gift_line(private=False), "")
        self.assertIn("刚给了你钱", obj._gift_line(private=True))
        self.assertEqual(obj._repay_line(private=False), "")
        self.assertIn("还了他钱", obj._repay_line(private=True))


if __name__ == "__main__":
    unittest.main()
