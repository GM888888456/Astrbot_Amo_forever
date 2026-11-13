# -*- coding: utf-8 -*-
"""每 N 轮私聊压成一条「里程碑」长期记忆。

只做三件纯函数的事，方便单测：
- ``count_turns``：数这段里有几轮"他"说的话；
- ``transcript``：拼成 ``[他]/[我]`` 的转写（截断，避免喂爆上下文）；
- ``build_prompt``：给模型的指令（写事、约定、状态变化，不写相对时间）。
"""

from __future__ import annotations

import re

from typing import Any, Dict, Iterable, List

MILESTONE_KIND = "milestone"
DEFAULT_EVERY_TURNS = 20
DEFAULT_MIN_MESSAGES = 12
_MAX_LINE_CHARS = 120


def count_turns(messages: Iterable[Dict[str, Any]]) -> int:
    """一轮 = 他说的一句；机器人自己说的不算。"""
    return sum(1 for row in messages or [] if str(row.get("role") or "") != "bot")


def transcript(messages: Iterable[Dict[str, Any]], max_lines: int = 160) -> str:
    lines: List[str] = []
    for row in messages or []:
        content = str(row.get("content") or "").strip().replace("\n", " ")
        if not content:
            continue
        who = "我" if str(row.get("role") or "") == "bot" else "他"
        lines.append("[" + who + "] " + content[:_MAX_LINE_CHARS])
        if len(lines) >= max(1, int(max_lines)):
            break
    return "\n".join(lines)


def should_archive(messages: Iterable[Dict[str, Any]],
                   every_turns: int = DEFAULT_EVERY_TURNS,
                   min_messages: int = DEFAULT_MIN_MESSAGES) -> bool:
    rows = list(messages or [])
    if len(rows) < max(1, int(min_messages)):
        return False
    return count_turns(rows) >= max(1, int(every_turns))


def build_prompt(date_label: str, body: str) -> str:
    return (
        "下面是" + str(date_label or "最近") + "这段时间的聊天记录（[他] 是主人，[我] 是你自己）。\n"
        "请把它压成 2-4 句长期记忆：写清这段聊到的事、约定、双方的状态变化（工作/情绪/计划）。\n"
        "每句必须带主体：主人（他）的事用「他……」，你自己的事用「我……」；不要出现无主语的句子。\n"
        "身体状态必须分清是谁的：你自己的生病、难受、疼、生理期一律写「我……」；\n"
        "写成「他难受/他生病」等于说主人病了，不要把他的事和你的事弄混。\n"
        "只写事实，不写「今天/昨天/刚才」这类相对时间；不要复述原话；不确定的不要编。\n\n"
        + str(body or "")
    )


def normalize_subject(text: str) -> str:
    """每句补主语：无主语的句子默认记成「他」。

    摘要注入后如果是一句「被扇了耳光，脸疼」，模型会读成自己的经历；
    这里按句补成「他被扇了耳光，脸疼」。
    """
    out: List[str] = []
    for piece in re.split(r"(?<=[。！？!?；;])", str(text or "")):
        piece = piece.strip()
        if not piece:
            continue
        if not piece.startswith(("他", "我", "她", "用户")):
            piece = "他" + piece
        out.append(piece)
    return "".join(out)


def build_content(date_label: str, summary: str) -> str:
    return "【里程碑 " + str(date_label or "") + "】" + normalize_subject(summary)[:400]
