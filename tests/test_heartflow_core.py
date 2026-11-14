# -*- coding: utf-8 -*-
"""心流数值核心：只有加减和边界，事件表是数据。"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from heartflow import (  # noqa: E402
    BASELINE,
    Desire,
    Emotion,
    Heartflow,
    HeartflowEvent,
    Physiology,
)


class FakeDB:
    def __init__(self):
        self.kv = {}

    def kv_get(self, key, default=None):
        return self.kv.get(key, default)

    def kv_set(self, key, value):
        self.kv[key] = value


class ValueTests(unittest.TestCase):
    def test_defaults_are_baseline(self):
        values = Heartflow(FakeDB()).values()
        self.assertEqual(len(values), 2 + 7 + 6)
        self.assertTrue(all(v == BASELINE for v in values.values()))

    def test_apply_event_changes_values(self):
        hf = Heartflow(FakeDB())
        out = hf.apply(HeartflowEvent.CHAT_PRAISE)
        self.assertGreater(out[Emotion.JOY.value], BASELINE)
        self.assertEqual(out[Emotion.ANGER.value], BASELINE)

    def test_clamped_to_0_100(self):
        hf = Heartflow(FakeDB())
        out = hf.apply(HeartflowEvent.CHAT_INSULT, {Emotion.ANGER: 500})
        self.assertEqual(out[Emotion.ANGER.value], 100.0)
        out = hf.apply(HeartflowEvent.CHAT_INSULT, {Emotion.ANGER: -500})
        self.assertEqual(out[Emotion.ANGER.value], 0.0)

    def test_unknown_event_is_ignored(self):
        hf = Heartflow(FakeDB())
        before = hf.values()
        hf.apply("not_an_event")
        self.assertEqual(hf.values(), before)

    def test_persists(self):
        db = FakeDB()
        Heartflow(db).apply(HeartflowEvent.PERIOD_START)
        again = Heartflow(db).values()
        self.assertGreater(again[Physiology.ENERGY.value], 0)
        self.assertEqual(again[Emotion.ANGER.value], BASELINE + 15)


class DecayTests(unittest.TestCase):
    def test_hunger_rises_and_energy_drops(self):
        hf = Heartflow(FakeDB())
        out = hf.decay(60)
        self.assertGreater(out[Physiology.HUNGER.value], BASELINE)
        self.assertLess(out[Physiology.ENERGY.value], BASELINE)

    def test_emotions_drift_toward_baseline(self):
        hf = Heartflow(FakeDB())
        hf.apply(HeartflowEvent.CHAT_PRAISE)
        hot = hf.values()[Emotion.JOY.value]
        out = hf.decay(180)
        self.assertLess(out[Emotion.JOY.value], hot)
        self.assertGreater(out[Emotion.JOY.value], BASELINE)

    def test_sleeping_restores_energy(self):
        """睡着时精力回涨，不然一夜下来还是 0，她会永远喊累。"""
        hf = Heartflow(FakeDB())
        hf.save({**hf.values(), Physiology.ENERGY.value: 10.0})
        out = hf.decay(60, sleeping=True)
        self.assertGreater(out[Physiology.ENERGY.value], 10.0)

    def test_hunger_rate_is_human(self):
        """一小时不该饿掉三分之一：以前 0.6/分钟，吃一顿只回 25 点，等于白吃。"""
        hf = Heartflow(FakeDB())
        out = hf.decay(60)
        self.assertLess(out[Physiology.HUNGER.value], BASELINE + 20)

    def test_zero_minutes_is_noop(self):
        hf = Heartflow(FakeDB())
        before = hf.values()
        self.assertEqual(hf.decay(0), before)


class PromptTests(unittest.TestCase):
    def test_summary_mentions_seven_feelings(self):
        text = Heartflow(FakeDB()).get_prompt_summary()
        self.assertIn("七情", text)
        for name in ("喜", "怒", "哀", "惧", "爱", "恶", "惊"):
            self.assertIn(name, text)

    def test_extremes_become_inner_voice(self):
        hf = Heartflow(FakeDB())
        hf.apply(HeartflowEvent.CHAT_INSULT, {Emotion.ANGER: 60})
        text = hf.get_prompt_summary()
        self.assertIn("内心", text)
        self.assertIn("火气", text)

    def test_mid_values_have_no_inner_voice(self):
        text = Heartflow(FakeDB()).get_prompt_summary()
        self.assertNotIn("内心", text)


class EnumTests(unittest.TestCase):
    def test_desire_has_six_and_emotion_seven(self):
        self.assertEqual(len(list(Desire)), 6)
        self.assertEqual(len(list(Emotion)), 7)

    def test_str_returns_value(self):
        self.assertEqual(str(Emotion.ANGER), "anger")
        self.assertEqual(Emotion.ANGER.value, "anger")


if __name__ == "__main__":
    unittest.main()
