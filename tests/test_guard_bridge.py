# -*- coding: utf-8 -*-
"""守护桥：缺席/超时/报错都要退回原文。"""

import asyncio
import types

import guard_bridge


class FakeGuard:
    def __init__(self, result=None, delay=0.0, raises=False):
        self.result = result if result is not None else {
            "status": "success", "output_list": ["加工后的文本"]}
        self.delay = delay
        self.raises = raises
        self.tasks = []

    async def process_task(self, task):
        self.tasks.append(task)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raises:
            raise RuntimeError("guard down")
        return self.result


class FakeContext:
    def __init__(self, stars=None, metas=None):
        self.stars = dict(stars or {})
        self.metas = list(metas or [])

    def get_registered_star(self, name):
        instance = self.stars.get(name)
        if instance is None:
            return None
        return types.SimpleNamespace(star_cls=instance)

    def get_all_stars(self):
        return self.metas


class FakePlugin:
    def __init__(self, context=None):
        self.context = context


def _run(coro):
    return asyncio.run(coro)


def test_without_guard_returns_raw():
    plugin = FakePlugin(FakeContext())
    assert _run(guard_bridge.process_reply_text(plugin, "原文")) == ["原文"]


def test_without_context_returns_raw():
    assert _run(guard_bridge.process_reply_text(FakePlugin(), "原文")) == ["原文"]


def test_success_returns_processed():
    guard = FakeGuard({"status": "success", "output_list": ["第一条", "第二条"]})
    plugin = FakePlugin(FakeContext({"Astrbot_Amo_Guard": guard}))
    assert _run(guard_bridge.process_reply_text(plugin, "原文")) == ["第一条", "第二条"]


def test_status_not_success_falls_back():
    guard = FakeGuard({"status": "timeout", "output_list": []})
    plugin = FakePlugin(FakeContext({"Astrbot_Amo_Guard": guard}))
    assert _run(guard_bridge.process_reply_text(plugin, "原文")) == ["原文"]


def test_empty_output_falls_back():
    guard = FakeGuard({"status": "success", "output_list": []})
    plugin = FakePlugin(FakeContext({"Astrbot_Amo_Guard": guard}))
    assert _run(guard_bridge.process_reply_text(plugin, "原文")) == ["原文"]


def test_exception_falls_back():
    guard = FakeGuard(raises=True)
    plugin = FakePlugin(FakeContext({"Astrbot_Amo_Guard": guard}))
    assert _run(guard_bridge.process_reply_text(plugin, "原文")) == ["原文"]


def test_slow_guard_times_out():
    guard = FakeGuard(delay=5.0)
    plugin = FakePlugin(FakeContext({"Astrbot_Amo_Guard": guard}))
    assert _run(guard_bridge.process_reply_text(plugin, "原文", timeout_ms=0)) == ["原文"]


def test_blank_text_returns_as_is():
    plugin = FakePlugin(FakeContext({"Astrbot_Amo_Guard": FakeGuard()}))
    assert _run(guard_bridge.process_reply_text(plugin, "   ")) == ["   "]


def test_task_payload():
    guard = FakeGuard()
    plugin = FakePlugin(FakeContext({"Astrbot_Amo_Guard": guard}))
    _run(guard_bridge.process_reply_text(
        plugin, "你好", "group", timeout_ms=1500, task_type="format",
        protected=["[Body: Hunger=90]"]))
    task = guard.tasks[0]
    assert task["scene"] == "group"
    assert task["task_type"] == "format"
    assert task["timeout_ms"] == 1500
    assert task["raw_content"] == "你好"
    assert task["protected_blocks"] == ["[Body: Hunger=90]"]
    assert task["task_id"].startswith("reply-")


def test_find_by_module_marker():
    guard = FakeGuard()
    context = FakeContext(metas=[types.SimpleNamespace(
        name="Astrbot_Amo_Guard", module_path="plugins/amo_guard", star_cls=guard)])
    plugin = FakePlugin(context)
    assert _run(guard_bridge.process_reply_text(plugin, "原文")) == ["加工后的文本"]


def test_instance_without_process_task_is_ignored():
    class Dumb:
        pass

    context = FakeContext({"Astrbot_Amo_Guard": Dumb()})
    plugin = FakePlugin(context)
    assert _run(guard_bridge.process_reply_text(plugin, "原文")) == ["原文"]


def test_build_task_defaults():
    task = guard_bridge.build_task("原文")
    assert task["task_type"] == "polish"
    assert task["scene"] == "private"
    assert task["timeout_ms"] == guard_bridge.DEFAULT_TIMEOUT_MS
