"""从用户说的话里识别「今天要改的日程」，交给 Amo 去改那一段。

只认明确改变当天行程的说法（去接她 / 提前回家 / 不去了 / 出去吃），
不认泛泛的闲聊。改完会写回 schedule 表，生图和状态都会跟着变。
"""
from __future__ import annotations

import datetime

# (触发词, 新的活动, 分类, 需要的时间推断方式)
_RULES = [
    {
        "keys": ("回来吧", "快回来", "回家吧", "回来呀", "别逛了", "别玩了", "别转了",
                 "回酒店", "回酒店吧", "别在外面", "早点回来"),
        "activity": "收拾一下往回走，回家",
        "place": "家",
        "category": "rest",
        "after": "now",
    },
    {
        "keys": ("过来吧", "过来", "来我这儿", "来陪我", "来找我", "来我这里"),
        "activity": "往他那儿去",
        "place": "他那儿",
        "category": "rest",
        "after": "now",
    },
    {
        "keys": ("去超市", "去趟超市", "去商场", "去咖啡店", "去公园", "去买点"),
        "activity": "按他说的换个地方",
        "place": "外面",
        "category": "rest",
        "after": "now",
    },
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


def _hhmm_to_min(value) -> int:
    try:
        hour, minute = str(value).split(":")[:2]
        return int(hour) * 60 + int(minute)
    except Exception:
        return -1


def _min_to_hhmm(value: int) -> str:
    value = max(0, min(24 * 60, int(value)))
    return "%02d:%02d" % (value // 60, value % 60)


HOME_WORDS = ("家", "回家", "家里", "小窝", "房间", "宿舍")


def _is_home(place: str) -> bool:
    text = str(place or "")
    return any(word in text for word in HOME_WORDS)


def _arrive(place: str, hour: int):
    """到达之后干什么：同一处地点轮着写，别每个小时都一句话。"""
    place = str(place or "").strip() or "家"
    if _is_home(place):
        options = ("到家歇一会儿，换身舒服的衣服", "窝着刷手机", "收拾一下屋子")
        return options[hour % len(options)], place, "rest"
    options = ("在%s慢慢逛" % place, "在%s待着看看" % place, "在%s坐一会儿" % place)
    return options[hour % len(options)], place, "play"


def apply_change(items: list[dict], change: dict, now: datetime.datetime,
                 transition_minutes: int = 30, hold_hours: int = 3) -> list[dict]:
    """按他的话改日程，但**先让她走过去**：不能上一秒市场、下一秒到家。

    做法：当前这一格拆成三段——
    1. 原活动（到此刻为止）；
    2. 路上一段（默认 30 分钟，可配）；
    3. 到达后的新活动（本格剩下的时间，以及之后 hold_hours 小时内的格子）。
    睡觉、吃饭这两类格子不覆盖，免得把她一天该有的节奏抹平。
    """
    if not items or not change:
        return items
    target_place = str(change.get("place") or "").strip()
    if not target_place:
        return items
    category = str(change.get("category") or "rest")
    cur = now.hour * 60 + now.minute
    try:
        travel = max(5, int(transition_minutes or 30))
    except (TypeError, ValueError):
        travel = 30
    try:
        hold = max(1, int(hold_hours or 3)) * 60
    except (TypeError, ValueError):
        hold = 180
    # 目标本来就是路上（例如「来接我」）就不用再加一段过渡
    if target_place in ("路上", "路上骑车", "车里"):
        travel = 0
    if category == "sleep":
        travel = 0
    arrive = min(cur + travel, 24 * 60)
    sleeping = category == "sleep"
    arrival_text = str(change.get("activity") or "").strip()
    out = []
    arrived_once = False
    changed = False
    for it in items:
        row = dict(it)
        start = _hhmm_to_min(row.get("start"))
        end = _hhmm_to_min(row.get("end"))
        if start < 0 or end <= start:
            out.append(row)
            continue
        if end <= cur:
            out.append(row)
            continue
        keep_until = min(cur, end)
        if start <= cur < end:
            # 1) 原来的活动到此刻
            if keep_until > start:
                head = dict(row)
                head["end"] = _min_to_hhmm(keep_until)
                out.append(head)
            # 2) 在路上
            road_end = min(arrive, end)
            if road_end > cur:
                out.append({
                    "start": _min_to_hhmm(cur), "end": _min_to_hhmm(road_end),
                    "activity": ("收拾一下往家走，在路上" if _is_home(target_place)
                                 else "往%s去，在路上" % target_place),
                    "place": "路上", "category": "commute", "zone": "road",
                    "mood": row.get("mood") or "平静", "effects": {}, "transition": True,
                })
            # 3) 到达之后
            if end > arrive:
                if sleeping:
                    text, place, cat = "睡觉", "家", "sleep"
                elif not arrived_once and arrival_text:
                    text, place, cat = arrival_text, target_place, category
                    arrived_once = True
                else:
                    text, place, cat = _arrive(target_place, (arrive // 60) % 24)
                out.append({
                    "start": _min_to_hhmm(arrive), "end": _min_to_hhmm(end),
                    "activity": text, "place": place, "category": cat,
                    "zone": row.get("zone") or "", "mood": row.get("mood") or "平静",
                    "effects": {}, "arrived": True,
                })
            changed = True
            continue
        # 未来的格子：到达前是路上，到达后 hold_hours 内是目的地
        if start < arrive:
            out.append({
                "start": _min_to_hhmm(start), "end": _min_to_hhmm(min(arrive, end)),
                "activity": ("收拾一下往家走，在路上" if _is_home(target_place)
                             else "往%s去，在路上" % target_place),
                "place": "路上", "category": "commute", "zone": "road",
                "mood": row.get("mood") or "平静", "effects": {}, "transition": True,
            })
            if end > arrive:
                if sleeping:
                    text, place, cat = "睡觉", "家", "sleep"
                elif not arrived_once and arrival_text:
                    text, place, cat = arrival_text, target_place, category
                    arrived_once = True
                else:
                    text, place, cat = _arrive(target_place, (arrive // 60) % 24)
                out.append({
                    "start": _min_to_hhmm(arrive), "end": _min_to_hhmm(end),
                    "activity": text, "place": place, "category": cat,
                    "zone": row.get("zone") or "", "mood": row.get("mood") or "平静",
                    "effects": {}, "arrived": True,
                })
            changed = True
            continue
        if sleeping:
            row["activity"] = "睡觉"
            row["place"] = "家"
            row["category"] = "sleep"
            row["arrived"] = True
            changed = True
            out.append(row)
            continue
        if (start < arrive + hold
                and str(row.get("category") or "") not in ("sleep", "meal")
                and not _is_home(str(it.get("place") or "")) == _is_home(target_place)):
            text, place, cat = _arrive(target_place, (start // 60) % 24)
            row["activity"] = text
            row["place"] = place
            row["category"] = cat
            row["arrived"] = True
            changed = True
        out.append(row)
    return out if changed else items
