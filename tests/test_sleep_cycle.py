# -*- coding: utf-8 -*-
"""睡眠状态机：他让她睡 → 掂量；睡着不回话；半夜醒来有原因（枚举）。"""

import datetime
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sleep_cycle import (  # noqa: E402
    WAKE_TEXT,
    SleepAnswer,
    SleepCycle,
    SleepPhase,
    WakeReason,
    pick_reason,
    reason_for,
)


class FakeDB:
    def __init__(self):
        self.kv = {}

    def kv_get(self, key, default=None):
        return self.kv.get(key, default)

    def kv_set(self, key, value):
        self.kv[key] = value


def cycle(chance=0.0):
    return SleepCycle(FakeDB(), accept_after=23, wake_hour=7, night_wake_chance=chance)


class AnswerTests(unittest.TestCase):
    def test_early_evening_is_refused(self):
        c = cycle()
        self.assertIs(c.answer(datetime.datetime(2026, 11, 13, 21, 30)), SleepAnswer.TOO_EARLY)

    def test_after_eleven_accepts(self):
        c = cycle()
        self.assertIs(c.answer(datetime.datetime(2026, 11, 13, 23, 10)), SleepAnswer.ACCEPT)

    def test_small_hours_accepts(self):
        c = cycle()
        self.assertIs(c.answer(datetime.datetime(2026, 11, 14, 2, 0)), SleepAnswer.ACCEPT)


class SleepStateTests(unittest.TestCase):
    def test_go_to_sleep_sets_state_and_wake_time(self):
        c = cycle()
        now = datetime.datetime(2026, 11, 13, 23, 20)
        c.go_to_sleep(now)
        self.assertIs(c.phase(), SleepPhase.ASLEEP)
        state = c.load()
        self.assertEqual(state["wake_at"], "07:00")
        self.assertEqual(state["wake_day"], "2026-11-14")
        self.assertTrue(c.is_asleep(now))

    def test_before_wake_time_is_still_asleep(self):
        c = cycle()
        c.go_to_sleep(datetime.datetime(2026, 11, 13, 23, 20))
        self.assertTrue(c.is_asleep(datetime.datetime(2026, 11, 14, 6, 59)))
        self.assertFalse(c.is_asleep(datetime.datetime(2026, 11, 14, 7, 1)))

    def test_wake_up_clears_sleep(self):
        c = cycle()
        c.go_to_sleep(datetime.datetime(2026, 11, 13, 23, 20))
        c.wake_up(datetime.datetime(2026, 11, 14, 7, 5))
        self.assertIs(c.phase(), SleepPhase.AWAKE)
        self.assertFalse(c.is_asleep(datetime.datetime(2026, 11, 14, 7, 6)))

    def test_sleeping_blocks_chat_only_until_wake(self):
        c = cycle()
        c.go_to_sleep(datetime.datetime(2026, 11, 13, 23, 50))
        self.assertTrue(c.is_asleep(datetime.datetime(2026, 11, 13, 23, 55)))
        self.assertFalse(c.is_asleep(datetime.datetime(2026, 11, 14, 8, 0)))


class NightWakeTests(unittest.TestCase):
    def test_no_wake_outside_sleep(self):
        c = cycle(chance=1.0)
        self.assertIsNone(c.maybe_night_wake(datetime.datetime(2026, 11, 13, 15, 0)))

    def test_wake_has_a_reason_and_sets_phase(self):
        c = cycle(chance=1.0)
        c.go_to_sleep(datetime.datetime(2026, 11, 13, 23, 20))
        reason = c.maybe_night_wake(datetime.datetime(2026, 11, 14, 3, 0), random.Random(7))
        self.assertIsInstance(reason, WakeReason)
        self.assertIs(c.phase(), SleepPhase.NIGHT_WAKE)
        self.assertEqual(c.today_woke_reason(), reason)
        self.assertTrue(reason_for(reason))

    def test_only_once_a_night(self):
        c = cycle(chance=1.0)
        c.go_to_sleep(datetime.datetime(2026, 11, 13, 23, 20))
        self.assertIsNotNone(c.maybe_night_wake(datetime.datetime(2026, 11, 14, 3, 0)))
        c.back_to_sleep(datetime.datetime(2026, 11, 14, 3, 20))
        self.assertIsNone(c.maybe_night_wake(datetime.datetime(2026, 11, 14, 4, 0)))

    def test_zero_chance_never_wakes(self):
        c = cycle(chance=0.0)
        c.go_to_sleep(datetime.datetime(2026, 11, 13, 23, 20))
        self.assertIsNone(c.maybe_night_wake(datetime.datetime(2026, 11, 14, 3, 0)))


class EnumTests(unittest.TestCase):
    def test_every_reason_has_chinese_text(self):
        for reason in WakeReason:
            self.assertIn(reason, WAKE_TEXT)
            self.assertTrue(reason_for(reason).strip())

    def test_pick_reason_returns_member(self):
        self.assertIsInstance(pick_reason(random.Random(1)), WakeReason)

    def test_phases_are_enums_not_strings(self):
        self.assertIsInstance(SleepPhase.ASLEEP, SleepPhase)
        self.assertEqual(SleepPhase.ASLEEP.value, "asleep")
        self.assertIsInstance(SleepAnswer.ACCEPT, SleepAnswer)


if __name__ == "__main__":
    unittest.main()
