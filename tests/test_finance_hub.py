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

    def test_expense_goes_to_lover_not_first_profile(self):
        """花钱记在相恋的人身上，不能记到列表里第一个陌生人头上。"""
        obj, _ = build(balance=1000)
        obj.db = type("DB", (), {
            "list_profiles": lambda self, *a, **k: [{"uid": "stranger"}],
        })()
        obj._lover_aliases = lambda: {"阿墨": "lover-uid"}
        self.assertEqual(obj._primary_uid(), "lover-uid")

    def test_primary_uid_falls_back_to_private_umo(self):
        obj, _ = build(balance=1000)
        obj.db = type("DB", (), {"list_profiles": lambda self, *a, **k: []})()
        obj._lover_aliases = lambda: {}
        obj._last_umo = "aiocqhttp:FriendMessage:3261748099"
        self.assertEqual(obj._primary_uid(), "3261748099")

    def test_charge_same_request_id_charges_once(self):
        """同一个幂等号重试只扣一次（医疗重试/网络重发都走这里）。"""
        obj, fake = build(balance=1000)
        first = run(obj.charge(200, "看病", "医院", request_id="med-abc"))
        second = run(obj.charge(200, "看病", "医院", request_id="med-abc"))
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertTrue(second.get("repeated"))
        self.assertAlmostEqual(fake.balance_value, 800.0)
        self.assertEqual(len(fake.calls), 1)

    def test_different_request_id_charges_twice(self):
        obj, fake = build(balance=1000)
        run(obj.charge(200, "看病", "医院", request_id="med-1"))
        run(obj.charge(200, "买药", "药房", request_id="med-2"))
        self.assertAlmostEqual(fake.balance_value, 600.0)

    def test_charge_rejects_bad_amount(self):
        obj, fake = build(balance=1000)
        self.assertEqual(run(obj.charge(0, "x"))["code"], "bad_amount")
        self.assertEqual(run(obj.charge(-5, "x"))["code"], "bad_amount")

    def test_charge_rejects_over_limit(self):
        obj, fake = build(balance=10 ** 9)
        result = run(obj.charge(obj.CHARGE_MAX + 1, "天价"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "over_limit")
        self.assertEqual(fake.calls, [])

    def test_charge_writes_expense_to_memory(self):
        """扣完要把「花了多少、扣没扣成」交给记忆，聊天时她才知道。"""
        obj, fake = build(balance=1000)
        obj.db = type("DB", (), {
            "list_profiles": lambda self, limit=1: [{"uid": "u1"}],
        })()
        seen = []

        async def fake_write(uid, content, kind="fact", tier=1, scope="private", group_id=""):
            seen.append((uid, content, kind, tier))
            return True

        obj._write_memory_checked = fake_write
        run(obj.charge(240, "看病", "医院", request_id="med-9", detail="挂号+药费"))
        self.assertEqual(seen[0][0], "u1")
        self.assertEqual(seen[0][2], "expense")
        self.assertEqual(seen[0][3], 0, "流水按事件层记，不进核心记忆")
        self.assertIn("看病（挂号+药费）", seen[0][1])
        self.assertIn("已扣款", seen[0][1])

    def test_charge_failure_also_recorded(self):
        obj, fake = build(balance=100)
        obj.db = type("DB", (), {
            "list_profiles": lambda self, limit=1: [{"uid": "u1"}],
        })()
        seen = []

        async def fake_write(uid, content, kind="fact", tier=1, scope="private", group_id=""):
            seen.append(content)
            return True

        obj._write_memory_checked = fake_write
        run(obj.charge(2400, "阑尾炎手术", "医院"))
        self.assertIn("没扣成", seen[0])

    def test_recent_money(self):
        obj, _ = build()
        items = obj.recent_money(3)
        self.assertTrue(items)


if __name__ == "__main__":
    unittest.main()
