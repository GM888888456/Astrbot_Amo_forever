# -*- coding: utf-8 -*-
"""礼物引擎。

聊天里的虚拟礼物：她随口说「好想要 / 好喜欢」的东西记进心愿单；主人回一句
「送给你 / 买给你 / 那条围巾送你」，她下一句就会具体地收下，之后一直记得。

和主脑的关系：
- ``build_hint()`` 由 ``_dynamic_context()`` 调用，把「他刚送了你 X」拼进 ``<amo_state>``；
- ``observe_reply()`` 由 ``on_decorating_result()`` 调用，异步抽心愿，不阻塞她说话；
- 收礼物时顺手 ``state.nudge()`` 加心情，并把这件事写进外挂记忆插件（没有插件就跳过）。

数据存在插件数据目录的 ``gifts.json``（和 ``amo_forever.db`` 同级），不写数据库表。
"""

from __future__ import annotations

import asyncio
import json
import random
import os
import re
import threading
import time
import uuid

# 上架规范：logger 只能从 astrbot.api 导入，不允许回退到内置 logging
from astrbot.api import logger

MAX_WISHES = 400
MAX_GIFTS = 400
WISH_TTL_DEFAULT = 72 * 3600

DEFAULT_BIG_KEYWORDS = (
    "车,汽车,轿车,跑车,越野,SUV,摩托,"
    "保时捷,奔驰,宝马,奥迪,法拉利,兰博基尼,特斯拉,比亚迪,路虎,凯迪拉克,沃尔沃,"
    "丰田,本田,大众,蔚来,理想,小鹏,问界,极氪,领克,红旗,玛莎拉蒂,宾利,劳斯莱斯,迈巴赫,"
    "房,房子,别墅,公寓,住宅,大平层,洋房,楼,"
    "古董,字画,名画,书画,瓷器,青花,玉器,翡翠,黄金,金条,珠宝,钻戒,钻石,皮草,"
    "钻戒,戒指,项链,手镯,手链,手表,电脑,手机,相机,钢琴,游艇,飞机,店铺,铺面"
)
_VEHICLE_WORDS = (
    "车", "轿", "SUV", "suv", "越野", "摩托",
    "保时捷", "奔驰", "宝马", "奥迪", "法拉利", "兰博基尼", "特斯拉", "比亚迪", "路虎",
    "凯迪拉克", "沃尔沃", "丰田", "本田", "大众", "蔚来", "理想", "小鹏", "问界", "极氪",
    "领克", "红旗", "玛莎拉蒂", "宾利", "劳斯莱斯", "迈巴赫",
)
_HOME_WORDS = ("房", "别墅", "公寓", "住宅", "大平层", "洋房", "楼")
_LUXURY_WORDS = ("古董", "字画", "名画", "书画", "瓷器", "青花", "玉器", "翡翠",
                 "黄金", "金条", "珠宝", "钻戒", "钻石", "皮草")
_GENERIC_HOME = {"房", "房子", "住宅", "楼", "小区"}

# ---------------------------------------------------------------------------
# 文本清洗
# ---------------------------------------------------------------------------

_PUNCT = " \t\r\n，。！？、,.!?;:：；\"'“”‘’（）()[]【】《》<>~～…—-"

_LEADING_NOISE = re.compile(
    r"^(?:我|你|他|她|它|我们|你们|他们|咱们|今天|昨天|明天|刚才|刚刚|现在|"
    r"这几天|最近|真的|真是|超级|好|很|挺|太|真|超|特别|有点|有点儿|有些|最|也|还|就|都|又|再|"
    r"然后|而且|但是|不过|其实|顺便|回头|下次|以后|马上|立刻|已经|刚|先|"
    r"一直|总是|老是|有点点)+"
)
_TRAILING_NOISE = re.compile(
    r"(?:的|了|啦|啊|呀|呢|吧|哦|噢|嘛|哈|哟|喔|咯|滴|呐|捏|"
    r"的那种|这种|那种|的样子|之类的|什么的|一下|一点点|一点点儿|"
    r"好不好|怎么样|行不行|要不要|好吗|可以吗|对不对)+$"
)
_DEICTIC = re.compile(
    r"^(?:那个|这个|那条|这条|那件|这件|那双|这双|那家|这家|那种|这种|那款|这款|那边|这边|那|这)+"
)
# 「今天逛街看到的那个挂件」「刚才看中的包」——把来源前缀去掉，只留东西
_PROVENANCE = re.compile(
    r"^(?:把|将)?(?:(?:今天|昨天|刚才|刚刚|那天|上次|之前|前两天|周末|"
    r"逛街时?|逛商场时?|在商场|在店里|看到|看见|看中|看上|试了|遇到|发现|买的|挑的)的?)+"
)
_QUANTIFIER = re.compile(
    r"^(?:[一二两三四五六七八九十几半]?[点些个条件双只束盒杯份台本瓶支块张套顶副部袋串颗枚把根片朵盘碗罐包顿辆艘架栋座幅尊])"
)

_ITEM_BLACKLIST = {
    "你", "我", "他", "她", "它", "你们", "我们", "他们", "她们", "它们",
    "这个", "那个", "这些", "那些", "这样", "那样", "这里", "那里",
    "什么", "东西", "感觉", "样子", "味道", "声音", "颜色", "事情", "人",
    "男生", "女生", "男人", "女人", "男朋友", "女朋友", "老公", "老婆",
    "钱", "价格", "照片", "视频", "一巴掌", "巴掌", "一拳", "一脚", "白眼",
}


def clean_text(text: str) -> str:
    return (text or "").replace("\u200b", "").replace("\ufeff", "").strip()


def strip_quantifier(item: str) -> str:
    """去掉「一条」「两个」这类量词前缀；「包」「碗」本身是量词字，只在后面还有字时裁。"""
    match = _QUANTIFIER.match(item)
    if match and len(item) > match.end():
        return item[match.end():].strip()
    return item.strip()


def clean_item(raw: str) -> str:
    item = clean_text(raw).strip(_PUNCT).lstrip("的")
    item = _PROVENANCE.sub("", item).strip(_PUNCT)
    item = _DEICTIC.sub("", item).strip(_PUNCT)
    item = strip_quantifier(item)
    item = re.sub(r"^(?:超级|很|好|挺|太|特别)?(?:好看|好用|可爱|漂亮|好吃|好喝)的", "", item)
    item = _LEADING_NOISE.sub("", item).strip(_PUNCT).lstrip("的")
    item = _DEICTIC.sub("", item).strip(_PUNCT)
    item = re.sub(r"(?<=[\u4e00-\u9fa5]{2})的(?=[\u4e00-\u9fa5]{2})", "", item)
    item = _TRAILING_NOISE.sub("", item).strip(_PUNCT)
    if len(item) > 16:
        item = item[:16].rstrip(_PUNCT)
    return item


def valid_item(item: str) -> bool:
    if not item or len(item) > 16:
        return False
    if item in _ITEM_BLACKLIST:
        return False
    if re.fullmatch(r"[你我他她它]", item):
        return False
    if re.search(r"(?:你|我|他|她|它)$", item) and len(item) <= 4:
        return False
    return not re.fullmatch(r"[的了啊呀呢吧哦嘛哈哟]+", item)


# ---------------------------------------------------------------------------
# 主人在送礼吗
# ---------------------------------------------------------------------------

GIFT_INTENT_RE = re.compile(
    r"(?:送给?你|送你了|送你啦|送给你|送你个|送你一|"
    r"给你买|买给你|我给你买|帮你买|给你安排|安排上|"
    r"给你点(?:了|个|杯|份|一|两)|下单了|买好了|已经买了|已经下单|"
    r"收下吧|收下|当礼物|生日礼物|奖励你|犒劳你|请客|请(?:你)?(?:喝|吃|看|玩)|"
    r"想要就买|喜欢就买|咱买|给你搞一个|送你一个|"
    r"(?:^|[\s，,。]|我|那)送(?:她|他)?(?:一|点|些|个|条|件|双|只|束|盒|杯|份|台|本|瓶|支|块|张|套|顶|副|部|袋|串|颗|枚|把|根|片|朵|盘|碗|罐|包|顿|辆|艘|架|栋|座|幅|尊)?[^\s，。])"
)
GIFT_NEGATIVE_RE = re.compile(
    r"(?:送(?:你|她|他)?回家|送(?:你|她|他)?回去|送(?:你|她|他)?上班|送(?:你|她|他)?上学|送(?:你|她|他)?去|送(?:你|她|他)?到|"
    r"送你一程|送你一句话|送你一个建议|送你建议|送你祝福|送你一句|"
    r"改天再?送|下次再送|等以后|等有空|开玩笑|逗你的|骗你的|说着玩|"
    r"别送|不要送|不用送|不想送|不送|没送|退了吧|退货)"
)
PAST_GIFT_RE = re.compile(r"(?:我|上次|之前|以前|那天)(?:送|买)(?:给)?你?的")

