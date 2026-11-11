# -*- coding: utf-8 -*-
"""会话归属：这几段聊天是群里的，还是只属于他们俩的。

里程碑、每日总结、日记都是**按人归纳**的产物，写进记忆时是 ``scope='private'``；
如果喂给模型的聊天里混进了群聊，群友说的话就会被压成「他……」，变成她只在私聊里
记得的事（反过来，群聊自己的记忆由正常聊天链路按 ``scope='group'`` 写，不用在这里补）。

这里只放纯函数，方便单测。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

# AstrBot 的 umo 形如 ``platform:MessageType:session_id``，
# 例如 ``aiocqhttp:FriendMessage:302578963`` / ``lark:GroupMessage:oc_xxx``。
GROUP_MARK = "GroupMessage"


def is_group_umo(umo: Any) -> bool:
    """这个会话是群聊吗。"""
    return GROUP_MARK in str(umo or "")


def is_group_row(row: Any) -> bool:
    """这行消息来自群聊吗。"""
    if not isinstance(row, dict):
        return False
    return is_group_umo(row.get("umo"))


def private_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """只留私聊的行。

    老版数据插件可能不回 ``umo`` 字段：那种行无从判断，按私聊保留
    （宁可多留，也不凭空丢掉历史）。真正的群聊行一定带 ``umo``。
    """
    out: List[Dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        umo = row.get("umo")
        if umo and is_group_umo(umo):
            continue
        out.append(row)
    return out
