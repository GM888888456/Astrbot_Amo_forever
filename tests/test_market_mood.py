# -*- coding: utf-8 -*-
"""股市盈亏 → 心情：赚了开心，亏了郁闷，一天只按方向记一次。"""

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


class FakeState:
    def __init__(self):
        self.mood = {}

    def nudge(self, **deltas):
        for key, value in deltas.items():
            self.mood[key] = self.mood.get(key, 0) + value


def build(signal):
    obj = object.__new__(M.HumanCorePlugin)
    obj.state = FakeState()
    fake = type("F", (), {"mood_signal": lambda self: signal})()
    obj._finance = lambda: fake
    obj.notes = []
    obj.rewards = []

    async def remember(text, kind="event"):
        obj.notes.append(text)

    async def reward(pnl):
        obj.rewards.append(pnl)

    obj._market_memory = remember
    obj._market_reward = reward
    return obj


class MarketMoodTests(unittest.TestCase):
    def test_profit_makes_her_happy(self):
        obj = build({"day_pnl": 300, "day_pnl_pct": 3.0})
        asyncio.run(obj._sync_market_mood())
        self.assertGreater(obj.state.mood.get("开心", 0), 0)
        self.assertTrue(obj.notes and "赚" in obj.notes[0])
        self.assertEqual(obj.rewards, [300])

    def test_loss_makes_her_gloomy(self):
        obj = build({"day_pnl": -500, "day_pnl_pct": -5.0})
        asyncio.run(obj._sync_market_mood())
        self.assertGreater(obj.state.mood.get("郁闷", 0), 0)
        self.assertGreater(obj.state.mood.get("焦虑", 0), 0)
        self.assertLess(obj.state.mood.get("开心", 0), 0)
        self.assertTrue(obj.notes and "亏" in obj.notes[0])
        self.assertEqual(obj.rewards, [], "亏了不该奖励自己")

    def test_small_move_does_nothing(self):
        obj = build({"day_pnl": 10, "day_pnl_pct": 0.3})
        asyncio.run(obj._sync_market_mood())
        self.assertEqual(obj.state.mood, {})
        self.assertEqual(obj.notes, [])

    def test_same_direction_only_once_per_day(self):
        obj = build({"day_pnl": 300, "day_pnl_pct": 3.0})
        asyncio.run(obj._sync_market_mood())
        first = dict(obj.state.mood)
        asyncio.run(obj._sync_market_mood())
        self.assertEqual(obj.state.mood, first, "同一天同一个方向不重复加")
        self.assertEqual(len(obj.notes), 1)

    def test_direction_change_applies(self):
        signal = {"day_pnl": 300, "day_pnl_pct": 3.0}
        obj = build(signal)
        asyncio.run(obj._sync_market_mood())
        signal["day_pnl"] = -300
        signal["day_pnl_pct"] = -3.0
        asyncio.run(obj._sync_market_mood())
        self.assertGreater(obj.state.mood.get("郁闷", 0), 0)

    def test_no_finance_plugin_is_noop(self):
        obj = object.__new__(M.HumanCorePlugin)
        obj.state = FakeState()
        obj._finance = lambda: None
        asyncio.run(obj._sync_market_mood())
        self.assertEqual(obj.state.mood, {})


if __name__ == "__main__":
    unittest.main()


class InvestAwarenessTests(unittest.TestCase):
    def _plugin(self, finance=None, invest=None):
        obj = object.__new__(M.HumanCorePlugin)
        obj.state = type("S", (), {"finance": finance or {}, "invest": invest or {}})()
        return obj

    def test_money_line(self):
        text = self._plugin(finance={"balance": 1234.0})._money_line()
        self.assertIn("¥1234", text)

    def test_invest_line_lists_positions(self):
        inv = {"positions": [{"name": "平安银行", "qty": 100, "pnl_pct": -0.4}],
               "day_pnl": -10.6}
        text = self._plugin(invest=inv)._invest_line()
        self.assertIn("平安银行", text)
        self.assertIn("100股", text)
        self.assertIn("亏了", text)

    def test_invest_line_without_positions(self):
        text = self._plugin()._invest_line()
        self.assertIn("还没有持仓", text)


class LeekTests(unittest.TestCase):
    """韭菜特质：涨了吹牛，亏了死扛、半夜哭。"""

    def _plugin(self, stance, proposal=None):
        obj = object.__new__(M.HumanCorePlugin)
        obj.state = type("S", (), {"invest": {"stance": stance, "proposal": proposal or {}}})()
        return obj

    def test_overconfident_brags(self):
        lines = " ".join(self._plugin("overconfident")._leek_lines())
        self.assertIn("巴菲特", lines)
        self.assertIn("买房", lines)

    def test_overconfident_shows_pending_proposal(self):
        prop = {"status": "pending", "name": "中国平安", "qty": 100, "amount": 5333}
        lines = " ".join(self._plugin("overconfident", prop)._leek_lines())
        self.assertIn("中国平安", lines)
        self.assertIn("点头", lines)

    def test_rejected_proposal_makes_her_pout(self):
        prop = {"status": "rejected", "name": "中国平安", "qty": 100, "amount": 5333}
        lines = " ".join(self._plugin("overconfident", prop)._leek_lines())
        self.assertIn("驳回", lines)

    def test_hodl_refuses_to_sell(self):
        lines = " ".join(self._plugin("hodl")._leek_lines())
        self.assertIn("死扛", lines)
        self.assertIn("不算亏", lines)

    def test_normal_day_has_no_leek_lines(self):
        self.assertEqual(self._plugin("")._leek_lines(), [])