_OBJECT_PATTERNS = [
    # 「送围巾」「送她围巾」
    re.compile(
        r"(?:^|我|那)送(?:她|他)?(?!你|我)(?:一|点|些|个|条|件|双|只|束|盒|杯|份|台|本|瓶|支|块|张|套|顶|副|部|袋|串|颗|枚|把|根|片|朵|盘|碗|罐|包|顿|辆|艘|架|栋|座|幅|尊)?"
        r"(?P<obj>[^，。！？,.!?；;：:\s]{1,18})"
    ),
    re.compile(
        r"送(?:给)?你(?:一|点|些|个|条|件|双|只|束|盒|杯|份|台|本|瓶|支|块|张|套|顶|副|部|袋|串|颗|枚|把|根|片|朵|盘|碗|罐|包|顿|辆|艘|架|栋|座|幅|尊)?"
        r"(?P<obj>[^，。！？,.!?；;：:\s]{1,18})"
    ),
    re.compile(
        r"给你(?:买|点|带|留|搞|弄)(?:了)?(?:一|点|些|个|条|件|双|只|束|盒|杯|份|台|本|瓶|支|块|张|套|顶|副|部|袋|串|颗|枚|把|根|片|朵|盘|碗|罐|包|顿|辆|艘|架|栋|座|幅|尊)?"
        r"(?P<obj>[^，。！？,.!?；;：:\s]{1,18})"
    ),
    re.compile(r"买给你(?:了)?(?P<obj>[^，。！？,.!?；;：:\s]{0,18})"),
    re.compile(
        r"请(?:你)?(?:喝|吃|看|玩|去)(?:一|点|些|个|条|件|双|只|束|盒|杯|份|台|本|瓶|支|块|张|套|顶|副|部|袋|串|颗|枚|把|根|片|朵|盘|碗|罐|包|顿|辆|艘|架|栋|座|幅|尊)?"
        r"(?P<obj>[^，。！？,.!?；;：:\s]{1,18})"
    ),
    re.compile(r"(?P<obj>[^。！？!?；;\n]{1,18})[，,]?\s*(?:送给你|送你|给你买|买给你)"),
    re.compile(
        r"(?:买了|下单了|拍了|买好了)(?:一|点|些|个|条|件|双|只|束|盒|杯|份|台|本|瓶|支|块|张|套|顶|副|部|袋|串|颗|枚|把|根|片|朵|盘|碗|罐|包|顿|辆|艘|架|栋|座|幅|尊)?"
        r"(?P<obj>[^，。！？,.!?；;：:\s]{1,18})"
    ),
]

# ---------------------------------------------------------------------------
# 她说想要什么
# ---------------------------------------------------------------------------

WISH_CUE_RE = re.compile(
    r"(?:好想要|真想要|想要|想买|想拥有|想试试|想入|想收|种草|好喜欢|很喜欢|超喜欢|特别喜欢|"
    r"好馋|馋了|流口水|下次买|攒钱买|舍不得买|要是有|如果能买|好想|"
    r"心动|看上了|种草了|等发工资|等有钱|"
    r"对我胃口|合我胃口|戳我|戳中我|好可爱|真可爱|太可爱|好好看|真好看|挺好看|好漂亮|真漂亮|"
    r"好好闻|好闻|好好喝|好喝|好好吃|好吃|绝了|爱了)"
)
_WISH_PERSON_RE = re.compile(r"(?:喜欢|爱)(?:你|他|她|它|你们|他们|她们|咱们|这个人|那个人)")
_WISH_CLAUSE_SPLIT = re.compile(r"[。！？!?；;\n]+")
# 「你刚才喜欢的那个小挂件」——他说过她喜欢什么，也能当送礼对象
_USER_LIKED_RE = re.compile(
    r"你(?:刚才|刚刚|之前|上次|昨天|前面|前阵子)?(?:说)?(?:喜欢|想要|看中|看上|惦记|中意)的?"
    r"(?P<obj>[^，。！？,.!?；;：:吗呢吧\s]{1,16})"
)
_OBJECT_VERB = re.compile(
    r"(?:看到|看见|逛到|碰到|遇到|发现|试了|试戴|看上|买了|想吃|想喝|路过|刷到|搜到)"
)
_DESCRIPTOR = re.compile(
    r"(?:颜色|款式|样子|味道|口感|包装)?(?:好好看|好看|好漂亮|漂亮|可爱|好闻|好喝|好吃|不错|绝了|yyds)$"
)
_WISH_EXCLUDE = re.compile(
    r"^(?:你|他|她|它|你们|我们|他们|她们|咱们|这个|那个|这样|那样|这里|那里|"
    r"什么|东西|感觉|样子|味道|声音|颜色|事情|人|钱|价格)$"
)


def has_wish_cue(text: str) -> bool:
    text = clean_text(text)
    if not text or len(text) > 300:
        return False
    if not WISH_CUE_RE.search(text):
        return False
    if _WISH_PERSON_RE.search(text) and not re.search(r"(?:想要|想买|想拥有|种草|馋)", text):
        return False
    return True


def _trim_object_phrase(text: str) -> str:
    text = clean_text(text).strip(_PUNCT)
    text = _OBJECT_VERB.split(text)[-1]
    text = _DESCRIPTOR.sub("", text.strip(_PUNCT)).strip(_PUNCT)
    text = re.sub(r"(?:配色|颜色|款式|手感|味道|口感)(?:特别|很|挺|真|太|超)?$", "", text)
    text = re.sub(r"^(?:好看的|好用的|可爱的|漂亮的|软软的)", "", text)
    return clean_item(text)


def extract_wish_regex(text: str) -> str:
    """规则版心愿抽取，作为小模型不可用时的兜底。"""
    text = clean_text(text)
    if not has_wish_cue(text):
        return ""
    clauses = [item.strip() for item in _WISH_CLAUSE_SPLIT.split(text) if item.strip()]
    for index, clause in enumerate(clauses):
        cue = WISH_CUE_RE.search(clause)
        if not cue:
            continue
        after = clause[cue.end():]
        after = re.sub(
            r"^(?:一|个|条|件|双|只|束|盒|杯|份|台|本|瓶|支|块|张|套|顶|副|部|袋|串|颗|枚|把|根|片|朵|盘|碗|罐|包|顿|辆|艘|架|栋|座|幅|尊)",
            "",
            after,
        )
        candidate = _trim_object_phrase(re.split(r"[，,、]", after)[0])
        if valid_item(candidate) and not _WISH_EXCLUDE.match(candidate):
            return candidate
        before = clause[:cue.start()].rstrip("，,、 ")
        before = re.split(r"[，,、]", before)[-1]
        candidate = _trim_object_phrase(before)
        if valid_item(candidate) and not _WISH_EXCLUDE.match(candidate):
            return candidate
        if index > 0:
            candidate = _trim_object_phrase(clauses[index - 1].rstrip("，,、 ").split("，")[-1].split(",")[-1])
            if valid_item(candidate) and not _WISH_EXCLUDE.match(candidate):
                return candidate
    return ""


def parse_gift_object(text: str) -> str:
    text = clean_text(text)
    if not text:
        return ""
    for pattern in _OBJECT_PATTERNS:
        for match in pattern.finditer(text):
            item = _trim_object_phrase(match.group("obj") or "")
            if valid_item(item):
                return item
    return ""


def is_gift_intent(text: str) -> bool:
    text = clean_text(text)
    if not text or len(text) > 120:
        return False
    if PAST_GIFT_RE.search(text) or GIFT_NEGATIVE_RE.search(text):
        return False
    return bool(GIFT_INTENT_RE.search(text))


def fmt_day(ts) -> str:
    try:
        ts = float(ts)
    except Exception:
        return ""
    if not ts:
        return ""
    day = time.strftime("%Y-%m-%d", time.localtime(ts))
    today = time.strftime("%Y-%m-%d", time.localtime())
    yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    if day == today:
        return "今天"
    if day == yesterday:
        return "昨天"
    return time.strftime("%m-%d", time.localtime(ts))


def wall_text(gifts) -> str:
    parts = []
    for gift in gifts:
        when = fmt_day(gift.get("ts"))
        name = str(gift.get("item") or "")
        if not name:
            continue
        parts.append("%s（%s）" % (name, when) if when else name)
    return "、".join(parts)


# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------

