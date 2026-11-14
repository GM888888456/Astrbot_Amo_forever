# -*- coding: utf-8 -*-
"""先审批再扣费：驳回不扣、成功回执、失败也回执。"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import astrbot_stub  # noqa: E402

astrbot_stub.install()

import main as term  # noqa: E402


class Fake:
    def __init__(self, decision=None, charge_result=None):
        self.decision = decision or {"approved": True, "decision": "allow", "reason": "ok"}
        self.charge_result = charge_result or {"ok": True, "code": "ok", "balance": 900}
        self.proposals = []
        self.charges = []
        self.receipts = []

    def submit_event(self, raw):
        self.proposals.append(raw)
        return dict(self.decision)

    async def charge(self, amount, **kwargs):
        self.charges.append((amount, kwargs))
        return dict(self.charge_result)

    def event_receipt(self, raw):
        self.receipts.append(raw)
        return {"accepted": True}

    def balance(self):
        return 1000.0


def _run(fake, amount, **kwargs):
    return asyncio.run(term.HumanCorePlugin._approved_charge(fake, amount, **kwargs))


def test_approved_charges_and_receipts():
    fake = Fake()
    result = _run(fake, 88.5, reason="买番茄", payee="市场", source="market")
    assert result["ok"] is True
    assert fake.charges and fake.charges[0][0] == 88.5
    assert fake.charges[0][1]["request_id"] == result["event_id"]
    assert fake.receipts and fake.receipts[0]["status"] == "success"


def test_denied_does_not_charge():
    fake = Fake({"approved": False, "decision": "defer", "reason": "群聊资金类行为暂缓"})
    result = _run(fake, 88.5, reason="买番茄", payee="市场", source="market", scene="group")
    assert result["ok"] is False and result["code"] == "defer"
    assert fake.charges == [] and fake.receipts == []


def test_failed_charge_still_receipts():
    fake = Fake(charge_result={"ok": False, "code": "no_money", "reason": "余额不足", "balance": 3})
    result = _run(fake, 999, reason="买手机", payee="数码店", source="market")
    assert result["ok"] is False
    assert fake.receipts and fake.receipts[0]["status"] == "fail"
    assert fake.receipts[0]["code"] == "no_money"


def test_proposal_shape():
    fake = Fake()
    _run(fake, 12, reason="买珍珠发圈", payee="市场", source="market", scene="group")
    proposal = fake.proposals[0]
    assert proposal["event_type"] == "market_buy"
    assert proposal["scene"] == "group"
    assert proposal["payload"]["cost"] == 12
    assert proposal["need_approve"] is True
    assert proposal["event_id"].startswith("market-")


def test_medical_source_maps_to_medical_treat():
    fake = Fake()
    _run(fake, 200, reason="治感冒", payee="医院", source="medical")
    assert fake.proposals[0]["event_type"] == "medical_treat"
