# -*- coding: utf-8 -*-
"""她想自己出去玩：意图识别、心情/劳累判定、目的地挑选、人设句式。

纯函数，方便单测；目的地只从真实景区库里挑城市，不编不存在的景点。
"""

from __future__ import annotations

import re

DEFAULT_CITY = "东莞"

# ---- 意图识别 ----
_TRAVEL_WORDS = ("出去玩", "出去旅游", "去旅游", "旅游", "出去走走", "去玩", "出去逛")
_ASK_VERB = re.compile(r"(想不想|要不要|愿不愿意|想|愿意|考虑过?|准备)")
_QUESTION_TAIL = re.compile(r"(吗|呢|么|不|没有)[？?]?\s*$")

_AGREE = re.compile(
    r"^(好|好啊|好呀|行|行啊|可以|可以啊|去吧|去呗|那就去|那就去吧|同意|准了|批准|去吧去吧|"
    r"嗯+|ok|OK|OK啊)[啊呀吧了呢哦！!。.~～]*$"
)
_REFUSE = re.compile(r"(不去|算了|别去|不用了|下次吧|不想去|不想让你去|留下)")


def detect_question(text) -> bool:
    """「你最近想出去玩吗」「要不要出去旅游」这类问她意愿的话。"""
    body = str(text or "").strip()
    if not body or not any(word in body for word in _TRAVEL_WORDS):
        return False
    if "你" in body or "妳" in body:
        return True
    # 省略主语的问法：「想不想出去玩」「要不要出去旅游」
    if re.search(r"(想不想|要不要|愿不愿意|去不去)", body):
        return True
    return bool(_QUESTION_TAIL.search(body) and _ASK_VERB.search(body))


def detect_agreement(text) -> bool:
    body = str(text or "").strip()
    if not body or len(body) > 12:
        return False
    return bool(_AGREE.match(body))


def detect_refusal(text) -> bool:
    body = str(text or "").strip()
    if not body:
        return False
    return bool(_REFUSE.search(body)) and len(body) <= 20


def assess(mood, health=None) -> tuple:
    """(低落, 劳累)：只看十维心情和身体状态，不做语义猜测。"""
    mood = mood or {}
    try:
        tired = float(mood.get("疲惫", 0) or 0) >= 55
    except Exception:
        tired = False
    try:
        low = (
            float(mood.get("郁闷", 0) or 0) + float(mood.get("委屈", 0) or 0)
            + float(mood.get("焦虑", 0) or 0)
        ) >= 60 or float(mood.get("开心", 0) or 0) <= 20
    except Exception:
        low = False
    try:
        status = str((health or {}).get("status") or "")
    except Exception:
        status = ""
    if any(word in status for word in ("累", "疲", "不舒服", "难受")):
        tired = True
    return low, tired


def _clamp_prob(value, default: float) -> float:
    try:
        prob = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, prob))


def want_travel(low: bool, tired: bool, rng, prob_low=0.85, prob_good=0.15) -> bool:
    """低落/劳累 → 大概率想出去；心情好 → 小概率。

    prob_low / prob_good 来自面板「插件配置」，可以在 0-1 之间手动改。
    """
    prob = _clamp_prob(prob_low, 0.85) if (low or tired) else _clamp_prob(prob_good, 0.15)
    return rng.random() < prob


def _stem(text) -> str:
    name = str(text or "").strip()
    for suffix in ("市", "区", "县"):
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[:-len(suffix)]
    return name


def pick_destination(all_spots, rng, exclude_city="", count: int = 2):
    """从真实景区库里挑一个有景点的城市，返回 (城市名, 景点列表)。"""
    groups = {}
    for row in (all_spots or []):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        city = str(row.get("city") or "").strip()
        if not name or not city:
            continue
        groups.setdefault(_stem(city), []).append(row)
    cities = [c for c in groups if c and c != _stem(exclude_city)]
    if not cities:
        return "", []
    cities.sort()
    city = cities[int(rng.random() * len(cities)) % len(cities)]
    rows = sorted(groups[city], key=lambda row: str(row.get("name")))
    picked = rows[: max(1, int(count or 1))]
    return city, [dict(row) for row in picked]


