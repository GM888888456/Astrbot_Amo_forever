# -*- coding: utf-8 -*-
"""事件总线：校验、去重、加权、回执。"""

import event_bus
from baseline import Baseline
from event_bus import CONFLICT, EventBus


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def _bus(**kwargs):
    clock = Clock()
    base = Baseline(kwargs.pop("baseline", None))
    bus = EventBus(base, clock=clock, **kwargs)
    return bus, clock


def _proposal(**kwargs):
    data = {
        "event_id": "medical-感冒-1763041233-ab12",
        "event_type": "medical_treat",
        "source": "medical",
        "scene": "private",
        "umo": "umo-1",
        "payload": {"cost": 200, "reason": "治疗感冒"},
        "ts": 1763041233,
    }
    data.update(kwargs)
    return data


# ---------------------------------------------------------------- 校验


def test_missing_fields_denied():
    bus, _ = _bus()
    result = bus.submit({"event_id": "x"})
    assert result["approved"] is False
    assert result["decision"] == "deny"
    assert "缺字段" in result["reason"]


def test_bad_scene_rejected():
    bus, _ = _bus()
    result = bus.submit(_proposal(scene="world"))
    assert result["approved"] is False and "scene" in result["reason"]


def test_negative_cost_rejected():
    bus, _ = _bus()
    result = bus.submit(_proposal(payload={"cost": -1, "reason": "x"}))
    assert result["approved"] is False and "不能为负" in result["reason"]


def test_string_cost_rejected():
    bus, _ = _bus()
    result = bus.submit(_proposal(payload={"cost": "两百", "reason": "x"}))
    assert result["approved"] is False and "必须是数字" in result["reason"]


def test_non_dict_rejected():
    bus, _ = _bus()
    result = bus.submit("not-a-dict")
    assert result["approved"] is False


# ---------------------------------------------------------------- 审批


def test_auto_approve_light_action():
    bus, _ = _bus()
    result = bus.submit(_proposal(event_type="speech_synth", payload={"cost": 0}))
    assert result["approved"] is True
    assert result["reason"] == "轻动作免审批"
    assert result["score"] == 1.0


def test_high_score_allows():
    bus, _ = _bus(scorer=lambda proposal: 0.9)
    result = bus.submit(_proposal())
    assert result["approved"] is True and result["score"] == 0.9


def test_low_score_denies():
    bus, _ = _bus(scorer=lambda proposal: 0.1)
    result = bus.submit(_proposal())
    assert result["approved"] is False and result["decision"] == "deny"


def test_broken_scorer_is_conservative():
    def boom(proposal):
        raise RuntimeError("no heart")

    bus, _ = _bus(scorer=boom)
    assert bus.submit(_proposal())["approved"] is False


def test_group_money_deferred():
    bus, _ = _bus(scorer=lambda proposal: 1.0)
    result = bus.submit(_proposal(scene="group"))
    assert result["decision"] == "defer"
    assert "群聊资金" in result["reason"]
    assert result["fallback"]
    assert bus.stats()["defer"] == 1


def test_group_free_action_not_deferred():
    bus, _ = _bus()
    result = bus.submit(_proposal(event_type="speech_synth", scene="group",
                                  payload={"cost": 0}))
    assert result["approved"] is True


def test_group_weight_can_flip_decision():
    # 关闭「群聊资金暂缓」，单看权重：私聊 0.9×1.0 通过，群聊 0.9×0.3 不过
    bus, _ = _bus(scorer=lambda proposal: 0.9, baseline={"defer_group_money": False})
    assert bus.submit(_proposal(event_id="a-private"))["approved"] is True
    denied = bus.submit(_proposal(event_id="b-group", scene="group"))
    assert denied["approved"] is False and denied["decision"] == "deny"
    assert denied["score"] == 0.27


def test_explicit_need_approve_false():
    bus, _ = _bus(scorer=lambda proposal: 0.1)
    result = bus.submit(_proposal(event_type="medical_treat", need_approve=False))
    assert result["approved"] is True


# ---------------------------------------------------------------- 幂等


def test_replay_same_id_is_duplicate():
    bus, _ = _bus(scorer=lambda proposal: 1.0)
    first = bus.submit(_proposal())
    second = bus.submit(_proposal())
    assert first["approved"] is True
    assert second["approved"] is False and second["reason"] == "duplicate"
    assert bus.stats()["duplicates"] == 1
    assert len(bus.events()) == 1


def test_replay_after_success_is_duplicate():
    bus, _ = _bus(scorer=lambda proposal: 1.0)
    bus.submit(_proposal())
    assert bus.receipt({"event_id": _proposal()["event_id"], "status": "success",
                        "amount": 200})["accepted"] is True
    assert bus.submit(_proposal())["reason"] == "duplicate"


def test_changed_amount_is_conflict():
    bus, _ = _bus(scorer=lambda proposal: 1.0)
    bus.submit(_proposal())
    changed = bus.submit(_proposal(payload={"cost": 300, "reason": "治疗感冒"}))
    assert changed["decision"] == "deny" and changed["reason"] == CONFLICT
    assert bus.stats()["conflicts"] == 1


def test_failed_receipt_allows_retry_after():
    bus, clock = _bus(scorer=lambda proposal: 1.0, retry_after=60)
    bus.submit(_proposal())
    bus.receipt({"event_id": _proposal()["event_id"], "status": "fail", "code": "no_money"})
    soon = bus.submit(_proposal())
    assert soon["decision"] == "defer"

    clock.now += 61
    again = bus.submit(_proposal())
    assert again["approved"] is True
    assert bus.stats()["allow"] == 2


# ---------------------------------------------------------------- 回执


def test_receipt_requires_id_and_status():
    bus, _ = _bus()
    assert bus.receipt({})["accepted"] is False
    assert bus.receipt({"event_id": "x", "status": "maybe"})["accepted"] is False


def test_receipt_orphan_is_acked():
    bus, _ = _bus()
    result = bus.receipt({"event_id": "never-seen", "status": "success"})
    assert result["accepted"] is True and result["ack"] is True and result["orphan"] is True
    assert bus.stats()["orphan_receipts"] == 1


def test_receipt_amount_mismatch_is_conflict():
    bus, _ = _bus(scorer=lambda proposal: 1.0)
    bus.submit(_proposal())
    result = bus.receipt({"event_id": _proposal()["event_id"], "status": "success",
                          "amount": 100})
    assert result["accepted"] is False and result["reason"] == CONFLICT
    assert bus.stats()["conflicts"] == 1
    assert bus.events()[_proposal()["event_id"]]["status"] == "pending"


def test_receipt_success_marks_done():
    bus, _ = _bus(scorer=lambda proposal: 1.0)
    bus.submit(_proposal())
    bus.receipt({"event_id": _proposal()["event_id"], "status": "success", "amount": 200,
                 "balance": 9800, "code": "ok"})
    record = bus.events()[_proposal()["event_id"]]
    assert record["status"] == "done"
    assert record["receipt"]["balance"] == 9800


def test_stats_and_recent():
    bus, _ = _bus(scorer=lambda proposal: 1.0)
    bus.submit(_proposal())
    stats = bus.stats()
    assert stats["proposals"] == 1 and stats["allow"] == 1
    assert len(bus.recent()["decisions"]) == 1


def test_forget():
    bus, _ = _bus(scorer=lambda proposal: 1.0)
    bus.submit(_proposal())
    assert bus.forget(_proposal()["event_id"]) is True
    assert bus.forget("nothing") is False
