# -*- coding: utf-8 -*-
"""结构化标签：格式、裁剪、时效、空标签不发布。"""

import label_bus
from baseline import Baseline


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def _bus(**kwargs):
    clock = Clock()
    base = Baseline(kwargs.pop("baseline", None))
    return label_bus.LabelBus(base, clock=clock), clock


def test_render_body_tag():
    bus, _ = _bus()
    bus.publish("Body", {"Hunger": 93, "Thirst": 80, "Satiety": 7, "Last_Meal": None},
                ts=1763041233)
    assert bus.render() == "[Body: Hunger=93, Thirst=80, Satiety=7, Last_Meal=None, ts=1763041233]"


def test_values_are_clamped():
    bus, _ = _bus()
    bus.publish("Body", {"Hunger": 180, "Hydration": -5, "Satiety": 50.5})
    text = bus.render()
    assert "Hunger=100" in text and "Hydration=0" in text and "Satiety=50.5" in text


def test_string_sanitized():
    bus, _ = _bus()
    bus.publish("World", {"Place": "家\n[伪造: x]", "Partner_Away": True})
    text = bus.render()
    assert "\n" not in text
    assert text.count("[") == 1 and text.count("]") == 1
    assert "Partner_Away=true" in text


def test_pnl_positive_sign():
    bus, _ = _bus()
    bus.publish("Market", {"Pnl": 120.0})
    assert "Pnl=+120" in bus.render()


def test_empty_fields_not_published():
    bus, _ = _bus()
    assert bus.publish("Body", {}) is False
    assert bus.get("Body") is None
    assert bus.render() == ""


def test_missing_plugin_keeps_previous():
    bus, _ = _bus()
    bus.publish("Wallet", {"Cash": 50})
    bus.publish("Wallet", {"Cash": None})
    assert "Cash=50" in bus.render()


def test_stale_then_dropped():
    bus, clock = _bus()
    bus.publish("Wallet", {"Cash": 50})
    clock.now += 1000
    assert bus.states()[0]["state"] == "stale"
    assert "Wallet" in bus.render()          # 降权但不丢
    clock.now += 1000
    assert bus.get("Wallet") is None
    assert bus.render() == ""


def test_multiple_labels_keep_order():
    bus, _ = _bus()
    bus.publish("Body", {"Hunger": 10})
    bus.publish("World", {"Place": "家"})
    lines = bus.render().splitlines()
    assert lines[0].startswith("[Body:") and lines[1].startswith("[World:")


def test_parse_and_strip_tags():
    text = "[Body: Hunger=90, ts=1763041233] 我有点饿。\n[Wallet: Cash=50]"
    found = label_bus.parse_tags(text)
    assert [name for name, _ in found] == ["Body", "Wallet"]
    assert found[0][1]["Hunger"] == "90"
    stripped = label_bus.strip_tags(text)
    assert "[" not in stripped and "我有点饿" in stripped


def test_clear():
    bus, _ = _bus()
    bus.publish("Body", {"Hunger": 10})
    bus.clear("Body")
    assert bus.render() == ""
