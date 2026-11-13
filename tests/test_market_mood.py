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


class DoctorTests(unittest.TestCase):
    def _plugin(self, sick=True, ok=True):
        calls = {}

        class FakeMedical:
            def status(self):
                return {"sick": sick}

            async def treat(self, auto=False):
                calls["treat"] = auto
                return {"ok": ok, "name": "感冒", "self_pay": 12.0,
                        "reason": "" if ok else "余额不足"}

        obj = object.__new__(M.HumanCorePlugin)
        obj._medical = lambda: FakeMedical()
        obj.db = type("DB", (), {
            "kv_set": lambda self, k, v: calls.__setitem__("note", v),
            "kv_get": lambda self, k, d=None: calls.get("note", d),
        })()
        obj._sync_health_from_medical = lambda: calls.__setitem__("synced", True)
        event = type("E", (), {"is_private_chat": lambda self: True})()
        return obj, event, calls

    def test_urged_when_sick(self):
        obj, event, calls = self._plugin()
        said = "都病成这样了还不去医院看看，走我带你去医院"
        self.assertTrue(asyncio.run(obj._maybe_user_takes_her_to_doctor(event, said)))
        self.assertEqual(calls.get("treat"), False)   # auto=False：手动就医
        self.assertTrue(calls.get("synced"))

    def test_pure_urge_does_not_treat(self):
        obj, event, calls = self._plugin()
        said = "都病成这样了还不去医院看看"
        self.assertFalse(asyncio.run(obj._maybe_user_takes_her_to_doctor(event, said)))
        self.assertNotIn("treat", calls)

    def test_not_urged_stays_home(self):
        obj, event, calls = self._plugin()
        self.assertFalse(asyncio.run(obj._maybe_user_takes_her_to_doctor(event, "今天吃什么")))
        self.assertNotIn("treat", calls)

    def test_healthy_ignores_urge(self):
        obj, event, calls = self._plugin(sick=False)
        self.assertFalse(asyncio.run(obj._maybe_user_takes_her_to_doctor(event, "走我带你去医院")))
        self.assertNotIn("treat", calls)


class AutoTreatTests(unittest.TestCase):
    def test_auto_treat_uses_auto_true(self):
        calls = {}

        class FakeMedical:
            def status(self):
                return {"sick": True, "illness": "cold", "status": "感冒"}

            async def treat(self, auto=False):
                calls["auto"] = auto
                return {"ok": True, "name": "感冒", "self_pay": 12.0}

        obj = object.__new__(M.HumanCorePlugin)
        obj._medical = lambda: FakeMedical()
        obj._sync_health_from_medical = lambda: calls.__setitem__("synced", True)
        obj.state = type("S", (), {"nudge": lambda self, **kw: None})()
        obj._treat_marked = None
        asyncio.run(obj._maybe_treat())
        self.assertEqual(calls.get("auto"), True)
        self.assertTrue(calls.get("synced"))


class DriveTests(unittest.TestCase):
    def test_drive_line_is_self(self):
        obj = object.__new__(M.HumanCorePlugin)
        obj._short_place = lambda p: p
        text = obj._drive_line({"activity": {
            "activity": "开车去商场，雾天路上有点堵", "place": "路上"}})
        self.assertIn("开车的是你", text)
        self.assertIn("我在开车", text)
        self.assertIn("不是他", text)

    def test_no_drive_line_when_home(self):
        obj = object.__new__(M.HumanCorePlugin)
        obj._short_place = lambda p: p
        self.assertEqual(obj._drive_line({"activity": {
            "activity": "窝在沙发上追剧", "place": "家"}}), "")


class SickTests(unittest.TestCase):
    def test_sick_line(self):
        obj = object.__new__(M.HumanCorePlugin)
        text = obj._sick_line({"health": {"status": "感冒", "note": "喉咙痛"}})
        self.assertIn("感冒", text)
        self.assertIn("医院", text)
        self.assertIn("难受", text)


