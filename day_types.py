"""日子类型：每天先掷一个「今天是哪种日子」，再按它生成日程。

移植自 dsh-daily-schedule 的 DAY_TYPES 设计（上班日 / 休息日 / 外出日 /
宅家日 / 加班日 / 摸鱼日），按权重随机，工作日与周末各抽各的池子。
"""
from __future__ import annotations

import random

DAY_TYPES = [
    {
        "id": "workday",
        "name": "上班日",
        "enabled": True,
        "weight": 5,
        "scope": "weekday",
        "guide": "常规上班日，两点一线：起床洗漱、通勤去上班，白天在单位干活，"
                 "中午吃饭，傍晚下班通勤回家，晚上吃饭、有一点自己的时间，然后睡觉。",
    },
    {
        "id": "restday",
        "name": "休息日",
        "enabled": True,
        "weight": 4,
        "scope": "weekend",
        "guide": "不上班，以待在家里为主：睡个懒觉，在家收拾、看书看剧，"
                 "出门散散步，去附近餐馆好好吃一顿，晚上在家放松。",
    },
    {
        "id": "outing",
        "name": "外出日",
        "enabled": True,
        "weight": 3,
        "scope": "weekend",
        "guide": "出门玩一整天：逛街、看展、去公园或海边、找好吃的店，"
                 "傍晚或晚上才回家，回家时有点累但很满足。"
                 "这一天大部分时间都在外面，不在家也不在单位。",
    },
    {
        "id": "homebody",
        "name": "宅家日",
        "enabled": True,
        "weight": 1,
        "scope": "any",
        "guide": "哪儿也不想去，几乎一整天窝在家：睡到中午，点外卖，"
                 "追剧看书，作息有点乱，晚上反而精神。",
    },
    {
        "id": "overtime",
        "name": "加班日",
        "enabled": True,
        "weight": 1,
        "scope": "weekday",
        "guide": "活多的一天：照常上班，但一直忙到很晚，午饭晚饭都随便对付，"
                 "回家已经很累，倒头就睡。",
    },
    {
        "id": "slacking",
        "name": "摸鱼日",
        "enabled": True,
        "weight": 1,
        "scope": "weekday",
        "guide": "名义上在上班，实际上一直找机会摸鱼：开小差、刷手机、"
                 "去茶水间找零食，但下班前会把要紧的事赶完。",
    },
]


def normalize_day_types(raw) -> list[dict]:
    src = raw if isinstance(raw, list) and raw else DAY_TYPES
    out, seen = [], set()
    for item in src[:30]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:20]
        ident = str(item.get("id") or name).strip()[:32]
        if not name or ident in seen:
            continue
        seen.add(ident)
        try:
            weight = max(0.0, min(50.0, float(item.get("weight", 1) or 0)))
        except Exception:
            weight = 1.0
        scope = str(item.get("scope") or "any")
        if scope not in ("weekday", "weekend", "any"):
            scope = "any"
        out.append({
            "id": ident,
            "name": name,
            "enabled": bool(item.get("enabled", True)),
            "weight": weight,
            "scope": scope,
            "guide": str(item.get("guide") or "").strip()[:300],
        })
    return out or list(DAY_TYPES)


def pick_day_type(day_types: list[dict], is_weekend: bool, seed: str) -> dict:
    """按权重抽一个今天的类型；同一个种子结果稳定。"""
    pool = []
    for item in day_types:
        if not item.get("enabled", True):
            continue
        scope = item.get("scope", "any")
        if scope == "weekday" and is_weekend:
            continue
        if scope == "weekend" and not is_weekend:
            continue
        if float(item.get("weight") or 0) <= 0:
            continue
        pool.append(item)
    if not pool:
        return {"id": "workday", "name": "上班日", "guide": ""}
    total = sum(float(x["weight"]) for x in pool)
    rng = random.Random(seed)
    point = rng.random() * total
    acc = 0.0
    for item in pool:
        acc += float(item["weight"])
        if point <= acc:
            return item
    return pool[-1]
