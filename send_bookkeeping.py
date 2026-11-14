# -*- coding: utf-8 -*-
"""守护把话发出去之后，终端这边的收尾动作。

分段引擎拆掉后，这四件事只剩一份实现：
关打字状态、写会话历史、写自己的消息表、通知心流「这一轮回过了」。
"""

from __future__ import annotations

import json
import time

from astrbot.api import logger


async def set_typing(event, typing: bool) -> None:
    """向平台发送「正在输入」状态；仅 aiocqhttp (QQ) 支持，其余静默忽略。"""
    try:
        if event.get_platform_name() != "aiocqhttp":
            return
        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
        if not isinstance(event, AiocqhttpMessageEvent):
            return
        user_id = event.message_obj.sender.user_id
        if not user_id:
            return
        await event.bot.api.call_action(
            "set_input_status",
            user_id=user_id,
            event_type=1 if typing else 0,
        )
    except Exception:
        pass


async def save_to_conversation_history(context, event, content: str) -> None:
    """把合并后的完整回复写进对话历史，保证上下文连贯。"""
    try:
        conv_mgr = getattr(context, "conversation_manager", None)
        if not conv_mgr:
            return
        umo = event.unified_msg_origin
        curr_cid = await conv_mgr.get_curr_conversation_id(umo)
        if not curr_cid:
            return
        conversation = await conv_mgr.get_conversation(umo, curr_cid)
        if not conversation:
            return
        try:
            history = json.loads(conversation.history) if isinstance(conversation.history, str) else conversation.history
        except (json.JSONDecodeError, TypeError):
            history = []
        user_content = getattr(event, "message_str", "")
        if user_content and (not history or history[-1].get("role") != "user"):
            history.append({"role": "user", "content": user_content})
        history.append({"role": "assistant", "content": content})
        await conv_mgr.update_conversation(
            unified_msg_origin=umo,
            conversation_id=curr_cid,
            history=history,
        )
    except Exception as exc:
        logger.error("[amo] 保存对话历史失败: %s" % exc)


def notify_heartflow(plugin, event, text: str = "") -> None:
    """手工发送后主动清除「判断暂停」，否则她会哑到超时。"""
    try:
        heartflow = getattr(plugin, "heartflow", None)
        marker = getattr(heartflow, "mark_replied", None)
        if callable(marker):
            marker(getattr(event, "unified_msg_origin", ""), text)
    except Exception:
        pass


async def after_external_send(plugin, event, text: str) -> None:
    """别的模块（守护）已经把话发出去时，这里只补记账，不再发一遍。"""
    text = str(text or "")
    if not text.strip():
        return
    try:
        await set_typing(event, False)
    except Exception:
        pass
    try:
        await save_to_conversation_history(getattr(plugin, "context", None), event, text)
    except Exception:
        pass
    try:
        remember = getattr(plugin, "_remember_bot_message", None)
        if callable(remember):
            remember(getattr(event, "unified_msg_origin", ""), text)
    except Exception:
        pass
    try:
        notify_heartflow(plugin, event, text)
    except Exception:
        pass
    try:
        getattr(plugin, "_last_reply_at", {})[getattr(event, "unified_msg_origin", "")] = time.time()
    except Exception:
        pass
