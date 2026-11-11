# -*- coding: utf-8 -*-
"""插件自记账：判分/润色这些不进 provider_stats 的调用要能算出来。"""

import asyncio
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import astrbot_stub  # noqa: E402

astrbot_stub.install()

import main as amo_main  # noqa: E402


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = amo_main.AmoDB(os.path.join(self.tmp, "amo.db"))
        self.db.init()

    def test_record_and_summarize(self):
        self.db.record_tokens("judge", "deepseek-flash", 6000, 0, 65)
        self.db.record_tokens("judge", "deepseek-flash", 6000, 1000, 70)
        self.db.record_tokens("polish", "deepseek-flash", 800, 0, 120)
        usage = self.db.usage_since(0)
        self.assertEqual(usage["calls"], 3)
        self.assertEqual(usage["input_other"], 12800)
        self.assertEqual(usage["input_cached"], 1000)
        self.assertEqual(usage["output"], 255)
        self.assertEqual(usage["by_kind"]["judge"]["calls"], 2)
        self.assertEqual(usage["by_kind"]["polish"]["calls"], 1)
        self.assertGreater(usage["cost"], 0)

    def test_since_filter(self):
        self.db.record_tokens("judge", "m", 100, 0, 10, ts=1000)
        self.db.record_tokens("judge", "m", 100, 0, 10, ts=5000)
        self.assertEqual(self.db.usage_since(2000)["calls"], 1)

    def test_bad_row_does_not_raise(self):
        self.db.record_tokens("judge", "", "abc", None, 0)   # 脏数据不应炸
        self.assertEqual(self.db.usage_since(0)["by_kind"]["judge"]["calls"], 1)


class RecordTokensHookTests(unittest.TestCase):
    def test_usage_object_recorded(self):
        plugin = object.__new__(amo_main.HumanCorePlugin)
        plugin.db = type("DB", (), {"calls": [], "record_tokens": lambda self, *a: self.calls.append(a)})()
        usage = type("U", (), {"input_other": 100, "input_cached": 20, "output": 5})()
        resp = type("R", (), {"usage": usage})()
        provider = type("P", (), {"get_model": lambda self: "deepseek-flash"})()
        plugin._record_tokens("judge", provider, resp)
        self.assertEqual(len(plugin.db.calls), 1)
        self.assertEqual(plugin.db.calls[0][0], "judge")

    def test_missing_usage_is_ignored(self):
        plugin = object.__new__(amo_main.HumanCorePlugin)
        plugin.db = type("DB", (), {"calls": [], "record_tokens": lambda self, *a: self.calls.append(a)})()
        resp = type("R", (), {"usage": None})()
        provider = type("P", (), {"get_model": lambda self: "m"})()
        plugin._record_tokens("judge", provider, resp)
        self.assertEqual(plugin.db.calls, [])


if __name__ == "__main__":
    unittest.main()


class PolishSkipTests(unittest.TestCase):
    def test_short_reply_skips_llm(self):
        plugin = object.__new__(amo_main.HumanCorePlugin)
        plugin.config = {"enable_polish": True, "polish_min_chars": 30}
        plugin.context = None
        service = amo_main.LLMService(plugin)
        called = []

        async def fake_chat(*args, **kwargs):
            called.append(args)
            return "改写过"

        service.chat = fake_chat

        async def fake_provider(umo=""):
            return object()

        service.provider = fake_provider
        out = asyncio.run(service.polish("umo", "嗯，好呀", "温柔"))
        self.assertEqual(out, "嗯，好呀")
        self.assertEqual(called, [])

    def test_consult_still_polished(self):
        plugin = object.__new__(amo_main.HumanCorePlugin)
        plugin.config = {"enable_polish": True, "polish_min_chars": 30}
        plugin.context = None
        service = amo_main.LLMService(plugin)
        called = []

        async def fake_chat(*args, **kwargs):
            called.append(args)
            return "润色后的回答"

        service.chat = fake_chat
        out = asyncio.run(service.polish("umo", "先点这里", "温柔", consult=True))
        self.assertEqual(out, "润色后的回答")
        self.assertEqual(len(called), 1)


class ModelLeakTests(unittest.TestCase):
    """后台信息拦截只该拦「她自己」的自曝，不该误伤用户聊自己的项目。"""

    def test_user_dev_chat_passes(self):
        for text in (
            "整体做壳、插件填功能，这思路本来就没毛病。对了你不是还有三个分支没合嘛。",
            "提示词？我哪来的那些东西，别乱猜。",
            "扁平改半写实手绘，画风一变，提示词得重新捋一遍，够你折腾的。",
            "行就行呗，那插件的配置到底丢没得。",
            "你这个模型选型挺省的。",
        ):
            self.assertFalse(amo_main.looks_like_model_leak(text), text)

    def test_self_disclosure_blocked(self):
        for text in (
            "我是基于 deepseek 的模型。",
            "我用的是 gpt-4o。",
            "我的提示词里写了要温柔。",
            "我是一个语言模型。",
            "我跑在 deepseek 上。",
        ):
            self.assertTrue(amo_main.looks_like_model_leak(text), text)

    def test_deflect_text_varies(self):
        self.assertTrue(amo_main.leak_deflect_text())


class JudgeRecordingTests(unittest.TestCase):
    """判分自记账绝不能把判分搞挂（线上曾因 'HeartflowEngine' object has no attribute 'p' 全挂）。"""

    def test_missing_plugin_ref_is_safe(self):
        import heartflow_engine as hf
        engine = object.__new__(hf.HeartflowEngine)
        hf._record_judge_tokens(engine, object(), object())   # 不抛异常即通过

    def test_records_when_plugin_present(self):
        import heartflow_engine as hf
        calls = []

        class Plugin:
            def _record_tokens(self, kind, provider, response):
                calls.append(kind)

        engine = object.__new__(hf.HeartflowEngine)
        engine.plugin = Plugin()
        hf._record_judge_tokens(engine, object(), object())
        self.assertEqual(calls, ["judge"])
