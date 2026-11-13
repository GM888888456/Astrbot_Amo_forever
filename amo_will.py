# -*- coding: utf-8 -*-
"""她的「意愿」判定：他花钱提的行程请求，以及私密照片请求。

两条原则：

1. **判定在本地、看心情**，不叫模型做决定；模型只负责把结果说得像她。
2. **写真话**：拒绝就是拒绝，答应之后日程要真的改，而且要有一个「收拾 → 路上 → 到」的过程，
   不能上一秒在市场、下一秒躺家里。

私密照片有硬边界：只认成年、单人、不裸露；越界的字眼直接拒，不进判定。
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 心情
# ---------------------------------------------------------------------------

#: 心情分越高越「不想动」/「不想配合」的维度
BAD_MOOD_KEYS = ("生气", "暴躁")
TIRED_MOOD_KEYS = ("疲惫",)
GOOD_MOOD_KEYS = ("开心", "兴奋", "依恋")


def _score(mood, keys) -> float:
    if not isinstance(mood, dict):
        return 0.0
    total = 0.0
    for key in keys:
        try:
            total += float(mood.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return total


def mood_brief(mood) -> dict:
    """把十维心情压成判定要用的几个数。"""
    return {
        "bad": _score(mood, BAD_MOOD_KEYS),
        "tired": _score(mood, TIRED_MOOD_KEYS),
        "good": _score(mood, GOOD_MOOD_KEYS),
    }


# ---------------------------------------------------------------------------
# 一、行程请求（他打赏之后提的「回来吧 / 去某某地方」）
# ---------------------------------------------------------------------------

#: 「回来」类说法
HOME_KEYS = ("回来", "回来吧", "回家", "回来陪我", "别逛了", "别玩了", "早点回来",
             "回我这边", "回来找我", "回窝里", "回家吧", "回来嘛", "收摊吧")
#: 「来找我 / 去某地」类说法
GO_KEYS = ("来找我", "过来找我", "来我这儿", "来我这里", "来我这", "到我这儿",
           "过来吧", "来陪我", "去看", "去趟", "去一下", "去逛逛", "去吃饭",
           "去公园", "去咖啡", "去商场", "去公司接我")


def detect_trip_request(text) -> dict | None:
    """他是不是在要求她改变当下行程。只认明确的动身/返回说法。"""
    raw = str(text or "").strip()
    if not raw:
        return None
    for key in HOME_KEYS:
        if key in raw:
            return {"target": "home", "place": "家", "raw": raw, "key": key}
    for key in GO_KEYS:
        if key in raw:
            # 「去XX」把 XX 抠出来当目的地
            match = re.search(r"去([^，,。！!？?]{1,12})", raw)
            place = match.group(1).strip() if match else "他那边"
            return {"target": "out", "place": place, "raw": raw, "key": key}
    return None


def decide_trip_request(mood, affection: float = 0.0, relation: str = "普通",
                        current_place: str = "", target_place: str = "家") -> dict:
    """她愿不愿意去。

    返回 ``{"accept": bool, "angry": bool, "reason": str}``：

    - 正在气头上：不去，而且直接怼；
    - 已经在他说的地方：不用动，软软地应一句；
    - 累了一天又叫他回家：愿意（本来就想歇）；
    - 心情好、依恋高、关系是相恋：愿意；
    - 其余：找个借口不折腾。
    """
    brief = mood_brief(mood)
    here = str(current_place or "").strip()
    target = str(target_place or "").strip() or "家"
    if here and target and (here == target or target in here):
        return {"accept": True, "angry": False, "reason": "本来就在这儿"}
    if brief["bad"] >= 110:
        return {"accept": False, "angry": True, "reason": "正在气头上，不想动"}
    if target == "家" and brief["tired"] >= 65:
        return {"accept": True, "angry": False, "reason": "本来也累了，正好回去"}
    if relation == "相恋" and (brief["good"] >= 90 or affection >= 60):
        return {"accept": True, "angry": False, "reason": "想见他"}
    if brief["good"] >= 120:
        return {"accept": True, "angry": False, "reason": "心情不错，愿意跑一趟"}
    if brief["tired"] >= 80:
        return {"accept": False, "angry": False, "reason": "太累了，不想折腾"}
    if relation == "相恋":
        return {"accept": True, "angry": False, "reason": "他难得开口，答应他"}
    return {"accept": False, "angry": False, "reason": "又不是他什么人，犯不上这么折腾"}


#: 收拾 / 路上 / 到达 的文案池（按时间顺序拼，不跳步）
PACK_LINES = ("收拾东西准备走", "把买的东西塞进包里", "结账，拎着袋子往外走",
              "跟店里的人打个招呼，起身")
ROAD_LINES = ("在路上，坐车往回赶", "挤在地铁上，站着刷手机",
              "打车回去，看着窗外的街", "在车上眯了一会儿")
ARRIVE_HOME = ("到家了，鞋一踢先瘫在沙发上", "进门先开窗通风，换身舒服的衣服",
               "到家，把东西放下长长舒一口气")
ARRIVE_OUT = ("到了{place}，站在门口找他", "到{place}附近，给他发消息说到了")


def build_transition(current: dict, target: dict, now_hour: int,
                     home_place: str = "家", far: bool = False) -> list[dict]:
    """把「现在就到家」拆成一段过程：收拾 → 路上 → 到达。

    返回每小时一条的日程，从 ``now_hour`` 开始覆盖，**不改已经过去的时段**。
    车程按 far 决定 1 或 2 小时，所以不会出现上一秒在市场、下一秒躺家里。
    """
    now_hour = max(0, min(23, int(now_hour)))
    kind = str((target or {}).get("target") or "home")
    place = str((target or {}).get("place") or home_place or "家")
    road_hours = 2 if far else 1
    plan = []
    hour = now_hour
    # 1. 收拾
    plan.append((hour, PACK_LINES[hour % len(PACK_LINES)], str(current.get("place") or ""),
                 str(current.get("zone") or "street"), "life"))
    hour += 1
    # 2. 路上
    for index in range(road_hours):
        if hour > 23:
            break
        plan.append((hour, ROAD_LINES[(hour + index) % len(ROAD_LINES)], "路上", "road", "commute"))
        hour += 1
    # 3. 到达
    if hour <= 23:
        if kind == "home":
            plan.append((hour, ARRIVE_HOME[hour % len(ARRIVE_HOME)], home_place, "home", "rest"))
        else:
            plan.append((hour, ARRIVE_OUT[hour % len(ARRIVE_OUT)].format(place=place),
                         place, "street", "play"))
        hour += 1
    # 4. 之后先按「待着」铺到当天结束，避免出现空洞
    while hour <= 23:
        if kind == "home":
            plan.append((hour, "在家待着", home_place, "home", "rest"))
        else:
            plan.append((hour, "在外面逛逛", place, "street", "play"))
        hour += 1
    return [
        {
            "start": "%02d:00" % h,
            "end": "24:00" if h == 23 else "%02d:00" % (h + 1),
            "activity": activity,
            "place": place_text,
            "zone": zone,
            "category": category,
        }
        for h, activity, place_text, zone, category in plan
    ]


# ---------------------------------------------------------------------------
# 二、私密照片（内衣 / 制服 / 指定姿势）
# ---------------------------------------------------------------------------

#: 越界词：出现就整条拒，不进判定，也不写进记忆
HARD_BLOCK = ("未成年", "萝莉", "幼女", "儿童", "裸体", "全裸", "露点", "性交",
              "做爱", "口交", "插入", "自慰", "射")

#: 内衣类
LINGERIE_WORDS = ("内衣", "蕾丝", "情趣", "吊带", "睡衣", "丝袜", "丁字", "睡裙",
                  "性感", "贴身")
#: 制服类
COSTUME_WORDS = ("制服", "jk", "jk制服", "护士服", "女仆装", "ol装", "旗袍",
                 "校服", "泳装", "比基尼", "情趣制服")
#: 请求词
ASK_WORDS = ("拍", "照片", "发", "看看", "来一张", "来张", "自拍", "给我看")


def detect_intimate(text) -> dict | None:
    """他要的是不是「私密照片」。越界的直接返回 blocked。"""
    raw = str(text or "").strip()
    if not raw:
        return None
    if any(word in raw for word in HARD_BLOCK):
        return {"blocked": True, "raw": raw, "reason": "这条越界了"}
    if not any(word in raw for word in ASK_WORDS):
        return None
    kinds = []
    if any(word in raw for word in LINGERIE_WORDS):
        kinds.append("lingerie")
    if any(word in raw.lower() for word in COSTUME_WORDS):
        kinds.append("costume")
    if not kinds:
        return None
    detail = ""
    match = re.search(r"穿([^，,。！!？?]{1,20})", raw)
    if match:
        detail = match.group(1).strip()
    return {"blocked": False, "kinds": kinds, "detail": detail, "raw": raw}


def judge_intimate(mood, affection: float = 0.0, relation: str = "普通",
                   asked_before: bool = False) -> dict:
    """羞不羞、给不给。

    顺序（按用户定的规矩）：

    1. 气头上：连判定都不做，直接开怼；
    2. 第一次要：害羞拒绝，并且记住「他问过」；
    3. 再要一次：心情平静或好 → 拍；心情不行 → 还是拒。
    """
    brief = mood_brief(mood)
    if brief["bad"] >= 110:
        return {"action": "refuse_angry", "allow": False, "remember": False,
                "reason": "正烦着，这句让她炸了"}
    if not asked_before:
        return {"action": "refuse_shy", "allow": False, "remember": True,
                "reason": "第一次提，先害羞一下"}
    if relation != "相恋":
        return {"action": "refuse_shy", "allow": False, "remember": False,
                "reason": "关系还没到那一步"}
    if brief["bad"] >= 70 or brief["tired"] >= 90:
        return {"action": "refuse_tired", "allow": False, "remember": False,
                "reason": "心情一般，不想拍"}
    if brief["good"] >= 60 or affection >= 55:
        return {"action": "allow", "allow": True, "remember": True,
                "reason": "心情不错，愿意给他看"}
    return {"action": "allow", "allow": True, "remember": True,
            "reason": "平静的时候，答应了"}


#: 无论怎么答应，这层边界都写进提示词
INTIMATE_LIMITS = (
    "成年女性，单人，室内私密空间；只拍穿着衣物的人像，"
    "不裸露、不出现性器官、不做性行为动作；不出现第二个人、不出现摄影师"
)


def build_intimate_prompt(detected: dict, place: str = "") -> str:
    """把「内衣 / 制服 / 姿势」拼成生图提示词（自拍，带边界）。"""
    detail = str((detected or {}).get("detail") or "").strip()
    kinds = (detected or {}).get("kinds") or []
    parts = ["自拍（手机前置，近景半身，直视镜头，画面里只有我自己，不是别人拿手机拍）"]
    if detail:
        parts.append("穿着" + detail)
    elif "lingerie" in kinds:
        parts.append("穿着贴身内衣")
    elif "costume" in kinds:
        parts.append("穿着制服")
    if "lingerie" in kinds:
        parts.append("室内暖光，床沿或衣柜前，氛围私密")
    if "costume" in kinds:
        parts.append("室内，服装细节清楚")
    if place:
        parts.append("在" + place)
    parts.append("表情有点害羞，脸红、避开一下镜头又看回来")
    parts.append(INTIMATE_LIMITS)
    return "，".join(parts)
