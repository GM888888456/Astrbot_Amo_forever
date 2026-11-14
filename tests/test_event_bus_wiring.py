# -*- coding: utf-8 -*-
"""终端事件总线接线：提案/回执/关闭时的直通。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import astrbot_stub  # noqa: E402

astrbot_stub.install()

import main as term  # noqa: E402


def _fake(**config):
    values = {"event_bus_enable": True, "event_default_score": 0.8, "event_retry_after": 60}
    values.update(config)
    fake = type("Fake", (), {})()
    fake.config = values
    fake.cfg_bool = lambda key, default=False: bool(values.get(key, default))
    fake.cfg_int = lambda key, default=0: int(values.get(key, default))
    fake.cfg_float = lambda key, default=0.0: float(values.get(key, default))
    fake.event_bus = lambda: term.HumanCorePlugin.event_bus(fake)
    fake._event_score = lambda proposal: term.HumanCorePlugin._event_score(fake, proposal)
    return fake


def _proposal(**kwargs):
    data = {"event_id": "med-感冒-1", "event_type": "medical_treat", "source": "medical",
            "scene": "private", "payload": {"cost": 200, "reason": "治感冒"}}
    data.update(kwargs)
    return data


def test_submit_and_receipt_roundtrip():
    fake = _fake()
    decision = term.HumanCorePlugin.submit_event(fake, _proposal())
    assert decision["decision"] == "allow"
    receipt = term.HumanCorePlugin.event_receipt(fake, {
        "event_id": "med-感冒-1", "status": "success", "amount": 200, "balance": 900})
    assert receipt["accepted"] is True and receipt["ack"] is True


def test_duplicate_is_denied():
    fake = _fake()
    term.HumanCorePlugin.submit_event(fake, _proposal())
    again = term.HumanCorePlugin.submit_event(fake, _proposal())
    assert again["approved"] is False and again["reason"] == "duplicate"


def test_group_money_is_deferred():
    fake = _fake()
    decision = term.HumanCorePlugin.submit_event(fake, _proposal(scene="group"))
    assert decision["decision"] == "defer"


def test_low_score_denied():
    fake = _fake(event_default_score=0.1)
    decision = term.HumanCorePlugin.submit_event(fake, _proposal(event_id="low-1"))
    assert decision["approved"] is False and decision["decision"] == "deny"


def test_disabled_bus_passes_everything():
    fake = _fake(event_bus_enable=False)
    decision = term.HumanCorePlugin.submit_event(fake, _proposal(scene="group"))
    assert decision["approved"] is True and decision["reason"] == "事件总线关闭"
    assert term.HumanCorePlugin.event_receipt(fake, {"event_id": "x"})["accepted"] is False


def test_event_status_has_stats():
    fake = _fake()
    term.HumanCorePlugin.submit_event(fake, _proposal())
    status = term.HumanCorePlugin.event_status(fake)
    assert status["enabled"] is True
    assert status["stats"]["proposals"] == 1
    assert status["stats"]["allow"] == 1