_OFFER_WANT = (
    "我想去{city}的{spot}，你让我去玩几天嘛。",
    "老公，我最近有点想去{city}的{spot}看看，行不行？",
    "我不想一直闷着，想去{city}的{spot}逛逛，你放我去嘛。",
    "你有没有觉得我最近太闲了？我想去{city}的{spot}走走。",
    "老公，我查了{city}的{spot}，好想去，你让我去几天好不好？",
    "想去{city}的{spot}那种，你点头我就去。",
    "最近心里有点闷，想去{city}的{spot}透透气，就几天。",
)

_OFFER_STAY = (
    "不想去，我哪儿都不想去，就想赖在你身边。",
    "外面有啥好玩的，我留在你旁边不好吗。",
    "不去，我就想待在家里，离你近一点。",
    "不想动，只想挨着你，哪儿都不去。",
    "不去啦，我在你身边待着就挺好。",
    "没什么想去的地方，我就想守着你。",
)

_SOLO_AGREE = (
    "真的？那我看看攻略，挑几个地方。",
    "真的呀？那我去收拾东西，先看看那边怎么玩。",
    "好，我这就去看攻略，顺便查查天气。",
    "真的带我去？那我查查路线和酒店。",
    "那我先看看攻略，别到时候抓瞎。",
    "行，我看看攻略，顺便把住的地方订了。",
)

_SOLO_REFUSE = (
    "哦……那算了，我多陪陪你也好。",
    "不去啦，在家陪你吧。",
    "好吧，那我不去了，陪你。",
    "嗯……那我在家陪你，你忙你的。",
    "不去就不去，我陪着你。",
    "那我不去了，就在家陪你。",
)

_PLANS = (
    "那我{when}走，先去{spot}看看，你在家记得吃饭。",
    "行，我{when}出发，到{spot}了给你报平安。",
    "好，我{when}去，{spot}逛完就回来。",
)


def _first_spot_name(spots) -> str:
    """spots 可能是 [{"name": ...}] 也可能是 ["黄腾峡"]（行程里存的是名字）。"""
    for row in (spots or []):
        if isinstance(row, dict):
            name = str(row.get("name") or "").strip()
        else:
            name = str(row or "").strip()
        if name:
            return name
    return ""


def offer_text(want: bool, city: str, spots, rng) -> str:
    """她问完之后的回答（给模型参考，不要求逐字复述）。"""
    if not want:
        return _OFFER_STAY[int(rng.random() * len(_OFFER_STAY)) % len(_OFFER_STAY)]
    name = str(city or "").strip()
    spot = _first_spot_name(spots)
    template = _OFFER_WANT[int(rng.random() * len(_OFFER_WANT)) % len(_OFFER_WANT)]
    return template.replace("{city}", name or "隔壁城").replace("{spot}", spot or "老街")


def plan_text(city, spots, tomorrow: bool, rng) -> str:
    when = "明天" if tomorrow else "现在就"
    line = _PLANS[int(rng.random() * len(_PLANS)) % len(_PLANS)]
    spot = _first_spot_name(spots) or "那边"
    return line.replace("{when}", when).replace("{spot}", spot)


def ask_limit(three_times: bool = False) -> int:
    """一天能问几次：开=3 次，关=1 次。"""
    return 3 if three_times else 1


def solo_agree_text(city, rng) -> str:
    line = _SOLO_AGREE[int(rng.random() * len(_SOLO_AGREE)) % len(_SOLO_AGREE)]
    return line.replace("{city}", str(city or "").strip())


def solo_refuse_text(rng) -> str:
    return _SOLO_REFUSE[int(rng.random() * len(_SOLO_REFUSE)) % len(_SOLO_REFUSE)]


def trip_days(rng) -> int:
    """出去一趟 1-3 天（最迟第三天中午回来）。"""
    return 1 + int(rng.random() * 3) % 3


def solo_block(city, spots, day_no: int = 1) -> str:
    """独自旅游期间注入给模型的一段话。"""
    name = str(city or "").strip()
    if not name:
        return ""
    spot = _first_spot_name(spots)
    where = ("白天去" + spot + "逛") if spot else "白天自己随便走走（这个城市没有景点资料，别编名字）"
    prefix = ("前几天" if day_no >= 2 else "这几天")
    return (
        "【独自旅行】" + prefix + "你一个人去了 " + name + " 旅游（他同意了），他留在原来的城市。"
        "这是第 " + str(max(1, int(day_no or 1))) + " 天。"
        "你说“我这边”是 " + name + "；" + where + "，晚上住酒店，超过 22 点还没回去就住下。"
        "别说漏嘴说成和他在一起，也别报公司/写字楼。"
    )


