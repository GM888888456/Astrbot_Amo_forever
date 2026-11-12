# -*- coding: utf-8 -*-
"""插完话别再哑 60 秒：手工发送后要主动清除「判断暂停」。"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import astrbot_stub  # noqa: E402

astrbot_stub.install()

import heartflow_engine as HF  # noqa: E402
import segment_engine as SE  # noqa: E402


class FakeState:
    def __init__(self):
        self.pending_heartflow_reply = True
        self.pending_heartflow_mode = "score"
        self.last_reply_time = 0.0
        self.total_replies = 0
        self.judgment_paused = True


class MarkRepliedTests(unittest.TestCase):
    def _engine(self):
        engine = object.__new__(HF.HeartflowEngine)
        engine._states = {}
        state = FakeState()
        engine._states["umo"] = state
        engine._get_chat_state = lambda umo: engine._states.setdefault(umo, FakeState())
        engine._is_immersive_mode_active = lambda umo: False
        engine._activate_immersive_mode = lambda umo: None
        engine._refresh_immersive_mode = lambda umo: None
        engine._record_bot_reply_manual = lambda umo, text: None
        engine._cancel_pause_restore_task = lambda umo: None
        engine._set_judgment_paused = lambda umo, paused=True: setattr(
            engine._states[umo], "judgment_paused", paused)
        return engine, state

    def test_clears_pause_and_pending(self):
        engine, state = self._engine()
        engine.mark_replied("umo", "说搬就搬")
        self.assertFalse(state.judgment_paused)
        self.assertFalse(state.pending_heartflow_reply)
        self.assertEqual(state.pending_heartflow_mode, "")
        self.assertEqual(state.total_replies, 1)

    def test_never_raises_on_weird_umo(self):
        engine, _ = self._engine()
        engine.mark_replied("", "")


class NotifierTests(unittest.TestCase):
    def test_uses_plugin_attribute(self):
        calls = []

        class Flow:
            def mark_replied(self, umo, text):
                calls.append((umo, text))

        plugin = type("P", (), {"heartflow": Flow()})()
        engine = object.__new__(SE.SegmentEngine)
        engine.plugin = plugin
        event = type("E", (), {"unified_msg_origin": "umo"})()
        engine._notify_heartflow(event, "hi")
        self.assertEqual(calls, [("umo", "hi")])

    def test_missing_heartflow_is_noop(self):
        engine = object.__new__(SE.SegmentEngine)
        engine.plugin = object()
        event = type("E", (), {"unified_msg_origin": "umo"})()
        engine._notify_heartflow(event, "hi")


if __name__ == "__main__":
    unittest.main()