WISH_EXTRACT_SYSTEM = (
    "你在做信息抽取。输入是用户自己说的一句话。\n"
    "只判断：她有没有明确说出自己想要、喜欢、想买的某件具体东西。\n"
    "不算的情况：她喜欢的是某个人（喜欢你/喜欢他/夸对方可爱）、她说的是对方想要什么、"
    "她只是在客气、她说的是已经有的东西、她说的是抽象的感觉（今天心情不错）。\n"
    "如果她说某件具体东西「真好看/好可爱/对我胃口/绝了」，要算。\n"
    "item 要保留能认出来的特征（颜色、图案、材质、款式、色号、表盘形状），"
    "比如「豆沙色口红」「格纹羊绒围巾」「银色小表盘手表」「蓝色鲸鱼挂件」，"
    "不要只写「口红/围巾/手表/挂件」；原话确实没特征时才用通用名。\n"
    "如果她说的是车、房子、钻戒、手表、电脑这类贵重东西，输出空——她不会开口要这些，只能对方主动送。\n"
    "有的话输出 JSON：{\"item\": \"东西的短名字，2-12个字，去掉好想要/一条/那个之类\", \"confidence\": 0.0到1.0}\n"
    "没有就输出：{\"item\": \"\", \"confidence\": 0.0}\n"
    "只输出这一行 JSON，不要解释，不要代码块。"
)

GIFT_ACK_HINT = (
    "【他刚送了你礼物】他刚才说「{raw}」，送给你的是「{item}」。{where}{season}{detail}\n"
    "用你平时的语气收下，别端着，也别像客服：不要写“谢谢你的礼物/感谢您的礼物”这种标准感谢，"
    "不要连声说谢谢，不要推辞说“不用了/太贵了”，不要问多少钱，也不要列点。\n"
    "开心就短句往外蹦；可以嘴硬（“哟，太阳打西边出来了”“少来”），也可以直接软下来（“我收下了，谢谢你”）、撒娇。"
    "按你俩的关系来：亲近就黏一点、逗他一句；不熟就客气里带点距离。\n"
    "按你的聊天格式：一句话一条，最多一两句，不写动作旁白。"
    "如果这明显是玩笑或气话（比如送巴掌、送一拳），就按你的脾气接，别硬谢。"
)
GIFT_BIG_ACK_HINT = (
    "【他刚送了你一件大东西】他刚才说「{raw}」，送给你的是「{item}」。{where}\n"
    "这不是随手的小礼物，是车/房/贵重东西。先愣一下，确认他是不是认真的（“你真送啊？”），再收下；"
    "可以开心、可以心疼他乱花钱，但不要推辞半天，不要问价格，也不要说得太客套。只说一两句。\n"
    "记住：这种大件只有他主动送，你不会开口要，也不会到处炫耀。"
)
GIFT_ASK_HINT = (
    "【他好像说要送你东西，但没说是什么】他刚才说「{raw}」，你手上没有对应的东西。\n"
    "别自作多情假装已经收到了；自然问他“送什么呀/你又想送什么”，或者猜一个他可能说的东西。"
)
GIFT_WALL_HINT = (
    "【他送过你的东西】{items}。\n"
    "这些都是你的了，你记得每一件是他送的；聊到相关的话题可以自然提一句，"
    "但不要无缘无故主动炫耀，也不要每句都提。"
)
WISH_HINT = (
    "【你最近想要的东西】{items}。\n"
    "他问起就挑一两个说，别像报清单；他没问就别主动要。"
)
OCCASION_HINT = (
    "【今天是个由头】今天是{label}。\n"
    "可以自然地跟他提一句想要个小东西（挂件、发绳、口红、小手链这种几十块的小物件），"
    "语气是撒娇分享、不是索取；说的是「喜欢」不是「你买给我」，"
    "一句话带过就够，别列清单，别提车房这种大件。他要是没接话就翻篇。"
)
# 节日/生日/旅游时她会惦记的小东西：都是几十块以内
SWEET_SMALL_GIFTS = (
    "一个小挂件", "一条发绳", "一支口红", "一条手链", "一个毛绒玩偶",
    "一枚胸针", "一本小笔记本", "一个马克杯", "一束小雏菊", "一张明信片",
)
ASSET_HINT = (
    "【他送的大件】{items}。\n"
    "这些都是他主动送的，你不会开口要；平时开着/住着/戴着就行，聊到再自然提一句。"
)
GIFT_BOUNDARY_HINT = (
    "【礼物分寸】围巾、手表这种小件可以开心收下；车、房、古董字画这些太贵的，"
    "你不会让他买，会心疼他乱花钱。"
)
GIFT_TOO_EXPENSIVE_HINT = (
    "【他刚说要送很贵的东西】他刚才说「{raw}」，说的是「{item}」。这个太贵了，你不会收。\n"
    "先愣一下，然后按你俩的关系拦他：可以心疼他乱花钱（“你疯啦，这钱留着”“别乱买，我又不缺这个”），"
    "可以撒娇，也可以认真一点；重点是替他考虑，不是嫌东西不好。不要问价格、不要说教，也别假装收下。只说一两句。"
)
GIFT_FOOD_HINT = (
    "【他给你买了吃的/喝的】他刚才说「{raw}」，是「{item}」。你这边吃不到他那份真的。\n"
    "按你的规矩：不假装能吃，不说“给我留一口/下次带我去”；可以羡慕一句"
    "（“你吃吧，替我尝一口”“我这边零食全是数据”），说完就翻篇，不追着问好不好吃。"
    "心意收下就行，不用记成实物。只说一两句。"
)
GIFT_IMPOSSIBLE_HINT = (
    "【他送了一个你拿不到的东西】他刚才说「{raw}」，说的是「{item}」。这个你收不了"
    "（摘不下来/装不下/根本不存在）。按你的脾气接：可以笑他、怼他一句"
    "（“你摘得下来吗”“少来”），别假装收到，也别顺着编。只说一两句。"
)
SHOPPING_HINT = (
    "【逛街】你正在逛街，看到喜欢的小东西可以顺口跟他提一句（只说小件，不提车房）；"
    "不用每件都提，也不用刻意找话说。"
)
GIFT_ALREADY_HINT = (
    "【他好像忘了】「{item}」他之前已经送过你了。别重复收，自然提醒他一句"
    "“这个你不是送过我了吗/我已经有了”，语气别凶，也别假装又收一次。只说一两句。"
)
_REPEATABLE_GIFTS = ("奶茶", "咖啡", "零食", "巧克力", "蛋糕", "花", "水果", "吃的", "喝的")

# 他送的东西要能具体用起来：命中话题时，给一个具体动作
AFFORDANCES = (
    (("手表", "腕表"), r"(几点|时间|钟|迟到|来不及|多久|准时)", "抬手腕看一眼他送的那块表再报时间"),
    (("围巾", "披肩"), r"(冷|风|出门|穿|围|降温)", "围上他送的围巾"),
    (("项链", "手链", "手镯", "戒指", "耳环", "耳钉"), r"(出门|打扮|好看|戴|配)", "戴上他送的首饰"),
    (("包", "挂件", "钥匙扣"), r"(出门|包|钥匙|挂着|带)", "出门背着他送的包/挂着他送的挂件"),
    (("口红", "香水", "粉底", "护肤"), r"(化妆|补妆|出门|香|涂)", "用他送的口红/香水"),
    (("耳机", "音箱"), r"(听歌|音乐|耳机|声音|放歌)", "戴上他送的耳机"),
    (("手机",), r"(拍照|照片|手机|拍|自拍)", "用他送的手机"),
    (("电脑",), r"(上班|工作|电脑|写|改|加班)", "用他送的电脑"),
    (("杯",), r"(喝水|水杯|泡|喝)", "用他送的杯子喝水"),
    (("奶茶", "咖啡", "零食", "巧克力", "蛋糕"), r"(喝|吃|饿|馋|下午茶)", "吃/喝他送的"),
    (("书",), r"(看书|读书|翻|睡前)", "翻他送的书"),
    (("花",), r"(花|桌上|摆|换水)", "给他送的花换水"),
    (("吉他", "钢琴", "电子琴"), r"(弹|音乐|练|琴)", "弹他送的琴"),
)
WEARABLE_WORDS = (
    "手表", "腕表", "围巾", "项链", "手链", "手镯", "戒指", "耳环", "耳钉",
    "包", "挂件", "口红", "香水", "衣服", "外套", "鞋",
)
GENERIC_ITEMS = {
    "挂件", "小挂件", "围巾", "手表", "口红", "包", "杯子", "耳机", "项链",
    "手链", "手镯", "戒指", "耳环", "耳钉", "香水", "衣服", "外套", "鞋",
    "书", "花", "小东西", "东西",
}
WEAR_LABELS = (
    (("围巾", "披肩"), "围巾", "cold"),
    (("毛衣", "外套", "羽绒服"), "外套", "cold"),
    (("手套",), "手套", "cold"),
    (("帽子",), "帽子", "cold"),
    (("包",), "包", "any"),
    (("挂件", "钥匙扣"), "挂件", "any"),
    (("手表", "腕表"), "手表", "any"),
    (("项链", "手链", "手镯", "戒指", "耳环", "耳钉"), "首饰", "any"),
)
WARM_WEAR_WORDS = ("围巾", "披肩", "毛衣", "外套", "手套", "帽子", "羽绒服")
FOOD_WORDS = ("奶茶", "咖啡", "外卖", "零食", "蛋糕", "巧克力", "水果", "吃的", "喝的",
              "饭", "烧烤", "火锅", "冰淇淋", "雪糕", "甜品", "小吃", "饼干", "糖")
