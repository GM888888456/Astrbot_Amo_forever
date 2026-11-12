# -*- coding: utf-8 -*-
"""心流判定在「上游 503」时的降级：不刷屏、不空转、被叫到要应。

上游模型偶尔整片 503（日志里那句 ``API node is temporarily unavailable``），
旧实现每条消息都打一条 ERROR、并且一律不回复。这里锁住三件事：

1. 失败日志限频，不按消息条数刷屏；
2. 连败 3 次熔断 60 秒，期间不再打上游；
3. 熔断/失败时，只要消息在叫她（名字/别名）或被连续打扰，仍然回复。
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import astrbot_stub  # noqa: E402

astrbot_stub.install()

import heartflow_engine as HF  # noqa: E402


class FakeEvent:
    def __init__(self, text="", force=False):
        self.message_str = text
        self.amo_force_reply = force


def build(text="", force=False):
    """只拼判定降级要用的那几个属性，避开整个引擎初始化。"""
    engine = object.__new__(HF.HeartflowEngine)
    engine.score_max = 10.0
    engine.bot_name = "秦晓沫"
    engine.bot_aliases = ["晓沫", "沫沫"]
    engine._judge_fail_streak = 0
    engine._judge_breaker_until = 0.0
    engine._judge_last_warn = 0.0
    engine._judge_last_error = ""
    return engine, FakeEvent(text, force)


class JudgeFallbackTests(unittest.TestCase):
    def test_transient_errors_are_recognized(self):
        engine, _ = build()
        self.assertTrue(engine._judge_is_transient(RuntimeError("Error code: 503 - service_unavailable")))
        self.assertTrue(engine._judge_is_transient(RuntimeError("Request timed out")))
        self.assertFalse(engine._judge_is_transient(ValueError("bad json")))

    def test_failure_log_is_throttled_and_breaker_opens(self):
        engine, _ = build()
        warnings = []
        with mock.patch.object(HF.logger, "warning", side_effect=lambda *a, **k: warnings.append(a)):
            for _ in range(6):
                engine._judge_note_failure(RuntimeError("503"))
        # 6 条失败：只留「第一次失败 + 一次熔断」，不按消息条数刷屏
        self.assertEqual(len(warnings), 2, warnings)
        self.assertIn("连续", warnings[0][0])
        self.assertIn("熔断", warnings[1][0])
        self.assertTrue(engine._judge_breaker_open(), "连败 3 次应熔断")

    def test_breaker_expires(self):
        engine, _ = build()
        engine._judge_breaker_until = time.time() - 1
        self.assertFalse(engine._judge_breaker_open())

    def test_fallback_replies_when_called_by_name(self):
        engine, event = build("晓沫你在吗")
        result = engine._judge_fallback(event, "503")
        self.assertTrue(result.should_reply)
        self.assertIn("叫我", result.reasoning)

    def test_fallback_silent_when_not_addressed(self):
        engine, event = build("今天天气不错")
        result = engine._judge_fallback(event, "503")
        self.assertFalse(result.should_reply)

    def test_fallback_replies_when_forced(self):
        engine, event = build("在干嘛", force=True)
        self.assertTrue(engine._judge_fallback(event, "503").should_reply)

    def test_success_resets_breaker(self):
        engine, _ = build()
        engine._judge_note_failure(RuntimeError("503"))
        engine._judge_note_failure(RuntimeError("503"))
        engine._judge_note_failure(RuntimeError("503"))
        self.assertTrue(engine._judge_breaker_open())
        engine._judge_ok()
        self.assertFalse(engine._judge_breaker_open())
        self.assertEqual(engine._judge_fail_streak, 0)


if __name__ == "__main__":
    unittest.main()
