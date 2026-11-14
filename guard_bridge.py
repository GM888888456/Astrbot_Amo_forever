# -*- coding: utf-8 -*-
"""守护插件的文本后处理桥（执行文档第七节 / 阶段 5）。

终端把「已经清洗、已经润色」的回复交给守护做最后一道工序：
润色 / 断句 / 去重复述 / 表情裁剪 / 分片 / 空内容兜底。

三条硬约束（和 7.3 对齐）：

1. **守护不在、超时、报错、关掉** → 一律用原文，绝不因为后处理把话吞了；
2. 结构化块（``[Body: ...]`` 标签、事件 JSON）放进 ``protected_blocks`` 原样透传；
3. 最多等 ``timeout_ms``（默认 2 秒），超过就放行原文。

9.7.0 起终端不再自带分段引擎：发送一律走 ``deliver(task_type="format")``，
由守护完成润色、断句、分片与逐条发送；守护缺席时终端整条直发兜底。
"""

from __future__ import annotations

import asyncio
import time

GUARD_NAMES = ("Astrbot_Amo_Guard", "astrbot_plugin_amo_guard", "amo_guard")
GUARD_MARKERS = ("amo_guard",)

DEFAULT_TIMEOUT_MS = 2000
DEFAULT_TASK_TYPE = "polish"


def _instance(meta):
    """从 meta 上取插件实例；必须是能 ``process_task`` 的那个。"""
    if meta is None:
        return None
    for attr in ("star_cls", "instance", "star", "plugin"):
        value = getattr(meta, attr, None)
        if value is None:
            continue
        if (callable(getattr(value, "process_task", None))
                or callable(getattr(value, "deliver", None))):
            return value
    return None


def find_guard(context):
    """找守护插件；没装返回 None，不抛异常。"""
    if context is None:
        return None
    getter = getattr(context, "get_registered_star", None)
    if callable(getter):
        for name in GUARD_NAMES:
            try:
                meta = getter(name)
            except Exception:
                meta = None
            instance = _instance(meta)
            if instance is not None:
                return instance
    lister = getattr(context, "get_all_stars", None)
    if callable(lister):
        try:
            metas = list(lister() or [])
        except Exception:
            metas = []
        for meta in metas:
            marker = ((getattr(meta, "name", "") or "") + " "
                      + (getattr(meta, "module_path", "") or "")).lower()
            if not any(word in marker for word in GUARD_MARKERS):
                continue
            instance = _instance(meta)
            if instance is not None:
                return instance
    return None


def build_task(text, scene="private", *, task_id="", timeout_ms=DEFAULT_TIMEOUT_MS,
               task_type=DEFAULT_TASK_TYPE, protected=None) -> dict:
    return {
        "task_id": task_id or "reply-%d" % int(time.time() * 1000),
        "task_type": task_type or DEFAULT_TASK_TYPE,
        "scene": "group" if str(scene or "").lower() == "group" else "private",
        "raw_content": str(text or ""),
        "protected_blocks": list(protected or []),
        "timeout_ms": max(0, int(timeout_ms)),
    }


async def process_reply_text(plugin, text, scene="private", *,
                             timeout_ms=DEFAULT_TIMEOUT_MS,
                             task_type=DEFAULT_TASK_TYPE,
                             protected=None, guard=None) -> list:
    """把一段回复交给守护加工；任何异常都退回原文。"""
    text = str(text or "")
    if not text.strip():
        return [text]
    instance = guard if guard is not None else find_guard(getattr(plugin, "context", None))
    if instance is None:
        return [text]
    budget = max(0, int(timeout_ms))
    task = build_task(text, scene, timeout_ms=budget, task_type=task_type,
                      protected=protected)
    try:
        result = await asyncio.wait_for(
            instance.process_task(task), timeout=max(0.1, budget / 1000.0 + 0.3))
    except Exception:
        return [text]
    if not isinstance(result, dict) or result.get("status") != "success":
        return [text]
    pieces = [str(item) for item in (result.get("output_list") or []) if str(item).strip()]
    return pieces or [text]

async def deliver_reply(plugin, text, scene="private", umo="", *, quote_id=None,
                        group=False, task_type="format",
                        timeout_ms=DEFAULT_TIMEOUT_MS, guard=None):
    """把「要说什么」交给守护，由它分段并发出去。

    返回守护的结果 dict；守护没装 / 没有 deliver 能力 / 调用异常 → 返回 None，
    终端据此整条原文直发兜底（宁可长一点，也不能把话吞了）。
    """
    text = str(text or "")
    umo = str(umo or "")
    if not text.strip() or not umo:
        return None
    instance = guard if guard is not None else find_guard(getattr(plugin, "context", None))
    if instance is None:
        return None
    deliver = getattr(instance, "deliver", None)
    if not callable(deliver):
        return None
    task = {
        "task_id": "reply-%d" % int(time.time() * 1000),
        "task_type": task_type or "format",
        "scene": "group" if str(scene or "").lower() == "group" else "private",
        "umo": umo,
        "quote_id": quote_id,
        "group": bool(group),
        "raw_content": text,
        "timeout_ms": max(0, int(timeout_ms)),
    }
    try:
        task["typing"] = {
            "enable": bool(plugin.cfg_bool("typing_simulate", True)),
            "base_ms": int(plugin.cfg_int("typing_base_ms", 700)),
            "per_char_ms": int(plugin.cfg_int("typing_per_char_ms", 400)),
            "max_ms": int(plugin.cfg_int("typing_max_ms", 20000)),
        }
    except Exception:
        task["typing"] = {}
    try:
        return await asyncio.wait_for(
            deliver(task), timeout=max(45.0, int(timeout_ms) / 1000.0 + 40.0))
    except Exception:
        return None
