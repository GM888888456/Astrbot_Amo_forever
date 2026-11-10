"""从用户说的话里识别「今天要改的日程」，交给 Amo 去改那一段。

只认明确改变当天行程的说法（去接她 / 提前回家 / 不去了 / 出去吃），
不认泛泛的闲聊。改完会写回 schedule 表，生图和状态都会跟着变。
"""
from __future__ import annotations

import datetime
import re

# (触发词, 新的活动, 分类, 需要的时间推断方式)
_RULES = [
    {
        "keys": ("来接我", "来接下我", "接我一下", "过来接我", "开车来接", "来接一下",
                 "来接你", "去接你", "接你下班", "接你回去"),
        "activity": "他开车来接我，一起回家",
        "place": "路上",
        "category": "commute",
        "after": "下班",     # 从下班那段开始改
    },
    {
        "keys": ("早点回家", "提前回家", "先回去了", "想回家"),
        "activity": "提前收拾东西回家",
        "place": "家",
        "category": "rest",
        "after": "now",
    },
    {
        "keys": ("不去了", "不去了吧", "不加班了", "别加班了"),
        "activity": "不去了，改回家待着",
        "place": "家",
        "category": "rest",
        "after": "now",
    },
    {
        "keys": ("一起吃", "去吃", "出来吃", "出去吃", "请你吃饭"),
        "activity": "和他一起出去吃饭",
        "place": "外面",
        "category": "meal",
        "after": "now",
    },
    {
        "keys": ("一起睡", "早点睡", "睡吧", "该睡了", "去睡觉"),
        "activity": "上床睡觉",
        "place": "家",
        "category": "sleep",
        "after": "now",
    },
]


def detect_schedule_change(text: str) -> dict | None:
    """返回 {activity, place, category, from_now: bool} 或者 None。"""
    raw = str(text or "")
    if not raw:
        return None
    for rule in _RULES:
        if any(k in raw for k in rule["keys"]):
            return {
                "activity": rule["activity"],
                "place": rule["place"],
                "category": rule["category"],
                "from_now": rule.get("after") == "now",
            }
    return None


def apply_change(items: list[dict], change: dict, now: datetime.datetime) -> list[dict]:
    """把日程里从「此刻」往后到该段结束的部分改掉。"""
    if not items or not change:
        return items
    cur = now.strftime("%H:%M")
    out = []
    changed = False
    sleeping = change.get("category") == "sleep"
    for it in items:
        start = str(it.get("start") or "")
        end = str(it.get("end") or "")
        if changed and sleeping:
            # 说了要睡：后面到第二天早上的整段都改成睡觉
            if end <= "06:00" or start >= cur:
                it = dict(it)
                it["activity"] = "睡觉"
                it["place"] = "家"
                it["category"] = "sleep"
                out.append(it)
                continue
        if not changed and start and end and start <= cur < end:
            # 当前这段：从此刻起改成新的活动
            it = dict(it)
            it["start"] = cur
            it["activity"] = change["activity"]
            it["place"] = change.get("place") or it.get("place")
            it["category"] = change.get("category") or it.get("category")
            changed = True
            out.append(it)
            continue
        out.append(it)
    return out
