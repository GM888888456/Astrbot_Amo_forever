# -*- coding: utf-8 -*-
"""全局基线：加权、审批默认值、标签时效。"""

import baseline


def test_defaults():
    base = baseline.Baseline()
    assert base.multiplier("private", 100) == 1.0
    assert base.multiplier("group", 100) == 0.3
    assert base.multiplier("group", 0) == 1.0


def test_complain_weight():
    base = baseline.Baseline({"baseline_group_complain": 0.2})
    assert base.multiplier("group", 0, "complain") == 0.2
    assert base.multiplier("private", 0, "complain") == 1.0


def test_weights_are_clamped():
    base = baseline.Baseline({"baseline_group_money": 9})
    assert base.multiplier("group", 1) == 2.0
    base = baseline.Baseline({"baseline_private_money": -1})
    assert base.multiplier("private", 1) == 0.0


def test_needs_approve():
    base = baseline.Baseline()
    assert base.needs_approve("speech_synth") is False
    assert base.needs_approve("medical_treat") is True
    assert base.needs_approve("unknown_type") is True


def test_auto_approve_from_string():
    base = baseline.Baseline({"auto_approve_types": "a, b，c"})
    assert base.auto_approve == ("a", "b", "c")


def test_label_state_boundaries():
    base = baseline.Baseline({"label_stale_seconds": 900, "label_drop_seconds": 1800})
    assert base.label_state(0) == "fresh"
    assert base.label_state(899) == "fresh"
    assert base.label_state(900) == "stale"
    assert base.label_state(1799) == "stale"
    assert base.label_state(1800) == "drop"
    assert base.label_state(-1) == "fresh"


def test_label_weight():
    base = baseline.Baseline()
    assert base.label_weight(0) == 1.0
    assert base.label_weight(1000) == 0.5
    assert base.label_weight(99999) == 0.0


def test_to_dict_roundtrip():
    data = baseline.Baseline().to_dict()
    assert data["baseline_group_money"] == 0.3
    assert "medical_treat" in data["high_risk_types"]


def test_as_list_handles_none_and_newlines():
    assert baseline.as_list(None) == []
    assert baseline.as_list("a\nb") == ["a", "b"]
