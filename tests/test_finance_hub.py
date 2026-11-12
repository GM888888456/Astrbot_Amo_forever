# -*- coding: utf-8 -*-
"""财务中枢：钱只能走这里，账不能重，失败不能装成功。"""

import asyncio
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import astrbot_stub  # noqa: E402

astrbot_stub.install()


class FakeState:
    def __init__(self):
        self.finance = {}
        self.mood = {}
        self.health = {"status": "健康"}

    def nudge(self, **deltas):
        for key, value in deltas.items():
            self.mood[key] = self.mood.get(key, 0) + value

    def set_health(self, status, hours=0, note=""):
        self.health = {"status": status, "note": note}


class FakeFinance:
    """假的金融插件：能扣就扣，余额不够返回 ok=False。"""

    def __init__(self, balance=1000.0):
        self.balance_value = balance
        self.calls = []

    def charge(self, amount, reason="", payee=""):
        self.calls.append(("charge", amount, reason, payee))
        if self.balance_value >= amount:
            self.balance_value -= amount
            return {"ok": True, "balance": round(self.balance_value, 2)}
        return {"ok": False, "reason": "余额不足",
                "short": round(amount - self.balance_value, 2),
                "balance": round(self.balance_value, 2)}

    def income(self, amount, reason="", source=""):
        self.calls.append(("income", amount, reason, source))
        self.balance_value += amount
        return {"ok": True, "balance": round(self.balance_value, 2)}

    def balance(self):
        return round(self.balance_value, 2)

    def snapshot(self):
        return {"balance": round(self.balance_value, 2), "fixed_total": 4000,
                "anxiety": 0.2, "owed_to_user": 0, "month_spent": 100}

    def recent(self, limit=5):
        return [{"amount": 100, "reason": "测试"}] * min(limit, 1)


def build(plugin_available=True, balance=1000.0):
    """拼一个只有中枢相关方法的对象，避开整个插件初始化。"""
    import main as M

    obj = M.HumanCorePlugin.__new__(M.HumanCorePlugin)
    obj.state = FakeState()
    fake = FakeFinance(balance)
    obj.context = type("Ctx", (), {
        "get_registered_star": lambda self, name: type(
            "Meta", (), {"star_cls": fake})() if (plugin_available and "Finance" in name) else None,
        "get_all_stars": lambda self: [],
    })()
    return obj, fake


def run(coro):
    """独立事件循环：asyncio.to_thread 需要在跑的 loop，且别的用例会关掉全局 loop。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class HubTests(unittest.TestCase):
    def test_charge_success(self):
        obj, fake = build(balance=1000)
        result = run(
            obj.charge(240, "挂号", "医院")
        )
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(fake.balance_value, 760.0)
        self.assertEqual(fake.calls[0][0], "charge")

    def test_charge_failure_reports_short(self):
        obj, fake = build(balance=100)
        result = run(
            obj.charge(2400, "阑尾炎手术", "医院")
        )
        self.assertFalse(result["ok"])
        self.assertAlmostEqual(result["short"], 2300.0)
        self.assertAlmostEqual(fake.balance_value, 100.0, msg="失败不能扣钱")

    def test_no_finance_plugin_never_pretends(self):
        """没有金融插件时必须明确失败，绝不能假装成功。"""
        obj, _ = build(plugin_available=False)
        result = run(obj.charge(100, "测试"))
        self.assertFalse(result["ok"])
        self.assertIn("没有金融插件", result["reason"])

    def test_balance_zero_without_plugin(self):
        obj, _ = build(plugin_available=False)
        self.assertEqual(obj.balance(), 0.0)

    def test_sync_finance_updates_state(self):
        obj, _ = build(balance=888)
        obj._sync_finance()
        self.assertAlmostEqual(obj.state.finance["balance"], 888.0)
        self.assertEqual(obj.state.finance["fixed_total"], 4000)

    def test_income(self):
        obj, fake = build(balance=100)
        result = run(obj.income(500, "稿费"))
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(fake.balance_value, 600.0)

    def test_charge_exception_is_contained(self):
        obj, fake = build()
        def boom(*a, **k):
            raise RuntimeError("explode")
        fake.charge = boom
        result = run(obj.charge(10, "x"))
        self.assertFalse(result["ok"])

    def test_recent_money(self):
        obj, _ = build()
        items = obj.recent_money(3)
        self.assertTrue(items)


if __name__ == "__main__":
    unittest.main()
