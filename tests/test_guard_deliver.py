# -*- coding: utf-8 -*-
"""守护发送桥 + 外部发送后的记账。"""

import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import astrbot_stub  # noqa: E402

astrbot_stub.install()

import guard_bridge  # noqa: E402
import send_bookkeeping as SB  # noqa: E402


class FakeGuard:
    def __init__(self, result=None, raises=False):
        self.result = result if result is not None else {
            "ok": True, "sent": 2, "text": "一\n\n二", "messages": ["一", "二"]}
        self.raises = raises
        self.tasks = []

    async def deliver(self, task):
        self.tasks.append(task)
        if self.raises:
            raise RuntimeError("boom")
        return self.result


class FakeContext:
    def __init__(self, guard=None, metas=None):
        self.guard = guard
        self.metas = list(metas or [])

    def get_registered_star(self, name):
        if self.guard is None:
            return None
        return types.SimpleNamespace(star_cls=self.guard)

    def get_all_stars(self):
        return self.metas


class FakePlugin:
    def __init__(self, context=None):
        self.context = context


def _run(coro):
    return asyncio.run(coro)


def test_deliver_success():
    guard = FakeGuard()
    plugin = FakePlugin(FakeContext(guard))
    result = _run(guard_bridge.deliver_reply(
        plugin, "原文", "group", "umo-1", quote_id="mid-1", group=True))
    assert result["sent"] == 2
    task = guard.tasks[0]
    assert task["umo"] == "umo-1"
    assert task["quote_id"] == "mid-1"
    assert task["scene"] == "group"
    assert task["task_type"] == "format"


def test_deliver_without_guard_returns_none():
    assert _run(guard_bridge.deliver_reply(
        FakePlugin(FakeContext()), "原文", "private", "umo-1")) is None


def test_deliver_without_method_returns_none():
    class Dumb:
        pass

    plugin = FakePlugin(FakeContext(Dumb()))
    assert _run(guard_bridge.deliver_reply(
        plugin, "原文", "private", "umo-1")) is None


def test_deliver_exception_returns_none():
    plugin = FakePlugin(FakeContext(FakeGuard(raises=True)))
    assert _run(guard_bridge.deliver_reply(
        plugin, "原文", "private", "umo-1")) is None


def test_deliver_needs_text_and_umo():
    plugin = FakePlugin(FakeContext(FakeGuard()))
    assert _run(guard_bridge.deliver_reply(plugin, "  ", "private", "umo-1")) is None
    assert _run(guard_bridge.deliver_reply(plugin, "原文", "private", "")) is None


def test_after_external_send_records():
    calls = []

    async def fake_typing(event, flag):
        calls.append(("typing", flag))

    async def fake_history(context, event, text):
        calls.append(("history", text))

    def fake_notify(plugin, event, text=""):
        calls.append(("heartflow", text))

    old = (SB.set_typing, SB.save_to_conversation_history, SB.notify_heartflow)
    SB.set_typing, SB.save_to_conversation_history, SB.notify_heartflow = fake_typing, fake_history, fake_notify
    try:
        plugin = types.SimpleNamespace(
            context=None,
            _last_reply_at={},
            _remember_bot_message=lambda umo, text: calls.append(("remember", text)),
        )
        event = types.SimpleNamespace(unified_msg_origin="umo-1")
        _run(SB.after_external_send(plugin, event, "你好"))
        assert ("remember", "你好") in calls
        assert ("heartflow", "你好") in calls
        assert ("history", "你好") in calls
        assert plugin._last_reply_at["umo-1"] > 0
    finally:
        SB.set_typing, SB.save_to_conversation_history, SB.notify_heartflow = old


def test_after_external_send_skips_blank():
    calls = []

    async def fake_typing(event, flag):
        calls.append("typing")

    old = SB.set_typing
    SB.set_typing = fake_typing
    try:
        plugin = types.SimpleNamespace(context=None, _last_reply_at={})
        _run(SB.after_external_send(plugin, types.SimpleNamespace(unified_msg_origin="u"), "  "))
        assert calls == []
    finally:
        SB.set_typing = old