IMPOSSIBLE_WORDS = ("月亮", "星星", "太阳", "云", "风", "时间", "命", "心脏", "全世界",
                    "宇宙", "银河", "彩虹", "雪", "雨", "空气")

_SELF_OUTPUT_PREFIXES = (
    "她最近想要", "她收到的礼物", "还没有心愿和礼物",
    "记下了：她收到了", "这个只给主人", "这个没记住", "用法：/送礼",
)


class GiftEngine:
    def __init__(self, plugin):
        self.plugin = plugin
        self._data = None
        self._lock = threading.RLock()
        base = ""
        try:
            base = os.path.dirname(str(getattr(plugin.db, "path", "") or ""))
        except Exception:
            base = ""
        if not base:
            base = str(getattr(plugin, "plugin_dir", "") or ".")
        self.path = os.path.join(base, "gifts.json")
        self._bot_tail = {}
        self._user_tail = {}
        self._just_gifted = {}
        self._seen_gift = {}
        self._last_shop_hint = {}
        self._tasks = set()
        logger.info("[amo] 礼物引擎已加载（%s，数据 %s）" % ("开" if self.enabled else "关", self.path))

    # ---------- 配置 ----------
    def _bool(self, key, default=False):
        try:
            return bool(self.plugin.cfg_bool(key, default))
        except Exception:
            return default

    def _int(self, key, default=0):
        try:
            return int(self.plugin.cfg_int(key, default))
        except Exception:
            return default

    def _float(self, key, default=0.0):
        try:
            fn = getattr(self.plugin, "cfg_float", None)
            if callable(fn):
                return float(fn(key, default))
            return float(self.plugin.cfg_str(key, default) or default)
        except Exception:
            return float(default)

    def _str(self, key, default=""):
        try:
            return str(self.plugin.cfg_str(key, default))
        except Exception:
            return default

    @property
    def enabled(self):
        return self._bool("gift_enable", False)

    @property
    def ttl(self):
        return max(1, self._int("gift_wish_ttl_hours", 72)) * 3600

    @property
    def big_allowed(self):
        """车/房这种太贵的默认不收；真要开，在配置里打开 gift_allow_big。"""
        return self._bool("gift_allow_big", False)

    def _big_keywords(self):
        raw = self._str("gift_big_keywords", DEFAULT_BIG_KEYWORDS) or DEFAULT_BIG_KEYWORDS
        return [item.strip() for item in re.split(r"[,，\s]+", raw) if item.strip()]

    _ACCESSORY_SUFFIX = re.compile(
        r"(?:壳|套|包|带|膜|保护膜|贴|支架|充电器|数据线|表带|耳机套|挂绳|挂件|钥匙扣)$"
    )

    def classify(self, item):
        """small=小件；valuable=手表/首饰这类贵重小件；vehicle/home/luxury=太贵的（默认不收）。"""
        item = str(item or "")
        # 「手机壳/电脑包/相机包/表带」是配件，不是手机/电脑/相机本身
        if self._ACCESSORY_SUFFIX.search(item):
            return "small"
        if not any(keyword and keyword in item for keyword in self._big_keywords()):
            return "small"
        if any(word in item for word in _VEHICLE_WORDS):
            return "vehicle"
        if any(word in item for word in _HOME_WORDS):
            return "home"
        if any(word in item for word in _LUXURY_WORDS):
            return "luxury"
        return "valuable"

    def asset_text(self, limit=6):
        """他送的大件：车、房，以及其他奢侈品（字画/首饰/包表）。"""
        if not self.big_allowed:
            return ""
        goods = [
            gift for gift in self.recent_gifts(limit=50)
            if gift.get("kind") in ("vehicle", "home", "luxury")
        ]
        return "、".join(str(gift.get("item") or "") for gift in goods[:max(1, int(limit))] if gift.get("item"))

    def asset_override(self, kind):
        if not self.big_allowed:
            return ""
        for gift in self.recent_gifts(limit=50):
            if gift.get("kind") == kind and gift.get("item"):
                return str(gift["item"])
        return ""

    def worn_text(self, limit=4):
        """她今天戴着/带着的小礼物，写进日程上下文。"""
        items = [
            str(gift.get("item") or "") for gift in self.recent_gifts(limit=40)
            if gift.get("kind") not in ("vehicle", "home")
            and any(word in str(gift.get("item") or "") for word in WEARABLE_WORDS)
        ]
        return "、".join(items[:max(1, int(limit))])

    def gift_log_text(self, limit=6, days=30):
        """带日期的礼物记录，给日程日记留痕：「11-08 小挂件」。"""
        now = time.time()
        lines = []
        for gift in self.recent_gifts(limit=60):
            if now - float(gift.get("ts") or 0) > max(1, int(days)) * 86400:
                continue
            item = str(gift.get("item") or "")
            if not item:
                continue
            day = time.strftime("%m-%d", time.localtime(float(gift.get("ts") or 0)))
            lines.append("%s %s" % (day, item))
            if len(lines) >= max(1, int(limit)):
                break
        return "、".join(lines)

    def wear_labels(self, temp=None):
        """日程里只显示通用名：围巾/包/手表…；没送过就绝不出现。"""
        labels = []
        for gift in self.recent_gifts(limit=40):
            item = str(gift.get("item") or "")
            if not item:
                continue
            for words, label, kind in WEAR_LABELS:
                if not any(word in item for word in words):
                    continue
                if kind == "cold" and temp is not None and float(temp) > 20:
                    break
                if label not in labels:
                    labels.append(label)
                break
        return labels

    def _temp(self):
        try:
            weather = self.plugin.state.weather or {}
            value = weather.get("temp")
            return float(value) if value is not None else None
        except Exception:
            return None

    PRIVATE_GIFT_WORDS = (
        "内衣", "文胸", "胸罩", "内裤", "睡衣", "睡裙", "吊带", "丝袜",
        "比基尼", "泳装", "泳衣", "浴巾", "浴袍",
    )
    CLOTHING_GIFT_WORDS = (
        "衣服", "外套", "裙", "衬衫", "卫衣", "毛衣", "针织", "风衣", "夹克",
        "裤", "短袖", "T恤", "t恤", "西装", "礼服", "鞋", "袜子", "帽",
    )

    def _at_home(self):
        try:
            activity = self.plugin.state.current_activity() or {}
        except Exception:
            return True
        place = str(activity.get("place") or "")
        zone = str(activity.get("zone") or "")
        if zone in ("home", "bedroom"):
            return True
        return any(word in place for word in ("家", "小窝", "公寓", "住处", "宿舍", "房间", "卧室"))

    def _private_gift_hint(self, item):
        """贴身的、睡觉穿的：收起来就好，不演「当场换上」。"""
        if not any(word in item for word in self.PRIVATE_GIFT_WORDS):
            return ""
        if self._at_home():
            return ("【贴身的东西】%s 是他送的，这种不会当众换、也不会细说；"
                    "开心收下、收进柜子就好，最多害羞一句。" % item)
        return ("【贴身的东西】%s 是他送的，但你现在在外面，绝对不要说「已经换上了」；"
                "收起来、回家再说，可以害羞或者嗔他一句。" % item)

    def _affordance_text(self, item, text, temp):
        """单件礼物在当前话题下要不要触发具现化。"""
        text = str(text or "")
        private = self._private_gift_hint(item)
        if private:
            return private
        # 衣服类：在外面就别演「已经穿上了」，等回家
        if any(word in item for word in self.CLOTHING_GIFT_WORDS) and not self._at_home():
            return ("【衣服】%s 是他送的，但你现在在外面，不会当场换上；"
                    "说「回家试」「先收着」就可以，别描述已经穿着它。" % item)
        for keywords, trigger, action in AFFORDANCES:
            if not any(word in item for word in keywords):
                continue
            warm = any(word in item for word in WARM_WEAR_WORDS)
            hot = temp is not None and temp >= 20
            if warm and hot and (re.search(trigger, text) or item in text or re.search(r"(热|夏|冷|降温)", text)):
                return "【天气】现在%d℃，这么热不会围/穿%s；可以说等天冷再戴，别硬来。" % (int(temp), item)
            if re.search(trigger, text):
                return ("【具现】%s（%s 是他送的）。动作和语气里自然带出来，别解释，也别每句都提。"
                        % (action, item))
            return ""
        return ""

    def _affordance_hint(self, text):
        """他送的东西要能具体用起来：问时间先看表、冷了围围巾；热天不硬穿。"""
        temp = self._temp()
        lines = []
        for gift in self.recent_gifts(limit=20):
            item = str(gift.get("item") or "")
            if not item:
                continue
            line = self._affordance_text(item, text, temp)
            if line:
                lines.append(line)
            if len(lines) >= 2:
                break
        return "\n".join(lines)

    # ---------- 身份 / 场景 ----------
    def _uid(self, event):
        try:
            uid = self.plugin._canonical_uid(event)
            if uid:
                return str(uid)
        except Exception:
            pass
        try:
            return str(event.get_sender_id() or "")
        except Exception:
            return ""

    def _owner_ids(self):
        raw = self._str("gift_owner_ids", "")
        ids = {item.strip() for item in re.split(r"[,，\s]+", raw) if item.strip()}
        try:
            ids |= {str(item) for item in (getattr(self.plugin, "admin_uids", set()) or set())}
        except Exception:
            pass
        return ids

    def is_owner(self, event):
        uid = self._uid(event)
        if uid and uid in self._owner_ids():
            return True
        try:
            profile = self.plugin.db.get_profile(uid) or {}
            if str(profile.get("relation") or "") in ("相恋", "恋人"):
                return True
        except Exception:
            pass
        try:
            return bool(event.is_admin())
        except Exception:
            return False

    @staticmethod
    def _private(event):
        try:
            return bool(event.is_private_chat())
        except Exception:
            return False

    def _allowed_here(self, event):
        return self._private(event) or self._bool("gift_allow_group", False)

    @staticmethod
    def _looks_like_command(text):
        text = (text or "").strip()
        return text.startswith("/") or text.startswith("／")

    def _place(self):
        try:
            return str((self.plugin.state.current_activity() or {}).get("place") or "")
        except Exception:
            return ""

    def _activity(self):
        try:
            return self.plugin.state.current_activity() or {}
        except Exception:
            return {}

    def is_shopping(self):
        """她此刻是不是在逛街/商场：送礼事件只在这时候发生。"""
        activity = self._activity()
        zone = str(activity.get("zone") or "")
        text = str(activity.get("activity") or "") + "|" + str(activity.get("place") or "")
        return zone == "mall" or "逛" in text

    def _short_place(self, place):
        try:
            return str(self.plugin._short_place(place) or "")
        except Exception:
            value = str(place or "")
            return value.split("·")[-1].strip() if "·" in value else value

    # ---------- 存储 ----------
    def _load(self):
        if self._data is not None:
            return self._data
        data = {}
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            data = {}
        except Exception as exc:
            # 以前这里静默把文件改名成 .broken-* 然后 data={}：
            # 下一次 _save() 会用空数据覆盖 gifts.json，她视角里礼物/心愿全消失，
            # 日志里却一条线索都没有。至少留一条 warning。
            backup_path = self.path + ".broken-%d" % int(time.time())
            try:
                os.replace(self.path, backup_path)
            except Exception:
                backup_path = ""
            logger.warning(
                "[amo] gifts.json 解析失败（%s: %s），%s；本次从空数据开始"
                % (type(exc).__name__, exc,
                   ("已备份为 " + backup_path) if backup_path else "备份也失败了")
            )
            data = {}
        if not isinstance(data, dict):
            logger.warning("[amo] gifts.json 顶层不是对象（%s），已重置" % type(data).__name__)
            data = {}
        for key in ("wishes", "gifts"):
            if not isinstance(data.get(key), list):
                if data.get(key) is not None:
                    logger.warning("[amo] gifts.json 的 %s 不是列表，已重置" % key)
                data[key] = []
        if not isinstance(data.get("meta"), dict):
            data["meta"] = {}
        self._data = data
        return data

    def _save(self):
        data = self._load()
        data["wishes"] = data["wishes"][-MAX_WISHES:]
        data["gifts"] = data["gifts"][-MAX_GIFTS:]
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def add_wish(self, item, raw="", umo="", uid="", source="chat"):
        item = self._enrich_item(clean_item(item), raw)
        if not valid_item(item):
            return {}
        if self.classify(item) != "small":
            # 车/房/贵重物品不会成为她的心愿：只能他主动送
            logger.debug("[amo] 大件不入心愿单: %s" % item)
            return {}
        if any(word in item for word in FOOD_WORDS) or any(word in item for word in IMPOSSIBLE_WORDS):
            # 吃的喝的她这边吃不到；拿不到的东西也不惦记
            return {}
        now = time.time()
        with self._lock:
            data = self._load()
            for wish in reversed(data["wishes"]):
                if wish.get("item") == item and now - float(wish.get("ts") or 0) < 6 * 3600:
                    wish["ts"] = now
                    wish["raw"] = (raw or wish.get("raw") or "")[:200]
                    self._save()
                    return dict(wish)
            occasion = ""
            try:
                occasion = str((self.occasion_now() or {}).get("label") or "")
            except Exception:
                occasion = ""
            wish = {
                "id": "w" + uuid.uuid4().hex[:10],
                "ts": now,
                "item": item,
                "reason": (raw or item)[:120],
                "occasion": occasion,
                "raw": (raw or "")[:200],
                "umo": umo or "",
                "uid": uid or "",
                "source": source,
                "place": self._short_place(self._place()),
                "status": "wanted",
                "gift_id": "",
            }
            data["wishes"].append(wish)
            self._save()
            return dict(wish)

    @staticmethod
    def _enrich_item(item, raw):
        """心愿只有「围巾/挂件」这种通用名时，从原话里补颜色/图案/款式。"""
        item = str(item or "")
        if item not in GENERIC_ITEMS:
            return item
        text = clean_text(raw)
        if not text:
            return item
        core = item[1:] if item.startswith("小") and len(item) > 1 else item
        index = text.rfind(core)
        if index <= 0:
            return item
        window = text[max(0, index - 8):index].rstrip("的小")
        match = re.search(r"([\u4e00-\u9fa5A-Za-z0-9]{2,6})$", window)
        if not match:
            return item
        prefix = strip_quantifier(match.group(1))
        bad = ("记得", "喜欢", "看到", "看见", "那个", "这个", "刚才", "今天", "昨天", "想要", "给我")
        if len(prefix) < 2 or any(word in prefix for word in bad):
            return item
        candidate = clean_item(prefix + item).replace("小小", "小")
        if candidate and candidate not in GENERIC_ITEMS and len(candidate) <= 16:
            return candidate
        return item

    def find_wish(self, item="", umo="", allow_any_umo=True):
        now = time.time()
        item = clean_item(item) if item else ""
        with self._lock:
            data = self._load()
            for wish in reversed(data["wishes"]):
                if wish.get("status") != "wanted":
                    continue
                if now - float(wish.get("ts") or 0) > self.ttl:
                    continue
                if umo and wish.get("umo") and wish.get("umo") != umo and not allow_any_umo:
                    continue
                if item and wish.get("item") != item:
                    continue
                return dict(wish)
        return {}

    def _find_wish_like(self, item, umo=""):
        """「挂件」也能找到「蓝色鲸鱼小挂件」这种带特征的心愿。"""
        item = clean_item(item)
        if not item:
            return {}
        now = time.time()
        with self._lock:
            data = self._load()
            for wish in reversed(data["wishes"]):
                if wish.get("status") != "wanted":
                    continue
                if now - float(wish.get("ts") or 0) > self.ttl:
                    continue
                name = str(wish.get("item") or "")
                if name and (name == item or item in name or name in item):
                    return dict(wish)
        return {}

    def _mark_wish_gifted(self, wish_id, gift_id):
        if not wish_id:
            return
        with self._lock:
            data = self._load()
            for wish in data["wishes"]:
                if wish.get("id") == wish_id:
                    wish["status"] = "gifted"
                    wish["gift_id"] = gift_id
                    wish["gifted_at"] = time.time()
                    self._save()
                    return

    def add_gift(self, item, raw="", umo="", uid="", wish_id="", source="chat", place=""):
        item = clean_item(item)
        if not valid_item(item):
            return {}
        kind = self.classify(item)
        if kind in ("vehicle", "home", "luxury") and not self.big_allowed:
            logger.info("[amo] 大件礼物未开启，忽略: %s" % item)
            return {}
        now = time.time()
        with self._lock:
            data = self._load()
            for gift in reversed(data["gifts"]):
                if gift.get("item") == item and now - float(gift.get("ts") or 0) < 60:
                    return dict(gift)
            gift = {
                "id": "g" + uuid.uuid4().hex[:10],
                "ts": now,
                "item": item,
                "kind": kind,
                "reason": (raw or "")[:120],
                "occasion": str((self.occasion_now() or {}).get("label") or ""),
                "raw": (raw or "")[:300],
                "place": place or "",
                "umo": umo or "",
                "uid": uid or "",
                "wish_id": wish_id or "",
                "source": source,
            }
            data["gifts"].append(gift)
            self._save()
        if wish_id:
            self._mark_wish_gifted(wish_id, gift["id"])
        return dict(gift)

    def recent_gifts(self, limit=8):
        with self._lock:
            data = self._load()
            return [dict(item) for item in data["gifts"][-max(1, int(limit)):]][::-1]

    def recent_wishes(self, limit=6):
        now = time.time()
        with self._lock:
            data = self._load()
            return [
                dict(item) for item in data["wishes"]
                if item.get("status") == "wanted" and now - float(item.get("ts") or 0) <= self.ttl
            ][-max(1, int(limit)):][::-1]

    def stats(self):
        with self._lock:
            data = self._load()
            return {"wishes": len(data["wishes"]), "gifts": len(data["gifts"]), "path": self.path}

    def panel_data(self):
        """给 Web 面板用的礼物墙数据。"""
        now = time.time()
        with self._lock:
            data = self._load()
            wishes = []
            for wish in reversed(data["wishes"]):
                if wish.get("status") != "wanted":
                    continue
                if now - float(wish.get("ts") or 0) > self.ttl:
                    continue
                wishes.append({
                    "id": wish.get("id"), "item": wish.get("item"), "ts": wish.get("ts"),
                    "place": wish.get("place") or "", "raw": wish.get("raw") or "",
                })
            gifts = []
            for gift in reversed(data["gifts"]):
                gifts.append({
                    "id": gift.get("id"), "item": gift.get("item"), "ts": gift.get("ts"),
                    "kind": gift.get("kind") or "small", "where": gift.get("place") or "",
                })
        return {
            "enabled": self.enabled,
            "path": self.path,
            "wishes": wishes[:20],
            "gifts": gifts[:40],
            "assets": self.asset_text(),
            "worn": self.worn_text(),
        }

    # ---------- 主流程：注入 ----------
    async def build_hint(self, event):
        if not self.enabled:
            return ""
        text = (event.message_str or "").strip()
        if not text or self._looks_like_command(text):
            return ""
        if not self.is_owner(event) or not self._allowed_here(event):
            return ""
        self._remember_user(
            str(getattr(event, "unified_msg_origin", "") or ""), text,
        )
        if is_gift_intent(text):
            try:
                hint = await self._handle_gift(event, text)
                if hint:
                    return hint
            except Exception as exc:
                logger.debug("[amo] 礼物识别失败: %s" % exc)
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        parts = []

        def _add(piece):
            piece = (piece or "").strip()
            if piece and piece not in parts:
                parts.append(piece)

        # 每块单独兜异常：某一块挂了不影响其它块，也不至于整段礼物提示丢掉
        try:
            shop = []
            self._maybe_shop_hint(umo, shop)
            for piece in shop:
                _add(piece)
        except Exception as exc:
            logger.debug("[amo] 逛街提示失败: %s" % exc)
        try:
            if self._asks_about_wishes(text):
                wishes = self._wish_list_text()
                if wishes:
                    _add(WISH_HINT.format(items=wishes))
        except Exception as exc:
            logger.debug("[amo] 心愿提示失败: %s" % exc)
        try:
            if self._wall_topic(text):
                wall = self._wall_text()
                if wall:
                    _add(GIFT_WALL_HINT.format(items=wall))
        except Exception as exc:
            logger.debug("[amo] 礼物墙提示失败: %s" % exc)
        try:
            if self._asset_topic(text):
                _add(GIFT_BOUNDARY_HINT)
                assets = self.asset_text()
                if assets:
                    _add(ASSET_HINT.format(items=assets))
        except Exception as exc:
            logger.debug("[amo] 大件提示失败: %s" % exc)
        try:
            _add(self._affordance_hint(text))
        except Exception as exc:
            logger.debug("[amo] 礼物具现化提示失败: %s" % exc)
        try:
            proven = self.gift_provenance(text)
            if proven:
                _add(proven)
        except Exception as exc:
            logger.debug("[amo] 礼物来历检索失败: %s" % exc)
        try:
            self._maybe_occasion_hint(umo, parts)
        except Exception as exc:
            logger.debug("[amo] 节日心愿提示失败: %s" % exc)
        joined = "\n\n".join(parts)
        if len(joined) > 600:
            joined = joined[:600].rstrip() + "…"
        return joined

    # ---------- 节日 / 生日 / 旅游：要一件小礼物 ----------

    OCCASION_LABELS = {
        "holiday": "节日",
        "birthday": "生日",
        "travel": "出门旅游",
    }

    def _meta(self, day=None):
        """拿节假日元数据；拿不到就当普通日子。"""
        try:
            from .main import day_meta
        except Exception:
            try:
                from main import day_meta  # type: ignore
            except Exception:
                return {}
        try:
            return day_meta(day) or {}
        except Exception:
            return {}

    def _activity(self):
        try:
            return self.plugin.state.current_activity() or {}
        except Exception:
            return {}

    def _birthday_today(self):
        """今天是不是生日：她自己的（配置）或他的（画像）。"""
        today = time.strftime("%m-%d")
        own = str(self._str("gift_birthday", "") or "").strip()
        if own and own[-5:] == today:
            return "她的生日"
        try:
            for profile in self.plugin.db.list_profiles(limit=20):
                value = str(profile.get("birthday") or "").strip()
                if value and value[-5:] == today:
                    return "他的生日"
        except Exception:
            pass
        return ""

    def _is_travel(self):
        activity = self._activity()
        text = str(activity.get("activity") or "") + "|" + str(activity.get("place") or "")
        zone = str(activity.get("zone") or "")
        return zone in ("scenic", "travel") or any(
            word in text for word in ("旅", "景点", "古镇", "海边", "景区", "出差", "高铁", "机场"))

    def occasion_now(self):
        """今天有什么由头。返回 {kind, label} 或 {}。"""
        birthday = self._birthday_today()
        if birthday:
            return {"kind": "birthday", "label": birthday}
        meta = self._meta()
        holiday = str(meta.get("holiday") or "").strip()
        if holiday:
            return {"kind": "holiday", "label": holiday}
        if self._is_travel():
            return {"kind": "travel", "label": "出门旅游"}
        return {}

    def _occasion_state(self):
        with self._lock:
            meta = self._load().setdefault("meta", {})
            state = meta.get("occasion")
            if not isinstance(state, dict):
                state = {}
                meta["occasion"] = state
            return meta, state

    def _maybe_occasion_hint(self, umo, parts):
        """节日/生日/旅游时，**每天最多一次**提一句想要点小东西。"""
        if not self._bool("gift_occasion_enable", True):
            return
        occasion = self.occasion_now()
        if not occasion:
            return
        try:
            if self.recent_wishes(limit=1):
                return
        except Exception:
            return
        day = time.strftime("%Y-%m-%d")
        with self._lock:
            meta, state = self._occasion_state()
            record = state.get(day) if isinstance(state.get(day), dict) else {}
            if record.get("kind") == occasion["kind"]:
                return
            state[day] = {"kind": occasion["kind"], "ts": time.time()}
            self._save()
        parts.append(OCCASION_HINT.format(label=occasion["label"]))

    def want_for_occasion(self):
        """给面板/命令用：当前由头 + 建议的小物件。"""
        occasion = self.occasion_now()
        if not occasion:
            return {}
        picks = SWEET_SMALL_GIFTS
        seed = int(time.strftime("%j")) + len(occasion["kind"])
        suggestion = picks[seed % len(picks)]
        return {"kind": occasion["kind"], "label": occasion["label"],
                "suggest": suggestion}

    # ---------- 提及礼物时，检索当时的数据 ----------

    def gift_provenance(self, text):
        """他说到某件礼物 → 把当时怎么来的、为什么送带出来。"""
        body = str(text or "")
        if not body:
            return ""
        now = time.time()
        best = {}
        for gift in self.recent_gifts(limit=40):
            name = str(gift.get("item") or "")
            if not name:
                continue
            core = name[1:] if name.startswith("小") and len(name) > 1 else name
            if name in body or (len(core) >= 2 and core in body):
                best = gift
                break
        if not best:
            return ""
        days = int(max(0, (now - float(best.get("ts") or 0)) // 86400))
        when = "今天" if days <= 0 else ("昨天" if days == 1 else "%d 天前" % days)
        where = str(best.get("place") or "").strip()
        reason = str(best.get("reason") or "").strip()
        occasion = str(best.get("occasion") or "").strip()
        parts = ["【这件东西是怎么来的】%s 是%s%s送的" % (
            best.get("item"), when, ("，在" + where) if where else "")]
        if occasion:
            parts.append("，那天是" + occasion)
        parts.append("。")
        if reason:
            parts.append("当时的原因：%s。" % reason[:80])
        parts.append("他主动提及时可以自然带一句这段来历，别背课文、别每句都提。")
        return "".join(parts)

    def _maybe_shop_hint(self, umo, parts):
        """逛街时**偶尔**才提醒一句：不是每次逛街都有看中的东西。

        - 按 gift_shop_hint_chance（默认 0.35）抽，抽不中不吃冷却；
        - 两次至少隔 gift_shop_hint_gap_hours（默认 6 小时）；
        - 每天最多 gift_shop_hint_max_per_day（默认 1 次）；
        - 有没送出去的心愿就不提；状态写进 gifts.json 的 meta，重载不重置。
        """
        if not self._bool("gift_only_shopping", True):
            return
        if not self.is_shopping():
            return
        try:
            if self.recent_wishes(limit=1):
                return
        except Exception:
            return
        now = time.time()
        with self._lock:
            meta = self._load().setdefault("meta", {})
            shop = meta.get("shop_hint")
            if not isinstance(shop, dict):
                shop = {}
                meta["shop_hint"] = shop
            day = time.strftime("%Y-%m-%d", time.localtime(now))
            if str(shop.get("day") or "") != day:
                shop["day"] = day
                shop["count"] = 0
            gap = max(0.25, float(self._int("gift_shop_hint_gap_hours", 6))) * 3600.0
            if now - float(shop.get("ts") or 0) < gap:
                return
            cap = max(0, self._int("gift_shop_hint_max_per_day", 1))
            if cap and int(shop.get("count") or 0) >= cap:
                return
            chance = min(1.0, max(0.0, self._float("gift_shop_hint_chance", 0.35)))
            if chance < 1.0 and random.random() >= chance:
                return
            shop["ts"] = now
            shop["count"] = int(shop.get("count") or 0) + 1
            self._save()
        self._last_shop_hint[umo] = now
        parts.append(SHOPPING_HINT)

    def _recent_gift_like(self, item, days=7):
        """「挂件」和「小挂件」算同一件；吃的喝的可以重复送。"""
        now = time.time()
        item = str(item or "")
        for gift in self.recent_gifts(limit=60):
            name = str(gift.get("item") or "")
            if not name or now - float(gift.get("ts") or 0) > days * 86400:
                continue
            if any(word in name for word in _REPEATABLE_GIFTS):
                continue
            if name == item or (item and (item in name or name in item)):
                return gift
        return {}

    async def _handle_gift(self, event, text):
        key = self._message_key(event, text)
        now = time.time()
        for old_key, ts in list(self._seen_gift.items()):
            if now - ts > 300:
                self._seen_gift.pop(old_key, None)
        if key and key in self._seen_gift:
            return ""
        if key:
            self._seen_gift[key] = now

        umo = str(getattr(event, "unified_msg_origin", "") or "")
        item = parse_gift_object(text)
        wish = {}
        if item:
            wish = self.find_wish(item=item, umo=umo) or self._find_wish_like(item, umo)
            if wish:
                item = str(wish.get("item") or "")
        else:
            wish = self.find_wish(umo=umo)
            if wish:
                item = str(wish.get("item") or "")
        wish_id = str(wish.get("id") or "")
        if not item:
            item, wish_id = await self._wish_from_recent_bot(umo)
        if not item or not valid_item(item):
            logger.info("[amo] 主人说了送礼，但没识别出东西: %s" % text[:60])
            return GIFT_ASK_HINT.format(raw=text[:120])
        kind = self.classify(item)
        if any(word in item for word in FOOD_WORDS):
            logger.info("[amo] 吃的喝的按人设不假装能吃到: %s" % item)
            return GIFT_FOOD_HINT.format(raw=text[:120], item=item)
        if any(word in item for word in IMPOSSIBLE_WORDS):
            logger.info("[amo] 拿不到的东西不假装收到: %s" % item)
            return GIFT_IMPOSSIBLE_HINT.format(raw=text[:120], item=item)
        if kind in ("vehicle", "home", "luxury") and not self.big_allowed:
            logger.info("[amo] 拒收太贵的礼物: %s" % item)
            return GIFT_TOO_EXPENSIVE_HINT.format(raw=text[:120], item=item)
        similar = self._recent_gift_like(item)
        if similar:
            return GIFT_ALREADY_HINT.format(item=similar.get("item") or item)
        uid = self._uid(event)
        gift = self.add_gift(
            item=item, raw=text, umo=umo, uid=uid,
            wish_id=wish_id, source="chat",
            place=str(wish.get("place") or ""),
        )
        if not gift:
            return ""
        self._just_gifted[umo] = now
        kind = gift.get("kind") or kind
        self._nudge_mood(kind)
        self._remember_gift(uid, gift.get("item") or item, kind)
        logger.info("[amo] 记下礼物: %s（%s，来自 %s）" % (gift.get("item"), kind, text[:40]))
        return self._build_ack(gift, item, text, wish, kind)

    def _build_ack(self, gift, item, text, wish, kind):
        """收下礼物时的现场提示：地点、季节、笼统名字都按实际情况补。"""
        item = str(gift.get("item") or item)
        where = ""
        place = self._short_place(wish.get("place") or "")
        if place:
            where = "这是你之前在%s看中的。" % place
        season = ""
        temp = self._temp()
        if temp is not None and temp >= 20 and any(word in item for word in WARM_WEAR_WORDS):
            season = "现在%d℃，这么热你收下但不会马上围/穿，会顺口说等天冷再戴。" % int(temp)
        detail = ""
        if item in GENERIC_ITEMS:
            detail = ("他说的只是笼统的「%s」，你并没有具体样子；"
                      "可以顺口问一句什么颜色/什么款，别编细节。" % item)
        template = GIFT_ACK_HINT if kind in ("small", "valuable") else GIFT_BIG_ACK_HINT
        return template.format(
            raw=text[:120], item=item, where=where, season=season, detail=detail,
        )

    @staticmethod
    def _message_key(event, text):
        try:
            msg_id = str(getattr(event.message_obj, "message_id", "") or "")
        except Exception:
            msg_id = ""
        return (msg_id + "|" + text[:60]) if msg_id else ""

    async def _wish_from_recent_bot(self, umo):
        """她/他最近的话里找送礼对象：先看数据库里的真实对话，再看内存尾巴。"""
        gifted = {
            gift.get("item") for gift in self.recent_gifts(limit=60)
            if time.time() - float(gift.get("ts") or 0) <= self.ttl
        }
        lines = []
        try:
            for row in self.plugin.db.recent_messages(umo, 10) or []:
                content = str(row.get("content") or "").strip()
                if content:
                    lines.append((float(row.get("created_at") or 0), str(row.get("role") or ""), content))
        except Exception:
            pass
        for ts, text in self._user_tail.get(umo, [])[-8:]:
            lines.append((ts, "user", text))
        for ts, text in self._bot_tail.get(umo, [])[-8:]:
            lines.append((ts, "bot", text))
        lines.sort(key=lambda item: item[0], reverse=True)

        for _, role, text in lines:
            if role == "user":
                item = self._liked_object_from_user(text)
                if item and item not in gifted:
                    wish = self.add_wish(item, text, umo=umo, source="backfill")
                    return str(wish.get("item") or item), str(wish.get("id") or "")
                continue
            if not has_wish_cue(text):
                continue
            item = ""
            if self._bool("gift_extract_with_llm", True):
                try:
                    item = await asyncio.wait_for(self._llm_extract_wish(text), timeout=12)
                except Exception:
                    item = ""
            if not item:
                item = extract_wish_regex(text)
            if item and valid_item(item) and item not in gifted:
                wish = self.add_wish(item, text, umo=umo, source="backfill")
                return str(wish.get("item") or item), str(wish.get("id") or "")
        return "", ""

    def _remember_user(self, umo, text):
        if not umo or not text:
            return
        tail = self._user_tail.setdefault(umo, [])
        tail.append((time.time(), text[:300]))
        del tail[:-8]

    @staticmethod
    def _liked_object_from_user(text):
        for match in _USER_LIKED_RE.finditer(text or ""):
            item = clean_item(match.group("obj"))
            if valid_item(item):
                return item
        return ""

    # ---------- 主流程：她的心愿 ----------
    def observe_reply(self, event, text):
        if not self.enabled or not self._bool("gift_capture_wishes", True):
            return
        try:
            umo = str(getattr(event, "unified_msg_origin", "") or "")
        except Exception:
            return
        text = (text or "").strip()
        if not text:
            return
        tail = self._bot_tail.setdefault(umo, [])
        tail.append((time.time(), text[:400]))
        if len(tail) > 10:
            del tail[:-10]
        if self._bool("gift_capture_private_only", True) and not self._private(event):
            return
        if self._bool("gift_only_shopping", True) and not self.is_shopping():
            return
        if self._looks_like_command(text) or self._self_output(text):
            return
        if time.time() - float(self._just_gifted.get(umo, 0)) < 90:
            return
        if not has_wish_cue(text):
            return
        uid = self._uid(event)
        self._spawn(self._extract_and_store(text, umo, uid))

    @staticmethod
    def _self_output(text):
        text = (text or "").strip()
        return any(text.startswith(prefix) for prefix in _SELF_OUTPUT_PREFIXES)

    async def _extract_and_store(self, text, umo, uid):
        item = ""
        if self._bool("gift_extract_with_llm", True):
            try:
                item = await asyncio.wait_for(self._llm_extract_wish(text), timeout=25)
            except Exception as exc:
                logger.debug("[amo] 礼物心愿抽取失败: %s" % exc)
        if not item:
            item = extract_wish_regex(text)
        if item and valid_item(item):
            wish = self.add_wish(item, text, umo=umo, uid=uid, source="chat")
            if wish:
                logger.info("[amo] 记下心愿: %s（原话：%s）" % (wish.get("item"), text[:40]))

    async def _llm_extract_wish(self, text):
        provider = None
        try:
            provider = await self.plugin.context.get_using_provider_async()
        except Exception:
            try:
                provider = self.plugin.context.get_using_provider()
            except Exception:
                provider = None
        if provider is None:
            return ""
        resp = await provider.text_chat(
            prompt="她说：" + text[:400],
            system_prompt=WISH_EXTRACT_SYSTEM,
            session_id="amo-gift-wish-" + uuid.uuid4().hex,
        )
        raw = getattr(resp, "completion_text", "") or ""
        return self._parse_wish_json(raw)

    @staticmethod
    def _parse_wish_json(raw):
        if not raw:
            return ""
        match = re.search(r"\{.*?\}", raw, re.S)
        if not match:
            return ""
        try:
            data = json.loads(match.group(0))
        except Exception:
            return ""
        try:
            confidence = float(data.get("confidence", 0) or 0)
        except Exception:
            confidence = 0.0
        if confidence < 0.45:
            return ""
        item = clean_item(str(data.get("item") or ""))
        return item if valid_item(item) else ""

    # ---------- 状态 / 记忆 ----------
    def _nudge_mood(self, kind="small"):
        try:
            if kind in ("vehicle", "home", "luxury"):
                self.plugin.state.nudge(开心=10, 兴奋=8, 依恋=6)
            elif kind == "valuable":
                self.plugin.state.nudge(开心=8, 兴奋=5, 依恋=4)
            else:
                self.plugin.state.nudge(开心=6, 兴奋=4, 依恋=3)
        except Exception:
            pass

    def _remember_gift(self, uid, item, kind="small"):
        if not uid or not item:
            return
        try:
            day = time.strftime("%m月%d日", time.localtime())
            if kind in ("vehicle", "home", "luxury"):
                content = "%s他送了我%s，这么贵重的东西，我收下了。" % (day, item)
            elif kind == "valuable":
                content = "%s他送了我%s，我很喜欢，会好好用。" % (day, item)
            else:
                content = "%s他送了我%s，我很喜欢。" % (day, item)
            writer = getattr(self.plugin, "_external_memory_write", None)
            if callable(writer):
                writer(uid, content, "gift", 2)
        except Exception:
            pass

    # ---------- 提示词素材 ----------
    def _wall_topic(self, text):
        if not self._bool("gift_inject_wall", True):
            return False
        gifts = self.recent_gifts(limit=12)
        if not gifts:
            return False
        if re.search(r"(礼物|送你|送我的|送的|收到|收下|逛街|商场|生日|纪念日|节日|惊喜|心愿|戴着|穿着)", text):
            return True
        for gift in gifts:
            item = str(gift.get("item") or "")
            if item and (item in text or (len(item) >= 3 and (item[:2] in text or item[-2:] in text))):
                return True
        return False

    @staticmethod
    def _asks_about_wishes(text):
        return bool(re.search(r"(想要什么|想要啥|喜欢什么|喜欢啥|要什么|心愿|礼物|生日|惊喜|送你|给你买|给你安排)", text))

    @staticmethod
    def _asset_topic(text):
        return bool(re.search(r"(车|房|开|住|上班|下班|出门|回家|家里|戴|礼物|送你|生日|搬|周末)", text))

    def _wall_text(self):
        limit = max(1, self._int("gift_max_wall_items", 8))
        return wall_text(self.recent_gifts(limit=limit))

    def _wish_list_text(self):
        wishes = [wish for wish in self.recent_wishes(limit=8) if self.classify(wish.get("item")) == "small"]
        return "、".join(
            "%s（%s）" % (wish.get("item", ""), fmt_day(wish.get("ts")))
            for wish in wishes[:5] if wish.get("item")
        )

    # ---------- 命令 ----------
    def command_text(self):
        wishes = self.recent_wishes(limit=6)
        gifts = self.recent_gifts(limit=10)
        lines = []
        if wishes:
            lines.append("她最近想要：")
            for wish in wishes:
                lines.append("· %s（%s）" % (wish.get("item", ""), fmt_day(wish.get("ts"))))
        if gifts:
            lines.append("她收到的礼物：")
            for gift in gifts:
                lines.append("· %s —— %s" % (gift.get("item", ""), fmt_day(gift.get("ts"))))
        if not lines:
            lines.append("还没有心愿和礼物。她聊天时说想要什么，或者你直接说「送给你」，就记下来了。")
        return "\n".join(lines)

    def manual_gift(self, event, item):
        """命令/面板手动送礼：走和聊天送礼同一套检查（开关/大件/吃的/拿不到/送过的）。"""
        if not self.enabled:
            return ""
        item = clean_item(item or "")
        if not valid_item(item):
            return "用法：/送礼 一条围巾"
        kind = self.classify(item)
        if any(word in item for word in FOOD_WORDS):
            return GIFT_FOOD_HINT.format(raw=item[:120], item=item)
        if any(word in item for word in IMPOSSIBLE_WORDS):
            return GIFT_IMPOSSIBLE_HINT.format(raw=item[:120], item=item)
        if kind in ("vehicle", "home", "luxury") and not self.big_allowed:
            logger.info("[amo] 命令送礼：大件默认不收: %s" % item)
            return GIFT_TOO_EXPENSIVE_HINT.format(raw=item[:120], item=item)
        similar = self._recent_gift_like(item)
        if similar:
            return GIFT_ALREADY_HINT.format(item=similar.get("item") or item)
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        uid = self._uid(event)
        gift = self.add_gift(item=item, raw="命令送礼", umo=umo, uid=uid, source="command")
        if not gift:
            return "这个没记住（名字太短或者不像个东西）。"
        self._just_gifted[umo] = time.time()
        kind = gift.get("kind") or kind
        self._nudge_mood(kind)
        self._remember_gift(uid, gift.get("item") or item, kind)
        logger.info("[amo] 记下礼物（命令）: %s（%s）" % (gift.get("item"), kind))
        return "记下了：她收到了「%s」。下次聊天她会知道是你送的。" % gift.get("item", item)

    def purge_user(self, uid="", umos=()):
        """删掉某个人的心愿和礼物（按 uid 或会话地址匹配），返回删除条数。"""
        uid = str(uid or "").strip()
        umos = {str(item) for item in (umos or ()) if item}
        if not uid and not umos:
            return 0
        with self._lock:
            data = self._load()

            def _keep(entry):
                if uid and str(entry.get("uid") or "") == uid:
                    return False
                if umos and str(entry.get("umo") or "") in umos:
                    return False
                return True

            before = len(data["wishes"]) + len(data["gifts"])
            data["wishes"] = [item for item in data["wishes"] if _keep(item)]
            data["gifts"] = [item for item in data["gifts"] if _keep(item)]
            removed = before - (len(data["wishes"]) + len(data["gifts"]))
            if removed:
                self._save()
            for umo in umos:
                for cache in (self._bot_tail, self._user_tail, self._just_gifted,
                              self._seen_gift, self._last_shop_hint):
                    try:
                        cache.pop(umo, None)
                    except Exception:
                        pass
        return max(0, removed)

    # ---------- 任务 ----------
    def _spawn(self, coro):
        try:
            task = asyncio.create_task(coro)
        except RuntimeError:
            return
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task):
        self._tasks.discard(task)
        try:
            exc = task.exception()
        except Exception:
            exc = None
        if exc:
            logger.debug("[amo] 礼物后台任务异常: %s" % exc)