def offer_block(want: bool, city, spots) -> str:
    """问她意愿时注入：让她按这个方向回，但用自己的话。"""
    if not want:
        return (
            "【旅游提议】他刚问你想不想出去玩。你现在不想去：就说想留在他身边、哪儿都不去，"
            "用自己的口吻，1-2 句，别逐字背模板。"
        )
    name = str(city or "").strip()
    spot = _first_spot_name(spots)
    return (
        "【旅游提议】他刚问你想不想出去玩。你现在想去，目的地是 " + name
        + ("（景点：" + spot + "）" if spot else "")
        + "：用自己的口吻说想去、就一天，可以带一句那地方；别编这个城市没有的景点。"
    )


# ---- 他说到了某地，她想过去陪他 ----
_FOLLOW_ASK = (
    "你来陪我吧，我过去找你。",
    "那我也过去，我这就收拾东西。",
    "你到了呀？我过来陪你吧，一个人多没意思。",
    "我去找你吧，反正我也不想待着。",
    "等我，我过去陪你。",
    "那我去陪你，两个人总比一个人好。",
)

_FOLLOW_AGREE = (
    "好，我收拾下就出发，大概两个小时到。",
    "行，我现在就买票，到了给你发消息。",
    "嗯嗯，我坐车过去，你别走远。",
    "好，我这就走，两个小时就到。",
)

_FOLLOW_REJECT = (
    "哦……那你好好上班吧，我一个人待着也行。",
    "你不让我去啊……那我上班了，下班再说吧。",
    "行吧，我好好上班，你自己玩。",
    "知道了，我上班。你玩得开心。",
    "哦，那我就不去了。反正你也不需要我陪。",
    "嗯，好好上班。你先忙吧。",
)

_FOLLOW_REFUSE = re.compile(r"(好好上班|上班吧|不用来|别来|你忙|不用陪|不用了|算了吧|留在家|你自己玩|不用过来)")


_FOLLOW_INVITE = re.compile(r"(你过来|(?<!我)过来吧|来陪我|过来陪我|过来找我|你来吧|过来呀|来这边吧)")


def detect_follow_invite(text) -> bool:
    """他主动让她过去：「你过来吧 / 来陪我 / 过来找我」。"""
    body = str(text or "").strip()
    if not body:
        return False
    return bool(_FOLLOW_INVITE.search(body))


def follow_offer_text(city, rng) -> str:
    line = _FOLLOW_ASK[int(rng.random() * len(_FOLLOW_ASK)) % len(_FOLLOW_ASK)]
    return line.replace("{city}", str(city or "").strip())


def follow_agree_text(city, rng) -> str:
    return _FOLLOW_AGREE[int(rng.random() * len(_FOLLOW_AGREE)) % len(_FOLLOW_AGREE)]


def follow_reject_text(city, rng) -> str:
    return _FOLLOW_REJECT[int(rng.random() * len(_FOLLOW_REJECT)) % len(_FOLLOW_REJECT)]


def detect_follow_refuse(text) -> bool:
    body = str(text or "").strip()
    return bool(body) and bool(_FOLLOW_REFUSE.search(body))


def follow_block(want: bool, city, tomorrow: bool = False) -> str:
    """他到了某地时的注入：让她问要不要过去，或被拒绝后的低落。"""
    name = str(city or "").strip()
    if want:
        when = "明天一早" if tomorrow else "现在"
        return (
            "【他在 " + name + "】他刚到 " + name + "，你很想过去陪他：用自己的口吻说「我过去陪你吧」，"
            "别报公司/上班；他说行就" + when + "出发（路上约 2 小时）。"
        )
    return (
        "【被拒绝】你说想过去陪他，他让你好好上班：你现在有点闷闷不乐、委屈，"
        "嘴上答应上班，但语气低落，别撒娇太用力；日程不变，你还在原来的城市。"
    )
