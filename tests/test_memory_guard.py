# -*- coding: utf-8 -*-
"""记忆守门人：去重、相对时间绝对化、冲突只提示不拦。"""

import datetime
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from memory_guard import absolutize, commit, prepare  # noqa: E402

NOW = datetime.datetime(2026, 11, 13, 20, 0)


class FakeDB:
    def __init__(self):
        self.kv = {}

    def kv_get(self, key, default=None):
        return self.kv.get(key, default)

    def kv_set(self, key, value):
        self.kv[key] = value


class AbsoluteTimeTests(unittest.TestCase):
    def test_yesterday_becomes_a_date(self):
        self.assertIn("11-12", absolutize("昨天去了恐龙园", NOW))

    def test_tomorrow_becomes_a_date(self):
        self.assertIn("11-14", absolutize("明天回贵阳", NOW))

    def test_longest_word_wins(self):
        out = absolutize("昨天夜里渴醒了", NOW)
        self.assertIn("11-12", out)
        self.assertNotIn("昨天", out)

    def test_plain_text_untouched(self):
        self.assertEqual(absolutize("她喜欢毛绒玩具", NOW), "她喜欢毛绒玩具")


class PrepareTests(unittest.TestCase):
    def test_empty_is_rejected(self):
        ok, text, reason = prepare(FakeDB(), "u1", "   ", NOW)
        self.assertFalse(ok)
        self.assertEqual(reason, "empty")

    def test_prepare_alone_does_not_mark(self):
        db = FakeDB()
        first = prepare(db, "u1", "他给我转账 100", NOW, now_ts=1000.0)
        second = prepare(db, "u1", "他给我转账 100", NOW, now_ts=1001.0)
        self.assertTrue(first[0])
        self.assertTrue(second[0], "没 commit 之前不该被当成重复")

    def test_commit_then_duplicate_within_window(self):
        db = FakeDB()
        ok, text, _ = prepare(db, "u1", "他给我转账 100", NOW, now_ts=1000.0)
        self.assertTrue(ok)
        commit(db, "u1", text, NOW, now_ts=1000.0)
        again = prepare(db, "u1", "他给我转账 100", NOW, now_ts=1200.0)
        self.assertFalse(again[0])
        self.assertEqual(again[2], "duplicate")

    def test_after_window_is_allowed(self):
        db = FakeDB()
        ok, text, _ = prepare(db, "u1", "他说晚上回来", NOW, now_ts=1000.0)
        commit(db, "u1", text, NOW, now_ts=1000.0)
        later = prepare(db, "u1", "他说晚上回来", NOW, now_ts=4600.0)
        self.assertTrue(later[0])


class ConflictTests(unittest.TestCase):
    def test_two_places_same_day_are_flagged(self):
        db = FakeDB()
        self.assertEqual(commit(db, "u1", "她在酒店休息", NOW), "")
        self.assertIn("不一致", commit(db, "u1", "她在景区逛", NOW))

    def test_same_place_is_not_flagged(self):
        db = FakeDB()
        commit(db, "u1", "她在酒店休息", NOW)
        self.assertEqual(commit(db, "u1", "酒店里的人不多", NOW), "")

    def test_no_place_no_flag(self):
        db = FakeDB()
        commit(db, "u1", "她在酒店休息", NOW)
        self.assertEqual(commit(db, "u1", "她想他了", NOW), "")


if __name__ == "__main__":
    unittest.main()