class DebtTests(unittest.TestCase):
    def _plugin(self, owed=0.0, repay=None):
        obj = object.__new__(M.HumanCorePlugin)
        obj.state = type("S", (), {})()
        obj._finance = lambda: type("F", (), {
            "borrow_info": lambda self: {"owed": owed},
            "money_repay": lambda self: (repay or {}),
        })()
        return obj

    def test_debt_line_when_owed(self):
        text = self._plugin(owed=800.0)._debt_line(can_ask=True)
        self.assertIn("欠他", text)
        self.assertIn("amo_repay", text)
        self.assertIn("依赖", text)

    def test_debt_line_clear(self):
        self.assertEqual(self._plugin(owed=0.0)._debt_line(can_ask=True), "")

    def test_repay_line(self):
        text = self._plugin(repay={"amount": 500.0, "remaining": 300.0,
                                   "seconds": 20})._repay_line()
        self.assertIn("还了他钱", text)
        self.assertIn("500", text)
        self.assertIn("300", text)


class LeekTests(unittest.TestCase):
    """韭菜特质：涨了吹牛，亏了死扛、半夜哭。"""

    def _plugin(self, stance, leek=None):
        obj = object.__new__(M.HumanCorePlugin)
        obj.state = type("S", (), {"invest": {"stance": stance, "leek": leek or {}}})()
        return obj

    def test_overconfident_brags(self):
        lines = " ".join(self._plugin("overconfident")._leek_lines())
        self.assertIn("巴菲特", lines)
        self.assertIn("买房", lines)

    def test_overconfident_after_buying(self):
        leek = {"kind": "bought", "name": "平安银行", "qty": 500}
        lines = " ".join(self._plugin("overconfident", leek)._leek_lines())
        self.assertIn("平安银行", lines)
        self.assertIn("邀功", lines)

    def test_no_money_makes_her_ask_for_a_top_up(self):
        leek = {"kind": "no_money"}
        lines = " ".join(self._plugin("overconfident", leek)._leek_lines(can_ask_money=True))
        self.assertIn("没钱", lines)
        self.assertIn("转点", lines)

    def test_no_room_sulks_and_can_ask_for_money(self):
        leek = {"kind": "no_room"}
        lines = " ".join(self._plugin("overconfident", leek)._leek_lines(can_ask_money=True))
        self.assertIn("仓位到顶", lines)
        self.assertIn("换一只继续买", lines)

    def test_hodl_refuses_to_sell(self):
        lines = " ".join(self._plugin("hodl")._leek_lines())
        self.assertIn("死扛", lines)
        self.assertIn("不算亏", lines)

    def test_normal_day_has_no_leek_lines(self):
        self.assertEqual(self._plugin("")._leek_lines(), [])


class PendingBlockTests(unittest.TestCase):
    """主动消息的等待窗口：不能因为「他没私聊回」就半天不开口。"""

    def _plugin(self, pending, last_seen, minutes=120):
        obj = object.__new__(M.HumanCorePlugin)
        obj.config = {"proactive_pending_max_minutes": minutes}
        obj._pending_key = lambda uid: "p:" + uid
        obj.db = type("DB", (), {
            "kv_get": lambda self, k, d=None: pending if k.startswith("p:") else d,
            "kv_set": lambda self, k, v: None,
        })()
        return obj

    def test_recent_message_blocks(self):
        import time
        now = time.time()
        obj = self._plugin({"sent_at": now - 600}, last_seen=now - 4000)
        self.assertTrue(obj._pending_still_blocking("u1", {"last_seen": now - 4000}, now))

    def test_user_spoke_anywhere_unblocks(self):
        import time
        now = time.time()
        obj = self._plugin({"sent_at": now - 600}, last_seen=now - 60)
        self.assertFalse(obj._pending_still_blocking("u1", {"last_seen": now - 60}, now))

    def test_window_expires(self):
        import time
        now = time.time()
        obj = self._plugin({"sent_at": now - 121 * 60}, last_seen=0)
        self.assertFalse(obj._pending_still_blocking("u1", {"last_seen": 0}, now))

    def test_no_pending_never_blocks(self):
        obj = self._plugin({}, last_seen=0)
        self.assertFalse(obj._pending_still_blocking("u1", {}, 1000.0))
