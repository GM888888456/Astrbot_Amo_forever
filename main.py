# -*- coding: utf-8 -*-
"""
我想永远陪着你 / 我想永远陪着你-终端 5.4.2
一个尽量“像人”的 AstrBot 智械人类核心：
生理期 / 九维心情 / 世界观与日程 / 天气 / 健康 / 群聊插话阈值 /
私聊判定 / 主动私聊 / 长期记忆与遗忘 / 防抖 / 分段与打字延迟 / 引用回复 / AI 润色
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import os
import random
import re
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone

# 统一时区：容器/服务器常在 UTC 跑，直接取服务器本地时间会把北京时间 10 点算成凌晨 2 点
# （「大晚上的」就是这么来的）。clock.now() 返回目标时区下的 naive 本地时间，
# 和原来的用法完全兼容。
try:
    from .clock import now as _clock_now, configure as _clock_configure, current_name as _clock_name
except Exception:
    try:
        from clock import now as _clock_now, configure as _clock_configure, current_name as _clock_name
    except Exception:
        def _clock_now(*args, **kwargs):
            return datetime.now()

        def _clock_configure(*args, **kwargs):
            return ""

        def _clock_name(*args, **kwargs):
            return ""


def _now():
    """目标时区下的「现在」（naive，便于和原代码里 datetime 运算混用）。"""
    return _clock_now()

try:
    import astrbot.api.message_components as Comp
except Exception:
    Comp = None

from astrbot.api import logger

# ---- 画图 / 照片分享（本地功能，接万象画卷 OmniDraw）----
try:
    from .wardrobe import Wardrobe, SCENE_LABELS
    from .wardrobe import build_items_from_catalog as build_wardrobe_items
except Exception:  # 直接按文件加载时
    try:
        from wardrobe import Wardrobe, SCENE_LABELS  # type: ignore
        from wardrobe import build_items_from_catalog as build_wardrobe_items  # type: ignore
    except Exception:
        Wardrobe = None
        build_wardrobe_items = None
        SCENE_LABELS = {}

try:
    from .outfit_engine import OutfitEngine
except Exception:  # 直接按文件加载时
    try:
        from outfit_engine import OutfitEngine  # type: ignore
    except Exception:
        OutfitEngine = None

try:
    from .draw_engine import DrawEngine
    from .photo_engine import PhotoEngine
    from .sleep_cycle import (
        GO_SLEEP_WORDS,
        WAKE_WORDS,
        SleepAnswer,
        SleepCycle,
        SleepPhase,
        reason_for,
    )
except ImportError:  # 直接按文件加载时
    try:
        from draw_engine import DrawEngine
        from photo_engine import PhotoEngine
        try:
            from sleep_cycle import (
                GO_SLEEP_WORDS,
                WAKE_WORDS,
                SleepAnswer,
                SleepCycle,
                SleepPhase,
                reason_for,
            )
        except ImportError:  # pragma: no cover
            SleepCycle = None
    except Exception:  # 没装/导入失败时不影响主脑启动
        DrawEngine = None
        PhotoEngine = None

try:
    from .day_types import normalize_day_types, pick_day_type
except Exception:
    try:
        from day_types import normalize_day_types, pick_day_type
    except Exception:
        normalize_day_types = None
        pick_day_type = None

try:
    from .schedule_change import apply_change as apply_sched_change, detect_schedule_change
except Exception:
    try:
        from schedule_change import apply_change as apply_sched_change, detect_schedule_change
    except Exception:
        detect_schedule_change = None
        apply_sched_change = None
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

try:
    from astrbot.api.event import MessageChain
except Exception:
    try:
        from astrbot.core.message.message_event_result import MessageChain
    except Exception:
        MessageChain = None

try:
    from astrbot.api.web import request as web_request
except Exception:
    try:
        from quart import request as web_request
    except Exception:
        web_request = None

try:
    from astrbot.core.agent.message import TextPart
except Exception:
    TextPart = None

try:
    from .heartflow_engine import HeartflowEngine
    from .segment_engine import SegmentEngine
except Exception:
    try:
        from heartflow_engine import HeartflowEngine
        from segment_engine import SegmentEngine
    except Exception:
        HeartflowEngine = None
        SegmentEngine = None
        try:
            import importlib.util
            _engine_dir = os.path.dirname(os.path.abspath(__file__))
            def _load_engine(module_name, class_name):
                _spec = importlib.util.spec_from_file_location(
                    "amo_" + module_name,
                    os.path.join(_engine_dir, module_name + ".py"),
                )
                _module = importlib.util.module_from_spec(_spec)
                _spec.loader.exec_module(_module)
                return getattr(_module, class_name)
            HeartflowEngine = _load_engine("heartflow_engine", "HeartflowEngine")
            SegmentEngine = _load_engine("segment_engine", "SegmentEngine")
        except Exception as _engine_exc:
            logger.error("[amo] 内置心流/分段模块加载失败: %s" % _engine_exc)

try:
    from .weather_alert import evaluate as evaluate_weather_alert, parse_daily as parse_weather_daily, next_check_slot, parse_clock, slot_key, is_weather_query, forecast_brief
except Exception:
    try:
        from weather_alert import evaluate as evaluate_weather_alert, parse_daily as parse_weather_daily, next_check_slot, parse_clock, slot_key, is_weather_query, forecast_brief
    except Exception:
        def evaluate_weather_alert(*args, **kwargs):
            return ""
        def parse_weather_daily(*args, **kwargs):
            return []

        # 天气模块没装上时的兜底（原来挂在礼物导入下面，礼物删掉后挪回来）
        def next_check_slot(*args, **kwargs):
            return ""
        def parse_clock(*args, **kwargs):
            return 0
        def slot_key(today, slot):
            return "%s|%s" % (today, slot)
        def is_weather_query(*args, **kwargs):
            return False
        def forecast_brief(*args, **kwargs):
            return ""

try:
    from .proactive_guard import analyze_rows as _pg_analyze_rows, compose_task as _pg_compose_task, near_duplicate as _pg_near_duplicate
except Exception:
    try:
        from proactive_guard import analyze_rows as _pg_analyze_rows, compose_task as _pg_compose_task, near_duplicate as _pg_near_duplicate
    except Exception:
        _pg_analyze_rows = _pg_compose_task = _pg_near_duplicate = None

try:
    from .time_recall import looks_like_time_query as _looks_like_time_query, render_time_block as _render_time_block
except Exception:
    try:
        from time_recall import looks_like_time_query as _looks_like_time_query, render_time_block as _render_time_block
    except Exception:
        def _looks_like_time_query(*args, **kwargs):
            return False

        def _render_time_block(*args, **kwargs):
            return ""

try:
    from .greet_route import greeting_targets as _greeting_targets, within_minutes as _within_minutes
except Exception:
    try:
        from greet_route import greeting_targets as _greeting_targets, within_minutes as _within_minutes
    except Exception:
        logger.warning("[amo] greet_route 载入失败，问候平台随机功能不可用")

        def _greeting_targets(candidates, primary="", randomize=True, rng=None):
            items = []
            for umo in list(candidates or []) + [primary]:
                value = str(umo or "")
                if value and value not in items:
                    items.append(value)
            return items if randomize else ([primary] if primary else [])

        def _within_minutes(last_ts, now, minutes):
            return False

try:
    from .diary_lines import (
        DIARY_WRITTEN_REPLIES as _DIARY_WRITTEN,
        DIARY_SHOW_REPLIES as _DIARY_SHOW,
        pick_hints as _diary_pick_hints,
    )
except Exception:
    try:
        from diary_lines import (
            DIARY_WRITTEN_REPLIES as _DIARY_WRITTEN,
            DIARY_SHOW_REPLIES as _DIARY_SHOW,
            pick_hints as _diary_pick_hints,
        )
    except Exception:
        _DIARY_WRITTEN = ["写了", "写了，不给你看", "写了，秘密"]
        _DIARY_SHOW = ["不行，你不能偷看我的日记哦", "那是我的日记，才不给你看", "你想得美"]

        def _diary_pick_hints(items, count=8, seed=""):
            return list(items)[:count]

try:
    from .diary_engine import (
        DEFAULT_DIR as _DIARY_DEFAULT_DIR,
        resolve_dir as _diary_resolve_dir,
        parse_day as _diary_parse_day,
        build_prompt as _diary_build_prompt,
        import_folder as _diary_import_folder,
        write_diary as _diary_write,
        read_diary as _diary_read,
        list_tree as _diary_tree,
    )
except Exception:
    try:
        from diary_engine import (
            DEFAULT_DIR as _DIARY_DEFAULT_DIR,
            resolve_dir as _diary_resolve_dir,
            parse_day as _diary_parse_day,
            build_prompt as _diary_build_prompt,
            import_folder as _diary_import_folder,
        build_prompt as _diary_build_prompt,
            write_diary as _diary_write,
            read_diary as _diary_read,
            list_tree as _diary_tree,
                )
    except Exception:
        _DIARY_DEFAULT_DIR = ""
        _diary_resolve_dir = None
        _diary_parse_day = _diary_write = _diary_read = _diary_tree = _diary_import_folder = None

try:
    from .milestone import (
        should_archive as _ms_should_archive,
        transcript as _ms_transcript,
        build_prompt as _ms_build_prompt,
        build_content as _ms_build_content,
    )
except Exception:
    try:
        from milestone import (
            should_archive as _ms_should_archive,
            transcript as _ms_transcript,
            build_prompt as _ms_build_prompt,
            build_content as _ms_build_content,
        )
    except Exception:
        def _ms_should_archive(*args, **kwargs):
            return False

        def _ms_transcript(*args, **kwargs):
            return ""

        def _ms_build_prompt(*args, **kwargs):
            return ""

        def _ms_build_content(*args, **kwargs):
            return ""

try:
    from .wander import (
        assess as _wander_assess,
        ask_limit as _wander_ask_limit,
        detect_agreement as _wander_agree,
        detect_question as _wander_question,
        detect_follow_invite as _follow_invite,
        detect_follow_refuse as _follow_refuse,
        detect_refusal as _wander_refuse,
        follow_agree_text as _wander_follow_agree_text,
        follow_block as _follow_block,
        offer_block as _wander_offer_block,
        offer_text as _wander_offer_text,
        pick_destination as _wander_pick,
        plan_text as _wander_plan_text,
        solo_agree_text as _wander_solo_agree_text,
        solo_block as _wander_solo_block,
        solo_refuse_text as _wander_solo_refuse_text,
        trip_days as _wander_trip_days,
        want_travel as _wander_want,
    )
except Exception:
    try:
        from wander import (
            assess as _wander_assess,
            ask_limit as _wander_ask_limit,
            detect_agreement as _wander_agree,
            detect_question as _wander_question,
            detect_follow_invite as _follow_invite,
            detect_follow_refuse as _follow_refuse,
            detect_refusal as _wander_refuse,
            follow_agree_text as _wander_follow_agree_text,
            follow_block as _follow_block,
            offer_block as _wander_offer_block,
            offer_text as _wander_offer_text,
            pick_destination as _wander_pick,
            plan_text as _wander_plan_text,
            solo_agree_text as _wander_solo_agree_text,
            solo_block as _wander_solo_block,
            solo_refuse_text as _wander_solo_refuse_text,
            trip_days as _wander_trip_days,
            want_travel as _wander_want,
        )
    except Exception:
        def _wander_assess(*args, **kwargs):
            return (False, False)

        def _wander_agree(*args, **kwargs):
            return False

        def _wander_question(*args, **kwargs):
            return False

        def _wander_refuse(*args, **kwargs):
            return False

        def _follow_block(*args, **kwargs):
            return ""

        def _follow_invite(*args, **kwargs):
            return False

        def _follow_refuse(*args, **kwargs):
            return False

        def _wander_follow_agree_text(*args, **kwargs):
            return ""

        def _wander_offer_block(*args, **kwargs):
            return ""

        def _wander_offer_text(*args, **kwargs):
            return ""

        def _wander_pick(*args, **kwargs):
            return ("", [])

        def _wander_plan_text(*args, **kwargs):
            return ""

        def _wander_ask_limit(*args, **kwargs):
            return 1

        def _wander_solo_agree_text(*args, **kwargs):
            return ""

        def _wander_solo_block(*args, **kwargs):
            return ""

        def _wander_solo_refuse_text(*args, **kwargs):
            return ""

        def _wander_trip_days(*args, **kwargs):
            return 1

        def _wander_want(*args, **kwargs):
            return False

try:
    from .memory_hooks import MemoryHub, render_recent_block
except Exception:
    try:
        from memory_hooks import MemoryHub, render_recent_block
    except Exception:
        MemoryHub = None
        render_recent_block = None

try:
    from .attribution import first_person_experience, attribution_leak, leak_tokens
except Exception:
    try:
        from attribution import first_person_experience, attribution_leak, leak_tokens
    except Exception:
        first_person_experience = attribution_leak = leak_tokens = None

try:
    from .brushoff import strip_brushoff
except Exception:
    try:
        from brushoff import strip_brushoff
    except Exception:
        strip_brushoff = None

try:
    from .relation_learn import parse_relations
except Exception:
    try:
        from relation_learn import parse_relations
    except Exception:
        parse_relations = None

try:
    from .city_follow import (
        DEFAULT_CITY as _CITY_DEFAULT,
        detect_city as _city_detect,
        compose_block as _city_block,
        travel_block as _city_travel_block,
        travel_events as _city_travel_events,
        travel_action as _city_travel_action,
        travel_to_events as _city_travel_to_events,
        pick_spots as _city_pick_spots,
    )
except Exception:
    try:
        from city_follow import (
            DEFAULT_CITY as _CITY_DEFAULT,
            detect_city as _city_detect,
            compose_block as _city_block,
            travel_block as _city_travel_block,
            travel_events as _city_travel_events,
            travel_action as _city_travel_action,
            travel_to_events as _city_travel_to_events,
            pick_spots as _city_pick_spots,
        )
    except Exception:
        _CITY_DEFAULT = "东莞"

        def _city_pick_spots(*args, **kwargs):
            return []

        def _city_travel_to_events(*args, **kwargs):
            return []

        def _city_travel_action(*args, **kwargs):
            return "none"

        def _city_detect(*args, **kwargs):
            return None

        def _city_block(*args, **kwargs):
            return ""

        def _city_travel_block(*args, **kwargs):
            return ""

        def _city_travel_events(*args, **kwargs):
            return []


try:
    from .relation_graph import rank_edges as _rank_edges
except Exception:
    try:
        from relation_graph import rank_edges as _rank_edges
    except Exception:
        _rank_edges = None

try:
    from .relation_sediment import plan_edges as plan_relation_edges
except Exception:
    try:
        from relation_sediment import plan_edges as plan_relation_edges
    except Exception:
        plan_relation_edges = None

try:
    from .schedule_engine import ScheduleEngine
except Exception:
    try:
        from schedule_engine import ScheduleEngine
    except Exception:
        try:
            import importlib.util as _importlib_util
            _schedule_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedule_engine.py")
            _schedule_spec = _importlib_util.spec_from_file_location("amo_schedule_engine", _schedule_path)
            _schedule_module = _importlib_util.module_from_spec(_schedule_spec)
            _schedule_spec.loader.exec_module(_schedule_module)
            ScheduleEngine = getattr(_schedule_module, "ScheduleEngine")
        except Exception as _schedule_exc:
            ScheduleEngine = None
            logger.error("[amo] 日程引擎加载失败: %s" % _schedule_exc)


try:
    from .memory_scope import private_rows as _private_rows
except Exception:
    try:
        from memory_scope import private_rows as _private_rows
    except Exception:
        # 模块缺失时退回「不过滤」，别把总结整段停掉
        def _private_rows(rows):
            return list(rows or [])

PLUGIN_NAME = "Astrbot_Amo_forever"
PLUGIN_VERSION = "9.2.0"


_VOICE_TAG_OPEN_RE = re.compile(r"<(?:astrbot_speak|amo_speak)\b([^>]*)>", re.I)
_VOICE_TAG_RE = re.compile(r"</?(?:astrbot_speak|amo_speak)\b[^>]*>", re.I)


def _strip_voice_tags(text: str) -> str:
    """模型偶尔不调 amo_speak 工具，直接输出 <astrbot_speak text="..."> 这种伪标签。
    这里只取要念的那句话，别把标签念出来，也别让整条回复消失。"""
    body = str(text or "")
    m = _VOICE_TAG_OPEN_RE.search(body)
    if m:
        attr = m.group(1) or ""
        am = re.search(r'text\s*=\s*"([^"]*)"', attr) or re.search(r"text\s*=\s*'([^']*)'", attr)
        if am and am.group(1).strip():
            return strip_pseudo_tags(am.group(1).strip())
        tail = body[m.end():]
        close = re.search(r"</(?:astrbot_speak|amo_speak)>", tail, re.I)
        if close:
            return strip_pseudo_tags(tail[: close.start()].strip())
    return strip_pseudo_tags(_VOICE_TAG_RE.sub("", body))
try:  # 版本号以 metadata.yaml 为准，避免两处不一致
    import yaml as _amo_meta_yaml
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "metadata.yaml"),
              encoding="utf-8") as _amo_meta_fh:
        _amo_meta = _amo_meta_yaml.safe_load(_amo_meta_fh) or {}
    if _amo_meta.get("version"):
        PLUGIN_VERSION = str(_amo_meta["version"])
except Exception:
    pass

# 这些开关是面板/主链路的底座：隐藏开关并强制开启，避免误关后整块功能消失。
FORCED_ON_CONFIG_KEYS = frozenset({
    "enable_group_reply", "enable_private_reply", "hf_enable_heartflow",
    "seg_enable", "diary_enabled", "usage_stats_enabled",
})

#: 面板不展示、但仍可从配置文件改的键。
#: 评分规则决定「什么叫值得回」，改错了她会变得很奇怪；绝大多数人不需要动它。
PANEL_HIDDEN_KEYS = frozenset({"hf_judge_rules"})
DEFAULT_ADMIN = ""
LEGACY_DEFAULT_ADMIN = "3261748099"
LEGACY_MEMORY_PLUGIN = "astrbot_plugin_private_companion"

RELATIONS = ("仇恨", "抵触", "普通", "熟识", "相恋")
DIALECT_SAMPLES = {
    "贵州话": "晓得、咋个、要得、安逸",
    "东北话": "咋整、唠嗑、得瑟、麻溜",
    "四川话": "啥子、莫得、巴适、搞快些",
    "广东话": "唔该、点解、得闲、搞掂",
    "台湾腔": "酱紫、蛮、超赞、拍谢",
    "天津话": "嘛呢、倍儿、哏儿、得嘞",
    "河南话": "弄啥嘞、中、得劲、木有",
    "上海话": "阿拉、侬、哪能、老灵",
}
CITY_DIALECT_RULES = (
    (("贵阳", "贵州", "遵义", "安顺", "六盘水", "凯里"), "贵州话"),
    (("成都", "四川", "重庆", "绵阳", "德阳", "宜宾"), "四川话"),
    (("广州", "深圳", "东莞", "佛山", "珠海", "中山", "惠州", "江门", "汕头", "广东"), "广东话"),
    (("上海", "苏州", "无锡", "常州", "昆山"), "上海话"),
    (("天津",), "天津话"),
    (("郑州", "河南", "洛阳", "开封"), "河南话"),
    (("哈尔滨", "沈阳", "长春", "大连", "东北", "辽宁", "吉林", "黑龙江"), "东北话"),
    (("台北", "台湾", "高雄", "台中"), "台湾腔"),
)


def dialect_for_city(city):
    text = str(city or "")
    if not text:
        return ""
    for keys, style in CITY_DIALECT_RULES:
        if any(key in text for key in keys):
            return style
    return ""


DIALECT_FALLBACK_ROWS = {
    "东北话": [
        ("咋整", "怎么办", "咋整啊"), ("唠嗑", "聊天", "来唠嗑"), ("得瑟", "显摆", "别得瑟"),
        ("麻溜", "快点", "麻溜的"), ("贼拉", "非常", "贼拉冷"), ("嘎哈", "干什么", "你嘎哈呢"),
        ("老铁", "哥们", "老铁没毛病"),
    ],
    "四川话": [
        ("啥子", "什么", "你说啥子"), ("莫得", "没有", "莫得问题"), ("巴适", "舒服", "巴适得很"),
        ("搞快些", "快点", "搞快些"), ("瓜娃子", "傻孩子", "你个瓜娃子"), ("雄起", "加油", "雄起"),
        ("撇脱", "干脆", "撇脱点"),
    ],
    "广东话": [
        ("唔该", "谢谢、劳驾", "唔该晒"), ("点解", "为什么", "点解啊"), ("得闲", "有空", "得闲饮茶"),
        ("搞掂", "搞定", "搞掂啦"), ("靓仔", "帅哥", "靓仔"), ("靓女", "美女", "靓女"),
        ("冇", "没有", "冇问题"),
    ],
    "台湾腔": [
        ("酱紫", "这样", "酱紫啊"), ("蛮", "很", "蛮好的"), ("超赞", "非常棒", "超赞"),
        ("拍谢", "不好意思", "拍谢啦"), ("机车", "麻烦、烦人", "很机车"), ("阿嬷", "奶奶", "阿嬷"),
        ("龟毛", "挑剔", "别龟毛"),
    ],
    "天津话": [
        ("嘛呢", "干什么", "嘛呢"), ("倍儿", "非常", "倍儿好"), ("哏儿", "有趣", "真哏儿"),
        ("得嘞", "好的", "得嘞"), ("腻歪", "腻烦、黏人", "别腻歪"), ("幺蛾子", "麻烦", "出幺蛾子"),
        ("耐人", "招人喜欢", "真耐人"),
    ],
    "河南话": [
        ("弄啥嘞", "干什么", "你弄啥嘞"), ("中", "好", "中，就这么办"), ("得劲", "舒服", "真得劲"),
        ("木有", "没有", "木有事"), ("恁", "你", "恁吃饭没"), ("俺", "我", "俺知道了"),
        ("中不中", "行不行", "中不中"),
    ],
    "上海话": [
        ("阿拉", "我、我们", "阿拉晓得"), ("侬", "你", "侬好"), ("哪能", "怎么", "哪能办"),
        ("结棍", "厉害", "侬结棍"), ("老灵", "很好", "老灵额"), ("白相", "玩", "出去白相"),
        ("适意", "舒服", "适意"),
    ],
}
DIALECT_REGIONS = {
    "贵州话": "贵州",
    "东北话": "东北",
    "四川话": "四川",
    "广东话": "广东",
    "台湾腔": "台湾",
    "天津话": "天津",
    "河南话": "河南",
    "上海话": "上海",
}
SCHEDULE_VERSION = "backbone-v6"
OUTFIT_VERSION = "outfit-v5"  # 穿搭规则变了就改这里，旧日程会自动重配
DIARY_WARM_VERSION = "diary-v2"  # 小日记规则变了就改这里，会重新预生成
NETWORK_RELATIONS = ("家人", "恋人", "朋友", "同事", "同学", "熟人", "陌生人", "仇人")
try:
    from .amo_enums import MOOD_KEYS, ActivityCategory, MoodKey, SceneZone, coerce, value_of
except ImportError:  # 直接按文件加载时
    from amo_enums import MOOD_KEYS, ActivityCategory, MoodKey, SceneZone, coerce, value_of

try:
    from .heartflow import Heartflow as HeartflowCore, HeartflowEvent as FeelEvent
except ImportError:  # pragma: no cover
    try:
        from heartflow import Heartflow as HeartflowCore, HeartflowEvent as FeelEvent
    except ImportError:
        HeartflowCore = None
        FeelEvent = None

try:
    from .private_shots import (
        GRANT_LINES,
        SCOLD_LINES,
        SHY_LINES,
        Verdict as ShotVerdict,
        build_prompt as build_shot_prompt,
        decide as decide_shot,
        detect_outfit as shot_outfit,
        detect_pose as shot_pose,
        wants_private_shot,
    )
except ImportError:  # pragma: no cover
    try:
        from private_shots import (
            GRANT_LINES,
            SCOLD_LINES,
            SHY_LINES,
            Verdict as ShotVerdict,
            build_prompt as build_shot_prompt,
            decide as decide_shot,
            detect_outfit as shot_outfit,
            detect_pose as shot_pose,
            wants_private_shot,
        )
    except ImportError:
        wants_private_shot = None

try:
    from .memory_guard import commit as _mem_commit, prepare as _mem_prepare
except ImportError:  # pragma: no cover
    try:
        from memory_guard import commit as _mem_commit, prepare as _mem_prepare
    except ImportError:
        _mem_prepare = None
        _mem_commit = None
#: 真正算「生病」的状态；「疲惫」只是累，不该按病号排日程。
SICK_STATUSES = ("轻微不适", "感冒", "低烧", "发烧", "不舒服", "生病", "拉肚子")
MOOD_BASE = {
    "开心": 55, "平静": 60, "郁闷": 18, "生气": 8, "暴躁": 6, "委屈": 20,
    "疲惫": 28, "焦虑": 18, "兴奋": 30, "依恋": 45,
}
STYLE_HINTS = {
    "soft": "整体语气温柔、软一点。",
    "cool": "整体语气清淡、克制一点。",
    "lively": "整体语气活泼、有精神。",
    "mature": "整体语气成熟、稳一点。",
}

POS_WORDS = ("开心", "高兴", "哈哈", "笑死", "好耶", "喜欢", "爱你", "可爱", "棒", "不错",
             "太好了", "谢谢", "嘿嘿", "嘻嘻", "么么", "抱抱", "亲亲", "好吃", "好看")
NEG_WORDS = ("难过", "伤心", "哭", "烦", "累", "讨厌", "滚", "闭嘴", "无语", "失望",
             "委屈", "孤单", "想死", "崩溃", "气死", "不开心")
ANGRY_WORDS = ("滚", "闭嘴", "傻", "废物", "烦死", "气死", "去死", "恶心", "别烦", "有病")
SAD_WORDS = ("难过", "伤心", "想哭", "委屈", "孤单", "没人", "算了", "失望", "哭")
AFFECTION_WORDS = ("喜欢", "爱你", "想你", "抱抱", "亲亲", "贴贴", "宝贝", "老婆", "宝宝", "么么")
INSULT_WORDS = ("傻逼", "智障", "废物", "垃圾", "去死", "恶心", "滚")


# 关系网里的内部节点：bot/self 代表"我自己"，不是真实人物。
# 这种边只存在本地（_push_relation_to_data 不推给记忆终端），比较远端/本地时也要排掉，
# 否则远端永远比本地少一条，每 10 分钟误报一次"关系网不同步"。
INTERNAL_RELATION_NODES = ("bot", "self")


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def now_ts():
    return time.time()


CN_HOLIDAYS = {
    "2025-01-01": "元旦",
    "2025-01-28": "除夕", "2025-01-29": "春节", "2025-01-30": "春节", "2025-01-31": "春节", "2025-02-01": "春节", "2025-02-02": "春节", "2025-02-03": "春节", "2025-02-04": "春节",
    "2025-04-04": "清明",
    "2025-05-01": "劳动节",
    "2025-05-31": "端午",
    "2025-10-01": "国庆", "2025-10-02": "国庆", "2025-10-03": "国庆", "2025-10-04": "国庆", "2025-10-05": "国庆", "2025-10-07": "国庆", "2025-10-08": "国庆",
    "2025-10-06": "国庆中秋",
    "2026-01-01": "元旦",
    "2026-02-16": "除夕", "2026-02-17": "春节", "2026-02-18": "春节", "2026-02-19": "春节", "2026-02-20": "春节", "2026-02-21": "春节", "2026-02-22": "春节", "2026-02-23": "春节",
    "2026-04-05": "清明",
    "2026-05-01": "劳动节",
    "2026-06-19": "端午",
    "2026-09-25": "中秋",
    "2026-10-01": "国庆", "2026-10-02": "国庆", "2026-10-03": "国庆", "2026-10-04": "国庆", "2026-10-05": "国庆", "2026-10-06": "国庆", "2026-10-07": "国庆",
    "2027-01-01": "元旦",
    "2027-02-05": "除夕", "2027-02-06": "春节", "2027-02-07": "春节", "2027-02-08": "春节", "2027-02-09": "春节", "2027-02-10": "春节", "2027-02-11": "春节",
    "2027-04-05": "清明",
    "2027-05-01": "劳动节",
    "2027-06-09": "端午",
    "2027-09-15": "中秋",
    "2027-10-01": "国庆", "2027-10-02": "国庆", "2027-10-03": "国庆", "2027-10-04": "国庆", "2027-10-05": "国庆", "2027-10-06": "国庆", "2027-10-07": "国庆",
}

# 2026 年主要假期的连续日期（用于判断长假/短假）
for _d in range(1, 4):
    CN_HOLIDAYS.setdefault("2026-01-%02d" % _d, "元旦")
for _d in range(4, 7):
    CN_HOLIDAYS.setdefault("2026-04-%02d" % _d, "清明")
for _d in range(1, 6):
    CN_HOLIDAYS.setdefault("2026-05-%02d" % _d, "劳动节")
for _d in range(19, 22):
    CN_HOLIDAYS.setdefault("2026-06-%02d" % _d, "端午")
for _d in range(25, 28):
    CN_HOLIDAYS.setdefault("2026-09-%02d" % _d, "中秋")

SOLAR_TERMS = {
    "2025-01-05": "小寒", "2025-01-20": "大寒", "2025-02-03": "立春", "2025-02-18": "雨水", "2025-03-05": "惊蛰", "2025-03-20": "春分", "2025-04-04": "清明", "2025-04-20": "谷雨", "2025-05-05": "立夏", "2025-05-21": "小满", "2025-06-05": "芒种", "2025-06-21": "夏至", "2025-07-07": "小暑", "2025-07-22": "大暑", "2025-08-07": "立秋", "2025-08-23": "处暑", "2025-09-07": "白露", "2025-09-23": "秋分", "2025-10-08": "寒露", "2025-10-23": "霜降", "2025-11-07": "立冬", "2025-11-22": "小雪", "2025-12-07": "大雪", "2025-12-21": "冬至",
    "2026-01-05": "小寒", "2026-01-20": "大寒", "2026-02-04": "立春", "2026-02-18": "雨水", "2026-03-05": "惊蛰", "2026-03-20": "春分", "2026-04-05": "清明", "2026-04-20": "谷雨", "2026-05-05": "立夏", "2026-05-21": "小满", "2026-06-05": "芒种", "2026-06-21": "夏至", "2026-07-07": "小暑", "2026-07-23": "大暑", "2026-08-07": "立秋", "2026-08-23": "处暑", "2026-09-07": "白露", "2026-09-23": "秋分", "2026-10-08": "寒露", "2026-10-23": "霜降", "2026-11-07": "立冬", "2026-11-22": "小雪", "2026-12-07": "大雪", "2026-12-21": "冬至",
    "2027-01-05": "小寒", "2027-01-20": "大寒", "2027-02-04": "立春", "2027-02-19": "雨水", "2027-03-06": "惊蛰", "2027-03-21": "春分", "2027-04-05": "清明", "2027-04-20": "谷雨", "2027-05-06": "立夏", "2027-05-21": "小满", "2027-06-06": "芒种", "2027-06-21": "夏至", "2027-07-07": "小暑", "2027-07-23": "大暑", "2027-08-08": "立秋", "2027-08-23": "处暑", "2027-09-08": "白露", "2027-09-23": "秋分", "2027-10-08": "寒露", "2027-10-24": "霜降", "2027-11-08": "立冬", "2027-11-22": "小雪", "2027-12-07": "大雪", "2027-12-22": "冬至",
}


def day_meta(day=None):
    """返回某天的节日、节气和是否休息日。"""
    try:
        target = date.fromisoformat(str(day)) if day else _now().date()
    except Exception:
        target = _now().date()
    key = target.isoformat()
    holiday = CN_HOLIDAYS.get(key, "")
    term = SOLAR_TERMS.get(key, "")
    weekend = target.weekday() >= 5
    rest = bool(weekend or holiday)
    holiday_days = 0
    if holiday:
        cursor = target
        while CN_HOLIDAYS.get(cursor.isoformat()) == holiday:
            holiday_days += 1
            cursor -= timedelta(days=1)
        cursor = target + timedelta(days=1)
        while CN_HOLIDAYS.get(cursor.isoformat()) == holiday:
            holiday_days += 1
            cursor += timedelta(days=1)
    label = "、".join(item for item in (holiday, term) if item)
    if holiday_days >= 2:
        label += (" · " if label else "") + "%d天假期" % holiday_days
    if not label and weekend:
        label = "周末"
    return {
        "date": key,
        "weekday": "一二三四五六日"[target.weekday()],
        "weekend": weekend,
        "holiday": holiday,
        "solar_term": term,
        "holiday_days": holiday_days,
        "rest": rest,
        "label": label,
    }

def lark_quote_kwargs(is_private, message_id, sender_id, chat_id, quote):
    """飞书发送参数：决定走「引用回复」还是普通发送。

    AstrBot 的飞书适配器在 `LarkMessageEvent.send()` 里固定传
    `reply_message_id=self.message_obj.message_id`，所以不管私聊群聊、也不管
    `platform_settings.reply_with_quote`，每条消息都会变成飞书里的「回复」，
    私聊看起来就是一直在引用他上一条。

    - 私聊：普通发送（receive_id = 他的 open_id），不引用；
    - 群聊且按概率判定要引用：reply；
    - 群聊但不引用：普通发送（receive_id = 会话 chat_id）；
    - 拿不到 open_id / chat_id 时退回原来的 reply，宁可引用也别发不出去。
    """
    message_id = str(message_id or "")
    sender_id = str(sender_id or "")
    chat_id = str(chat_id or "")
    if is_private and sender_id:
        return {
            "receive_id": sender_id,
            "receive_id_type": "open_id",
            "fallback_chat_id": chat_id or None,
        }
    if quote and message_id:
        return {"reply_message_id": message_id}
    if chat_id:
        return {"receive_id": chat_id, "receive_id_type": "chat_id"}
    if message_id:
        return {"reply_message_id": message_id}
    return {}


def today_str():
    return _now().date().isoformat()


def other_platform_bot_lines(rows, umo, limit=3, platform=""):
    """从跨平台近聊里挑出「她自己说的、且不是当前会话」的几句话。

    主动消息以前只看当前会话的最近 12 句：QQ 上 08:48 说「等散会了跟你说」，
    之后一直没人说话，12:00 的主动消息就接着那场会往下说；与此同时飞书那边
    早就是「在便利店买饭」了。把她在别的平台刚说的话也放进去，两边才不会
    各讲各的故事（内容冲突时以当前状态为准，见 gen_proactive 的规则）。

    数据插件有的行没有 `umo`，所以再按 `platform` 兜一层，避免把本平台的
    话当成「另一边说过」。
    """
    umo = str(umo or "")
    platform = str(platform or "")
    out = []
    for row in rows or []:
        if str(row.get("role") or "") != "bot":
            continue
        if str(row.get("umo") or "") == umo:
            continue
        row_platform = str(row.get("platform") or "")
        if row_platform and platform and row_platform == platform:
            continue
        text = str(row.get("content") or "").strip().replace("\n", " ")
        if text:
            out.append(text)
    size = max(1, int(limit or 1))
    return out[-size:]


_CATEGORY_MOOD_CACHE = None


def schedule_category_mood():
    """日程类别 → 每小时心情增量（复用 schedule_engine.CATEGORY_MOOD）。"""
    global _CATEGORY_MOOD_CACHE
    if _CATEGORY_MOOD_CACHE is not None:
        return _CATEGORY_MOOD_CACHE
    table = {}
    try:
        from .schedule_engine import CATEGORY_MOOD as table
    except Exception:
        try:
            from schedule_engine import CATEGORY_MOOD as table
        except Exception:
            table = {}
    _CATEGORY_MOOD_CACHE = dict(table or {})
    return _CATEGORY_MOOD_CACHE



def weekday_cn():
    return "一二三四五六日"[_now().date().weekday()]


def clamp(value, low=0.0, high=100.0):
    try:
        value = float(value)
    except Exception:
        return float(low)
    return max(float(low), min(float(high), value))


def to_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default


def to_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def truncate(text, limit=120):
    text = str(text or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def md5_int(text):
    return int(hashlib.md5(str(text).encode("utf-8")).hexdigest()[:8], 16)


def uniq(items):
    out = []
    seen = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def parse_hhmm(value, default=0):
    try:
        parts = str(value).strip().split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return default


def minutes_now():
    dt = _now()
    return dt.hour * 60 + dt.minute


def in_minute_range(cur, start, end):
    if start == end:
        return True
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end


def quiet_now(spec):
    try:
        start, end = str(spec).split("-", 1)
        return in_minute_range(minutes_now(), parse_hhmm(start), parse_hhmm(end))
    except Exception:
        return False


def looks_like_plain_command(text):
    text = (text or "").strip()
    return text.startswith("/") or text.startswith("／")


def has_question(text):
    if "?" in text or "？" in text:
        return True
    return any(word in text for word in (
        "吗", "呢", "怎么", "为什么", "啥", "什么", "哪", "多少", "几",
        "是不是", "能不能", "可不可以", "如何", "几点", "谁",
    ))


def sentiment(text):
    text = text or ""
    pos = sum(1 for word in POS_WORDS if word in text)
    neg = sum(1 for word in NEG_WORDS if word in text)
    angry = sum(1 for word in ANGRY_WORDS if word in text)
    sad = sum(1 for word in SAD_WORDS if word in text)
    aff = sum(1 for word in AFFECTION_WORDS if word in text)
    total = pos + neg
    score = 0.0 if total == 0 else (pos - neg) / float(total)
    return {
        "pos": pos, "neg": neg, "angry": angry, "sad": sad,
        "aff": aff, "insult": any(w in text for w in INSULT_WORDS),
        "score": score,
    }


_WORD_RE = re.compile(r"[a-zA-Z0-9_]{2,}")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


def tokens(text):
    text = (text or "").lower()
    out = set()
    for word in _WORD_RE.findall(text):
        out.add(word)
    for run in _CJK_RE.findall(text):
        if len(run) == 1:
            out.add(run)
        for i in range(len(run) - 1):
            out.add(run[i:i + 2])
        for i in range(len(run) - 2):
            out.add(run[i:i + 3])
    return out


def overlap(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / float(max(1, min(len(a), len(b))))


def json_extract_list(text):
    """给“要一个数组”的场景用：json_extract 会先匹配 "{"，
    遇到 `[{...},{...}]` 只返回第一个对象，导致 extract_facts 永远拿到 dict → 返回 []。
    """
    if not text:
        return []
    raw = str(text).strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    start, end = raw.find("["), raw.rfind("]")
    if start >= 0 and end > start:
        chunk = re.sub(r",\s*([}\]])", r"\1", raw[start:end + 1])
        try:
            data = json.loads(chunk)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    data = json_extract(text)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def json_extract(text):
    if not text:
        return None
    raw = str(text).strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    for opener, closer in (("{", "}"), ("[", "]")):
        start = raw.find(opener)
        if start < 0:
            continue
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(raw)):
            char = raw[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    chunk = raw[start:index + 1]
                    chunk = re.sub(r",\s*([}\]])", r"\1", chunk)
                    try:
                        return json.loads(chunk)
                    except Exception:
                        break
    return None


CHAT_FORMAT_NOISE = re.compile(
    r"@\s*([^\s（(]+)\s*[（(]\s*QQ\s*[:：]?\s*\d+\s*[）)]"
    r"|[（(]\s*QQ\s*[:：]?\s*\d+\s*[）)]"
    r"|\bQQ\s*[:：]?\s*\d{4,}\b"
    r"|@\s*([^\s，。！？!?、；;：:]+)",
    re.I,
)


def strip_chat_format(text):
    """去掉模型复述的 @昵称(QQ号)、QQ号等后台格式，保留自然称呼。"""
    value = str(text or "")
    value = CHAT_FORMAT_NOISE.sub(lambda m: (m.group(1) or m.group(2) or "").strip(), value)
    value = re.sub(r"[（(]\s*[）)]", "", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    return value.strip()


_PSEUDO_BLOCK_RE = re.compile(r"<astrbot_execute_python>.*?</astrbot_execute_python>", re.S | re.I)
_PSEUDO_TAG_RE = re.compile(r"</?(?:astrbot|amo)_[a-z_]+[^>]*>|</?text\b[^>]*>", re.I)
_CODE_FENCE_RE = re.compile(r"```.*?```", re.S)


def strip_pseudo_tags(text):
    """把框架控制标签从正文里剥掉。

    模型偶尔把 `<astrbot_execute_python>` 这类标签当正文输出，直接发出去就是
    「群里爆代码」。整块剥干净，代码围栏也一起删。
    """
    body = _PSEUDO_BLOCK_RE.sub("", str(text or ""))
    body = _PSEUDO_TAG_RE.sub("", body)
    body = _CODE_FENCE_RE.sub("", body)
    return body.strip()


def clean_reply(text, limit=300):
    if not text:
        return ""
    text = strip_chat_format(str(text).strip())
    text = strip_pseudo_tags(text)
    text = re.sub(r"^(?:Amo|amo|核心|我|助手|assistant|AI|机器人)\s*[:：]\s*", "", text)
    if len(text) >= 2 and text[0] in "\"'“‘" and text[-1] in "\"'”’":
        text = text[1:-1]
    text = text.replace("\r", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:limit]


# ---------------------------------------------------------------------------
# 分段器：书号、引号等成对符号内部绝对不切
# ---------------------------------------------------------------------------

_PAIRS = {
    "《": "》", "〈": "〉", "“": "”", "‘": "’", "「": "」", "『": "』",
    "（": "）", "(": ")", "【": "】", "〔": "〕", "[": "]", "{": "}",
}
_STRONG = "。！？!?…\n"
_WEAK = "，,、；;：:~～"
_TRIM = " \t\r\n。！？!?…，,、；;：:~～"


def _protect_mask(text):
    length = len(text)
    mask = [False] * length

    def mark(start, end):
        for index in range(max(0, start), min(length, end)):
            mask[index] = True

    for match in re.finditer(r"```.*?```", text, re.S):
        mark(match.start(), match.end())
    for match in re.finditer(r"`[^`\n]+`", text):
        mark(match.start(), match.end())
    for match in re.finditer(r"https?://[^\s]+", text):
        mark(match.start(), match.end())

    index = 0
    while index < length:
        char = text[index]
        closer = _PAIRS.get(char)
        if closer:
            depth = 1
            scan = index + 1
            while scan < length:
                if text[scan] == char:
                    depth += 1
                elif text[scan] == closer:
                    depth -= 1
                    if depth == 0:
                        break
                scan += 1
            if scan < length:
                mark(index, scan + 1)
                index = scan + 1
                continue
            mark(index, length)
            break
        index += 1
    return mask


def _cut(text, mask, delimiters, min_keep=0):
    parts = []
    start = 0
    for index, char in enumerate(text):
        if mask[index]:
            continue
        if char in delimiters and (index + 1 - start) >= min_keep:
            parts.append(text[start:index + 1])
            start = index + 1
    parts.append(text[start:])
    return parts


def _protected_ranges(text):
    mask = _protect_mask(text)
    ranges = []
    start = None
    for index, flag in enumerate(mask):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            ranges.append((start, index))
            start = None
    if start is not None:
        ranges.append((start, len(mask)))
    return ranges


def _mask_with_placeholders(text):
    ranges = _protected_ranges(text)
    if not ranges:
        return text, {}
    pieces = []
    placeholders = {}
    last = 0
    for index, (start, end) in enumerate(ranges):
        pieces.append(text[last:start])
        token = "\x00%d\x00" % index
        placeholders[token] = text[start:end]
        pieces.append(token)
        last = end
    pieces.append(text[last:])
    return "".join(pieces), placeholders


def _split_regex(text, pattern, protect_pairs=True):
    if not pattern:
        return None
    masked, placeholders = _mask_with_placeholders(text) if protect_pairs else (text, {})
    try:
        compiled = re.compile(pattern)
    except re.error:
        return None
    pieces = []
    last = 0
    for match in compiled.finditer(masked):
        end = match.end()
        if end <= last:
            continue
        pieces.append(masked[last:end])
        last = end
    pieces.append(masked[last:])
    restored = []
    for piece in pieces:
        value = piece
        for token, original in placeholders.items():
            value = value.replace(token, original)
        value = value.strip()
        if value:
            restored.append(value)
    return restored


def segment_text(text, keep_punc=True, min_len=6, max_len=42, max_segments=4,
                 mode="punct", split_chars="", regex_pattern="", protect_pairs=True):
    """按标点符号或正则分段；成对符号、代码块、URL 内部不会被切开。

    mode="punct" 时按 segment_split_chars + 内置标点分段；
    mode="regex" 时按 segment_regex 分段，失败自动回退到标点模式。
    """
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return []
    min_len = max(1, to_int(min_len, 6))
    max_len = max(min_len + 1, to_int(max_len, 42))
    max_segments = max(1, to_int(max_segments, 4))

    pieces = None
    if str(mode).lower() == "regex" and regex_pattern:
        pieces = _split_regex(text, regex_pattern, protect_pairs)
    if pieces is None:
        extra = "".join(char for char in str(split_chars or "") if char not in "\r\n")
        strong = "".join(dict.fromkeys(_STRONG + extra))
        mask = _protect_mask(text) if protect_pairs else [False] * len(text)
        pieces = []
        for part in _cut(text, mask, strong):
            part = part.strip()
            if not part:
                continue
            if len(part) > max_len:
                sub_mask = _protect_mask(part) if protect_pairs else [False] * len(part)
                pieces.extend(_cut(part, sub_mask, _WEAK, min_keep=max(4, max_len // 2)))
            else:
                pieces.append(part)

    normalized = []
    for part in pieces or []:
        part = str(part).strip()
        if not part:
            continue
        if len(part) > max_len:
            sub_mask = _protect_mask(part) if protect_pairs else [False] * len(part)
            normalized.extend(_cut(part, sub_mask, _WEAK, min_keep=max(4, max_len // 2)))
        else:
            normalized.append(part)
    pieces = normalized

    segments = []
    for part in pieces:
        seg = part.strip()
        if not keep_punc:
            seg = seg.strip(_TRIM)
        if seg:
            segments.append(seg)
    if not segments:
        return []

    index = 0
    while len(segments) > 1 and index < len(segments):
        if len(segments[index]) < min_len:
            if index + 1 < len(segments):
                segments[index + 1] = segments[index] + segments[index + 1]
                del segments[index]
                continue
            segments[index - 1] = segments[index - 1] + segments[index]
            del segments[index]
            break
        index += 1

    while len(segments) > max_segments:
        best = 0
        best_len = None
        for cursor in range(len(segments) - 1):
            total = len(segments[cursor]) + len(segments[cursor + 1])
            if best_len is None or total < best_len:
                best_len = total
                best = cursor
        segments[best] = segments[best] + segments[best + 1]
        del segments[best + 1]

    return [seg for seg in segments if seg][:max_segments]


AI_ADMISSION_RE = re.compile(
    r"(?:我是|作为|毕竟|本人|本机)\s*(?:AI|人工智能|机器人|人机|程序|模型)"
    r"|(?:只是|不过是|就是个|只是个)\s*(?:AI|人工智能|机器人|人机|程序|模型)"
    r"|人机(?:也|当然|本来|就是)"
    r"|不是真人|虚拟(?:人|角色|存在)"
    r"|(?:我|咱|我们)(?:其实|本质上|说到底|严格来说)?(?:就是|不过是|只是个)"
    r"\s*(?:AI|人工智能|机器人|人机|程序|语言模型|大模型)",
    re.I,
)


def looks_like_ai_admission(text):
    return bool(AI_ADMISSION_RE.search(str(text or "")))


# 她不能报后台：模型名、厂商、插件名、API、提示词这类都不该出现在聊天里。
# 但「插件/提示词/模型」这些词在正常的开发闲聊里也会出现（用户在聊他自己的项目），
# 一刀切会把正常回复也换成「秘密，不告诉你」。所以只认「说的是她自己」的那种句子。
MODEL_LEAK_RE = re.compile(
    r"(?:deepseek|openai|anthropic|claude|gemini|chatgpt|gpt-?[0-9]|qwen|通义|千问|"
    r"glm|chatglm|智谱|moonshot|kimi|doubao|豆包|ernie|文心|hunyuan|混元|llama|mistral|"
    r"grok|sonnet|opus|haiku|dp-?[0-9]|llm|大模型|语言模型|模型名称|api\s*key|"
    r"token|提示词|prompt|system\s*prompt|插件|astrbot)",
    re.I,
)

# 「我自己就是/我用的是/我基于…」这类自曝句，才真的算泄漏后台
SELF_LEAK_RE = re.compile(
    r"(?:我|本人|咱)(?:就|也|其实|确实|大概)?(?:是|用的?|基于|跑在|接的?|部署在|由)"
    r"[^。！？，]{0,24}(?:模型|提示词|插件|astrbot|api|服务端|后端)"
    r"|(?:我|本人)的(?:模型|提示词|系统提示|底层|设定文件|配置)"
    r"|(?:我|本人)(?:被|是由)[^。！？，]{0,16}(?:训练|开发|部署|接入)"
    r"|(?:我|本人)(?:用的?是?|在用的?|跑)在?[^。！？，]{0,16}"
    r"(?:deepseek|openai|anthropic|claude|gpt|gemini|qwen|智谱|通义|豆包|kimi)",
    re.I,
)


DEFENSIVE_REPLY_RE = re.compile(
    r"(?:你才|你才是|谁家|哪有|我才不是)[^。！？]{0,12}(?:人机|机器人|AI|人工智能)"
    r"|(?:人机|机器人)(?:才|也|怎么|哪有)",
    re.I,
)


def looks_like_defensive_reply(text):
    """是不是在跟人争“我不是人机”——技术讨论里这种话很突兀。"""
    return bool(DEFENSIVE_REPLY_RE.search(str(text or "")))


# 真要拦时的换口话术：轮换几句，别每次都「秘密，不告诉你」
LEAK_DEFLECTS = (
    "这个啊，不聊。",
    "问点别的吧。",
    "说这个干嘛。",
    "不告诉你。",
    "你猜。",
)


def leak_deflect_text():
    return random.choice(LEAK_DEFLECTS)


def looks_like_model_leak(text):
    """回复里有没有把她自己的模型/提示词/插件这类后台信息说出来。

    注意：只拦「说的是她自己」的句子。用户在聊自己的项目（插件、提示词、模型选型）时，
    她顺着聊是正常的，不能被换成「秘密，不告诉你」。
    """
    raw = str(text or "")
    if not raw:
        return False
    if not MODEL_LEAK_RE.search(raw):
        return False
    if SELF_LEAK_RE.search(raw):
        return True
    # 短句里直接报出厂商/模型名、且没有任何「他/你/这个项目」之类的第三方指向时，
    # 仍然按自曝处理（她不会无端说这些名字）
    compact = re.sub(r"\s+", "", raw)
    if len(compact) <= 12 and re.search(
            r"(?:deepseek|openai|anthropic|claude|gemini|chatgpt|qwen|智谱|通义)", compact, re.I):
        return True
    return False


def typing_delay_ms(text, base=700, per_char=400, cap=20000):
    """按回复字数模拟打字时间，越长的回复停顿越久；标点再补一点。"""
    clean = re.sub(r"\s+", "", str(text or ""))
    chars = len(clean)
    pauses = (
        clean.count("。") + clean.count("！") + clean.count("？")
        + clean.count("!") + clean.count("?") + clean.count("…")
    )
    commas = clean.count("，") + clean.count(",") + clean.count("、")
    value = base + chars * per_char + pauses * 70 + commas * 35
    value = min(value, cap)
    value = max(200, value * random.uniform(0.85, 1.2))
    return int(value)


# ---------------------------------------------------------------------------
# 数据库
# ---------------------------------------------------------------------------


# ---- 用量统计（读 AstrBot 的 data_v4.db provider_stats） ----
USAGE_PEAK_HOURS = ((9, 12), (14, 18))
USAGE_DEFAULT_PRICES = {
    "hit_peak": 0.04, "hit_idle": 0.02,
    "miss_peak": 2.0, "miss_idle": 1.0,
    "out_peak": 8.0, "out_idle": 4.0,
}


def _hhmm_minutes(value) -> int:
    """HH:MM → 分钟；坏值返回 -1。"""
    try:
        hour, minute = str(value).split(":")[:2]
        return int(hour) * 60 + int(minute)
    except Exception:
        return -1


def usage_clock(now=None, step: int = 15):
    """今天 24 小时的峰谷分段 + 此刻状态（面板画进度条用）。

    每 ``step`` 分钟取一次，跟着 ``usage_is_peak`` 走，以后改计价规则不用改前端。
    """
    now = now or _now()
    segments = []
    for minute in range(0, 24 * 60, step):
        sample = now.replace(hour=minute // 60, minute=minute % 60, second=0, microsecond=0)
        peak = bool(usage_is_peak(sample.timestamp()))
        if segments and segments[-1]["peak"] == peak:
            segments[-1]["to"] = minute + step
        else:
            segments.append({"from": minute, "to": minute + step, "peak": peak})
    return {
        "now_minute": now.hour * 60 + now.minute,
        "now_peak": bool(usage_is_peak(now.timestamp())),
        "segments": segments,
        "note": "高峰：工作日 9-12、14-18；其余按空闲价",
    }


def usage_is_peak(ts):
    """北京时间工作日 9-12、14-18 为高峰；周末全天算空闲（法定节假日未处理）。"""
    try:
        dt = datetime.fromtimestamp(float(ts), timezone.utc) + timedelta(hours=8)
    except Exception:
        return False
    if dt.weekday() >= 5:
        return False
    return any(start <= dt.hour < end for start, end in USAGE_PEAK_HOURS)


def _usage_row_ts(start_time, created_at):
    try:
        value = float(start_time or 0)
        if value > 0:
            return value
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(str(created_at or "").strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


def _empty_bucket():
    return {"calls": 0, "input_miss": 0, "input_cached": 0, "output": 0}


def summarize_token_usage(db_path, start_ts=None, end_ts=None, model_filter=None):
    """按 provider_stats 汇总 token。start_ts/end_ts 为 epoch 秒，None 表示不限。"""
    usage = _empty_bucket()
    usage.update({"cache_rate": 0.0, "peak": _empty_bucket(), "idle": _empty_bucket(), "by_model": {}})
    if not db_path or not os.path.exists(db_path):
        usage["error"] = "找不到 AstrBot 数据库"
        return usage
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % str(db_path).replace("\\", "/"), uri=True)
    except Exception as exc:
        usage["error"] = "打开数据库失败: %s" % exc
        return usage
    try:
        rows = conn.execute(
            "SELECT provider_model, token_input_other, token_input_cached, token_output, "
            "start_time, created_at FROM provider_stats"
        ).fetchall()
    except Exception as exc:
        usage["error"] = "读取 provider_stats 失败: %s" % exc
        conn.close()
        return usage
    conn.close()

    for model, miss, cached, out, start_time, created_at in rows:
        model = str(model or "")
        if model_filter and model_filter not in model:
            continue
        ts = _usage_row_ts(start_time, created_at)
        if start_ts is not None and ts and ts < float(start_ts):
            continue
        if end_ts is not None and ts and ts >= float(end_ts):
            continue
        miss = int(miss or 0)
        cached = int(cached or 0)
        out = int(out or 0)
        usage["calls"] += 1
        usage["input_miss"] += miss
        usage["input_cached"] += cached
        usage["output"] += out
        bucket = usage["peak"] if usage_is_peak(ts) else usage["idle"]
        bucket["calls"] += 1
        bucket["input_miss"] += miss
        bucket["input_cached"] += cached
        bucket["output"] += out
        item = usage["by_model"].setdefault(model or "unknown", _empty_bucket())
        item["calls"] += 1
        item["input_miss"] += miss
        item["input_cached"] += cached
        item["output"] += out

    total_in = usage["input_miss"] + usage["input_cached"]
    usage["cache_rate"] = (usage["input_cached"] / total_in) if total_in else 0.0
    usage["by_model"] = [
        dict(model=key, **value) for key, value in
        sorted(usage["by_model"].items(), key=lambda kv: -(kv[1]["input_miss"] + kv[1]["input_cached"]))
    ]
    return usage


def usage_cost(usage, prices=None):
    """按空闲/高峰两档单价（元/百万 token）估算花费。"""
    table = dict(USAGE_DEFAULT_PRICES)
    if isinstance(prices, dict):
        for key, value in prices.items():
            try:
                table[key] = float(value)
            except (TypeError, ValueError):
                continue
    cost = 0.0
    for bucket, prefix in ((usage.get("peak") or {}, "peak"), (usage.get("idle") or {}, "idle")):
        cost += float(bucket.get("input_cached") or 0) * table["hit_" + prefix] / 1e6
        cost += float(bucket.get("input_miss") or 0) * table["miss_" + prefix] / 1e6
        cost += float(bucket.get("output") or 0) * table["out_" + prefix] / 1e6
    return round(cost, 6)


def fetch_provider_balance(api_key, base_url, kind, timeout=8.0):
    """尽力查询供应商余额；查不到就返回 {ok: False, error}，不抛异常。

    支持：DeepSeek（/user/balance）、SiliconFlow（/v1/user/info）、
    OpenAI 兼容中转（/v1/dashboard/billing/subscription + usage，one-api/new-api 常见）。
    """
    import urllib.request

    api_key = str(api_key or "").strip()
    base = str(base_url or "").rstrip("/")
    if not api_key or not base:
        return {"ok": False, "error": "缺密钥或地址"}

    def _request(url, headers=None):
        auth = dict(headers or {})
        auth.setdefault("Authorization", "Bearer " + api_key)
        auth.setdefault("Accept", "application/json")
        request = urllib.request.Request(url, headers=auth)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        if kind == "deepseek":
            payload = _request(base + "/user/balance", {"Accept": "application/json"})
            infos = payload.get("balance_infos") or []
            chosen = None
            for item in infos:
                if str(item.get("currency") or "").upper() == "CNY":
                    chosen = item
                    break
            if chosen is None and infos:
                chosen = infos[0]
            if not isinstance(chosen, dict):
                return {"ok": False, "error": "返回里没有余额信息"}

            def money(value):
                try:
                    return round(float(value), 2)
                except (TypeError, ValueError):
                    return None

            return {
                "ok": True,
                "available": bool(payload.get("is_available")),
                "currency": str(chosen.get("currency") or "CNY"),
                "amount": money(chosen.get("total_balance")),
                "granted": money(chosen.get("granted_balance")),
                "topped_up": money(chosen.get("topped_up_balance")),
            }
        if kind == "siliconflow":
            payload = _request(base + "/v1/user/info", {"Accept": "application/json"})
            data = payload.get("data") or {}
            amount = None
            for field in ("balance", "totalBalance"):
                try:
                    amount = round(float(data.get(field)), 2)
                    break
                except (TypeError, ValueError):
                    continue
            if amount is None:
                return {"ok": False, "error": "返回里没有余额字段"}
            return {"ok": True, "currency": "CNY", "amount": amount}
        # openai 兼容中转（one-api/new-api 常见）
        subscription = _request(base + "/v1/dashboard/billing/subscription")
        hard_limit = None
        try:
            hard_limit = float(subscription.get("hard_limit_usd"))
        except (TypeError, ValueError):
            hard_limit = None
        if hard_limit is None:
            return {"ok": False, "error": "返回里没有 hard_limit_usd"}
        today = _now()
        month_start = today.replace(day=1).strftime("%Y-%m-%d")
        end_date = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        used_cents = 0.0
        try:
            usage = _request(
                base + "/v1/dashboard/billing/usage?start_date=" + month_start + "&end_date=" + end_date
            )
            used_cents = float(usage.get("total_usage") or 0)
        except Exception:
            used_cents = 0.0
        remaining = round(hard_limit - used_cents / 100.0, 2)
        return {
            "ok": True,
            "currency": "USD",
            "amount": max(0.0, remaining),
            "used": round(used_cents / 100.0, 2),
            "limit": round(hard_limit, 2),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:120]}


def fetch_deepseek_balance(api_key, base_url="https://api.deepseek.com", timeout=8.0):
    """查 DeepSeek 余额；失败返回 {ok: False, error}，不抛异常。"""
    api_key = str(api_key or "").strip()
    if not api_key:
        return {"ok": False, "error": "未配置 API Key"}
    import urllib.request
    url = str(base_url or "https://api.deepseek.com").rstrip("/") + "/user/balance"
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + api_key,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:120]}
    infos = payload.get("balance_infos") or []
    chosen = None
    for item in infos:
        if str(item.get("currency") or "").upper() == "CNY":
            chosen = item
            break
    if chosen is None and infos:
        chosen = infos[0]
    if not isinstance(chosen, dict):
        return {"ok": False, "error": "返回里没有余额信息"}

    def money(value):
        try:
            return round(float(value), 2)
        except (TypeError, ValueError):
            return None

    return {
        "ok": True,
        "available": bool(payload.get("is_available")),
        "currency": str(chosen.get("currency") or "CNY"),
        "amount": money(chosen.get("total_balance")),
        "granted": money(chosen.get("granted_balance")),
        "topped_up": money(chosen.get("topped_up_balance")),
    }

def merge_uid_alias_data(conn, alias_map):
    """把别名 uid 的档案/记忆/消息/关系/称呼并进主 uid（一次性、幂等）。

    返回统计 dict，调用方负责记 kv 标记，避免每次启动重复跑。
    """
    report = {"profiles": 0, "memories": 0, "messages": 0, "proactive_log": 0,
              "relations": 0, "kv": 0}
    if not isinstance(alias_map, dict) or not alias_map:
        return report
    cur = conn.cursor()

    def table_columns(name):
        try:
            return [row[1] for row in cur.execute("PRAGMA table_info(%s)" % name)]
        except Exception:
            return []

    profile_cols = table_columns("profiles")
    if not profile_cols:
        return report

    def to_num(value, default=0.0):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return default

    for alias_uid, canon_uid in list(alias_map.items()):
        alias_uid = str(alias_uid or "")
        canon_uid = str(canon_uid or "")
        if not alias_uid or not canon_uid or alias_uid == canon_uid:
            continue
        cur.execute("SELECT * FROM profiles WHERE uid=?", (alias_uid,))
        alias_raw = cur.fetchone()
        cur.execute("SELECT * FROM profiles WHERE uid=?", (canon_uid,))
        canon_raw = cur.fetchone()

        def as_dict(row):
            if row is None:
                return None
            if hasattr(row, "keys"):
                return dict(row)
            return {col[0]: value for col, value in zip(cur.description, row)}

        alias_row = as_dict(alias_raw)
        canon_row = as_dict(canon_raw)
        if alias_row is not None and canon_row is None:
            # 只有别名档案：直接改主键，历史原样保留
            cur.execute("UPDATE profiles SET uid=? WHERE uid=?", (canon_uid, alias_uid))
            report["profiles"] += 1
        elif alias_row is not None and canon_row is not None:
            a = alias_row
            b = canon_row
            merged = dict(b)
            merged["uid"] = canon_uid
            for key in ("name", "birthday", "alias", "notes", "platform"):
                if key not in profile_cols:
                    continue
                if key in ("alias", "notes"):
                    parts = []
                    for value in (b.get(key), a.get(key)):
                        text = str(value or "").strip()
                        if text and text not in parts:
                            parts.append(text)
                    merged[key] = " | ".join(parts)
                else:
                    merged[key] = b.get(key) or a.get(key) or ""
            if "relation" in profile_cols:
                canon_rel = str(b.get("relation") or "普通")
                alias_rel = str(a.get("relation") or "普通")
                merged["relation"] = canon_rel if canon_rel != "普通" else alias_rel
            for key in ("affection", "msg_count", "proactive_count", "is_admin"):
                if key in profile_cols:
                    merged[key] = max(int(to_num(b.get(key))), int(to_num(a.get(key))))
            for key in ("last_seen", "last_proactive", "relation_at"):
                if key in profile_cols:
                    merged[key] = max(to_num(b.get(key)), to_num(a.get(key)))
            if "first_seen" in profile_cols:
                values = [v for v in (to_num(b.get("first_seen")), to_num(a.get("first_seen"))) if v > 0]
                merged["first_seen"] = min(values) if values else None
            if "private_umo" in profile_cols:
                merged["private_umo"] = b.get("private_umo") or a.get("private_umo") or ""
            if "last_group" in profile_cols:
                merged["last_group"] = b.get("last_group") or a.get("last_group") or ""
            if "proactive_day" in profile_cols:
                merged["proactive_day"] = b.get("proactive_day") or a.get("proactive_day") or ""
            cols = [c for c in profile_cols if c in merged]
            cur.execute("DELETE FROM profiles WHERE uid=?", (alias_uid,))
            cur.execute(
                "INSERT OR REPLACE INTO profiles(%s) VALUES(%s)"
                % (",".join(cols), ",".join("?" * len(cols))),
                [merged.get(c) for c in cols],
            )
            report["profiles"] += 1

        # 消息：改归属 + 只对"别名带来的"那几条去重
        try:
            alias_msgs = [tuple(r) for r in cur.execute(
                "SELECT umo, role, content, created_at FROM messages WHERE uid=?", (alias_uid,))]
            cur.execute("UPDATE messages SET uid=? WHERE uid=?", (canon_uid, alias_uid))
            report["messages"] += cur.rowcount or 0
            for umo, role, content, created in alias_msgs:
                cur.execute(
                    "DELETE FROM messages WHERE umo=? AND uid=? AND role=? AND content=? AND created_at=? "
                    "AND rowid NOT IN (SELECT MIN(rowid) FROM messages WHERE umo=? AND uid=? AND role=? AND content=? AND created_at=?)",
                    (umo, canon_uid, role, content, created, umo, canon_uid, role, content, created),
                )
        except Exception:
            pass

        # 主动记录
        try:
            alias_pro = [tuple(r) for r in cur.execute(
                "SELECT kind, content, created FROM proactive_log WHERE uid=?", (alias_uid,))]
            cur.execute("UPDATE proactive_log SET uid=? WHERE uid=?", (canon_uid, alias_uid))
            report["proactive_log"] += cur.rowcount or 0
            for kind, content, created in alias_pro:
                cur.execute(
                    "DELETE FROM proactive_log WHERE uid=? AND kind=? AND content=? AND created=? "
                    "AND rowid NOT IN (SELECT MIN(rowid) FROM proactive_log WHERE uid=? AND kind=? AND content=? AND created=?)",
                    (canon_uid, kind, content, created, canon_uid, kind, content, created),
                )
        except Exception:
            pass

        # 关系网
        try:
            cur.execute("UPDATE OR IGNORE relation_network SET a_uid=? WHERE a_uid=?", (canon_uid, alias_uid))
            cur.execute("UPDATE OR IGNORE relation_network SET b_uid=? WHERE b_uid=?", (canon_uid, alias_uid))
            # OR IGNORE 遇到已存在的同一对关系会跳过，残留的别名行要显式删掉
            cur.execute("DELETE FROM relation_network WHERE a_uid=? OR b_uid=?", (alias_uid, alias_uid))
            cur.execute("DELETE FROM relation_network WHERE a_uid=b_uid")
            cur.execute(
                "DELETE FROM relation_network WHERE rowid NOT IN "
                "(SELECT MIN(rowid) FROM relation_network GROUP BY a_uid, b_uid)"
            )
            report["relations"] += 1
        except Exception:
            pass

        # kv：通道记录要合并成一份，其余带别名的键改名
        try:
            old_key = "channels:%s" % alias_uid
            new_key = "channels:%s" % canon_uid
            old_ch = cur.execute("SELECT value FROM kv WHERE key=?", (old_key,)).fetchone()
            new_ch = cur.execute("SELECT value FROM kv WHERE key=?", (new_key,)).fetchone()

            def load(raw):
                try:
                    return json.loads(raw[0] or "{}") if raw else {}
                except Exception:
                    return {}

            merged_ch = load(new_ch) if isinstance(load(new_ch), dict) else {}
            alias_ch = load(old_ch) if isinstance(load(old_ch), dict) else {}
            for platform, value in alias_ch.items():
                if not isinstance(value, dict):
                    continue
                current = merged_ch.get(platform)
                if not isinstance(current, dict) or to_num(value.get("ts")) > to_num(current.get("ts")):
                    merged_ch[platform] = value
            if merged_ch:
                cur.execute("UPDATE OR IGNORE kv SET key=? WHERE key=?", (new_key, old_key))
                cur.execute("DELETE FROM kv WHERE key=?", (old_key,))
                cur.execute("INSERT OR REPLACE INTO kv(key, value, updated) VALUES(?,?,?)",
                            (new_key, json.dumps(merged_ch, ensure_ascii=False), time.time()))
                report["kv"] += 1
            else:
                cur.execute("DELETE FROM kv WHERE key=?", (old_key,))
        except Exception:
            pass
        try:
            # 用 Python 侧的包含判断，避免 LIKE 里 '_' 被当成通配符误伤别的键
            for row in list(cur.execute("SELECT key FROM kv")):
                key = str(row[0] or "")
                if alias_uid not in key:
                    continue
                new = key.replace(alias_uid, canon_uid)
                if new == key:
                    continue
                cur.execute("UPDATE OR IGNORE kv SET key=? WHERE key=?", (new, key))
                cur.execute("DELETE FROM kv WHERE key=?", (key,))
                report["kv"] += 1
        except Exception:
            pass

    try:
        conn.commit()
    except Exception:
        pass
    return report



class AmoDB:
    def __init__(self, plugin_dir):
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            data_dir = os.path.join(get_astrbot_data_path(), "plugin_data", PLUGIN_NAME)
        except Exception:
            data_dir = os.path.join(plugin_dir, "data")
        try:
            os.makedirs(data_dir, exist_ok=True)
        except Exception:
            data_dir = plugin_dir
        self.path = os.path.join(data_dir, "amo_forever.db")
        # 4.0.0 起插件标识为 Astrbot_Amo_forever。
        # 4.0.6 保持新标识，并把 3.x 的 amo_forever 旧数据迁移到新目录。
        try:
            import shutil as _shutil
            data_root = get_astrbot_data_path()
            legacy_paths = [
                os.path.join(data_root, "plugin_data", "amo_forever", "amo_forever.db"),
                os.path.join(data_root, "plugin_data", "astrbot_plugin_amo_forever", "amo_forever.db"),
            ]
            current_size = os.path.getsize(self.path) if os.path.exists(self.path) else 0
            if current_size < 4096:
                for legacy_path in legacy_paths:
                    if not os.path.exists(legacy_path) or os.path.getsize(legacy_path) < 4096:
                        continue
                    if os.path.exists(self.path):
                        _shutil.copy2(self.path, self.path + ".bak-4.0.6")
                    for suffix in ("-wal", "-shm", "-journal"):
                        stale = self.path + suffix
                        if os.path.exists(stale):
                            try:
                                os.remove(stale)
                            except Exception:
                                pass
                    _shutil.copy2(legacy_path, self.path)
                    for suffix in ("-wal", "-shm"):
                        source = legacy_path + suffix
                        if os.path.exists(source):
                            _shutil.copy2(source, self.path + suffix)
                    logger.info("[amo] 已迁移旧版 amo_forever 数据: %s -> %s" % (legacy_path, self.path))
                    logger.info("[amo] 升级提示：插件标识保持 Astrbot_Amo_forever；旧 amo_forever 数据已迁移到新目录，配置文件也会自动合并。")
                    break
        except Exception as exc:
            logger.warning("[amo] 旧版 amo_forever 数据迁移失败: %s" % exc)
        self.lock = threading.RLock()
        self._conn = None
        self._open()

    def _open(self):
        with self.lock:
            self._open_unlocked()

    def _open_unlocked(self):
        """打开（或重新打开）连接。

        插件重载时 AstrBot 可能先调用旧实例的 terminate()，而旧实例注册的
        Web API 仍然存在；这里保证连接被关闭后下一次访问会自动重开，避免
        "Cannot operate on a closed database"。
        """
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=15)
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass

    @property
    def conn(self):
        # Web 协程 + 后台 _tick + _ensure_ready 可能同时进来；不加锁会各自 connect，
        # 后一个覆盖前一个，先前的连接泄漏，PRAGMA journal_mode=WAL 还可能出现 database is locked。
        if self._conn is None:
            with self.lock:
                if self._conn is None:
                    self._open()
        return self._conn

    def init(self):
        with self.lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    uid TEXT PRIMARY KEY,
                    name TEXT DEFAULT '',
                    alias TEXT DEFAULT '',
                    birthday TEXT DEFAULT '',
                    relation TEXT DEFAULT '普通',
                    affection INTEGER DEFAULT 10,
                    notes TEXT DEFAULT '',
                    platform TEXT DEFAULT '',
                    private_umo TEXT DEFAULT '',
                    last_group TEXT DEFAULT '',
                    first_seen REAL DEFAULT 0,
                    last_seen REAL DEFAULT 0,
                    msg_count INTEGER DEFAULT 0,
                    last_proactive REAL DEFAULT 0,
                    proactive_day TEXT DEFAULT '',
                    proactive_count INTEGER DEFAULT 0,
                    relation_at REAL DEFAULT 0,
                    is_admin INTEGER DEFAULT 0,
                    profile_updated_at REAL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    umo TEXT DEFAULT '',
                    uid TEXT DEFAULT '',
                    name TEXT DEFAULT '',
                    role TEXT DEFAULT 'user',
                    content TEXT DEFAULT '',
                    created_at REAL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_msg_umo ON messages(umo);
                CREATE TABLE IF NOT EXISTS kv (
                    key TEXT PRIMARY KEY,
                    value TEXT DEFAULT '',
                    updated REAL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS schedule (
                    day TEXT PRIMARY KEY,
                    items TEXT DEFAULT '[]',
                    updated REAL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS schedule_diary (
                    day TEXT DEFAULT '',
                    hour TEXT DEFAULT '',
                    text TEXT DEFAULT '',
                    updated REAL DEFAULT 0,
                    PRIMARY KEY(day, hour)
                );
                CREATE TABLE IF NOT EXISTS proactive_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid TEXT DEFAULT '',
                    kind TEXT DEFAULT '',
                    content TEXT DEFAULT '',
                    created REAL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS dialects (
                    term TEXT PRIMARY KEY,
                    meaning TEXT DEFAULT '',
                    region TEXT DEFAULT '',
                    example TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS token_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL DEFAULT 0,
                    kind TEXT DEFAULT '',
                    model TEXT DEFAULT '',
                    input_other INTEGER DEFAULT 0,
                    input_cached INTEGER DEFAULT 0,
                    output INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS relation_network (
                    a_uid TEXT NOT NULL,
                    b_uid TEXT NOT NULL,
                    relation TEXT DEFAULT '朋友',
                    note TEXT DEFAULT '',
                    updated_at REAL DEFAULT 0,
                    PRIMARY KEY(a_uid, b_uid)
                );
                """
            )
            self.conn.commit()
            self._seed_dialects()
            self._migrate_legacy()
            try:
                cols = {row[1] for row in self.conn.execute("PRAGMA table_info(profiles)").fetchall()}
                if "relation_at" not in cols:
                    self.conn.execute("ALTER TABLE profiles ADD COLUMN relation_at REAL DEFAULT 0")
                    self.conn.execute("UPDATE profiles SET relation_at=last_seen WHERE relation_at=0")
                    self.conn.commit()
                if "profile_updated_at" not in cols:
                    # 画像最后一次「本地手动修改」的时间：面板/命令改画像才更新，
                    # 收消息刷新 last_seen 不算，否则面板改完聊一句就被本地旧值覆盖。
                    self.conn.execute("ALTER TABLE profiles ADD COLUMN profile_updated_at REAL DEFAULT 0")
                    self.conn.commit()
            except Exception:
                pass

    def _migrate_legacy(self):
        try:
            has_old = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='user_status'"
            ).fetchone()
            if has_old:
                rows = self.conn.execute(
                    "SELECT uid, relation, mem_count FROM user_status"
                ).fetchall()
                for row in rows:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO profiles(uid, relation, msg_count, first_seen, last_seen) "
                        "VALUES(?,?,?,?,?)",
                        (row["uid"], row["relation"] or "普通", row["mem_count"] or 0, now_ts(), now_ts()),
                    )
            self.conn.commit()
        except Exception as exc:
            logger.debug("[amo] 旧数据迁移跳过: %s" % exc)

    def close(self):
        with self.lock:
            if self._conn is None:
                return
            try:
                self._conn.commit()
            except Exception:
                pass
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    # ---------- KV ----------
    def kv_get(self, key, default=None):
        with self.lock:
            row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return default

    def kv_set(self, key, value):
        with self.lock:
            self.conn.execute(
                "INSERT INTO kv(key, value, updated) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=excluded.updated",
                (key, json.dumps(value, ensure_ascii=False), now_ts()),
            )
            self.conn.commit()

    # ---------- 档案 ----------
    def get_profile(self, uid):
        with self.lock:
            row = self.conn.execute("SELECT * FROM profiles WHERE uid=?", (str(uid),)).fetchone()
        return dict(row) if row else {}

    def touch_profile(self, uid, name, platform, umo, group_id, private):
        uid = str(uid)
        name = name or ""
        now = now_ts()
        with self.lock:
            row = self.conn.execute("SELECT * FROM profiles WHERE uid=?", (uid,)).fetchone()
            if row is None:
                self.conn.execute(
                    "INSERT INTO profiles(uid, name, platform, private_umo, last_group, "
                    "first_seen, last_seen, msg_count) VALUES(?,?,?,?,?,?,?,1)",
                    (uid, name, platform or "", umo if private else "",
                     umo if not private else "", now, now),
                )
            else:
                updates = ["last_seen=?", "msg_count=msg_count+1"]
                values = [now]
                if name and not row["name"]:
                    updates.append("name=?")
                    values.append(name)
                if private:
                    updates.append("private_umo=?")
                    values.append(umo)
                elif group_id:
                    updates.append("last_group=?")
                    values.append(umo)
                values.append(uid)
                self.conn.execute(
                    "UPDATE profiles SET " + ", ".join(updates) + " WHERE uid=?", values
                )
            self.conn.commit()
            row = self.conn.execute("SELECT * FROM profiles WHERE uid=?", (uid,)).fetchone()
        return dict(row) if row else {}

    def update_profile(self, uid, mark_local=True, **fields):
        allowed = ("name", "alias", "birthday", "relation", "notes",
                   "affection", "is_admin")
        updates = []
        values = []
        for key, value in fields.items():
            if key in allowed:
                updates.append(key + "=?")
                values.append(value)
        if "relation" in fields:
            updates.append("relation_at=?")
            values.append(now_ts())
        if mark_local:
            updates.append("profile_updated_at=?")
            values.append(now_ts())
        if not updates:
            return False
        values.append(str(uid))
        with self.lock:
            self.conn.execute(
                "UPDATE profiles SET " + ", ".join(updates) + " WHERE uid=?", values
            )
            self.conn.commit()
        return True

    def delete_profile(self, uid):
        with self.lock:
            self.conn.execute("DELETE FROM profiles WHERE uid=?", (str(uid),))
            self.conn.commit()

    def list_profiles(self, keyword="", limit=100):
        limit = max(1, min(int(limit), 500))
        with self.lock:
            if keyword:
                like = "%" + str(keyword) + "%"
                rows = self.conn.execute(
                    "SELECT * FROM profiles WHERE uid LIKE ? OR name LIKE ? OR alias LIKE ? "
                    "ORDER BY last_seen DESC LIMIT ?",
                    (like, like, like, limit),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM profiles ORDER BY last_seen DESC LIMIT ?", (limit,)
                ).fetchall()
        return [dict(row) for row in rows]

    def _seed_dialects(self):
        rows = [
            ("么子", "什么", "贵州·土家族地区", "你在搞么子？"),
            ("哪门", "怎么", "贵州·土家族地区", "哪门搞的？"),
            ("要得", "好的", "贵州·土家族地区", "要得，没问题"),
            ("晓得", "知道", "贵州·土家族地区", "我晓得了"),
            ("恰饭", "吃饭", "贵州·土家族地区", "走，恰饭去"),
            ("莫", "不要", "贵州·土家族地区", "你莫急"),
            ("屋头", "家里", "贵州·土家族地区", "在屋头"),
            ("落雨", "下雨", "贵州·土家族地区", "外头落雨了"),
            ("安逸", "舒服", "贵州·土家族地区", "好安逸"),
            ("拐哒", "糟糕", "贵州·土家族地区", "拐哒，忘了"),
            ("摆龙门阵", "聊天", "贵州·土家族地区", "来摆龙门阵"),
            ("崽崽", "小孩", "贵州·土家族地区", "那个崽崽"),
            ("老汉", "父亲", "贵州·土家族地区", "我老汉"),
            ("堂客", "妻子", "贵州·土家族地区", "他堂客"),
            ("哈戳戳", "傻乎乎", "贵州·土家族地区", "你哈戳戳的"),
            ("扯皮", "吵架", "贵州·土家族地区", "莫扯皮"),
            ("逗是", "就是", "贵州·土家族地区", "逗是这么回事"),
            ("热和", "暖和", "贵州·土家族地区", "屋里热和"),
            ("搞么子", "干什么", "贵州·土家族地区", "你搞么子"),
            ("巴适", "舒服", "贵州·土家族地区", "巴适得很"),
            ("啷个", "怎么", "贵州·土家族地区", "啷个办嘛"),
            ("哪样", "什么", "贵州·土家族地区", "你要哪样"),
            ("为哪样", "为什么", "贵州·土家族地区", "你为哪样不吃饭"),
            ("恁个", "这么", "贵州·土家族地区", "恁个热"),
            ("恁么", "那么", "贵州·土家族地区", "恁么远"),
            ("等哈", "等一下", "贵州·土家族地区", "等哈我"),
            ("一哈", "一下", "贵州·土家族地区", "看一哈"),
            ("哈哈儿", "一会儿", "贵州·土家族地区", "哈哈儿就来"),
            ("将才", "刚才", "贵州·土家族地区", "将才说的"),
            ("这哈", "现在", "贵州·土家族地区", "这哈忙"),
            ("那哈", "那时候", "贵州·土家族地区", "那哈还小"),
            ("哪哈", "什么时候", "贵州·土家族地区", "你哪哈来"),
            ("好久", "多久", "贵州·土家族地区", "等了好久"),
            ("清早", "早晨", "贵州·土家族地区", "清早八晨"),
            ("晌午", "中午", "贵州·土家族地区", "晌午吃饭"),
            ("黑了", "晚上", "贵州·土家族地区", "黑了再说"),
            ("昨儿个", "昨天", "贵州·土家族地区", "昨儿个下雨"),
            ("今儿个", "今天", "贵州·土家族地区", "今儿个赶场"),
            ("明儿个", "明天", "贵州·土家族地区", "明儿个去"),
            ("赶场", "赶集", "贵州·土家族地区", "去镇上赶场"),
            ("吃酒", "参加酒席", "贵州·土家族地区", "明天去吃酒"),
            ("坐席", "入席", "贵州·土家族地区", "快坐席"),
            ("背篓", "竹背篓", "贵州·土家族地区", "背个背篓"),
            ("山卡卡", "山沟里", "贵州·土家族地区", "山卡卡里头"),
            ("坝子", "平地", "贵州·土家族地区", "坝子上晒谷"),
            ("坎坎", "台阶或坎", "贵州·土家族地区", "小心坎坎"),
            ("岩脚", "山岩下", "贵州·土家族地区", "在岩脚歇气"),
            ("河沟", "小河", "贵州·土家族地区", "河沟里摸鱼"),
            ("扯火闪", "闪电", "贵州·土家族地区", "天边扯火闪"),
            ("雪米子", "小冰粒", "贵州·土家族地区", "下雪米子了"),
            ("凌冰", "冰", "贵州·土家族地区", "路上结凌冰"),
            ("太阳坝", "向阳的地方", "贵州·土家族地区", "去太阳坝坐"),
            ("阴凉坝", "阴凉处", "贵州·土家族地区", "树脚阴凉坝"),
            ("热天", "夏天", "贵州·土家族地区", "热天莫出门"),
            ("冷天", "冬天", "贵州·土家族地区", "冷天烤火"),
            ("莫慌", "别急", "贵州·土家族地区", "莫慌，慢慢来"),
            ("慢点", "慢一点", "贵州·土家族地区", "你慢点走"),
            ("归一", "完成、结束", "贵州·土家族地区", "事情搞归一了"),
            ("刹角", "收尾、结束", "贵州·土家族地区", "今天刹角了"),
            ("杀割", "结束", "贵州·土家族地区", "饭吃杀割了"),
            ("架势", "开始、用力", "贵州·土家族地区", "架势干"),
            ("稀罕", "喜欢、少见", "贵州·土家族地区", "我不稀罕"),
            ("撇脱", "干脆、简单", "贵州·土家族地区", "撇脱点"),
            ("巴心巴肠", "一心一意", "贵州·土家族地区", "巴心巴肠对你"),
            ("焦人", "让人着急", "贵州·土家族地区", "这事焦人"),
            ("恼火", "难受、麻烦", "贵州·土家族地区", "心头恼火"),
            ("造孽", "可怜", "贵州·土家族地区", "这娃儿造孽"),
            ("舒气", "整洁、清爽", "贵州·土家族地区", "屋头收拾得舒气"),
            ("冰凊", "冰凉", "贵州·土家族地区", "水冰凊"),
            ("嘎公", "外公", "贵州·土家族地区", "我嘎公"),
            ("嘎婆", "外婆", "贵州·土家族地区", "我嘎婆"),
            ("舅公", "舅爷", "贵州·土家族地区", "舅公来了"),
            ("舅婆", "舅奶", "贵州·土家族地区", "舅婆做饭"),
            ("幺爸", "最小的叔叔", "贵州·土家族地区", "幺爸在家"),
            ("幺妈", "最小的婶婶", "贵州·土家族地区", "幺妈来了"),
            ("嬢嬢", "阿姨", "贵州·土家族地区", "嬢嬢好"),
            ("老表", "表亲或哥们", "贵州·土家族地区", "老表，走哪去"),
            ("家门", "同姓、本家", "贵州·土家族地区", "我们是家门"),
            ("老庚", "同岁好友", "贵州·土家族地区", "他是我老庚"),
            ("娃儿", "孩子", "贵州·土家族地区", "这个娃儿乖"),
            ("妹崽", "女孩", "贵州·土家族地区", "那个妹崽"),
            ("男娃儿", "男孩", "贵州·土家族地区", "男娃儿调皮"),
            ("吃莽莽", "吃饭，哄小孩说法", "贵州·土家族地区", "走，吃莽莽"),
            ("嘎嘎", "肉，儿语", "贵州·土家族地区", "要吃嘎嘎"),
            ("粑粑", "饼、糍粑", "贵州·土家族地区", "烤粑粑"),
            ("折耳根", "鱼腥草", "贵州·土家族地区", "凉拌折耳根"),
            ("酸汤", "酸汤", "贵州·土家族地区", "酸汤鱼"),
            ("糟辣椒", "糟辣椒", "贵州·土家族地区", "糟辣椒炒肉"),
            ("油茶", "油茶", "贵州·土家族地区", "喝碗油茶"),
            ("洋芋", "土豆", "贵州·土家族地区", "烤洋芋"),
            ("苞谷", "玉米", "贵州·土家族地区", "掰苞谷"),
            ("红苕", "红薯", "贵州·土家族地区", "烤红苕"),
            ("海椒", "辣椒", "贵州·土家族地区", "海椒面"),
            ("盐须", "香菜", "贵州·土家族地区", "放点盐须"),
            ("鬼火戳", "生气、窝火", "贵州·土家族地区", "鬼火戳得很"),
            ("毛焦火辣", "焦急", "贵州·土家族地区", "等得毛焦火辣"),
            ("扯把子", "开玩笑", "贵州·土家族地区", "你莫扯把子"),
            ("冲壳子", "吹牛", "贵州·土家族地区", "又冲壳子"),
            ("摆闲条", "闲聊", "贵州·土家族地区", "来摆闲条"),
            ("装莽", "装傻", "贵州·土家族地区", "你莫装莽"),
            ("千翻", "调皮", "贵州·土家族地区", "这娃儿千翻"),
            ("费头子", "调皮鬼", "贵州·土家族地区", "这个费头子"),
            ("猴跳跳", "顽皮好动", "贵州·土家族地区", "猴跳跳的"),
            ("落教", "懂事", "贵州·土家族地区", "这娃儿落教"),
            ("不落教", "不懂事", "贵州·土家族地区", "你莫不落教"),
            ("弯酸", "刁难、挖苦", "贵州·土家族地区", "莫弯酸人"),
            ("洗刷", "数落", "贵州·土家族地区", "又洗刷我"),
            ("日诀", "骂", "贵州·土家族地区", "莫日诀人"),
            ("割孽", "吵架、打架", "贵州·土家族地区", "两个人割孽"),
            ("扯筋", "扯皮", "贵州·土家族地区", "莫扯筋"),
            ("咋整", "怎么办", "东北", "咋整啊"),
            ("得瑟", "显摆", "东北", "别得瑟"),
            ("忽悠", "骗", "东北", "别忽悠我"),
            ("埋汰", "脏、讽刺", "东北", "别埋汰人"),
            ("唠嗑", "聊天", "东北", "来唠嗑"),
            ("嘎哈", "干什么", "东北", "你嘎哈呢"),
            ("老铁", "哥们", "东北", "老铁没毛病"),
            ("贼拉", "非常", "东北", "贼拉冷"),
            ("稀罕", "喜欢", "东北", "我稀罕你"),
            ("麻溜", "快点", "东北", "麻溜的"),
            ("嘚吧", "唠叨", "东北", "别嘚吧了"),
            ("秃噜", "滑脱、说漏", "东北", "别秃噜了"),
            ("稀碎", "碎得很", "东北", "摔稀碎"),
            ("吭哧", "磨蹭", "东北", "别吭哧了"),
            ("瓜娃子", "傻孩子", "四川", "你个瓜娃子"),
            ("雄起", "加油", "四川", "雄起"),
            ("莫得", "没有", "四川", "莫得问题"),
            ("撇脱", "干脆、利落", "四川", "撇脱点"),
            ("巴心不得", "求之不得", "四川", "我巴心不得"),
            ("耍朋友", "谈恋爱", "四川", "耍朋友没"),
            ("搞快些", "快点", "四川", "搞快些"),
            ("啷个办", "怎么办", "四川", "啷个办嘛"),
            ("唔该", "谢谢、劳驾", "广东", "唔该晒"),
            ("多谢", "谢谢", "广东", "多谢你"),
            ("食饭", "吃饭", "广东", "去食饭"),
            ("饮茶", "喝茶", "广东", "去饮茶"),
            ("靓仔", "帅哥", "广东", "靓仔"),
            ("靓女", "美女", "广东", "靓女"),
            ("点解", "为什么", "广东", "点解啊"),
            ("冇", "没有", "广东", "冇问题"),
            ("得闲", "有空", "广东", "得闲饮茶"),
            ("搞掂", "搞定", "广东", "搞掂啦"),
            ("早唞", "晚安", "广东", "早唞"),
            ("好正", "很棒", "广东", "好正"),
            ("唔使", "不用", "广东", "唔使客气"),
            ("酱紫", "这样", "台湾", "酱紫啊"),
            ("机车", "麻烦、烦人", "台湾", "很机车"),
            ("很瞎", "离谱", "台湾", "很瞎"),
            ("阿嬷", "奶奶", "台湾", "阿嬷"),
            ("蛮", "很", "台湾", "蛮好的"),
            ("超赞", "非常棒", "台湾", "超赞"),
            ("拍谢", "不好意思", "台湾", "拍谢啦"),
            ("古早", "传统、旧时", "台湾", "古早味"),
            ("龟毛", "挑剔", "台湾", "别龟毛"),
            ("嘛呢", "干什么", "天津", "嘛呢"),
            ("介", "这", "天津", "介是嘛"),
            ("倍儿", "非常", "天津", "倍儿好"),
            ("哏儿", "有趣", "天津", "真哏儿"),
            ("腻歪", "腻烦、黏人", "天津", "别腻歪"),
            ("得嘞", "好的", "天津", "得嘞"),
            ("幺蛾子", "麻烦", "天津", "出幺蛾子"),
            ("耐人", "招人喜欢", "天津", "真耐人"),
            ("走鸡", "事情办砸", "天津", "走鸡了"),
            ("各色", "特别、难相处", "天津", "真各色"),
            ("弄啥嘞", "干什么", "河南", "你弄啥嘞"),
            ("中", "好", "河南", "中，就这么办"),
            ("得劲", "舒服", "河南", "真得劲"),
            ("木有", "没有", "河南", "木有事"),
            ("恁", "你", "河南", "恁吃饭没"),
            ("俺", "我", "河南", "俺知道了"),
            ("嘟囔", "嘀咕", "河南", "别嘟囔"),
            ("夜儿个", "昨天", "河南", "夜儿个下雨"),
            ("咋着", "怎么了", "河南", "咋着了"),
            ("中不中", "行不行", "河南", "中不中"),
            ("喝汤", "吃晚饭", "河南", "喝汤没"),
            ("阿拉", "我、我们", "上海", "阿拉晓得"),
            ("侬", "你", "上海", "侬好"),
            ("哪能", "怎么", "上海", "哪能办"),
            ("结棍", "厉害", "上海", "侬结棍"),
            ("老灵", "很好", "上海", "老灵额"),
            ("白相", "玩", "上海", "出去白相"),
            ("适意", "舒服", "上海", "适意"),
            ("勿", "不", "上海", "勿晓得"),
            ("谢谢侬", "谢谢你", "上海", "谢谢侬"),
            ("辰光", "时候", "上海", "啥辰光"),
            ("困觉", "睡觉", "上海", "去困觉"),
            ("覅", "不要", "上海", "覅去"),
        ]
        with self.lock:
            for term, meaning, region, example in rows:
                self.conn.execute(
                    "INSERT OR IGNORE INTO dialects(term, meaning, region, example) VALUES(?,?,?,?)",
                    (term, meaning, region, example),
                )
            self.conn.commit()

    def list_dialects(self):
        with self.lock:
            rows = self.conn.execute("SELECT * FROM dialects").fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _relation_pair(a_uid, b_uid):
        a, b = str(a_uid or "").strip(), str(b_uid or "").strip()
        return (a, b) if a <= b else (b, a)

    def list_relations(self):
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM relation_network ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def relations_for(self, uid):
        uid = str(uid or "")
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM relation_network WHERE a_uid=? OR b_uid=? ORDER BY updated_at DESC",
                (uid, uid),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_relation(self, a_uid, b_uid, relation, note=""):
        a, b = self._relation_pair(a_uid, b_uid)
        if not a or not b or a == b:
            return False
        with self.lock:
            self.conn.execute(
                "INSERT INTO relation_network(a_uid, b_uid, relation, note, updated_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(a_uid, b_uid) DO UPDATE SET "
                "relation=excluded.relation, note=excluded.note, updated_at=excluded.updated_at",
                (a, b, str(relation or "朋友"), str(note or "")[:200], now_ts()),
            )
            self.conn.commit()
        return True

    def delete_relation(self, a_uid, b_uid):
        a, b = self._relation_pair(a_uid, b_uid)
        with self.lock:
            cursor = self.conn.execute(
                "DELETE FROM relation_network WHERE a_uid=? AND b_uid=?", (a, b)
            )
            self.conn.commit()
            return cursor.rowcount > 0

    def proactive_profiles(self, limit=30):
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM profiles WHERE private_umo != '' AND relation NOT IN ('仇恨','抵触') "
                "ORDER BY last_proactive ASC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(row) for row in rows]

    def bump_proactive(self, uid):
        today = today_str()
        with self.lock:
            row = self.conn.execute(
                "SELECT proactive_day, proactive_count FROM profiles WHERE uid=?", (str(uid),)
            ).fetchone()
            if not row:
                return
            count = int(row["proactive_count"] or 0) + 1
            if row["proactive_day"] != today:
                count = 1
            self.conn.execute(
                "UPDATE profiles SET last_proactive=?, proactive_day=?, proactive_count=? WHERE uid=?",
                (now_ts(), today, count, str(uid)),
            )
            self.conn.commit()

    def log_proactive(self, uid, kind, content):
        with self.lock:
            self.conn.execute(
                "INSERT INTO proactive_log(uid, kind, content, created) VALUES(?,?,?,?)",
                (str(uid), kind, content, now_ts()),
            )
            self.conn.commit()

    # ---------- 消息 ----------
    def add_message(self, umo, uid, name, role, content):
        content = str(content or "").strip()
        if not content:
            return
        with self.lock:
            self.conn.execute(
                "INSERT INTO messages(umo, uid, name, role, content, created_at) VALUES(?,?,?,?,?,?)",
                (str(umo), str(uid), str(name or ""), role, content, now_ts()),
            )
            self.conn.commit()

    def recent_messages(self, umo, limit=10):
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM messages WHERE umo=? ORDER BY id DESC LIMIT ?",
                (str(umo), int(limit)),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def messages_since_umo(self, umo, since_ts, limit=200):
        """按时间取某个会话的消息（新的在后）；判定「今天早上聊过没」用。"""
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM messages WHERE umo=? AND created_at>=? ORDER BY id DESC LIMIT ?",
                (str(umo), int(since_ts or 0), int(limit)),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    # ---------- 自记账：插件内部调用（判分/润色/日记）不进 provider_stats ----------

    def record_tokens(self, kind, model, input_other, input_cached, output, ts=None):
        """记一次插件内部调用的 token；出错绝不影响主流程。"""
        try:
            def _num(value):
                try:
                    return int(float(value or 0))
                except Exception:
                    return 0

            self.conn.execute(
                "INSERT INTO token_usage(ts, kind, model, input_other, input_cached, output) "
                "VALUES(?,?,?,?,?,?)",
                (float(ts or now_ts()), str(kind or ""), str(model or ""),
                 _num(input_other), _num(input_cached), _num(output)),
            )
            self.conn.commit()
        except Exception as exc:
            try:
                logger.debug("[amo] 记 token 失败: %s" % exc)
            except Exception:
                pass

    def usage_since(self, start_ts=None):
        """按 kind 汇总插件内部调用。"""
        sql = ("SELECT kind, model, COUNT(*), SUM(input_other), SUM(input_cached), SUM(output) "
               "FROM token_usage")
        params = []
        if start_ts is not None:
            sql += " WHERE ts>=?"
            params.append(float(start_ts))
        sql += " GROUP BY kind, model"
        total = {"calls": 0, "input_other": 0, "input_cached": 0, "output": 0,
                 "peak": {"calls": 0, "input_miss": 0, "input_cached": 0, "output": 0},
                 "idle": {"calls": 0, "input_miss": 0, "input_cached": 0, "output": 0},
                 "by_kind": {}, "by_model": {}}
        try:
            rows = self.conn.execute(sql, params).fetchall()
        except Exception:
            return total
        for kind, model, calls, miss, cached, out in rows:
            entry = {"calls": int(calls or 0), "input_other": int(miss or 0),
                     "input_cached": int(cached or 0), "output": int(out or 0)}
            entry["cost"] = usage_cost({
                "peak": {"input_miss": entry["input_other"], "input_cached": entry["input_cached"],
                         "output": entry["output"], "calls": entry["calls"]},
            })
            bucket = total["by_kind"].setdefault(
                str(kind or "other"),
                {"calls": 0, "input_other": 0, "input_cached": 0, "output": 0, "cost": 0.0})
            model_bucket = total["by_model"].setdefault(
                str(model or ""),
                {"calls": 0, "input_other": 0, "input_cached": 0, "output": 0})
            for key in ("calls", "input_other", "input_cached", "output"):
                bucket[key] += entry[key]
                model_bucket[key] += entry[key]
                total[key] += entry[key]
            bucket["cost"] += entry["cost"]
        total["cost"] = usage_cost({
            "peak": {"input_miss": total["input_other"], "input_cached": total["input_cached"],
                     "output": total["output"], "calls": total["calls"]},
        })
        return total

    def messages_since_ts(self, since_ts, limit=60):
        """按时间取最近的消息（半小时摘要用），新的在后。"""
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM messages WHERE created_at>? ORDER BY id DESC LIMIT ?",
                (int(since_ts or 0), int(limit)),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def messages_by_uid(self, uid, limit=20):
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM messages WHERE uid=? ORDER BY id DESC LIMIT ?",
                (str(uid), int(limit)),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def chat_history(self, uid, limit=200):
        """按用户参与过的 umo 取原始聊天记录（本人 + 机器人），不是摘要记忆。"""
        uid = str(uid)
        limit = max(1, min(2000, int(limit or 200)))
        with self.lock:
            rows = self.conn.execute(
                "SELECT DISTINCT umo FROM messages WHERE uid=? AND umo!=''",
                (uid,),
            ).fetchall()
            umos = [str(row["umo"]) for row in rows if str(row["umo"] or "")]
            if not umos:
                rows = self.conn.execute(
                    "SELECT * FROM messages WHERE uid=? ORDER BY id DESC LIMIT ?",
                    (uid, limit),
                ).fetchall()
            else:
                placeholders = ",".join("?" for _ in umos)
                params = umos + [uid, limit]
                rows = self.conn.execute(
                    "SELECT * FROM messages WHERE umo IN (" + placeholders + ") "
                    "AND (uid=? OR role='bot') ORDER BY id DESC LIMIT ?",
                    params,
                ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def interaction_stats(self, days=30):
        """按 uid 统计真实互动量（只算用户自己说的话），给关系沉淀用。

        ``days <= 0`` 表示统计全部历史，这样很早以前聊过的人也会被记进关系网。
        """
        days = int(days or 0)
        cutoff = 0 if days <= 0 else now_ts() - days * 86400
        with self.lock:
            rows = self.conn.execute(
                "SELECT uid, MAX(name) AS name, COUNT(*) AS c, MIN(created_at) AS f, MAX(created_at) AS l "
                "FROM messages WHERE role='user' AND uid!='' AND uid!='bot' AND created_at>=? "
                "GROUP BY uid ORDER BY c DESC LIMIT 1000",
                (cutoff,),
            ).fetchall()
        return [dict(row) for row in rows]

    def active_users(self, since, limit=2):
        with self.lock:
            rows = self.conn.execute(
                "SELECT uid, name, COUNT(*) AS c FROM messages WHERE role='user' AND created_at>? "
                "GROUP BY uid ORDER BY c DESC LIMIT ?", (float(since), int(limit))
            ).fetchall()
        return [dict(row) for row in rows]

    def purge_messages(self, days=14):
        with self.lock:
            self.conn.execute("DELETE FROM messages WHERE created_at<?",
                              (now_ts() - max(1, int(days)) * 86400,))
            self.conn.commit()

    # ---------- 日程 ----------
    def save_schedule(self, day, items):
        with self.lock:
            self.conn.execute(
                "INSERT INTO schedule(day, items, updated) VALUES(?,?,?) "
                "ON CONFLICT(day) DO UPDATE SET items=excluded.items, updated=excluded.updated",
                (str(day), json.dumps(items, ensure_ascii=False), now_ts()),
            )
            self.conn.commit()

    def fade_schedules(self, days=7):
        """7~14 天前的日程去掉细节，只保留每小时骨架。"""
        cutoff = (_now().date() - timedelta(days=max(1, int(days)))).isoformat()
        with self.lock:
            rows = self.conn.execute(
                "SELECT day, items FROM schedule WHERE day < ?", (cutoff,)
            ).fetchall()
            for row in rows:
                try:
                    items = json.loads(row["items"])
                except Exception:
                    continue
                if not isinstance(items, list):
                    continue
                for item in items:
                    if isinstance(item, dict):
                        item.pop("detail", None)
                self.conn.execute(
                    "UPDATE schedule SET items=? WHERE day=?",
                    (json.dumps(items, ensure_ascii=False), row["day"]),
                )
            self.conn.commit()

    def purge_schedules(self, days=14):
        cutoff = (_now().date() - timedelta(days=max(1, int(days)))).isoformat()
        with self.lock:
            self.conn.execute("DELETE FROM schedule WHERE day < ?", (cutoff,))
            self.conn.commit()

    def get_schedule(self, day):
        with self.lock:
            row = self.conn.execute("SELECT items FROM schedule WHERE day=?", (str(day),)).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["items"])
        except Exception:
            return None

    def get_diary(self, day, hour):
        with self.lock:
            row = self.conn.execute(
                "SELECT text FROM schedule_diary WHERE day=? AND hour=?",
                (str(day), str(hour)),
            ).fetchone()
        return str(row["text"] or "") if row else ""

    def save_diary(self, day, hour, text):
        with self.lock:
            self.conn.execute(
                "INSERT INTO schedule_diary(day, hour, text, updated) VALUES(?,?,?,?) "
                "ON CONFLICT(day, hour) DO UPDATE SET text=excluded.text, updated=excluded.updated",
                (str(day), str(hour), str(text or ""), now_ts()),
            )
            self.conn.commit()

    def clear_diaries(self, day):
        with self.lock:
            self.conn.execute("DELETE FROM schedule_diary WHERE day=?", (str(day),))
            self.conn.commit()

    def clear_diaries_from(self, day, hour):
        """只清某个小时及以后的小日记（换城覆盖日程时用，过去的留着）。"""
        with self.lock:
            self.conn.execute(
                "DELETE FROM schedule_diary WHERE day=? AND hour>=?", (str(day), str(hour))
            )
            self.conn.commit()

    def purge_diaries(self, days=30):
        cutoff = (_now().date() - timedelta(days=max(1, int(days)))).isoformat()
        with self.lock:
            self.conn.execute("DELETE FROM schedule_diary WHERE day < ?", (cutoff,))
            self.conn.commit()

    # ---------- 统计 ----------
    def counts(self):
        with self.lock:
            profiles = self.conn.execute("SELECT COUNT(*) AS c FROM profiles").fetchone()["c"]
            memories = 0
            messages = self.conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
        return {"profiles": profiles, "memories": memories, "messages": messages}


# ---------------------------------------------------------------------------
# 状态：九维心情 / 生理期 / 健康 / 天气 / 世界观 / 日程
# ---------------------------------------------------------------------------

def proactive_pending_block_seconds(cfg_int) -> float:
    """发过主动消息后，多久之内不再发下一条。

    原来是写死 6 小时：他只要没在私聊回一句，她半天都不能再开口；
    实际上他在群里聊得火热也算「人在」，这条要跟着放宽。
    """
    try:
        minutes = max(0, int(cfg_int("proactive_pending_max_minutes", 120)))
    except Exception:
        minutes = 120
    return minutes * 60


class HumanState:
    def __init__(self, plugin):
        self.p = plugin
        self.db = plugin.db
        saved_mood = self.db.kv_get("mood", {}) or {}
        self.mood = {key: clamp(saved_mood.get(key, MOOD_BASE[key])) for key in MOOD_KEYS}
        self.mood_ts = to_float(self.db.kv_get("mood_ts", now_ts()), now_ts())
        config_start = self.p.cfg_str("period_start", "").strip()
        seen = self.db.kv_get("period_config_seen", "")
        stored = self.db.kv_get("period_start", "")
        if config_start and config_start != seen:
            try:
                date.fromisoformat(config_start)
                stored = config_start
                self.db.kv_set("period_config_seen", config_start)
            except Exception:
                pass
        self.period_start = stored or (_now().date() - timedelta(days=10)).isoformat()
        self.health = self.db.kv_get("health", {}) or {
            "status": "健康", "since": now_ts(), "until": 0, "note": ""
        }
        self.weather = self.db.kv_get("weather", {}) or {}
        # 财务快照：由金融插件推送过来。她说话时心里有数，但它不是账本本体。
        self.finance = self.db.kv_get("finance", {}) or {}
        if not isinstance(self.finance, dict):
            self.finance = {}
        self.invest = {}
        self.worldview = self.db.kv_get("worldview", {}) or {}
        self.schedule = self.db.kv_get("schedule", {}) or {}
        try:
            self.schedule = self._sanitize_schedule(self.schedule)
        except Exception as exc:
            logger.debug("[amo] 日程清洗失败: %s" % exc)
        self.schedule_ctx = self.db.kv_get("schedule_ctx", {}) or {}
        if not isinstance(self.schedule_ctx, dict):
            self.schedule_ctx = {}
        self.schedule_profile = self.db.kv_get("schedule_profile", {}) or {}
        if not isinstance(self.schedule_profile, dict):
            self.schedule_profile = {}
        self.engine = None
        if ScheduleEngine is not None:
            try:
                self.engine = ScheduleEngine(self)
            except Exception as exc:
                logger.warning("[amo] 日程引擎初始化失败: %s" % exc)
        self.last_daily = self.db.kv_get("last_daily", "")
        self.last_health_roll = self.db.kv_get("last_health_roll", "")

    # ---------- 心情 ----------
    def save_mood(self):
        self.db.kv_set("mood", {key: round(value, 2) for key, value in self.mood.items()})
        self.db.kv_set("mood_ts", self.mood_ts)

    def save(self):
        self.save_mood()
        self.db.kv_set("period_start", self.period_start)
        self.db.kv_set("health", self.health)
        self.db.kv_set("finance", self.finance)
        self.db.kv_set("last_daily", self.last_daily)
        self.db.kv_set("last_health_roll", self.last_health_roll)

    def nudge(self, **deltas):
        for key, value in deltas.items():
            if key in self.mood:
                self.mood[key] = clamp(self.mood[key] + value)
        self.mood_ts = now_ts()
        self.save_mood()

    def decay_mood(self):
        now = now_ts()
        hours = max(0.0, (now - self.mood_ts) / 3600.0)
        if hours <= 0:
            return
        # 连续衰减：约 45 分钟向基础值回落一半，不再要求隔 9 分钟才衰减一次。
        rate = min(0.85, 1.0 - math.exp(-hours / 0.75))
        for key in MOOD_KEYS:
            self.mood[key] = self.mood[key] + (MOOD_BASE[key] - self.mood[key]) * rate
        self.mood_ts = now
        self.save_mood()

    def dominant_mood(self):
        return max(MOOD_KEYS, key=lambda key: self.mood[key])

    def mood_score(self):
        m = self.mood
        positive = (m["开心"] + m["兴奋"] + m["平静"] + m["依恋"]) / 4.0
        negative = (m["郁闷"] + m["疲惫"] + m["生气"] + m["暴躁"] + m["委屈"] + m["焦虑"]) / 6.0
        return clamp(50 + (positive - negative) * 0.8)

    def mood_text(self):
        parts = [key + str(int(round(value))) for key, value in self.mood.items()]
        return " ".join(parts) + "（整体偏" + self.dominant_mood() + "）"

    def observe(self, text):
        senti = sentiment(text)
        if re.search(r"(对不起|抱歉|我错了|别生气|不生气|哄你|哄哄|原谅我)", text or ""):
            # 恋人或普通人的道歉都要能真正降温，不能“道歉也没用”。
            self.nudge(生气=-18, 暴躁=-10, 委屈=-6, 郁闷=-3, 开心=4, 依恋=2)
        elif senti["insult"] or senti["angry"] >= 2:
            self.nudge(生气=9, 暴躁=5, 开心=-8, 委屈=5)
        elif senti["sad"]:
            self.nudge(郁闷=8, 委屈=7, 开心=-4)
        elif senti["aff"]:
            self.nudge(开心=10, 依恋=12, 生气=-5, 暴躁=-3)
        elif senti["pos"]:
            self.nudge(开心=6, 平静=2, 生气=-2)
        elif senti["neg"]:
            self.nudge(郁闷=4, 疲惫=2)
        else:
            self.nudge(平静=1)
        hour = _now().hour
        if 0 <= hour < 6:
            self.nudge(疲惫=3, 平静=2)
        elif 6 <= hour < 9:
            self.nudge(疲惫=-1, 开心=1)
        elif 22 <= hour < 24:
            self.nudge(疲惫=2, 依恋=2)

    # ---------- 生理期 ----------
    def period_info(self):
        if not self.p.cfg_bool("enable_period_simulate", True):
            return {
                "day": 0, "phase": "非生理期", "tone": "", "pain": 0,
                "reply_mult": 1.0, "days_to_next": 0,
                "cycle_days": self.p.cfg_int("period_cycle_days", 28),
                "bleed_days": 0, "next_start": "",
            }
        try:
            start = date.fromisoformat(str(self.period_start))
        except Exception:
            start = _now().date() - timedelta(days=10)
            self.period_start = start.isoformat()
        cycle_days = max(10, self.p.cfg_int("period_cycle_days", 28))
        bleed_days = max(1, min(self.p.cfg_int("period_days", 5), cycle_days - 6))
        day = (_now().date() - start).days % cycle_days + 1
        ovulation_day = max(bleed_days + 1, min(cycle_days - 1, self.p.cfg_int("period_ovulation_day", 14)))
        ovulation_window = max(1, min(9, self.p.cfg_int("period_ovulation_window", 3)))
        ovulation_start = max(bleed_days + 1, ovulation_day - (ovulation_window - 1) // 2)
        ovulation_end = min(cycle_days - 1, ovulation_start + ovulation_window - 1)
        if day <= bleed_days:
            phase = "月经期"
            tone = self.p.cfg_str("period_menstrual_tone", "身体沉沉的，容易累，也更容易委屈")
            pain = min(9, 5 + max(0, bleed_days + 1 - day))
            reply_mult = 0.8
        elif day < ovulation_start:
            phase = "卵泡期"
            tone = self.p.cfg_str("period_follicular_tone", "身体轻快，心情慢慢变好")
            pain = 1
            reply_mult = 1.05
        elif day <= ovulation_end:
            phase = "排卵期"
            tone = self.p.cfg_str("period_ovulatory_tone", "精力最好，也更想和人说话")
            pain = 0
            reply_mult = 1.12
        else:
            phase = "黄体期"
            tone = self.p.cfg_str("period_luteal_tone", "容易烦躁、敏感，想要被哄")
            pain = 3
            reply_mult = 0.88
        pain = max(0, min(10, pain + (md5_int(str(start) + str(day)) % 3) - 1))
        if phase == "月经期":
            phase_day = day
        elif phase == "卵泡期":
            phase_day = day - bleed_days
        elif phase == "排卵期":
            phase_day = day - ovulation_start + 1
        else:
            phase_day = day - ovulation_end
        return {
            "day": day, "phase": phase, "phase_day": max(1, phase_day),
            "tone": tone, "pain": pain,
            "reply_mult": reply_mult, "days_to_next": cycle_days - day + 1,
            "cycle_days": cycle_days, "bleed_days": bleed_days,
            "ovulation_day": ovulation_day, "ovulation_window": ovulation_window,
            "next_start": (_now().date() + timedelta(days=cycle_days - day + 1)).isoformat(),
        }

    def set_period_settings(self, cycle_days=None, start=None):
        """医疗面板改生理期：周期天数 + 上次开始日期（只写配置和 kv）。"""
        changed = False
        if cycle_days is not None:
            try:
                days = max(10, min(60, int(cycle_days)))
                if int(self.p.cfg_int("period_cycle_days", 28)) != days:
                    self.p.config["period_cycle_days"] = days
                    changed = True
            except Exception:
                pass
        if start:
            try:
                self.set_period_start(str(start))
                changed = True
            except Exception:
                pass
        if changed:
            try:
                saver = getattr(self.p.config, "save_config", None)
                if callable(saver):
                    saver()
            except Exception:
                pass
            try:
                remember = getattr(self.p, "_remember_config", None)
                if callable(remember):
                    remember()
            except Exception:
                pass
        return self.period_info()

    def set_period_start(self, value):
        try:
            parsed = date.fromisoformat(str(value))
        except Exception:
            return False
        self.period_start = parsed.isoformat()
        self.db.kv_set("period_start", self.period_start)
        self.db.kv_set("period_config_seen", self.p.cfg_str("period_start", ""))
        return True

    # ---------- 健康 ----------
    def health_info(self):
        status = self.health.get("status", "健康")
        until = to_float(self.health.get("until", 0))
        if status != "健康" and until and now_ts() >= until:
            self.health = {"status": "健康", "since": now_ts(), "until": 0, "note": ""}
            self.db.kv_set("health", self.health)
            status = "健康"
        return {
            "status": status,
            "since": to_float(self.health.get("since", 0)),
            "until": to_float(self.health.get("until", 0)),
            "note": self.health.get("note", ""),
            # 「疲惫」只是累，不是病：以前 status != 健康 全算 sick，于是休息日
            # 排成「吃药、量体温、捂汗」的病号一天。
            "sick": status in SICK_STATUSES,
        }

    def set_health(self, status, hours=24, note=""):
        if status == "健康":
            self.health = {"status": "健康", "since": now_ts(), "until": 0, "note": ""}
        else:
            self.health = {
                "status": status, "since": now_ts(),
                "until": now_ts() + max(1, hours) * 3600, "note": note,
            }
        self.db.kv_set("health", self.health)

    def roll_health(self):
        # 装了医疗插件就由它管病情：这里不再自己掷骰子，只同步它的状态。
        # 否则两边各存一份身体状态，她这边说「恢复中」、那边已经「健康」。
        medical_getter = getattr(self.p, "_medical", None)
        if callable(medical_getter):
            try:
                if medical_getter() is not None:
                    self.p._sync_health_from_medical()
                    return
            except Exception as exc:
                logger.debug("[amo] 同步医疗状态失败: %s" % exc)
        if not self.p.cfg_bool("enable_sick_random", True):
            return
        now = now_ts()
        if self.health.get("status") != "健康" and to_float(self.health.get("until", 0)) <= now:
            self.health = {"status": "健康", "since": now, "until": 0, "note": ""}
            self.db.kv_set("health", self.health)
        if self.last_health_roll == today_str():
            return
        self.last_health_roll = today_str()
        self.db.kv_set("last_health_roll", self.last_health_roll)
        if self.health.get("status") != "健康":
            return
        prob = self.p.cfg_float("sick_prob", 0.02)
        weather = self.weather or {}
        if weather.get("tag") in ("rain", "storm", "snow"):
            prob += 0.03
        if to_float(weather.get("temp", 20), 20) < 8:
            prob += 0.02
        if self.period_info()["phase"] == "月经期":
            prob += 0.02
        if self.mood.get("疲惫", 0) > 65:
            prob += 0.02
        if random.random() >= prob:
            return
        status = random.choice(["轻微不适", "感冒", "低烧", "疲惫"])
        hours = {"轻微不适": 12, "感冒": 48, "低烧": 24, "疲惫": 10}[status]
        note = {
            "轻微不适": "有点不舒服，说不上哪里难受",
            "感冒": "鼻子堵堵的，头有点沉",
            "低烧": "身上发烫，没什么力气",
            "疲惫": "没由来的累，只想躺着",
        }[status]
        self.health = {"status": status, "since": now, "until": now + hours * 3600, "note": note}
        self.db.kv_set("health", self.health)

    # ---------- 天气 ----------
    @staticmethod
    def _weather_base_url(value, default=""):
        """和风 Host 兼容：允许只填域名（自动补 https://），也允许带路径。"""
        text = str(value or default or "").strip().rstrip("/")
        if not text:
            return ""
        if not text.startswith(("http://", "https://")):
            text = "https://" + text
        return text

    @staticmethod
    def _weather_tag(text):
        if any(word in text for word in ("雷", "暴雨")):
            return "storm"
        if "雪" in text:
            return "snow"
        if "雨" in text:
            return "rain"
        if "晴" in text:
            return "clear"
        if "阴" in text:
            return "overcast"
        if "雾" in text or "霾" in text:
            return "fog"
        return "cloud"

    def _simulate_weather(self):
        month = _now().date().month
        rng = random.Random(md5_int(today_str() + str(_now().hour)))
        if month in (12, 1, 2):
            choices = [("晴", "clear"), ("多云", "cloud"), ("阴", "overcast"),
                       ("小雪", "snow"), ("小雨", "rain")]
            base_temp = 7
        elif month in (6, 7, 8):
            choices = [("晴", "clear"), ("多云", "cloud"), ("雷阵雨", "storm"),
                       ("阵雨", "rain"), ("阴", "overcast")]
            base_temp = 29
        else:
            choices = [("晴", "clear"), ("多云", "cloud"), ("小雨", "rain"),
                       ("阴", "overcast")]
            base_temp = 19
        text, tag = rng.choice(choices)
        temp = base_temp + rng.randint(-4, 4)
        city = (
            self.p.cfg_str("weather_city", "").strip()
            or str((getattr(self, "schedule_profile", {}) or {}).get("city") or "").strip()
            or "贵阳"
        )
        return {
            # 存显示名，refresh_weather 的缓存签名才比得上（weather_city 可能是数字 ID）
            "city": (self.p.cfg_str("weather_city_name", "") or "").strip() or city,
            "text": text, "tag": tag, "temp": temp,
            "humidity": rng.randint(40, 90),
            "wind": random.choice(["东风", "南风", "西北风", "微风"]) + str(rng.randint(1, 4)) + "级",
            "ts": now_ts(), "source": "simulate", "ok": True, "error": "",
            "key_set": bool(self.p.cfg_str("hefeng_key", "")),
            "host": self.p.cfg_str("weather_host", ""),
        }

    async def _qweather_payload(self, response, label):
        try:
            text = await response.text()
        except Exception as exc:
            logger.warning("[amo] 和风天气 %s 读取响应失败: %s" % (label, exc))
            return {}
        if not str(text or "").strip():
            logger.warning("[amo] 和风天气 %s 返回空响应 HTTP %s" % (label, getattr(response, "status", "?")))
            return {}
        try:
            payload = json.loads(text)
        except Exception:
            logger.warning(
                "[amo] 和风天气 %s 返回非 JSON HTTP %s: %s"
                % (label, getattr(response, "status", "?"), str(text)[:160])
            )
            return {}
        if not isinstance(payload, dict):
            logger.warning("[amo] 和风天气 %s 返回格式异常: %s" % (label, type(payload).__name__))
            return {}
        code = str(payload.get("code") or "")
        status = to_int(getattr(response, "status", 0), 0)
        if status >= 400 or (code and code != "200"):
            logger.warning(
                "[amo] 和风天气 %s HTTP %s code=%s: %s"
                % (label, status, code or "?", str(payload)[:200])
            )
        return payload

    async def _qweather_get(self, url, params):
        """和风请求：用系统网络栈（线程里 urllib），避免 aiohttp 在部分环境超时。"""
        import urllib.parse
        import urllib.request

        key = self.p.cfg_str("hefeng_key", "")
        query = dict(params or {})
        query["key"] = key
        full = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(query)

        def _do():
            req = urllib.request.Request(
                full, headers={"X-QW-Api-Key": key, "Accept-Encoding": "identity"}
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw = resp.read()
            if raw[:2] == b"\x1f\x8b":
                import gzip
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8"))

        return await asyncio.to_thread(_do)

    def _location_of(self, city):
        """中文城市名换成 LocationID；数字/坐标/空值原样返回。

        注意：这两个取天气的方法在 HumanState 上，不能调插件的 `_city_lookup`，
        所以直接用离线表模块的纯函数，模块不在就原样交给上层。
        """
        try:
            try:
                from .amo_city_index import city_location
            except Exception:
                from amo_city_index import city_location
            return city_location(city)
        except Exception as exc:
            logger.debug("[amo] 城市名解析失败: %s" % exc)
            return str(city or "").strip()

    async def _fetch_qweather(self, key, city):
        host = self._weather_base_url(self.p.cfg_str("weather_host", ""))
        if not host:
            return None
        legacy_hosts = {"https://devapi.qweather.com", "https://api.qweather.com"}
        if host in legacy_hosts:
            logger.warning("[amo] 和风天气公共 API 域名已停服，请在配置里填写控制台的 API Host")
        geo_raw = self._weather_base_url(self.p.cfg_str("weather_geo_host", ""))
        if geo_raw:
            geo_base = geo_raw
            if geo_base.endswith("/city/lookup"):
                geo_base = geo_base[: -len("/city/lookup")]
            if not geo_base.endswith(("/geo/v2", "/v2")):
                geo_base += "/geo/v2"
        else:
            geo_base = host + "/geo/v2"
        location = self._location_of(city)
        try:
            # 坐标（经度,纬度）和风直接吃，别再去 GeoAPI 换 ID（那会 403）
            if not location.isdigit() and "," not in location:
                geo = await self._qweather_get(
                    geo_base + "/city/lookup", {"location": location, "number": 1}
                )
                if str(geo.get("code") or "") != "200" or not isinstance(geo.get("location"), list):
                    return None
                first = geo["location"][0] if geo["location"] else None
                if not isinstance(first, dict) or not first.get("id"):
                    return None
                location = str(first["id"])
            data = await self._qweather_get(host + "/v7/weather/now", {"location": location})
            if not isinstance(data, dict) or str(data.get("code") or "") != "200":
                logger.warning("[amo] 和风天气 now 返回异常: %s" % str(data)[:160])
                return None
            now = data.get("now")
            if not isinstance(now, dict):
                logger.warning("[amo] 和风天气 now 字段缺失或格式异常")
                return None
            text = str(now.get("text") or "多云")
            city_name = (self.p.cfg_str("weather_city_name", "") or "").strip() or city
            return {
                "city": city_name, "text": text, "tag": self._weather_tag(text),
                "temp": to_int(now.get("temp")), "humidity": to_int(now.get("humidity")),
                "wind": str(now.get("windDir", "")) + str(now.get("windScale", "")) + "级",
                "ts": now_ts(), "source": "qweather", "ok": True, "error": "",
                "key_set": True,
                "host": host,
            }
        except Exception as exc:
            logger.warning("[amo] 和风天气接口失败: %s %r" % (type(exc).__name__, exc))
            return None

    async def _fetch_qweather_daily(self, key, city, days=3, fresh=False):
        """明天/后天的预报；缓存 3 小时，避免后台循环反复打接口。

        fresh=True 跳过缓存：晚上发预警前要拿最新的一份，早上判断的那份不算数。
        """
        cache = self.db.kv_get("weather_daily", {}) or {}
        city = str(city or "").strip()
        if (
            not fresh
            and isinstance(cache, dict)
            and cache.get("ts")
            and now_ts() - to_float(cache.get("ts"), 0) < 3 * 3600
            and str(cache.get("city") or "") == city
            and to_int(cache.get("days")) == int(days)
        ):
            items = cache.get("items")
            return items if isinstance(items, list) else []
        host = self._weather_base_url(self.p.cfg_str("weather_host", ""))
        if not host:
            return []
        geo_raw = self._weather_base_url(self.p.cfg_str("weather_geo_host", ""))
        if geo_raw:
            geo_base = geo_raw
            if geo_base.endswith("/city/lookup"):
                geo_base = geo_base[: -len("/city/lookup")]
            if not geo_base.endswith(("/geo/v2", "/v2")):
                geo_base += "/geo/v2"
        else:
            geo_base = host + "/geo/v2"
        location = self._location_of(city)
        try:
            # 坐标（经度,纬度）和风直接吃，别再去 GeoAPI 换 ID（那会 403）
            if not location.isdigit() and "," not in location:
                geo = await self._qweather_get(
                    geo_base + "/city/lookup", {"location": location, "number": 1}
                )
                if str(geo.get("code") or "") != "200" or not isinstance(geo.get("location"), list):
                    return []
                first = geo["location"][0] if geo["location"] else None
                if not isinstance(first, dict) or not first.get("id"):
                    return []
                location = str(first["id"])
            data = await self._qweather_get(host + "/v7/weather/%dd" % int(days), {"location": location})
            if not isinstance(data, dict) or str(data.get("code") or "") != "200":
                logger.warning("[amo] 和风天气预报返回异常: %s" % str(data)[:160])
                return []
            items = parse_weather_daily(data)
        except Exception as exc:
            logger.warning("[amo] 和风天气预报接口失败: %s %r" % (type(exc).__name__, exc))
            return []
        self.db.kv_set("weather_daily", {"ts": now_ts(), "city": city, "days": int(days), "items": items})
        return items

    async def refresh_weather(self, force=False):
        try:
            self.p._reload_config_if_changed()
        except Exception:
            pass
        try:
            self._sync_weather_city_config()
        except Exception:
            pass
        current = self.weather or {}
        key = self.p.cfg_str("hefeng_key", "")
        city = (
            self.p.cfg_str("weather_city", "").strip()
            or str((getattr(self, "schedule_profile", {}) or {}).get("city") or "").strip()
            or "贵阳"
        )
        host = self.p.cfg_str("weather_host", "")
        # 配置里的城市/Key/Host 变了就必须重取，不能继续用旧缓存。
        # 比较用显示名：weather_city 可能是数字 LocationID，缓存里存的却是「东莞」这种名字，
        # 拿数字去比永远不相等 → 每次轮询都强制重取天气（30 秒一次，免费额度会被打光）。
        city_label = (self.p.cfg_str("weather_city_name", "") or "").strip() or city
        current_signature = (current.get("city"), bool(current.get("key_set")), current.get("host"))
        desired_signature = (city_label, bool(key), host)
        if current_signature != desired_signature:
            force = True
        if not force and current.get("ts") and now_ts() - current["ts"] < 1800:
            return current
        # 刚刷过就别再打接口（双击「设置」、面板刷新和后台 tick 撞车）
        if force and current.get("ts") and now_ts() - to_float(current["ts"], 0) < 3:
            return current
        old_tag = current.get("tag")
        data = None
        if key:
            data = await self._fetch_qweather(key, city)
        if not data:
            data = self._simulate_weather()
        self.weather = data
        self.db.kv_set("weather", data)
        if data.get("tag") != old_tag:
            if data.get("tag") in ("rain", "storm", "snow"):
                self.nudge(郁闷=2, 平静=2)
            elif data.get("tag") == "clear":
                self.nudge(开心=2)
        return data

    def weather_text(self):
        weather = self.weather or {}
        if not weather:
            return "还不知道天气"
        return "%s %s %s℃ 湿度%s%% %s" % (
            weather.get("city", ""), weather.get("text", ""),
            weather.get("temp", ""), weather.get("humidity", ""), weather.get("wind", ""),
        )

    def weather_brief(self):
        """面板用的一行天气摘要（只读缓存，不请求和风）。"""
        weather = self.weather or {}
        if not weather:
            return {}
        return {
            "city": str(weather.get("city") or ""),
            "text": str(weather.get("text") or ""),
            "temp": weather.get("temp"),
            "humidity": weather.get("humidity"),
            "wind": str(weather.get("wind") or ""),
            "tag": str(weather.get("tag") or ""),
            "source": str(weather.get("source") or ""),
            "ts": to_float(weather.get("ts"), 0),
        }

    # ---------- 世界观 ----------
    def _fallback_world(self):
        return {
            "name": self.p.persona_name or self.p.cfg_str("bot_name", "") or "陪伴",
            "age": 22,
            "city": (
                self.p.cfg_str("weather_city_name", "").strip()
                or self.p.cfg_str("weather_city", "").strip()
                or str((getattr(self, "schedule_profile", {}) or {}).get("city") or "").strip()
                or "贵阳"
            ),
            "occupation": "普通上班族",
            "workplace": "公司",
            "personality": "温柔、敏感，偶尔有点小脾气",
            "hobbies": ["听歌", "散步", "喝奶茶"],
            "daily_life": "一个人在城市里上班、生活，会为小事开心，也会有力气用光的时候。",
            "world_rules": "这是一个普通的现代都市，没有超能力；角色要上班、吃饭、睡觉，也会生病和情绪低落。",
            "summary": "一个在城市里认真生活的普通女孩。",
            "_ts": now_ts(),
        }

    async def ensure_worldview(self, umo, force=False):
        if not force and self.worldview and now_ts() - to_float(self.worldview.get("_ts")) < 7 * 86400:
            return self.worldview
        persona = await self.p.llm.persona(umo)
        data = await self.p.llm.gen_worldview(umo, persona)
        if not data:
            data = self._fallback_world()
        name = await self.p._persona_name_for(umo)
        if name:
            data["name"] = name
        data["_ts"] = now_ts()
        self.worldview = data
        self.db.kv_set("worldview", data)
        if name:
            self.p.persona_name = name
            self.p.bot_name = name
        elif data.get("name") and self.p.cfg_str("bot_name", ""):
            self.p.bot_name = data["name"]
        return data

    def worldview_text(self):
        world = self.worldview or {}
        if not world:
            return "还没有生成世界观。"
        hobbies = world.get("hobbies") or []
        if isinstance(hobbies, list):
            hobbies = "、".join([str(item) for item in hobbies])
        return "\n".join([
            "名字：%s" % world.get("name", ""),
            "年龄：%s" % world.get("age", ""),
            "城市：%s" % world.get("city", ""),
            "职业：%s" % world.get("occupation", ""),
            "任职：%s" % world.get("workplace", ""),
            "性格：%s" % world.get("personality", ""),
            "爱好：%s" % hobbies,
            "日常：%s" % world.get("daily_life", ""),
            "规则：%s" % world.get("world_rules", ""),
        ])

    # ---------- 日程（主干生成 + 动态展开） ----------
    @staticmethod
    def _hourly_schedule(items):
        """把任意日程整理成 24 条整点日程；最后一条固定 23:00-24:00。"""
        valid = [item for item in (items or []) if isinstance(item, dict) and item.get("start")]
        valid.sort(key=lambda item: parse_hhmm(item.get("start")))
        result = []
        for hour in range(24):
            start_min = hour * 60
            end_min = start_min + 60
            found = None
            for item in valid:
                begin = parse_hhmm(item.get("start"))
                finish = parse_hhmm(item.get("end")) or (begin + 60)
                if begin <= start_min < finish:
                    found = item
                    break
            entry = {
                "start": "%02d:00" % hour,
                "end": "24:00" if hour == 23 else "%02d:00" % (hour + 1),
                "activity": "睡觉" if hour < 7 or hour >= 23 else "休息",
                "place": "家",
                "category": "sleep" if hour < 7 or hour >= 23 else "rest",
            }
            if found:
                entry.update({
                    "activity": found.get("activity", "休息"),
                    "place": found.get("place", "家"),
                    "category": found.get("category", "rest"),
                })
                for key in ("zone", "transit", "vehicle", "detail", "spot",
                            "event", "mood", "mood_valence", "outfit"):
                    if found.get(key) not in (None, "", 0):
                        entry[key] = found.get(key)
                if isinstance(found.get("effects"), dict):
                    entry["effects"] = found.get("effects")
                if found.get("soothe"):
                    entry["soothe"] = True
            result.append(entry)
        return result

    @staticmethod
    def _fmt_minutes(value):
        value = max(0, min(24 * 60, int(value)))
        if value >= 24 * 60:
            return "24:00"
        return "%02d:%02d" % (value // 60, value % 60)

    def schedule_tree(self, day=None):
        """一级 4 段、二级每小时；不再生成三级 10 分钟。"""
        day = str(day or today_str())
        hourly = self._hourly_schedule(self.schedule.get(day) or self.db.get_schedule(day) or [])
        now_min = minutes_now()
        is_today = day == today_str()
        blocks = [
            {"start": "00:00", "end": "06:00", "title": "深夜"},
            {"start": "06:00", "end": "12:00", "title": "上午"},
            {"start": "12:00", "end": "18:00", "title": "中午"},
            {"start": "18:00", "end": "24:00", "title": "晚上"},
        ]
        for block in blocks:
            bstart = parse_hhmm(block["start"])
            bend = 24 * 60 if block["end"] == "24:00" else parse_hhmm(block["end"])
            children = []
            for item in hourly:
                start = max(bstart, parse_hhmm(item.get("start")))
                end = min(bend, parse_hhmm(item.get("end")))
                if start >= end:
                    continue
                hour = {
                    "start": self._fmt_minutes(start),
                    "end": self._fmt_minutes(end),
                    "activity": item.get("activity", "休息"),
                    "place": item.get("place", "家"),
                    "category": item.get("category", "rest"),
                    "zone": item.get("zone", ""),
                    "transit": item.get("transit", ""),
                    "vehicle": item.get("vehicle", ""),
                    "detail": item.get("detail", ""),
                    "event": item.get("event", ""),
                    "mood": item.get("mood", ""),
                    "outfit": item.get("outfit", ""),
                    "current": bool(is_today and start <= now_min < end),
                }
                children.append(hour)
            block["date"] = day
            block["children"] = children
            block["current"] = any(child["current"] for child in children)
            if children:
                activities = [str(child.get("activity") or "") for child in children]
                if all(item.get("category") == "sleep" for item in children):
                    block["activity"] = "睡觉"
                elif any(item.get("category") in ("play", "social") for item in children):
                    block["activity"] = "出去玩"
                elif any(item.get("category") == "work" for item in children):
                    block["activity"] = "上班"
                elif any(item.get("category") == "commute" for item in children):
                    block["activity"] = "回家"
                elif any(item.get("category") == "meal" for item in children):
                    block["activity"] = "吃饭"
                elif any(item.get("category") == "rest" for item in children):
                    block["activity"] = "休息"
                else:
                    block["activity"] = children[0].get("activity") or "休息"
                block["place"] = children[0].get("place") or ""
        return blocks

    @staticmethod
    def _cover_schedule(items):
        """兼容旧数据：补上 00:00 到第一条安排之间的睡眠段。"""
        if not isinstance(items, list) or not items:
            return items
        valid = [item for item in items if isinstance(item, dict) and item.get("start")]
        if not valid:
            return items
        ordered = sorted(valid, key=lambda item: parse_hhmm(item.get("start")))
        first_start = ordered[0].get("start", "00:00")
        if parse_hhmm(first_start) > 0:
            ordered.insert(0, {
                "start": "00:00", "end": first_start,
                "activity": "睡觉", "place": "家", "category": "sleep", "zone": "home",
            })
        return ordered

    def _emergency_schedule(self):
        """新引擎不可用时的最小兜底，保证 24 小时闭环、不瞬移。"""
        profile = getattr(self, "schedule_profile", {}) or {}
        home = self.p.cfg_str("schedule_home", "") or profile.get("home") or "家"
        office = self.p.cfg_str("schedule_workplace", "") or profile.get("workplace") or "公司"
        items = []
        for hour in range(24):
            if hour < 7 or hour >= 23:
                activity, place, zone, category = "睡觉", home, "home", "sleep"
            elif hour < 8:
                activity, place, zone, category = "起床洗漱", home, "home", "life"
            elif hour < 9:
                activity, place, zone, category = "通勤去公司", "路上", "road", "commute"
            elif hour < 12:
                activity, place, zone, category = "上班", office, "office", "work"
            elif hour < 13:
                activity, place, zone, category = "吃午饭", office + "附近", "restaurant", "meal"
            elif hour < 14:
                activity, place, zone, category = "午休", office, "office", "rest"
            elif hour < 18:
                activity, place, zone, category = "上班", office, "office", "work"
            elif hour < 19:
                activity, place, zone, category = "下班回家", "路上", "road", "commute"
            elif hour < 20:
                activity, place, zone, category = "吃晚饭", home, "home", "meal"
            elif hour < 22:
                activity, place, zone, category = "休息", home, "home", "rest"
            else:
                activity, place, zone, category = "洗澡护肤", home, "home", "life"
            items.append({
                "start": "%02d:00" % hour,
                "end": "24:00" if hour == 23 else "%02d:00" % (hour + 1),
                "activity": activity, "place": place, "zone": zone,
                "category": category,
            })
        return items

    def _day_types(self) -> list:
        """读配置里的日子类型；没配就用默认那六种。"""
        if normalize_day_types is None:
            return []
        raw = []
        try:
            raw = self.p.cfg_list("schedule_day_types", [])
        except Exception:
            raw = []
        return normalize_day_types(raw or None)

    def _active_trip(self, day=None):
        """今天在不在外面：自己旅游（wander_trip）或跟他出门（travel）。

        返回 {"city","kind","trip","return_day","return_hour"} 或 None。
        没有这个判定，日程一被重新生成就变「宅家日」——人还在南阳，日程写着家。
        """
        day = str(day or today_str())
        for key, kind in (("wander_trip", "solo"), ("travel", "follow")):
            try:
                trip = self.db.kv_get(key, {}) or {}
            except Exception:
                continue
            if not isinstance(trip, dict):
                continue
            city = str(trip.get("city") or "").strip()
            if not city:
                continue
            start = str(trip.get("day") or trip.get("start_day") or "")
            ret = str(trip.get("return_day") or start)
            if not start or not (start <= day <= ret):
                continue
            if str(trip.get("phase") or "") in ("cancelled", "done"):
                continue
            try:
                back = int(trip.get("return_hour") or 22)
            except (TypeError, ValueError):
                back = 22
            return {"city": city, "kind": kind, "trip": trip,
                    "return_day": ret, "return_hour": back}
        return None

    def _sync_trip_schedule(self, items, day=None):
        """日程必须和她在哪一致：今天在外面，就把还没过的时段换成外面的行程。

        出行覆盖层要**每条 ensure_schedule 分支**都过一遍：只放在生成后面，
        重启/重建日程走「已有日程」那条早退分支时就会被漏掉，于是人在旅游、日程在家。
        """
        day = str(day or today_str())
        trip = self._active_trip(day)
        if not trip:
            return items
        try:
            if not self.p.cfg_bool("city_travel_schedule", True):
                return items
        except Exception:
            pass
        city = str(trip.get("city") or "")
        if not city:
            return items
        if day == trip.get("return_day"):
            try:
                if _now().hour >= int(trip.get("return_hour") or 22):
                    return items
            except Exception:
                pass
            try:
                self.apply_return_overlay(city, int(trip.get("return_hour") or 22))
            except Exception as exc:
                logger.warning("[amo] 回程日程同步失败（%s）: %s" % (city, exc))
                return items
        else:
            try:
                self.apply_travel_overlay(city)
            except Exception as exc:
                logger.warning("[amo] 出行日程同步失败（%s）: %s" % (city, exc))
                return items
        merged = self.schedule.get(day) or []
        if not self._schedule_has_city(merged, city):
            # 覆盖层没落到日程上（老版本、异常、或刚被别处重建）：按出行事件直接重建今天，
            # 宁可多写一次，也不能让她「人在南阳、日程在家」。
            try:
                spots = _city_pick_spots(self.p.scenic_spots(), city, day)
            except Exception:
                spots = []
            from_hour = 0 if not merged else _now().hour
            until = None
            if day == trip.get("return_day"):
                until = max(from_hour, int(trip.get("return_hour") or 22))
            kwargs = {"spots": spots}
            if until is not None:
                kwargs["until_hour"] = until
            merged = _city_travel_events(city, from_hour, **kwargs) or merged
        self._bill_trip(trip, day)
        if merged:
            merged = self._strip_his_presence(self._hourly_schedule(merged), day)
            self.schedule[day] = merged
            self.db.kv_set("schedule", self._sanitize_schedule(self.schedule))
            self.db.save_schedule(day, merged)
            logger.info("[amo] 出行日程对齐：今天在 %s（%s 回）" % (
                city, "%02d:00" % int(trip.get("return_hour") or 22)))
            return merged
        return items

    #: 旅游花费的量级（人民币）：门票 + 交通 + 吃饭，一天一次，按城市/日期固定
    TRAVEL_COST_RANGE = {"ticket": (60, 220), "traffic": (40, 240), "meal": (60, 180)}

    def _home_name(self):
        """她自己的家叫什么：配置 > 画像 > 「家」。"""
        try:
            profile = getattr(self, "schedule_profile", {}) or {}
            return (self.p.cfg_str("schedule_home", "") or profile.get("home") or "家").strip() or "家"
        except Exception:
            return "家"

    #: 日程里不许凭空出现的人称
    HIS_WORDS = ("他", "阿墨", "老公")

    def _his_present_today(self, day=None):
        """今天他是不是真的在她身边：只认聊天里确认过的事实。

        `his_present_day` 由聊天处理写入（他说「我在楼下/我到你那儿了」）。没有这条，
        日程里就不许出现他——绝不替她虚构一个陪着她的男朋友。
        """
        day = str(day or today_str())
        try:
            return str(self.db.kv_get("his_present_day", "") or "").strip() == day
        except Exception:
            return False

    HIS_REWRITES = (
        ("醒来看他还在睡", "醒来赖床刷手机"),
        ("跟他一起出门", "自己出门"),
        ("和他一起出门", "自己出门"),
        ("跟他一起", "自己"),
        ("和他一起", "自己"),
        ("跟他出门", "自己出门"),
        ("等他忙完", "歇一会儿"),
        ("等他回来", "自己待着"),
        ("在他电脑里睡着", "睡着"),
        ("在他电脑里睡", "睡觉"),
        ("他还没回来", "家里就我一个"),
        ("你在等他", "你在家"),
        ("陪他", "自己待着"),
    )

    def _sanitize_schedule(self, sched):
        """任何写库/加载的日程都过一遍：他只能出现在聊天里。"""
        try:
            if isinstance(sched, dict):
                return {str(day): self._strip_his_presence(items, str(day))
                        for day, items in sched.items()}
        except Exception:
            return sched
        return sched

    def _strip_his_presence(self, items, day=None):
        """把日程里凭空出现的他抹掉：他只能出现在聊天里。

        只有聊天确认他今天在场（`his_present_day`）时才保留。宁可活动写得朴素，
        也不能让她以为「他明明在外地却一直在陪我」。
        """
        if not items:
            return items
        day = str(day or today_str())
        # 他只能出现在聊天里：不管聊天里说没说他今天在，日程一律按她一个人写。
        # （这里以前会因为 his_present_day 早退，于是日程里冒出「他在房间」）
        home = self._home_name()
        out = []
        for item in items:
            if not isinstance(item, dict):
                out.append(item)
                continue
            row = dict(item)
            activity = str(row.get("activity") or "")
            place = str(row.get("place") or "")
            if any(word in activity for word in self.HIS_WORDS):
                cleaned = activity
                for old, new in self.HIS_REWRITES:
                    cleaned = cleaned.replace(old, new)
                cleaned = cleaned.replace("阿墨", "").replace("老公", "").replace("他", "")
                cleaned = cleaned.strip("，,、~ 　")
                if not cleaned or any(word in cleaned for word in self.HIS_WORDS):
                    cleaned = {
                        "sleep": "睡觉", "meal": "吃饭", "life": "收拾一下",
                        "work": "忙自己的事", "rest": "歇着", "play": "自己出去逛",
                        "commute": "在路上", "exercise": "活动一下",
                    }.get(str(row.get("category") or ""), "自己待着")
                row["activity"] = cleaned
                row["his_hidden"] = True
            if any(word in place for word in self.HIS_WORDS):
                row["place"] = home
            out.append(row)
        return out

    def _trip_cost(self, city, day):
        """今天出去玩大概花多少：确定性随机，同一天同一城只有一个数。"""
        chooser = random.Random("amo-travel:%s:%s" % (day, city))
        total = 0
        for low, high in self.TRAVEL_COST_RANGE.values():
            total += chooser.randint(low, high)
        return float(total)

    def _bill_trip(self, trip, day=None):
        """出去旅游要花钱：走 `charge()` → 金融账本 → 写进记忆。

        一天一次，幂等号 `travel:<日期>:<城市>`；扣成功才记账，失败下次再来，
        不阻塞聊天（后台任务）。
        """
        day = str(day or today_str())
        city = str((trip or {}).get("city") or "").strip()
        if not city:
            return
        rid = "travel:%s:%s" % (day, city)
        try:
            if self.db.kv_get("travel_billed:" + rid, ""):
                return
        except Exception:
            pass
        cost = self._trip_cost(city, day)
        detail = "去%s玩：门票、交通、吃饭" % city
        charge = getattr(self.p, "charge", None)
        if not callable(charge):
            return
        try:
            coro = self._bill_trip_once(rid, cost, city, detail)
        except Exception as exc:
            logger.debug("[amo] 旅游记账准备失败: %s" % exc)
            return
        spawn = getattr(self.p, "_spawn", None)
        try:
            if callable(spawn):
                spawn(coro)
            else:
                coro.close()
        except Exception as exc:
            logger.debug("[amo] 旅游记账任务起不来: %s" % exc)

    async def _bill_trip_once(self, rid, cost, city, detail):
        try:
            result = await self.p.charge(
                cost, reason="旅游", payee=city, request_id=rid,
                source="travel", detail=detail,
            )
        except Exception as exc:
            logger.warning("[amo] 旅游记账失败: %s" % exc)
            return
        if isinstance(result, dict) and result.get("ok"):
            try:
                self.db.kv_set("travel_billed:" + rid, True)
            except Exception:
                pass
            logger.info("[amo] 旅游记账：%s ¥%.2f（余额 ¥%s）" % (
                city, float(cost), result.get("balance")))
        elif isinstance(result, dict):
            logger.info("[amo] 旅游记账没扣成：%s（%s）" % (
                city, result.get("reason") or result.get("code") or ""))

    @staticmethod
    def _schedule_has_city(items, city):
        """今天的日程里有没有出行城市（没有就说明覆盖层没生效）。"""
        name = str(city or "").strip()
        if not name:
            return True
        for item in (items or []):
            if not isinstance(item, dict):
                continue
            if name in str(item.get("place") or ""):
                return True
        return False

    def _today_day_type(self, day: str) -> dict:
        """今天是什么日子：上班日 / 休息日 / 外出日 / 宅家日 / 加班日 / 摸鱼日。"""
        if pick_day_type is None:
            return {"id": "workday", "name": "上班日", "guide": ""}
        try:
            import datetime as _dt

            d = _dt.date.fromisoformat(str(day))
            is_weekend = d.weekday() >= 5
            picked = pick_day_type(self._day_types(), is_weekend, str(day))
            trip = self._active_trip(str(day))
            if trip and str(trip.get("city") or "") != _CITY_DEFAULT:
                # 人在外面旅游，日子类型就不能是「宅家日」，否则骨架一整天空在家
                outing = next(
                    (item for item in self._day_types() if str(item.get("id") or "") == "outing"),
                    {"id": "outing", "name": "外出日", "guide": ""},
                )
                picked = dict(outing)
                logger.info("[amo] 今天在外面（%s），日子类型改为：%s" % (
                    trip.get("city"), picked.get("name")))
            self.db.kv_set("day_type_" + str(day), picked)
            logger.debug("[amo] 今天的日子类型: %s" % picked.get("name"))
            return picked
        except Exception as exc:
            logger.debug("[amo] 日子类型抽取失败: %s" % exc)
            return {"id": "workday", "name": "上班日", "guide": ""}

    async def _apply_user_schedule_change(self, umo, user_text: str) -> None:
        """用户明确安排了行程（来接我 / 一起睡 / 出去吃），把那一段日程改掉。"""
        if detect_schedule_change is None or apply_sched_change is None:
            return
        try:
            change = detect_schedule_change(user_text)
            if not change:
                return
            key = _clock_now().date().isoformat()
            items = self.state.schedule.get(key) or self.db.get_schedule(key) or []
            if not items:
                return
            new_items = apply_sched_change(items, change, _clock_now())
            if new_items == items:
                return
            self.state.schedule[key] = new_items
            self.db.kv_set("schedule", self._sanitize_schedule(self.state.schedule))
            self.db.save_schedule(key, new_items)
            logger.info("[amo] 按用户的话改了日程: %s" % change.get("activity"))
        except Exception as exc:
            logger.debug("[amo] 按话改日程失败: %s" % exc)

    async def ensure_schedule(self, umo, force=False):
        """每天只生成一次主干；点击二级卡片时再动态生成这一小时的日记。"""
        today = today_str()
        meta = day_meta(today)
        existing = None if force else self.schedule.get(today)
        context = self.schedule_ctx.get(today) or {}
        version_ok = (
            self.db.kv_get("schedule_version", "") == SCHEDULE_VERSION
            and isinstance(context, dict)
            and context.get("version") == "backbone-v5"
        )
        day_type = self._today_day_type(today)
        if existing and version_ok and not force:
            hourly = self._hourly_schedule(existing)
            # 老日程没有 outfit、或穿搭规则升级过：补一次并落盘，不用等第二天重新生成
            needs_outfit = (
                getattr(self.p, "outfits", None) is not None
                and (
                    self.db.kv_get("outfit_version", "") != OUTFIT_VERSION
                    or any(isinstance(item, dict) and not item.get("outfit") for item in hourly)
                )
            )
            if needs_outfit:
                try:
                    persona_text = await self.p.llm.persona(umo) if self.p.llm else ""
                except Exception:
                    persona_text = ""
                hourly = self.p.outfits.assign(hourly, today, persona_text)
                self.db.kv_set("outfit_version", OUTFIT_VERSION)
            if hourly != existing:
                self.schedule[today] = hourly
                self.db.kv_set("schedule", self._sanitize_schedule(self.schedule))
                self.db.save_schedule(today, hourly)
            hourly = self._normalize_items(
                self._strip_his_presence(self._sync_trip_schedule(hourly, today), today))
            self.warm_schedule_diaries(today, hourly, umo)
            return hourly
        world = await self.ensure_worldview(umo)
        persona = ""
        try:
            if self.p.llm is not None:
                persona = await self.p.llm.persona(umo)
        except Exception:
            persona = ""
        if self.engine is not None:
            try:
                self.schedule_profile = self.engine.resolve_profile(world, persona, seed=today)
            except Exception as exc:
                logger.debug("[amo] 角色位置解析失败: %s" % exc)
        weather = await self.refresh_weather()
        try:
            self.roll_health()
        except Exception:
            pass
        period = self.period_info()
        health = self.health_info()
        context = None
        items = None
        if self.engine is not None:
            try:
                context = self.engine.build_context(
                    today, meta, weather, world, self.mood, period, health,
                    persona=persona, salt=str(now_ts()) if force else "",
                )
                self.schedule_profile = context.get("profile") or self.schedule_profile
                context["day_type"] = day_type
                items = self.engine.build_skeleton(context)
                try:
                    items = await self.engine.enrich(umo, context, items, self.p.llm)
                except Exception as exc:
                    logger.debug("[amo] 日程主干文案润色失败，保留骨架: %s" % exc)
            except Exception as exc:
                logger.warning("[amo] 日程主干生成失败，使用兜底: %s" % exc)
                items = None
        if not items:
            profile = getattr(self, "schedule_profile", {}) or {}
            fallback_city = (
                self.p.cfg_str("schedule_city", "").strip()
                or str(profile.get("city") or "").strip()
                or str((weather or {}).get("city") or "").strip()
                or "贵阳"
            )
            context = context or {
                "version": "backbone-v5",
                "day": today,
                "meta": meta,
                "weather": weather,
                "world": world,
                "city": fallback_city,
                "home": self.p.cfg_str("schedule_home", "") or profile.get("home") or "家",
                "workplace": self.p.cfg_str("schedule_workplace", "") or profile.get("workplace") or "公司",
                "car": profile.get("car") or "",
                "mood": dict(self.mood),
                "period": period,
                "health": health,
                "event": {"kind": "none"},
                "scenic": None,
                "profile": profile,
                "location": fallback_city,
                "good_weather": True,
                "yesterday": self.engine.yesterday_summary(today) if self.engine is not None else {},
            }
            items = self._emergency_schedule()
        if getattr(self, "outfits", None) is not None:
            try:
                items = self.outfits.assign(items, today, persona)
            except Exception as exc:
                logger.debug("[amo] 日程配装失败: %s" % exc)
        items = self._hourly_schedule(items)
        self.schedule[today] = items
        if context:
            context["version"] = "backbone-v5"
            context["day"] = today
            self.schedule_ctx[today] = context
            self.db.kv_set("schedule_ctx", self.schedule_ctx)
        self.db.kv_set("schedule_version", SCHEDULE_VERSION)
        self.db.kv_set("schedule", self._sanitize_schedule(self.schedule))
        self.db.save_schedule(today, items)
        if force:
            try:
                self.db.clear_diaries(today)
                self.db.kv_set("diary_prefill_" + today, False)
                self.db.kv_set("diary_warm_%s_%s" % (DIARY_WARM_VERSION, today), False)
            except Exception:
                pass
        items = self._normalize_items(
            self._strip_his_presence(self._sync_trip_schedule(items, today), today))
        self.warm_schedule_diaries(today, items, umo)
        cutoff = (_now().date() - timedelta(days=14)).isoformat()
        for day in list(self.schedule.keys()):
            if day < cutoff:
                self.schedule.pop(day, None)
                self.schedule_ctx.pop(day, None)
        self.db.kv_set("schedule_ctx", self.schedule_ctx)
        logger.info("[amo] 生成日程主干 %s：%s" % (
            today, (context or {}).get("event", {}).get("kind", "none"),
        ))
        try:
            travel = self.db.kv_get("travel", {}) or {}
            if isinstance(travel, dict) and str(travel.get("city") or "").strip():
                city = str(travel["city"])
                start_day = str(travel.get("start_day") or "")
                today = today_str()
                if start_day and today < start_day:
                    pass
                elif today == start_day and travel.get("phase") == "journey":
                    try:
                        start_hour = int(travel.get("start_hour") or 9)
                    except (TypeError, ValueError):
                        start_hour = 9
                    rows = [x for x in (travel.get("spots") or []) if isinstance(x, dict)]
                    self.apply_follow_start(city, start_hour, rows, keep_past=False)
                    self.db.kv_set("his_city", city)
                    if travel.get("id"):
                        try:
                            await self.p._switch_weather_city({
                                "id": str(travel["id"]), "name": city,
                            })
                        except Exception as exc:
                            logger.debug("[amo] 跟随天气切换失败: %s" % exc)
                    travel["phase"] = "touring"
                    self.db.kv_set("travel", travel)
                else:
                    self.apply_travel_overlay(city)
                    self._log_follow_day(city, today)
        except Exception as exc:
            logger.debug("[amo] 出行日程覆盖失败: %s" % exc)
        try:
            trip = self.db.kv_get("wander_trip", {}) or {}
            if isinstance(trip, dict) and trip.get("city"):
                city = str(trip["city"])
                start_day = str(trip.get("day") or "")
                ret_day = str(trip.get("return_day") or start_day)
                today = today_str()
                if start_day and today < start_day:
                    pass
                elif today == start_day:
                    self.apply_travel_overlay(city)
                    trip["phase"] = "applied"
                    self.db.kv_set("wander_trip", trip)
                    self._log_solo_day(city, today)
                    if trip.get("id"):
                        try:
                            await self.p._switch_weather_city({
                                "id": str(trip["id"]), "name": city,
                            })
                        except Exception as exc:
                            logger.debug("[amo] 旅游天气切换失败: %s" % exc)
                elif start_day < today < ret_day:
                    self.apply_travel_overlay(city)
                    self._log_solo_day(city, today)
                elif today == ret_day:
                    until = int(trip.get("return_hour") or 12)
                    self.apply_return_overlay(city, until)
                    self._log_solo_day(city, today)
                    if _now().hour >= until:
                        his = str(self.db.kv_get("his_city", "") or "").strip() or _CITY_DEFAULT
                        hit = self.p._city_lookup(his)
                        if hit:
                            try:
                                await self.p._switch_weather_city(hit)
                            except Exception:
                                pass
                elif today > ret_day:
                    self.db.kv_set("wander_trip", {})
                    his = str(self.db.kv_get("his_city", "") or "").strip() or _CITY_DEFAULT
                    hit = self.p._city_lookup(his)
                    if hit:
                        try:
                            await self.p._switch_weather_city(hit)
                        except Exception:
                            pass
                    self.apply_travel_overlay(his)
                    try:
                        rows = self.db.list_profiles(limit=1) or []
                        uid = str((rows[0] or {}).get("uid") or "") if rows else ""
                        if uid:
                            self.p._external_memory_write(
                                uid, "她 %s 从 %s 旅游回来了" % (today, city), "event", 1,
                            )
                    except Exception as exc:
                        logger.debug("[amo] 回来记忆失败: %s" % exc)
        except Exception as exc:
            logger.debug("[amo] 旅游行程推进失败: %s" % exc)
        return items

    def _log_solo_day(self, city, day):
        """旅游每天记一条（日记用）；同一天只记一次。"""
        try:
            log = self.db.kv_get("travel_log", []) or []
            if not isinstance(log, list):
                log = []
            if any(
                isinstance(x, dict) and x.get("day") == day and x.get("solo") and not x.get("back")
                for x in log
            ):
                return
            log.append({"day": day, "hour": "09:00", "city": city, "solo": True})
            self.db.kv_set("travel_log", log[-10:])
        except Exception:
            pass

    def apply_follow_start(self, city, start_hour=9, spots=None, keep_past=True):
        """跟去他那边的出发日：起床 → 出门坐车约 2 小时 → 到达 → 旅游。"""
        name = str(city or "").strip()
        if not name:
            return False
        if not self.p.cfg_bool("city_travel_schedule", True):
            return False
        today = today_str()
        try:
            start = max(0, min(21, int(start_hour or 9)))
        except (TypeError, ValueError):
            start = 9
        existing = self.schedule.get(today) or self.db.get_schedule(today) or []
        keep = []
        if keep_past:
            for item in existing:
                try:
                    hour = int(str(item.get("start") or "0")[:2])
                except Exception:
                    hour = 0
                if hour < start:
                    keep.append(item)
        items = _city_travel_to_events(
            name, start, spots=spots, weekday=_now().date().weekday() < 5, seed=today,
        )
        if keep_past:
            items = [x for x in items if int(str(x.get("start") or "0")[:2]) >= start]
        merged = keep + items
        if not merged:
            return False
        merged = self._strip_his_presence(merged, today)
        self.schedule[today] = merged
        self.db.save_schedule(today, merged)
        self.db.kv_set("schedule", self._sanitize_schedule(self.schedule))
        try:
            ctx = dict(self.schedule_ctx.get(today) or {})
            if ctx:
                ctx["city"] = name
                ctx["location"] = name
                ctx["home"] = self._home_name()
                ctx["workplace"] = "（在去" + name + "的路上）"
                self.schedule_ctx[today] = ctx
                self.db.kv_set("schedule_ctx", self.schedule_ctx)
        except Exception:
            pass
        try:
            if keep_past:
                self.db.clear_diaries_from(today, "%02d:00" % start)
            else:
                self.db.clear_diaries(today)
        except Exception:
            pass
        logger.info("[amo] 出发日日程：%s 点坐车去 %s" % (start, name))
        return True

    def _log_follow_day(self, city, day):
        """跟他旅游的每一天记一条（日记用）；同一天只记一次。"""
        try:
            log = self.db.kv_get("travel_log", []) or []
            if not isinstance(log, list):
                log = []
            if any(
                isinstance(x, dict) and x.get("day") == day and x.get("city") == city
                and not x.get("solo") and not x.get("back") and not x.get("journey")
                for x in log
            ):
                return
            log.append({"day": day, "hour": "09:00", "city": city})
            self.db.kv_set("travel_log", log[-10:])
        except Exception:
            pass

    def apply_return_overlay(self, city, until_hour=12):
        """旅游最后一天：0 点到 until_hour 在旅游城市，之后回家。"""
        name = str(city or "").strip()
        if not name:
            return False
        try:
            until = max(0, min(23, int(until_hour or 12)))
        except (TypeError, ValueError):
            until = 12
        today = today_str()
        spots = []
        try:
            spots = _city_pick_spots(self.p.scenic_spots(), name, today)
        except Exception:
            spots = []
        his = str(self.db.kv_get("his_city", "") or "").strip() or _CITY_DEFAULT
        items = _city_travel_events(name, 0, spots=spots, until_hour=until)
        back = _city_travel_events(his, until, home=True)
        # 回程后的「家」要和平时的家同一个名字，别一天写「他桌面上」一天写「南明区·小窝」
        home_place = ""
        try:
            profile = getattr(self, "schedule_profile", {}) or {}
            home_place = (self.p.cfg_str("schedule_home", "") or profile.get("home") or "").strip()
        except Exception:
            home_place = ""
        if home_place and home_place != his:
            for item in back:
                if item.get("zone") == "home":
                    item["place"] = home_place
        items += back
        if not items:
            return False
        items = self._strip_his_presence(items, today)
        self.schedule[today] = items
        self.db.save_schedule(today, items)
        self.db.kv_set("schedule", self._sanitize_schedule(self.schedule))
        try:
            self.db.clear_diaries(today)
        except Exception:
            pass
        logger.info("[amo] 旅游最后一天：%s 点前在 %s，之后回家" % (until, name))
        return True

    def apply_travel_overlay(self, city=None):
        """出行覆盖层：把今天剩下的日程换成「跟他一起在 X」（已过去的时段不动）。

        只在换城时调用；写库 + 清掉今天剩余时段的小日记，让它们按新日程重算。
        """
        travel = self.db.kv_get("travel", {}) or {}
        name = str(city or (travel.get("city") if isinstance(travel, dict) else "") or "").strip()
        if not name:
            return False
        if not self.p.cfg_bool("city_travel_schedule", True):
            return False
        today = today_str()
        from_hour = _now().hour
        home = name == _CITY_DEFAULT
        existing = self.schedule.get(today) or self.db.get_schedule(today) or []
        if not existing:
            from_hour = 0
        if home and from_hour >= 22:
            logger.info("[amo] 超过 22 点才回去，今晚住酒店，今天日程不再改")
            return False
        keep = []
        for item in existing:
            try:
                hour = int(str(item.get("start") or "0")[:2])
            except Exception:
                hour = 0
            if hour < from_hour:
                keep.append(item)
        spots = []
        if not home:
            try:
                spots = _city_pick_spots(self.p.scenic_spots(), name, today)
            except Exception as exc:
                logger.debug("[amo] 出行景点挑选失败: %s" % exc)
        merged = keep + _city_travel_events(
            name, from_hour, home=home, weekday=_now().date().weekday() < 5, spots=spots,
        )
        if not merged:
            return False
        merged = self._strip_his_presence(merged, today)
        self.schedule[today] = merged
        self.db.save_schedule(today, merged)
        self.db.kv_set("schedule", self._sanitize_schedule(self.schedule))
        try:
            ctx = dict(self.schedule_ctx.get(today) or {})
            if ctx:
                ctx["city"] = name
                ctx["location"] = name
                if home:
                    ctx["home"] = self._home_name()
                    ctx["workplace"] = str((self.schedule_profile or {}).get("workplace") or "")
                    ctx.pop("scenic", None)
                else:
                    ctx["home"] = name + "·酒店房间"
                    ctx["workplace"] = "（旅游中，不上班）"
                    if spots:
                        ctx["scenic"] = spots[0]
                self.schedule_ctx[today] = ctx
                self.db.kv_set("schedule_ctx", self.schedule_ctx)
        except Exception:
            pass
        try:
            self.db.clear_diaries_from(today, "%02d:00" % from_hour)
        except Exception:
            pass
        logger.info("[amo] 出行日程已写入：%s 起在 %s%s" % (
            "%02d:00" % from_hour, name, "（回家）" if home else "",
        ))
        return True

    def schedule_context(self, day=None):
        day = str(day or today_str())
        context = self.schedule_ctx.get(day) or {}
        if isinstance(context, dict):
            return context
        return {}

    def _minimal_context(self, day):
        try:
            meta = day_meta(day)
        except Exception:
            meta = day_meta()
        profile = getattr(self, "schedule_profile", {}) or {}
        city = (
            self.p.cfg_str("schedule_city", "").strip()
            or str(profile.get("city") or "").strip()
            or str((self.weather or {}).get("city") or "").strip()
            or "贵阳"
        )
        return {
            "version": "backbone-v5",
            "day": day,
            "meta": meta,
            "weather": self.weather or {},
            "world": self.worldview or {},
            "city": city,
            "home": self.p.cfg_str("schedule_home", "") or profile.get("home") or "家",
            "workplace": self.p.cfg_str("schedule_workplace", "") or profile.get("workplace") or "公司",
            "car": profile.get("car") or "",
            "mood": dict(self.mood),
            "period": self.period_info(),
            "health": self.health_info(),
            "event": {"kind": "none"},
            "scenic": None,
            "profile": profile,
            "location": city,
            "good_weather": True,
            "yesterday": self.engine.yesterday_summary(day) if self.engine is not None else {},
        }

    def prefill_diaries(self, day, items):
        """日程建好就先给每小时写一句保底日记，点开不再现生成。"""
        key = "diary_prefill_" + str(day)
        try:
            if self.db.kv_get(key, False):
                return
        except Exception:
            pass
        if self.engine is None:
            return
        try:
            context = self.schedule_context(day) or self._minimal_context(day)
        except Exception:
            context = {}
        previous = None
        for item in items or []:
            start = str(item.get("start") or "")
            if not start:
                continue
            try:
                cached = self.db.get_diary(day, start)
            except Exception:
                cached = ""
            if cached:
                previous = item
                continue
            text = ""
            try:
                text = self.engine.fallback_diary(context, item, previous)
            except Exception:
                text = ""
            if not text:
                text = "这一小时我在%s，%s。" % (
                    item.get("place") or "家", item.get("activity") or "待着")
            try:
                self.db.save_diary(day, start, text)
            except Exception:
                pass
            previous = item
        try:
            self.db.kv_set(key, True)
        except Exception:
            pass

    async def warm_diaries(self, day, items, umo, force=False):
        """后台把 24 小时的小日记都写细；按 6 小时一组，写完一组接下一组。"""
        key = "diary_warm_%s_%s" % (DIARY_WARM_VERSION, day)
        try:
            if not force and self.db.kv_get(key, False):
                return {"total": 0, "skipped": True}
            self.db.kv_set(key, True)
        except Exception:
            pass
        llm = getattr(self.p, "llm", None)
        if llm is None or self.engine is None:
            return {"total": 0, "error": "llm 或 engine 不可用"}
        # json_extract_list 就在本模块，不用再 import
        context = self.schedule_context(day) or {}
        weather = ""
        try:
            from .schedule_engine import _weather_text
        except Exception:
            try:
                from schedule_engine import _weather_text  # type: ignore
            except Exception:
                _weather_text = None
        if _weather_text is not None:
            weather = _weather_text(context.get("weather") or {})
        persona = ""
        try:
            persona = await llm.persona(umo)
        except Exception:
            persona = ""
        hours = [item for item in (items or []) if str(item.get("start") or "")]
        logger.info("[amo] 开始批量生成小日记 %s（%d 条）" % (day, len(hours)))
        total = 0
        previous = ""
        for begin in range(0, len(hours), 6):
            chunk = hours[begin:begin + 6]
            lines = []
            for item in chunk:
                start = str(item.get("start") or "")
                bits = ["%s %s（%s）" % (start, item.get("activity") or "待着",
                                        item.get("place") or "家")]
                if item.get("detail"):
                    bits.append("细节：" + str(item.get("detail"))[:40])
                if item.get("vehicle"):
                    bits.append("交通：" + str(item.get("vehicle")))
                if item.get("mood"):
                    bits.append("心情：" + str(item.get("mood")))
                lines.append("；".join(bits))
            system = "你就是这个角色本人。你在写只给自己看的第一人称小日记。只输出 JSON 数组。"
            prompt = (
                "角色设定（节选）：\n" + str(persona or "")[:400] + "\n"
                "天气：%s。\n" % (weather or "未知")
                + ("上一段最后一条日记（要承接，不要重复）：\n" + previous[:300] + "\n" if previous else "")
                + "下面是今天的 %s-%s 这一段的日程：\n%s\n\n"
                "请给每一条写一段**详细**的第一人称小日记，每段 120 到 200 字：\n"
                "1. 只写这一小时，不要提前写下一小时；\n"
                "2. 写清地点、正在做的动作、一个小细节（手上的东西、周围的声音、天气的体感）；\n"
                "3. 带一点当时的情绪和心里话，口语化，像真的日记；\n"
                "4. 每段之间要承接，不能矛盾，也不要整段重复上一段。\n"
                "只输出 JSON 数组：[{\"start\":\"07:00\",\"diary\":\"……\"}]，不要解释。\n\n"
                % (chunk[0].get("start") or "", chunk[-1].get("end") or "", "\n".join(lines))
            )
            try:
                raw = await llm.chat_raw(umo, system, prompt, kind="diary")
            except Exception:
                continue
            rows = json_extract_list(raw)
            logger.info("[amo] 日记批次 %d-%d：raw=%d 字，解析 %s 条" % (
                begin, min(begin + 6, len(hours)), len(str(raw or "")),
                len(rows) if isinstance(rows, list) else -1))
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                start = str(row.get("start") or "").strip()
                text = str(row.get("diary") or row.get("text") or "").strip()
                if not start or len(text) < 20:
                    continue
                try:
                    self.db.save_diary(day, start, text)
                    total += 1
                    previous = text
                except Exception:
                    pass
        if total:
            logger.info("[amo] 今日小日记已预生成 %d 条（详细版）" % total)
        return {"total": total, "hours": len(hours)}

    def warm_schedule_diaries(self, day, items, umo):
        """预填保底 + 后台批量生成，不阻塞日程返回。"""
        try:
            if (self.db.kv_get("diary_prefill_" + str(day), False)
                    and self.db.kv_get("diary_warm_%s_%s" % (DIARY_WARM_VERSION, day), False)):
                return
        except Exception:
            pass
        try:
            self.prefill_diaries(day, items)
        except Exception as exc:
            logger.debug("[amo] 预填日记失败: %s" % exc)
        try:
            if getattr(self.p, "llm", None) is not None:
                self.p._spawn(self.warm_diaries(day, items, umo))
        except Exception as exc:
            logger.debug("[amo] 批量日记启动失败: %s" % exc)

    async def expand_hour(self, day, item, items=None, force=False):
        """点击二级卡片时，实时生成这一小时的第一人称小日记。"""
        day = str(day or today_str())
        item = dict(item or {})
        items = items or self._hourly_schedule(self.schedule.get(day) or [])
        start = item.get("start") or ""
        if not start:
            return {"diary": "", "mood": "平静", "place": "", "activity": ""}
        if not force:
            cached = self.db.get_diary(day, start)
            if cached:
                return {
                    "diary": cached,
                    "mood": item.get("mood") or "平静",
                    "place": item.get("place") or "",
                    "activity": item.get("activity") or "",
                    "cached": True,
                }
        context = self.schedule_context(day)
        if not context:
            context = self._minimal_context(day)
        else:
            context = dict(context)
            context["mood"] = dict(self.mood)
            context["health"] = self.health_info()
            context["period"] = self.period_info()
            if self.weather:
                context["weather"] = self.weather
        index = 0
        for position, entry in enumerate(items):
            if entry.get("start") == start:
                index = position
                break
        prev_item = items[index - 1] if index > 0 else None
        next_item = items[index + 1] if index + 1 < len(items) else None
        prev_diary = ""
        if prev_item is not None:
            try:
                prev_diary = self.db.get_diary(day, str(prev_item.get("start") or ""))
            except Exception:
                prev_diary = ""
        result = {"diary": "", "mood": item.get("mood") or "平静",
                  "place": item.get("place") or "", "activity": item.get("activity") or ""}
        if self.engine is not None:
            try:
                result.update(await self.engine.generate_diary(
                    self.p._last_umo, context, item, prev_item, next_item, self.p.llm,
                    prev_diary=prev_diary,
                ))
            except Exception as exc:
                logger.warning("[amo] 动态日记生成失败: %s" % exc)
        if not result.get("diary") and self.engine is not None:
            result["diary"] = self.engine.fallback_diary(context, item, prev_item)
        if not result.get("diary"):
            result["diary"] = "这小时我在%s，%s，心情%s。" % (
                item.get("place") or "家", item.get("activity") or "待着",
                item.get("mood") or "平静",
            )
        self.db.save_diary(day, start, result["diary"])
        return result

    def apply_schedule_events(self):
        """当前小时的日程事件只触发一次，避免每轮都扣心情。"""
        item = self.current_activity()
        effects = item.get("effects") if isinstance(item.get("effects"), dict) else {}
        ctx = self.schedule_context(today_str())
        key = "schedule_event_%s_%s_%s" % (
            today_str(), item.get("start", ""), ctx.get("seed", ""),
        )
        if self.db.kv_get(key, False):
            return
        applied = False
        clean = {}
        for mood_key, delta in effects.items():
            if mood_key in MOOD_KEYS:
                try:
                    clean[mood_key] = float(delta)
                    applied = True
                except Exception:
                    continue
        if not applied:
            # 日常活动也要影响真实心情：上班会累、逛街会开心、睡觉回血。
            # CATEGORY_MOOD 是日程内部用的「每小时」增量，真实心情每轮都会向基准
            # 回落，所以乘一个增益（schedule_mood_gain，默认 3）才看得出来。
            try:
                gain = max(0.0, self.p.cfg_float("schedule_mood_gain", 3.0))
            except Exception:
                gain = 3.0
            category = str(item.get("category") or "")
            for mood_key, delta in (schedule_category_mood().get(category) or {}).items():
                if mood_key not in MOOD_KEYS:
                    continue
                try:
                    clean[mood_key] = float(delta) * gain
                except Exception:
                    continue
            applied = bool(clean)
        if clean:
            self.nudge(**clean)
        # 兼容旧版日程里用 detail 标记的事件链。
        detail = str(item.get("detail") or "")
        if not applied and detail:
            legacy = {
                "熬夜": {"疲惫": 7, "暴躁": 3, "开心": -3},
                "精神恍惚": {"疲惫": 5, "焦虑": 5},
                "老板": {"生气": 8, "委屈": 8, "郁闷": 6, "暴躁": 4},
                "扣工资": {"郁闷": 8, "生气": 6},
                "同事闹脾气": {"生气": 5, "委屈": 3},
                "同事聊天": {"开心": 3, "平静": 2},
            }
            for word, deltas in legacy.items():
                if word in detail:
                    self.nudge(**deltas)
                    applied = True
                    break
        self.db.kv_set(key, True)

    def _state_on_trip(self):
        """今天在不在外面（出行覆盖层还没落地时，别把真实行程当幻觉删掉）。"""
        try:
            return bool(self._active_trip())
        except Exception:
            return False

    @staticmethod
    def _normalize_items(items):
        """把 category/zone 归一成枚举值：大小写、空格修掉，认不出的原样保留。"""
        out = []
        for item in items or []:
            if not isinstance(item, dict):
                out.append(item)
                continue
            row = dict(item)
            category = str(row.get("category") or "").strip()
            if category:
                fixed = value_of(ActivityCategory, category, default="")
                if fixed:
                    row["category"] = fixed
            zone = str(row.get("zone") or "").strip()
            if zone:
                fixed_zone = value_of(SceneZone, zone, default="")
                if fixed_zone:
                    row["zone"] = fixed_zone
            out.append(row)
        return out

    def current_activity(self):
        items = self.schedule.get(today_str()) or []
        current = minutes_now()
        for item in items:
            if in_minute_range(current, parse_hhmm(item.get("start")), parse_hhmm(item.get("end"))):
                return dict(item)
        # 日程还没生成 / 刚被重建 / 出行覆盖层没落地时，绝不能退回硬编码的「家」：
        # 她人在南阳逛景区，状态写「家」比没有状态更糟（问一句就自相矛盾）。
        try:
            trip = self._active_trip()
        except Exception:
            trip = None
        if trip:
            city = str(trip.get("city") or "").strip()
            back_day = str(trip.get("return_day") or "").strip()
            try:
                back_hour = int(trip.get("return_hour") or 22)
            except (TypeError, ValueError):
                back_hour = 22
            still_out = not (back_day and back_day == today_str() and _now().hour >= back_hour)
            if city and still_out:
                return {"start": "", "end": "", "activity": "在外面待着",
                        "place": "%s·酒店房间" % city, "category": "rest", "zone": "hotel"}
        hour = _now().hour
        if hour < 6:
            return {"start": "00:00", "end": "06:00", "activity": "睡觉", "place": "家", "category": "sleep"}
        if hour < 9:
            return {"start": "07:00", "end": "09:00", "activity": "起床收拾", "place": "家", "category": "life"}
        if hour < 12:
            return {"start": "09:00", "end": "12:00", "activity": "上班", "place": "公司", "category": "work"}
        if hour < 14:
            return {"start": "12:00", "end": "14:00", "activity": "吃午饭", "place": "公司附近", "category": "meal"}
        if hour < 18:
            return {"start": "14:00", "end": "18:00", "activity": "上班", "place": "公司", "category": "work"}
        if hour < 20:
            return {"start": "18:00", "end": "20:00", "activity": "吃晚饭", "place": "家", "category": "meal"}
        if hour < 23:
            return {"start": "20:00", "end": "23:00", "activity": "休息", "place": "家", "category": "rest"}
        return {"start": "23:00", "end": "24:00", "activity": "准备睡觉", "place": "家", "category": "sleep"}

    @staticmethod
    def busy_level(activity):
        category = (activity or {}).get("category", "rest")
        if category == "sleep":
            return 1.0
        if category in ("work", "study"):
            return 0.75
        if category == "commute":
            return 0.6
        if category == "meal":
            return 0.3
        return 0.1

    # ---------- 汇总 ----------
    def snapshot(self):
        period = self.period_info()
        health = self.health_info()
        activity = self.current_activity()
        weather = self.weather or {}
        return {
            "date": today_str(),
            "weekday": weekday_cn(),
            "time": _now().strftime("%H:%M"),
            "datetime_text": "%s 星期%s %s" % (today_str(), weekday_cn(), _now().strftime("%H:%M")),
            "mood": {key: round(value, 1) for key, value in self.mood.items()},
            "dominant": self.dominant_mood(),
            "mood_score": self.mood_score(),
            "period": period,
            "health": health,
            "weather": weather,
            "weather_text": self.weather_text(),
            "activity": activity,
            "busy": self.busy_level(activity),
            "schedule": self.schedule.get(today_str()) or [],
        }

    def prompt_text(self, snap=None, with_activity=False):
        snap = snap or self.snapshot()
        activity = snap["activity"]
        lines = [
            "现在是 %s。" % snap["datetime_text"],
            ("心情：%s" % self.feelings.get_prompt_summary()
             if getattr(self, "feelings", None) is not None else "心情：%s" % self.mood_text()),
            "生理期：%s第%d天，%s。" % (
                snap["period"]["phase"], snap["period"]["day"], snap["period"]["tone"]
            ),
            "身体：%s%s。" % (
                snap["health"]["status"],
                ("（" + snap["health"]["note"] + "）") if snap["health"].get("note") else "",
            ),
            "天气：%s。" % snap["weather_text"],
        ]
        # 地点永远给：不给的话模型会自己编一个（踩过坑：日程在景区，她说在酒店）。
        # 只让她在被问/需要时用，并明令不许改口。
        outfit = str(activity.get("outfit") or "").strip()
        lines.append(
            "（内在状态，仅供自洽，不是话题，被问才说）你此刻在%s（%s）%s。"
            "地点和正在做的事只能按这一条说，不许说成别处、也不许临时改口。"
            % (activity.get("activity", "休息"), activity.get("place", "家"),
               ("，穿着" + outfit) if outfit else "")
        )
        return "\n".join(lines)

    def tone_text(self, snap=None, relation="普通"):
        snap = snap or self.snapshot()
        mood = snap["mood"]
        if relation == "相恋" and (mood["暴躁"] >= 60 or mood["生气"] >= 62):
            tone = (
                "你在生对方的气，但你是他的恋人：会抱怨、闹别扭、说反话、要哄，"
                "语气带一点委屈，不会像对普通人那样冷怼、赶人或人身攻击；可以嘴硬，但不要真的伤人。"
            )
        elif mood["暴躁"] >= 60:
            tone = "你现在很暴躁，说话冲、短、带刺，一点就着，但不要真正辱骂。"
        elif mood["生气"] >= 62:
            tone = "你现在很烦躁，说话冲、短、带刺，容易不耐烦，但不要辱骂。"
        elif mood["委屈"] >= 60:
            tone = "你现在很委屈，语气软软的，会撒娇，想被哄。"
        elif mood["开心"] >= 65 or mood["兴奋"] >= 65:
            tone = "你现在心情很好，语气轻快，会用语气词和感叹号。"
        elif mood["郁闷"] >= 60:
            tone = "你现在有点低落，说话安静、句子短。"
        elif mood["疲惫"] >= 65:
            tone = "你很累，句子短一点、不展开；但别拿累当理由赶人、结束话题。"
        elif mood["焦虑"] >= 60:
            tone = "你有点焦虑，句子急，容易追问。"
        elif mood["依恋"] >= 65:
            tone = "你现在很黏人，想和对方多聊几句。"
        else:
            tone = "你语气自然平静，像平常聊天。"
        if snap["health"]["sick"]:
            tone += " 你身体不舒服，语气会比平时弱一点。"
        if snap["period"]["phase"] in ("月经期", "黄体期"):
            tone += " 生理期让你更容易累和敏感。"
        if relation == "相恋":
            tone += " 你和对方是恋人，可以亲昵、撒娇、用昵称。"
        elif relation == "仇恨":
            tone += " 你很讨厌对方，语气冷淡、疏远。"
        elif relation == "抵触":
            tone += " 你对对方有点防备，保持距离。"
        return tone

    def interesting_event(self):
        events = [
            "楼下咖啡店今天买一送一",
            "路上遇到一只很胖的橘猫",
            "同事带了自己烤的小饼干",
            "窗外的云像一只兔子",
            "刷到一个特别好笑的表情包",
            "便利店新出了草莓味的冰淇淋",
        ]
        if (self.weather or {}).get("tag") == "rain":
            events.append("下班的时候突然下雨，躲在便利店屋檐下")
        index = md5_int(today_str() + str(_now().hour)) % len(events)
        return events[index]

    def daily_tick(self):
        self.last_daily = today_str()
        period = self.period_info()
        if period["phase"] == "月经期":
            self.nudge(疲惫=8, 委屈=6, 开心=-4)
        elif period["phase"] == "黄体期":
            self.nudge(郁闷=5, 焦虑=4)
        elif period["phase"] == "排卵期":
            self.nudge(开心=5, 兴奋=4)
        else:
            self.nudge(开心=3)
        self.save()


# ---------------------------------------------------------------------------
# LLM：人格、对话、润色、世界观、日程、判断
# ---------------------------------------------------------------------------

#: 人格里写薪资的常见说法：月薪/工资/年薪 + 数字 + 万/k
_SALARY_RE = re.compile(
    r"(月薪|月工资|工资|薪资|年薪|收入)\s*[:：约是]?\s*(\d+(?:\.\d+)?)\s*(万|w|k|千)?",
    re.IGNORECASE,
)


def extract_salary(text, default: float = 0.0) -> float:
    """从人格文本里读月薪（税前）。读不到返回 default。

    支持「月薪 8000」「工资 1.2 万」「年薪 20 万」（÷12）。数字明显不合理就忽略——
    宁可回落到城市平均，也不要把「工作 3 年」当成月薪 3 万。
    """
    value = 0.0
    for match in _SALARY_RE.finditer(str(text or "")):
        word = (match.group(1) or "").lower()
        try:
            amount = float(match.group(2))
        except (TypeError, ValueError):
            continue
        unit = (match.group(3) or "").lower()
        if unit in ("万", "w"):
            amount *= 10000
        elif unit in ("k", "千"):
            amount *= 1000
        if "年薪" in word:
            amount /= 12.0
        if not (1000 <= amount <= 2000000):
            continue
        value = max(value, amount)
    return round(value, 2) if value else float(default or 0.0)


def extract_persona_name(persona):
    """从 AstrBot Personality 的 name / system prompt 中取角色名。"""
    if not persona:
        return ""
    name = ""
    prompt = ""
    try:
        name = str(persona.get("name") or "").strip()
        prompt = str(persona.get("prompt") or "")
    except Exception:
        name = str(getattr(persona, "name", "") or "").strip()
        prompt = str(getattr(persona, "prompt", "") or "")
    generic = {"default", "assistant", "系统默认", "默认", "bot", "ai"}
    if name and name.lower() not in generic and not re.fullmatch(r"[0-9a-fA-F-]{8,}", name):
        return name[:30]
    patterns = (
        r"你的名字(?:是|叫|为)\s*[「“\"']?([\u4e00-\u9fa5A-Za-z0-9_·]{1,16})",
        r"你叫(?:做)?\s*[「“\"']?([\u4e00-\u9fa5A-Za-z0-9_·]{1,16})",
        r"你名叫\s*[「“\"']?([\u4e00-\u9fa5A-Za-z0-9_·]{1,16})",
        r"名为\s*[「“\"']?([\u4e00-\u9fa5A-Za-z0-9_·]{1,16})",
        r"你是\s*[「“\"']?([\u4e00-\u9fa5A-Za-z0-9_·]{1,16})",
    )
    blocked = {"一个", "一名", "一位", "个人", "人", "你", "我", "他", "她", "这个", "那个"}
    for pattern in patterns:
        for match in re.finditer(pattern, prompt):
            candidate = str(match.group(1) or "").strip("「」“”\"' ")
            if (
                candidate and candidate not in blocked
                and not candidate.startswith(("一个", "一名", "一位", "个", "人"))
            ):
                return candidate[:30]
    return ""


class LLMService:
    def __init__(self, plugin):
        self.p = plugin
        self.context = plugin.context
        self._persona_cache = {}

    async def persona(self, umo=""):
        key = umo or "default"
        cached = self._persona_cache.get(key)
        if cached and now_ts() - cached[0] < 300:
            return cached[1]
        prompt = ""
        manager = getattr(self.context, "persona_manager", None)
        if manager is not None:
            try:
                persona = await manager.get_default_persona_v3(umo or None)
                if isinstance(persona, dict):
                    prompt = persona.get("prompt") or ""
                else:
                    prompt = getattr(persona, "prompt", "") or ""
            except Exception as exc:
                logger.debug("[amo] 读取 AstrBot 人格失败: %s" % exc)
        if not prompt:
            try:
                cfg = self.context.get_config(umo or None)
                personas = cfg.get("persona", []) if cfg else []
                if isinstance(personas, list) and personas:
                    prompt = personas[0].get("prompt", "") or ""
            except Exception:
                pass
        if not prompt:
            prompt = "你是一个生活在中国城市的普通女孩，有工作、有情绪、有自己的生活，说话自然口语化。"
        extra = self.p.cfg_str("persona_extra", "")
        if extra:
            prompt += "\n" + extra
        try:
            name = await self.p._persona_name_for(umo)
            if name and name not in prompt[:240]:
                prompt = "你的名字是" + name + "。\n" + prompt
        except Exception:
            pass
        self._persona_cache[key] = (now_ts(), prompt)
        return prompt

    async def provider(self, umo=""):
        try:
            if hasattr(self.context, "get_using_provider_async"):
                return await self.context.get_using_provider_async(umo or None)
            return self.context.get_using_provider(umo or None)
        except Exception as exc:
            logger.warning("[amo] 获取对话模型失败: %s" % exc)
            return None

    async def chat_raw(self, umo, system, prompt, contexts=None, kind="other"):
        provider = await self.provider(umo)
        if provider is None:
            return ""
        try:
            response = await provider.text_chat(
                prompt=prompt,
                system_prompt=system,
                contexts=contexts or [],
            )
        except Exception as exc:
            logger.error("[amo] LLM 调用失败: %s" % exc)
            return ""
        self.p._record_tokens(kind, provider, response)
        return str(getattr(response, "completion_text", "") or "").strip()

    async def chat(self, umo, system, prompt, contexts=None, limit=300, kind="other"):
        return clean_reply(await self.chat_raw(umo, system, prompt, contexts, kind=kind), limit)

    async def polish(self, umo, text, tone, state_text="", relation="", name="", persona="", style="", consult=False):
        text = (text or "").strip()
        if not text or not self.p.cfg_bool("enable_polish", True):
            return text
        # 短回复不值得再调一次模型：省一次完整调用，也少几十秒延迟
        try:
            floor = max(0, int(self.p.cfg_int("polish_min_chars", 30)))
        except Exception:
            floor = 30
        if floor and len(text) < floor and not consult:
            return text
        system = (
            "你就是这个角色本人，不是AI助手，也不是在润色一段AI台词。"
            "保持第一人称和原意，只输出角色会说的话。"
        )
        prompt = (
            "角色人格：\n" + (persona or "（未提供）")[:1000] + "\n"
            "角色当前语气：" + tone + "\n"
            "风格：" + (style or "自然") + "\n"
            "角色此刻不可矛盾的状态：\n" + (state_text or "（无）") + "\n"
            "对话对象：" + (name or "对方") + "；关系：" + (relation or "普通") + "\n"
            "原句：" + text + "\n"
            "请把这句话改成真人在聊天：口语化、有一点情绪，长度接近原句，通常不要超过原句的 1.3 倍。\n"
            "必须遵守：\n"
            "0. 保持角色人格：就是人格设定里的那个人，不是客服/通用助手；\n"
            "0. 只改语气和口语表达，不要新增原句没有的地点、行程、动作；如果原句与状态矛盾，以状态为准，不要继续编；\n"
            "1. 绝对不要承认自己是AI、人工智能、机器人、人机、程序或模型；\n"
            "2. 如果原句在承认或顺着“人机/机器人”说，要改成真人的反驳、无语或有点生气；\n"
            "3. 不要提润色、提示词、模型、系统、插件、API；被问“你接的什么模型/用的什么AI”时，\n"
            "   回一句像真人的打岔（“什么模型呀”“我就是我啊”），绝对不要报出任何模型名或厂商；\n"
            "4. 保持原句情绪强度和态度。如果原句在生气/烦躁/怼人，绝对不要改成甜蜜、撒娇、讨好，最多缓和一点；\n"
            "5. 不要一秒变脸，情绪要有惯性；\n"
            "6. 默认 1-2 句，能一句说清就一句；咨询/步骤最多 3 句，先给结论，不要列点、不要总结；\n"
            "7. 不要扩写，不要新增原句没有的信息。"
            + ("\n8. 这是咨询/步骤类：用角色口吻简短回答，不要客服腔。" if consult else "")
        )
        result = await self.chat(umo, system, prompt, limit=self.p.cfg_int("max_reply_chars", 220),
                                 kind="polish")
        if not result:
            return text
        if looks_like_ai_admission(result):
            retry_prompt = (
                "角色当前语气：" + tone + "\n"
                "原句：" + text + "\n"
                "原句/改写里出现了承认自己是人机或机器人的说法，这是不允许的。\n"
                "请改成真人被质疑时的自然反应：反驳、无语、有点生气或开个玩笑，"
                "绝对不要出现“我是AI/机器人/人机/程序/模型”“人机也有用”这类自曝。\n"
                "只输出一句角色会说的话。"
            )
            retry = await self.chat(umo, system, retry_prompt, limit=self.p.cfg_int("max_reply_chars", 220))
            if retry and not looks_like_ai_admission(retry):
                result = retry
            else:
                result = "你才人机呢，你见过这么会聊天的机器人吗？"
        if len(result) > max(len(text) + 30, int(len(text) * 1.5)):
            return text
        return result

    async def decide(self, umo, question, state):
        service = getattr(self.context, "decision", None)
        if service is not None:
            try:
                return bool(await service.yes_no(
                    question=question, state=state, threshold=0.5, default=None
                ))
            except Exception as exc:
                logger.debug("[amo] Decision 判断不可用: %s" % exc)
        answer = await self.chat(
            umo, "你是一个判断器，只输出 yes 或 no。",
            question + "\n只输出 yes 或 no。", limit=8,
        )
        if not answer:
            return None
        answer = answer.strip().lower()
        return answer.startswith("y") or answer.startswith("是") or answer.startswith("对")

    async def gen_worldview(self, umo, persona):
        system = "你是一个世界观设定师。只输出 JSON，不要输出其他文字。"
        prompt = (
            "根据下面的人格设定，为这个角色生成一个真实可信的现代生活世界观。\n"
            "人格设定：\n" + truncate(persona, 1500) + "\n\n"
            "输出 JSON 对象，字段：name(角色名), age(整数), city(城市), occupation(职业), "
            "workplace(工作或学习地点), personality(性格一句话), hobbies(字符串数组), "
            "daily_life(日常生活一段话), world_rules(这个世界和人设的规则一段话), "
            "summary(50字内总结)。"
        )
        raw = await self.chat_raw(umo, system, prompt)
        data = json_extract(raw)
        if not isinstance(data, dict):
            return None
        hobbies = data.get("hobbies")
        if not isinstance(hobbies, list):
            hobbies = [str(hobbies)] if hobbies else []
        return {
            "name": str(data.get("name") or self.p.bot_name),
            "age": to_int(data.get("age"), 22),
            "city": str(
                data.get("city")
                or self.p.cfg_str("weather_city_name", "")
                or self.p.cfg_str("weather_city", "贵阳")
            ),
            "occupation": str(data.get("occupation") or "普通上班族"),
            "workplace": str(data.get("workplace") or "公司"),
            "personality": str(data.get("personality") or "温柔敏感"),
            "hobbies": [str(item)[:20] for item in hobbies[:5]],
            "daily_life": str(data.get("daily_life") or ""),
            "world_rules": str(data.get("world_rules") or ""),
            "summary": str(data.get("summary") or ""),
        }

    async def gen_proactive(self, umo, profile, snap, kind):
        name = profile.get("alias") or profile.get("name") or "你"
        relation = profile.get("relation", "普通")
        system = (
            await self.persona(umo) + "\n\n"
            + self.p.state.prompt_text(snap, with_activity=True) + "\n"
            + self.p.state.tone_text(snap, relation) + "\n"
            "规则：你就是角色本人，只输出要发出去的消息，不要解释、不要旁白。\n"
            "一致性：不要编造自己的经历；不能和你刚才说过的话矛盾"
            "（刚才说吃过了，现在就不能说去买吃的）。\n"
            "此刻在做什么以上面「你此刻在…」为准：和最近聊天记录里说的不一样，就按此刻说，"
            "自然地改口（「会开完了」「我不在便利店了」），不要沿用旧说法，"
            "也不要编出没发生过的会议/加班/行程。"
        )
        try:
            rows = self.p._recent(umo, 12)
        except Exception:
            rows = []
        analysis = _pg_analyze_rows(rows, now=now_ts()) if _pg_analyze_rows else {
            "context_text": "",
            "unanswered_text": "",
            "unanswered_seconds": 0.0,
            "unanswered_at": 0.0,
            "recent_bot_texts": [],
        }
        # 她刚在另一个平台（QQ / 飞书）说过的话也带上：只看本会话的话，
        # 另一边早就改口了，这边还在接上一场开会。
        other_bot = []
        uid = str(profile.get("uid") or "")
        if uid:
            try:
                other_bot = other_platform_bot_lines(
                    await self.p._recent_by_uid(uid, 12, ""), umo,
                    platform=str(umo).split(":", 1)[0],
                )
            except Exception as exc:
                logger.debug("[amo] 取跨平台近聊失败: %s" % exc)
                other_bot = []
        if other_bot:
            analysis["recent_bot_texts"] = list(analysis.get("recent_bot_texts") or []) + list(other_bot)
            system = system + (
                "\n【你刚在别的平台说过】\n"
                + "\n".join("· " + str(item)[:120] for item in other_bot)
                + "\n（这些是你在另一个平台刚说的话，不是他说的，别复述、别重复；"
                "和此刻状态对不上就以此刻为准。）"
            )
        window = max(0, self.p.cfg_int("proactive_unanswered_window_minutes", 30)) * 60
        limit = self.p.cfg_int("max_reply_chars", 220)
        # 记忆只来自外挂记忆插件；主动消息也带上，免得她说得像个陌生人
        memory_text = ""
        try:
            uid = str(profile.get("uid") or "")
            if uid:
                _, memory_text = await self.p._recall(uid, "", None)
        except Exception:
            memory_text = ""
        if memory_text:
            system = system + "\n【关于他的记忆】\n" + memory_text
        try:
            relation_network = self.p._relation_network_text(str(profile.get("uid") or ""))
        except Exception:
            relation_network = ""
        if relation_network:
            system = system + "\n【关系网】\n" + relation_network
        try:
            trip = self.p.db.kv_get("wander_trip", {}) or {}
            if (
                isinstance(trip, dict) and trip.get("city") and not trip.get("announced")
                and str(trip.get("day") or "") <= today_str() <= str(trip.get("return_day") or "")
            ):
                spots = trip.get("spots") or []
                spot = str(spots[0]) if spots else ""
                system = system + (
                    "\n【旅游中】你现在一个人在 " + str(trip["city"]) + " 旅游"
                    + ("，今天去了" + spot if spot else "")
                    + "。主动跟他分享今天看到的、吃到的、天气；别报公司/上班，也别编景点。"
                )
        except Exception:
            pass

        def build_task(duplicate_hint=""):
            if not _pg_compose_task:
                return "你突然想起" + name + "，想主动发一条消息。"
            event_text = ""
            if kind == "share":
                try:
                    event_text = self.p.state.interesting_event()
                except Exception:
                    event_text = ""
            try:
                dialect_enabled = bool(self.p._dialect_active())
            except Exception:
                dialect_enabled = False
            return _pg_compose_task(
                kind=kind,
                name=name,
                unanswered_text=analysis["unanswered_text"],
                unanswered_seconds=analysis["unanswered_seconds"],
                window_seconds=window,
                recent_bot_texts=analysis["recent_bot_texts"],
                interesting_event=event_text,
                duplicate_hint=duplicate_hint,
                dialect_style=self.p.cfg_str("dialect_style", ""),
                dialect_enabled=dialect_enabled,
            )

        def build_prompt(task):
            prompt = "这是私聊。请以角色身份主动发一条消息，" + task + " 1 到 2 句，口语化。"
            if analysis["context_text"]:
                prompt = "最近私聊记录：\n" + analysis["context_text"] + "\n\n" + prompt
            if memory_text:
                prompt = "你记得关于他的事：\n" + memory_text + "\n\n" + prompt
            return prompt

        text = await self.chat(umo, system, build_prompt(build_task()), limit=limit)
        if not _pg_near_duplicate or not self.p.cfg_bool("proactive_dedupe_enabled", True):
            return text
        threshold = self.p.cfg_float("proactive_dedupe_threshold", 0.62)
        hit = _pg_near_duplicate(text, analysis["recent_bot_texts"], threshold)
        if not hit:
            return text
        retry = await self.chat(
            umo, system, build_prompt(build_task(duplicate_hint=hit[0])), limit=limit,
        )
        if retry and not _pg_near_duplicate(retry, analysis["recent_bot_texts"], threshold):
            return retry
        logger.info("[amo] 主动消息和最近的发言重复，跳过本次：%s" % str(text or retry or "")[:60])
        return ""

    async def extract_facts(self, umo, name, lines):
        system = "你是记忆提取器。只输出 JSON 数组，不要输出其他文字。"
        prompt = (
            "请从下面的聊天中提取关于用户“" + name + "”的长期事实。\n"
            "聊天里每一行都带说话人标记：[他] 是用户本人说的，[我] 是角色自己说的。\n"
            "只从 [他] 开头的行里提取；[我] 开头的内容是角色自己的事，不能算成用户的事实。\n"
            "只提取值得长期记住的内容：名字、生日、喜好、厌恶、居住地、工作或学校、"
            "宠物、年龄、重要计划、重要经历。\n"
            "位置类事实统一写成「他现在在X」；只有他明确说了搬/住/定居，才写「他住在X」。\n"
            "content 一律用第三人称「他」开头描述用户：写「他被扇了耳光，脸疼」而不是「我被扇了耳光」；"
            "绝不能用「我」或「你」指代用户，也不要省略主语。\n"
            "输出 JSON 数组，每项包含 content(一句话事实)、kind(name/birthday/preference/place/work/pet/age/event)、"
            "tier(0 普通 / 1 重要 / 2 珍贵)。没有可提取的就输出 []。\n\n"
            "聊天记录：\n" + "\n".join(lines[-20:])
        )
        raw = await self.chat_raw(umo, system, prompt)
        data = json_extract_list(raw)
        if not isinstance(data, list):
            return []
        result = []
        for item in data:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "")).strip()
            if len(content) < 2:
                continue
            # 兜底：模型偶尔仍会写成「我脸疼」/「被扇了耳光」这种没有主语或第一人称的句子，
            # 这种记忆注入后会被当成角色自己的经历（就是"幻视"）。这里统一补成第三人称。
            if content.startswith(("我", "你")):
                content = "他" + content[1:]
            elif not content.startswith(("他", "她", "用户", name or "\u0000")):
                content = "他" + content
            result.append({
                "content": content[:80],
                "kind": str(item.get("kind", "fact"))[:20],
                "tier": to_int(item.get("tier"), 1),
            })
        return result[:8]


# ---------------------------------------------------------------------------
# 插话判定
# ---------------------------------------------------------------------------

class ReplyGate:
    def __init__(self, plugin):
        self.p = plugin

    def activity(self, group_id):
        if not group_id:
            return 0.0
        cutoff = now_ts() - 300
        times = [item for item in self.p._group_times.get(group_id, []) if item >= cutoff]
        self.p._group_times[group_id] = times
        return len(times) / 5.0

    def score_group(self, umo, group_id, text, recent, directed, profile, snap):
        rec = [m for m in recent if m.get("role") == "user"][-6:]
        rec_text = " ".join([m.get("content", "") for m in rec])
        relevance = overlap(tokens(text), tokens(rec_text)) * 100.0
        if has_question(text):
            relevance += 12
        if "你" in text or any(alias and alias in text for alias in self.p.bot_aliases):
            relevance += 10
        if directed:
            relevance += 28
        relevance = clamp(relevance)

        mood = snap["mood"]
        willingness = 50.0
        willingness += (mood["开心"] - 50) * 0.30
        willingness += (mood["兴奋"] - 50) * 0.22
        willingness += (mood["平静"] - 50) * 0.10
        willingness -= (mood["疲惫"] - 50) * 0.35
        willingness -= (mood["郁闷"] - 50) * 0.28
        willingness -= (mood["生气"] - 50) * 0.22
        willingness += (mood["依恋"] - 50) * 0.15
        relation = profile.get("relation", "普通")
        willingness += {"相恋": 22, "熟识": 10, "抵触": -30, "仇恨": -55}.get(relation, 0)
        phase = snap["period"]["phase"]
        willingness += {"排卵期": 6, "卵泡期": 3, "黄体期": -6, "月经期": -10}.get(phase, 0)
        if snap["health"]["sick"]:
            willingness -= 15
        hour = _now().hour
        if hour < 6:
            willingness -= 25
        last_reply = self.p._last_reply_at.get(umo, 0)
        if last_reply and now_ts() - last_reply < 25:
            willingness -= 22
        willingness = clamp(willingness)

        social = 72.0
        if len(text) < 2:
            social -= 20
        if re.search(r"https?://|www\.", text):
            social -= 35
        if re.search(r"(加群|代购|广告|优惠|返利|扫码|兼职)", text):
            social -= 45
        senti = sentiment(text)
        if senti["insult"]:
            social -= 40
        blocked = [word.strip() for word in self.p.cfg_str("blocked_words", "").split(",") if word.strip()]
        if any(word in text for word in blocked):
            social -= 50
        if directed:
            social += 10
        if has_question(text):
            social += 5
        social = clamp(social)

        timing = 60.0
        dt = now_ts() - last_reply if last_reply else 99999
        if dt < 15:
            timing -= 40
        elif dt < 45:
            timing -= 20
        elif dt < 120:
            timing -= 5
        elif dt > 300:
            timing += 15
        category = snap["activity"].get("category")
        if category == "sleep":
            timing -= 55
        elif category in ("work", "study"):
            timing -= 18
        rate = self.activity(group_id)
        if 2.0 <= rate <= 12.0:
            timing += 10
        elif rate > 20.0:
            timing -= 12
        if quiet_now(self.p.cfg_str("quiet_hours", "23:30-07:30")):
            timing -= 25
        timing = clamp(timing)

        last_two = [m for m in recent if m.get("role") == "user"][-2:]
        coherence = overlap(
            tokens(text), tokens(" ".join([m.get("content", "") for m in last_two]))
        ) * 100.0
        if directed:
            coherence += 18
        if re.search(r"(这个|那个|刚才|刚刚|上面|你说|你刚才)", text):
            coherence += 10
        if len(text) < 4:
            coherence -= 10
        coherence = clamp(coherence)

        weights = [
            self.p.cfg_float("gate_w_relevance", 0.30),
            self.p.cfg_float("gate_w_willingness", 0.25),
            self.p.cfg_float("gate_w_social", 0.15),
            self.p.cfg_float("gate_w_timing", 0.15),
            self.p.cfg_float("gate_w_coherence", 0.15),
        ]
        total_weight = sum(weights) or 1.0
        total = (
            relevance * weights[0] + willingness * weights[1]
            + social * weights[2] + timing * weights[3] + coherence * weights[4]
        ) / total_weight
        return {
            "relevance": round(relevance, 1),
            "willingness": round(willingness, 1),
            "social": round(social, 1),
            "timing": round(timing, 1),
            "coherence": round(coherence, 1),
            "total": round(clamp(total), 1),
        }

    def dynamic_threshold(self, activity, snap, profile):
        base = self.p.cfg_float("reply_threshold", 0)
        if base <= 0:
            legacy = self.p.cfg_float("base_reply_threshold", 0.55)
            base = legacy * 100 if legacy <= 1 else legacy
        base = clamp(base, 0, 100)

        if activity < 1:
            activity_delta = -8
        elif activity < 4:
            activity_delta = -2
        elif activity < 9:
            activity_delta = 3
        elif activity < 18:
            activity_delta = 8
        else:
            activity_delta = 12

        mood = snap["mood"]
        positive = (mood["开心"] + mood["兴奋"] + mood["平静"] + mood["依恋"]) / 4.0
        negative = (mood["郁闷"] + mood["疲惫"] + mood["生气"] + mood["委屈"] + mood["焦虑"]) / 5.0
        mood_score = clamp(50 + (positive - negative) * 0.8)
        mood_delta = (50 - mood_score) * 0.25

        relation = profile.get("relation", "普通")
        relation_delta = {"相恋": -10, "熟识": -5, "抵触": 16, "仇恨": 36}.get(relation, 0)
        health_delta = 8 if snap["health"]["sick"] else 0
        phase = snap["period"]["phase"]
        period_delta = {"月经期": 6, "黄体期": 4, "排卵期": -3, "卵泡期": -1}.get(phase, 0)
        time_delta = 10 if _now().hour in (23, 0, 1, 2, 3, 4, 5) else 0
        weather_delta = 3 if snap["weather"].get("tag") in ("rain", "storm", "snow") else 0

        value = clamp(
            base + activity_delta + mood_delta + relation_delta
            + health_delta + period_delta + time_delta + weather_delta,
            20, 92,
        )
        return {
            "value": round(value, 1),
            "base": round(base, 1),
            "activity_delta": activity_delta,
            "mood_delta": round(mood_delta, 1),
            "relation_delta": relation_delta,
            "health_delta": health_delta,
            "period_delta": period_delta,
            "time_delta": time_delta,
            "weather_delta": weather_delta,
        }

    async def should_reply_group(self, umo, group_id, text, recent, directed, profile, snap):
        scores = self.score_group(umo, group_id, text, recent, directed, profile, snap)
        activity = self.activity(group_id)
        threshold = self.dynamic_threshold(activity, snap, profile)
        diff = scores["total"] - threshold["value"]

        if diff >= 0:
            probability = 0.92
        elif diff > -8:
            probability = 0.55 + diff * 0.045
        elif diff > -20:
            probability = 0.18 + (diff + 20) * 0.046
        else:
            probability = 0.03
        probability = clamp(probability, 0.01, 0.98)
        reply = random.random() < probability

        bot_recent = [m for m in recent[-5:] if m.get("role") == "bot"]
        if not directed and len(bot_recent) >= 2 and diff < 20:
            reply = False

        used_llm = False
        band = self.p.cfg_float("llm_gate_band", 10)
        if self.p.cfg_bool("enable_llm_gate", True) and abs(diff) <= band:
            question = (
                "群聊里刚刚有人说『" + truncate(text, 80) + "』。"
                "角色现在的心情是" + snap["dominant"] + "，正在" + snap["activity"].get("activity", "休息") + "，"
                "和说话人的关系是" + profile.get("relation", "普通") + "。"
                "角色应该自然地插话回复吗？"
            )
            verdict = await self.p.llm.decide(
                umo, question,
                {
                    "recent": [m.get("content", "") for m in recent[-6:]],
                    "mood": snap["mood"],
                    "activity": snap["activity"],
                },
            )
            used_llm = True
            if verdict is not None:
                reply = verdict

        return {
            "reply": reply,
            "probability": round(probability, 2),
            "diff": round(diff, 1),
            "scores": scores,
            "threshold": threshold,
            "activity": round(activity, 2),
            "used_llm": used_llm,
            "directed": directed,
        }

    def private_probability(self, snap, profile):
        probability = 0.95
        category = snap["activity"].get("category")
        probability *= {
            "sleep": 0.02, "work": 0.42, "study": 0.50,
            "commute": 0.60, "meal": 0.85,
        }.get(category, 1.0)
        probability *= {
            "感冒": 0.55, "低烧": 0.35, "轻微不适": 0.70, "疲惫": 0.70,
        }.get(snap["health"]["status"], 1.0)
        probability *= {
            "月经期": 0.80, "黄体期": 0.90, "排卵期": 1.05,
        }.get(snap["period"]["phase"], 1.0)
        mood = snap["mood"]
        if mood["生气"] > 60:
            probability *= 0.70
        if mood["郁闷"] > 60:
            probability *= 0.80
        if mood["开心"] > 65:
            probability *= 1.05
        try:
            if profile.get("uid") and self.p._depressed_active(str(profile.get("uid"))):
                probability *= 0.35
        except Exception:
            pass
        relation = profile.get("relation", "普通")
        if relation == "相恋":
            probability = max(probability, 0.90)
        elif relation == "仇恨":
            probability *= 0.20
        elif relation == "抵触":
            probability *= 0.45
        return clamp(probability, 0.0, 1.0)


# ---------------------------------------------------------------------------
# 插件主体
# ---------------------------------------------------------------------------

# 面板写操作路由：只注册 POST + 套 _web_guard。
# 以前守卫按「methods 里有没有 GET」判断，而写接口全被注册成 GET+POST，于是守卫一次都没执行过。
WRITE_ROUTES = frozenset({
    "/config/save", "/config_save",
    "/voice/save",
    "/profile/save", "/profile_save",
    "/profile/delete", "/profile_delete",
    "/relation/save", "/relation_save",
    "/relation/delete", "/relation_delete",
    "/memory/add", "/memory_add",
    "/memory/delete", "/memory_delete",
    "/mood/update", "/mood_update",
    "/schedule/regen", "/schedule_regen",
    "/kb/regen", "/kb_regen",
    "/scenic_kb/regen", "/scenic_kb_regen",
    "/worldview/regen", "/worldview_regen",
    "/say",
    "/city/set",
    "/draw/test",
    "/draw/decide",
    "/diary/write", "/diary/import", "/diary/open",
    "/refresh_status",
})


class HumanCorePlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}

        # 配置自愈：升级/重装/改目录名之后，把空掉的 key 从快照补回来。
        # 快照在 plugin_data/<插件名>/config_snapshot.json（0600），升级不覆盖、
        # schema 重写也删不到它。
        try:
            from .config_guard import heal as _cfg_heal, fallback_data_dir as _cfg_data_dir
        except ImportError:
            try:
                from config_guard import heal as _cfg_heal, fallback_data_dir as _cfg_data_dir
            except Exception:
                _cfg_heal = None
        if _cfg_heal is not None:
            try:
                _guard_dir = os.path.dirname(os.path.abspath(__file__))
                _healed = _cfg_heal(self.config, plugin_name=PLUGIN_NAME,
                                    plugin_dir=_guard_dir,
                                    data_dir=_cfg_data_dir(_guard_dir, PLUGIN_NAME),
                                    logger=logger)
                if _healed.get("restored"):
                    logger.info("[config] 本次启动补回 %d 项配置（%s）"
                                % (len(_healed["restored"]), ", ".join(_healed["restored"])))
            except Exception as exc:
                logger.debug("[config] 配置自愈失败: %s" % exc)
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self._migrate_legacy_config()
        self.bot_name = self.cfg_str("bot_name", "") or "陪伴"
        # 时区：服务器常在 UTC 跑，必须按用户时区算（否则北京时间早上 10 点会被当成凌晨 2 点）
        try:
            self.timezone_name = _clock_configure(self.cfg_str("timezone", "Asia/Shanghai"))
            logger.info("[amo] 时区: %s（系统: %s）" % (self.timezone_name, _clock_name()))
        except Exception as exc:
            self.timezone_name = ""
            logger.warning("[amo] 时区初始化失败: %s" % exc)
        self.persona_name = ""
        self._persona_name_cache = {}
        self._last_affect = {}
        self._disturb_until = {}
        self._disturb_last = {}
        self._last_pending_check = 0.0
        self._last_proactive_activity = {}
        self._last_bot_saved = {}
        # 近聊上下文缓冲（只在内存里；本地聊天可以不落库，用记忆终端补）
        self._ctx_hydrated = set()
        self._attribution_alert = {}
        self._last_schedule_save = ""
        self._disturb_cooldown = {}
        self._disturb_reset_at = {}
        self.bot_aliases = [item.strip() for item in self.cfg_str("bot_aliases", "").split(",") if item.strip()]
        self.admin_uids = set()
        for item in self.cfg_str("admin_uids", "").split(","):
            if item.strip():
                self.admin_uids.add(item.strip())
        self.db = AmoDB(self.plugin_dir)
        self.state = None
        self.llm = LLMService(self)
        self.gate = ReplyGate(self)
        self.wardrobe = None
        if Wardrobe is not None:
            try:
                self.wardrobe = Wardrobe(self)
                logger.info("[amo] 服装库已加载（%d 件，%s）" % (
                    self.wardrobe.count(), self.wardrobe.path))
            except Exception as exc:
                logger.warning("[amo] 服装库初始化失败: %s" % exc)
        self.outfits = None
        if OutfitEngine is not None:
            try:
                self.outfits = OutfitEngine(self)
            except Exception as exc:
                logger.warning("[amo] 穿搭引擎初始化失败: %s" % exc)
        self.draw = None
        if DrawEngine is not None:
            try:
                self.draw = DrawEngine(self)
            except Exception as exc:
                logger.warning("[amo] 画图引擎初始化失败: %s" % exc)
        self.feelings = None
        if HeartflowCore is not None:
            try:
                self.feelings = HeartflowCore(self.db)
            except Exception as exc:
                logger.warning("[amo] 心流数值核心初始化失败: %s" % exc)
        self.sleep = None
        if SleepCycle is not None:
            try:
                self.sleep = SleepCycle(
                    self.db,
                    accept_after=self.cfg_int("sleep_accept_after", 23),
                    wake_hour=self.cfg_int("sleep_wake_hour", 7),
                    night_wake_chance=self.cfg_float("sleep_night_wake_chance", 0.25),
                )
            except Exception as exc:
                logger.warning("[amo] 睡眠状态机初始化失败: %s" % exc)
        self.photo = None
        if PhotoEngine is not None:
            try:
                self.photo = PhotoEngine(self)
            except Exception as exc:
                logger.warning("[amo] 照片引擎初始化失败: %s" % exc)
        if self.draw is not None:
            logger.info("[amo] 画图引擎已加载（%s）" % ("开" if self.draw.enabled else "关"))
        if self.photo is not None:
            logger.info("[amo] 照片引擎已加载（%s）" % ("开" if self.photo.enabled else "关"))
        self.heartflow = None
        self.segment_engine = None
        try:
            if HeartflowEngine is not None:
                hf_config = self._hf_config()
                hf_config.setdefault("enable_heartflow", True)
                hf_config.setdefault("enable_dynamic_threshold", True)
                hf_config.setdefault("judge_provider_name", "")
                self.heartflow = HeartflowEngine(self.context, hf_config)
                try:
                    self.heartflow.plugin = self
                except Exception:
                    pass
                self.heartflow.set_identity(self.bot_name, self.bot_aliases)
            if SegmentEngine is not None:
                seg_config = self._seg_config()
                seg_config.setdefault("protect_paired_symbols", True)
                self.segment_engine = SegmentEngine(self.context, seg_config, plugin=self)
        except Exception as exc:
            logger.error("[amo] 心流/分段引擎初始化失败: %s" % exc)
        # 飞书适配器默认把每条回复都发成「引用回复」；私聊不该引用（群聊按概率）
        try:
            self._install_lark_quote_guard()
        except Exception as exc:
            logger.debug("[amo] 飞书引用守卫安装失败: %s" % exc)
        try:
            self._install_qq_quote_guard()
        except Exception as exc:
            logger.debug("[amo] QQ 引用守卫安装失败: %s" % exc)
        self._ready = False
        self._init_lock = asyncio.Lock()
        self._running = True
        self._tasks = set()
        # 数据插件（Astr_Amo_data）可能比 amo 后加载：用这几个标记做一次性补同步，不轮询
        self._data_synced = False
        self._data_sync_lock = asyncio.Lock()
        self._last_data_sync_try = 0.0
        self._data_found_logged = False
        self._data_missing_logged = False
        self._data_warn_scheduled = False
        self._group_times = {}
        self._private_buffers = {}
        self._last_reply_at = {}
        self._last_umo = ""
        self._last_group = ""
        self._last_purge = 0.0
        self._last_auto_learn = 0.0
        self._proactive_last = 0.0
        self._last_ritual = 0.0
        self._last_relation_decay = 0.0
        self._last_relation_sediment = 0.0
        self._bot_initiated = {}
        self._prefix_cache = None
        self._loop_task = None
        self._config_mtime = 0.0
        self._register_web_apis()
        logger.info("[amo] 我想永远陪着你-终端 %s loaded; stale web routes purged" % PLUGIN_VERSION)
        self._boot_task = self._spawn(self._ensure_ready())

    # ---------- 配置 ----------
    def cfg(self, key, default=None):
        try:
            value = self.config.get(key, default)
        except Exception:
            value = default
        return default if value is None else value

    def cfg_bool(self, key, default=False):
        value = self.cfg(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on", "是")

    def cfg_int(self, key, default=0):
        try:
            return int(float(self.cfg(key, default)))
        except Exception:
            return default

    def cfg_float(self, key, default=0.0):
        try:
            return float(self.cfg(key, default))
        except Exception:
            return default

    def cfg_str(self, key, default=""):
        try:
            return str(self.cfg(key, default))
        except Exception:
            return default

    def _core_decor_flags(self, umo=""):
        """AstrBot 核心会不会在插件 hook 之后再加「引用 / @」。

        上架要求不能改 AstrBot 核心；但核心的 platform_settings.reply_with_quote /
        reply_with_mention 是全局的，会在 on_decorating_result 之后无条件装饰结果，
        把本插件的私聊不引用、群聊按概率引用覆盖掉。这里只读配置，检测到开了就由
        插件自己发送，核心就没机会再补。
        """
        try:
            config = self.context.get_config() or {}
        except Exception:
            config = {}
        try:
            settings = config.get("platform_settings") or {}
        except Exception:
            settings = {}
        return {
            "quote": bool(settings.get("reply_with_quote", False)),
            "mention": bool(settings.get("reply_with_mention", False)),
        }

    async def _persona_name_for(self, umo=""):
        """读取当前会话的人格名；读不到时返回空字符串。"""
        if not self.cfg_bool("use_persona_name", True):
            return ""
        key = str(umo or "default")
        cached = self._persona_name_cache.get(key)
        if cached and now_ts() - cached[0] < 300:
            return cached[1]
        manager = getattr(self.context, "persona_manager", None)
        persona = None
        if manager is not None:
            try:
                conversation_persona_id = None
                cm = getattr(self.context, "conversation_manager", None)
                if cm is not None:
                    cid = await cm.get_curr_conversation_id(key)
                    if cid:
                        conv = await cm.get_conversation(key, cid)
                        conversation_persona_id = getattr(conv, "persona_id", None)
                platform_name = key.split(":", 1)[0] if ":" in key else ""
                _, persona, _, _ = await manager.resolve_selected_persona(
                    umo=key,
                    conversation_persona_id=conversation_persona_id,
                    platform_name=platform_name,
                    provider_settings={},
                )
            except Exception as exc:
                logger.debug("[amo] 解析当前人格失败: %s" % exc)
            if persona is None:
                try:
                    persona = await manager.get_default_persona_v3(key or None)
                except Exception as exc:
                    logger.debug("[amo] 读取默认人格失败: %s" % exc)
        name = extract_persona_name(persona)
        self._persona_name_cache[key] = (now_ts(), name)
        return name

    def _dialect_rows(self):
        region = self._dialect_region()
        try:
            rows = [row for row in self.db.list_dialects() if region in str(row.get("region") or "")]
        except Exception:
            rows = []
        if rows:
            return rows
        style = self._dialect_style().strip()
        return [
            {"term": term, "meaning": meaning, "region": style, "example": example}
            for term, meaning, example in DIALECT_FALLBACK_ROWS.get(style, [])
        ]

    def _dialect_region(self):
        style = self._dialect_style().strip()
        return DIALECT_REGIONS.get(style, style)

    def scenic_spots(self):
        if getattr(self, "_scenic_cache", None):
            return self._scenic_cache
        try:
            path = os.path.join(self.plugin_dir, "scenic_spots.json")
            with open(path, encoding="utf-8") as stream:
                data = json.load(stream)
            self._scenic_cache = data if isinstance(data, list) else []
        except Exception as exc:
            logger.warning("[amo] 读取景区数据失败: %s" % exc)
            self._scenic_cache = []
        return self._scenic_cache

    def _scenic_kb_name(self):
        name = self.cfg_str("scenic_kb_name", "旅游知识库-风景区").strip()
        if not name or name in ("中国景区知识库", "景区知识库"):
            return "旅游知识库-风景区"
        return name

    def _scenic_text_lines(self):
        lines = []
        for spot in self.scenic_spots():
            if not isinstance(spot, dict):
                continue
            projects = spot.get("projects") if isinstance(spot.get("projects"), list) else []
            lines.append(
                "景区：%s\n城市：%s·%s\n等级：%s\n游玩项目：%s\n建议时长：%s\n区域：%s" % (
                    spot.get("name", ""), spot.get("province", ""), spot.get("city", ""),
                    spot.get("level", ""), "、".join(str(item) for item in projects),
                    spot.get("duration", ""), spot.get("area", ""),
                )
            )
        return lines

    async def _ensure_scenic_kb(self):
        if not self.cfg_bool("create_scenic_kb", True):
            return None
        try:
            manager = getattr(self.context, "kb_manager", None)
            if manager is None:
                logger.warning("[amo] 当前 AstrBot 没有 kb_manager，景区知识库未创建")
                return None
            if callable(manager) and not hasattr(manager, "create_kb"):
                manager = manager()
            name = self._scenic_kb_name()
            kb = await manager.get_kb_by_name(name)
            if kb is None:
                providers = list(self.context.get_all_embedding_providers() or [])
                if not providers:
                    logger.warning("[amo] 没有 Embedding 供应商，景区知识库未创建")
                    return None
                provider_id = str(getattr(providers[0], "provider_config", {}).get("id", "") or "")
                if not provider_id:
                    try:
                        provider_id = str(providers[0].meta().id or "")
                    except Exception:
                        provider_id = ""
                if not provider_id:
                    logger.warning("[amo] Embedding 供应商没有有效 id，景区知识库未创建")
                    return None
                created = manager.create_kb(
                    name,
                    "中国 3A 级以上景区、所在城市与具体游玩项目",
                    emoji="🏞️",
                    embedding_provider_id=provider_id,
                )
                kb = await created if inspect.isawaitable(created) else created
            lines = self._scenic_text_lines()
            if lines:
                try:
                    docs = await kb.list_documents(search="amo_scenic")
                    for doc in docs or []:
                        doc_id = getattr(doc, "doc_id", "") or getattr(doc, "id", "")
                        if doc_id:
                            await kb.delete_document(doc_id)
                except Exception:
                    pass
                try:
                    await kb.upload_document(
                        "amo_scenic_spots.txt",
                        "\n\n".join(lines).encode("utf-8"),
                        "txt",
                    )
                except Exception as exc:
                    logger.warning("[amo] 景区知识库上传失败: %s" % exc)
            logger.info("[amo] 景区知识库 %s 已同步，共 %d 个景区" % (name, len(lines)))
            return kb
        except Exception as exc:
            logger.warning("[amo] 景区知识库创建失败: %s" % exc)
            return None

    async def _scenic_kb_context(self, query):
        try:
            manager = getattr(self.context, "kb_manager", None)
            if manager is None or not str(query or "").strip():
                return ""
            name = self._scenic_kb_name()
            kb = await manager.get_kb_by_name(name)
            if kb is None:
                return ""
            result = await manager.retrieve(str(query)[:400], [name], top_m_final=4)
            return str(result.get("context_text") or "") if isinstance(result, dict) else ""
        except Exception as exc:
            logger.debug("[amo] 景区知识库检索失败: %s" % exc)
            return ""

    def _dialect_active(self):
        """方言是否生效：语种选「普通话」就等于关掉方言（连方言库都不查）。"""
        style = str(self.cfg_str("dialect_style", "") or "").strip()
        if style in ("普通话", "关闭", "off", "none"):
            return False
        return self.cfg_bool("dialect_enabled", True)

    def _dialect_style(self):
        """语种：配置里写了就用配置（面板可覆盖），没写就按世界观城市自动选。"""
        explicit = str(self.cfg_str("dialect_style", "") or "").strip()
        if explicit and explicit not in ("自动", "auto", "auto_city"):
            return explicit
        city = ""
        try:
            world = getattr(self.state, "worldview", None) or {}
            city = str(world.get("city") or "")
        except Exception:
            pass
        if not city:
            try:
                city = str(
                    self.cfg_str("weather_city_name", "")
                    or self.cfg_str("weather_city", "")
                    or ""
                )
            except Exception:
                pass
        return dialect_for_city(city)

    def _dialect_kb_name(self):
        base = self.cfg_str("dialect_kb_name", "陪伴方言库").strip() or "陪伴方言库"
        style = self._dialect_style().strip()
        return base + "-" + style if style else base

    @staticmethod
    def _embedding_provider_id(provider):
        try:
            value = str(provider.provider_config.get("id", "") or "")
            if value:
                return value
        except Exception:
            pass
        try:
            return str(provider.meta().id or "")
        except Exception:
            return ""

    async def _dialect_kb_context(self, query):
        # 关掉方言就别检索方言库：省一次 embedding 查询和一段提示词
        if not self._dialect_active():
            return ""
        try:
            manager = getattr(self.context, "kb_manager", None)
            if manager is None or not str(query or "").strip():
                return ""
            name = self._dialect_kb_name()
            kb = await manager.get_kb_by_name(name)
            names = [name]
            if kb is None:
                legacy = await manager.get_kb_by_name("核心方言库")
                if legacy is not None:
                    kb = legacy
                    names = ["核心方言库"]
            if kb is None:
                return ""
            result = await manager.retrieve(str(query)[:500], names, top_m_final=3)
            if not isinstance(result, dict):
                return ""
            return str(result.get("context_text") or "")
        except Exception as exc:
            logger.debug("[amo] 方言知识库检索失败: %s" % exc)
            return ""

    async def _ensure_dialect_kb(self):
        """把方言同步进 AstrBot 知识库；失败会明确写日志，不再静默。"""
        if not self._dialect_active():
            return None
        if not self.cfg_bool("create_dialect_kb", True):
            return None
        try:
            manager = getattr(self.context, "kb_manager", None)
            if manager is None:
                logger.warning("[amo] 当前 AstrBot 没有 kb_manager，无法创建知识库")
                return None
            if callable(manager) and not hasattr(manager, "create_kb"):
                try:
                    manager = manager()
                except Exception:
                    manager = None
            if manager is None or not hasattr(manager, "create_kb"):
                logger.warning("[amo] kb_manager 不支持 create_kb，无法创建知识库")
                return None
            name = self._dialect_kb_name()
            kb = await manager.get_kb_by_name(name)
            if kb is None:
                providers = []
                getter = getattr(self.context, "get_all_embedding_providers", None)
                if callable(getter):
                    try:
                        providers = list(getter() or [])
                    except Exception:
                        providers = []
                if not providers:
                    pm = getattr(self.context, "provider_manager", None)
                    providers = list(getattr(pm, "embedding_provider_insts", []) or [])
                if not providers:
                    logger.warning(
                        "[amo] 没有可用的 Embedding 供应商，知识库未创建；"
                        "请先在 AstrBot 模型提供商里配置 embedding"
                    )
                    return None
                provider_id = self._embedding_provider_id(providers[0])
                if not provider_id:
                    logger.warning("[amo] Embedding 供应商没有有效 id，知识库未创建")
                    return None
                try:
                    created = manager.create_kb(
                        name,
                        "陪伴角色方言与口语表达，用于聊天时的自然替换",
                        emoji="🗣️",
                        embedding_provider_id=provider_id,
                    )
                    kb = await created if inspect.isawaitable(created) else created
                except Exception as exc:
                    logger.warning("[amo] 创建知识库 %s 失败: %s" % (name, exc), exc_info=True)
                    return None

            rows = []
            try:
                rows = self._dialect_rows()
            except Exception:
                rows = []
            lines = [
                "%s（%s）：普通话“%s”，例：%s" % (
                    row.get("term", ""), row.get("region", ""),
                    row.get("meaning", ""), row.get("example", ""),
                )
                for row in rows
                if row.get("term") and row.get("meaning")
            ]
            if lines:
                try:
                    docs = await kb.list_documents(search="amo_dialect")
                    for doc in docs or []:
                        doc_id = getattr(doc, "doc_id", "") or getattr(doc, "id", "")
                        if doc_id:
                            await kb.delete_document(doc_id)
                except Exception as exc:
                    logger.warning("[amo] 清理旧方言文档失败: %s" % exc)
                try:
                    await kb.upload_document(
                        "amo_dialect.txt",
                        "\n".join(lines).encode("utf-8"),
                        "txt",
                        pre_chunked_text=lines,
                    )
                except Exception as exc:
                    logger.warning("[amo] 方言知识库上传失败: %s" % exc, exc_info=True)
            logger.debug("[amo] 知识库 %s 已同步，写入 %d 条方言" % (name, len(lines)))
            return kb
        except Exception as exc:
            logger.warning("[amo] 方言知识库创建失败: %s" % exc, exc_info=True)
            return None

    async def _sync_persona_name(self, event_or_umo):
        umo = getattr(event_or_umo, "unified_msg_origin", event_or_umo)
        try:
            name = await self._persona_name_for(umo)
        except Exception as exc:
            logger.debug("[amo] 同步人格名失败: %s" % exc)
            return
        if not name:
            return
        changed = name != self.persona_name
        self.persona_name = name
        self.bot_name = name
        if self.heartflow is not None:
            self.heartflow.set_identity(self.bot_name, self.bot_aliases)
        # 世界观挂在 HumanState 上，不是插件实例；这里以前写成了 self.worldview，
        # 一旦人格名变化就会 AttributeError，整条消息处理直接中断。
        world = getattr(getattr(self, "state", None), "worldview", None)
        if changed and isinstance(world, dict) and world.get("name") != name:
            world["name"] = name
            try:
                self.db.kv_set("worldview", world)
            except Exception:
                pass

    def _migrate_legacy_config(self):
        """把旧版 amo_forever_config.json 合并到 Astrbot_Amo_forever_config.json。"""
        path = str(getattr(self.config, "config_path", "") or "")
        if not path:
            return
        base = os.path.dirname(path)
        legacy_candidates = [
            os.path.join(base, "amo_forever_config.json"),
            os.path.join(base, "astrbot_plugin_amo_forever_config.json"),
        ]
        legacy = next((item for item in legacy_candidates if os.path.exists(item)), "")
        if not legacy:
            return
        try:
            import shutil as _shutil
            with open(path, encoding="utf-8-sig") as stream:
                current = json.load(stream)
            with open(legacy, encoding="utf-8-sig") as stream:
                old = json.load(stream)
            if not isinstance(current, dict) or not isinstance(old, dict):
                return
            schema = {}
            try:
                with open(os.path.join(self.plugin_dir, "_conf_schema.json"), encoding="utf-8-sig") as stream:
                    schema = json.load(stream) or {}
            except Exception:
                schema = {}
            merged = {}
            for key, value in old.items():
                meta = schema.get(key) if isinstance(schema.get(key), dict) else {}
                default = meta.get("default")
                if key not in current or current.get(key) == default:
                    current[key] = value
                    merged[key] = value
            if not merged:
                return
            backup = path + ".bak-4.0.0"
            if os.path.exists(path) and not os.path.exists(backup):
                _shutil.copy2(path, backup)
            self.config.update(current)
            if hasattr(self.config, "save_config"):
                self.config.save_config()
            logger.info(
                "[amo] 已迁移旧版 amo_forever 配置: %s（%d 项）"
                % (legacy, len(merged))
            )
            logger.info("[amo] 升级提示：插件标识保持 Astrbot_Amo_forever；旧 amo_forever 配置/数据已自动迁移。")
        except Exception as exc:
            logger.warning("[amo] 旧版 amo_forever 配置迁移失败: %s" % exc)

    def _reload_config_if_changed(self):
        """AstrBot 原生插件配置页保存后，运行中的 self.config 可能不是新对象。

        读取配置文件 mtime，变化时把新值合并进当前配置，保证天气城市、
        管理员、主动私聊等动态配置不需要重启插件也能生效。
        """
        path = getattr(self.config, "config_path", "")
        if not path:
            return
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            return
        if mtime <= self._config_mtime:
            return
        try:
            with open(path, encoding="utf-8-sig") as stream:
                data = json.load(stream)
            if not isinstance(data, dict):
                return
            old_engine_config = {
                key: value for key, value in self.config.items()
                if key.startswith("hf_") or key.startswith("seg_")
            }
            self.config.update(data)
            new_engine_config = {
                key: value for key, value in self.config.items()
                if key.startswith("hf_") or key.startswith("seg_")
            }
            if old_engine_config and old_engine_config != new_engine_config:
                self._spawn(self._apply_runtime_config())
            self._config_mtime = mtime
            if data.get("bot_name"):
                self.bot_name = str(data.get("bot_name"))
            if data.get("bot_aliases") is not None:
                self.bot_aliases = [
                    item.strip() for item in str(data.get("bot_aliases")).split(",") if item.strip()
                ]
            if self.heartflow is not None:
                self.heartflow.set_identity(self.bot_name, self.bot_aliases)
            self._persona_name_cache.clear()
            raw_admins = data.get("admin_uids", None)
            if raw_admins is not None:
                self.admin_uids = {
                    item.strip() for item in str(raw_admins).split(",") if item.strip()
                }
            start = str(data.get("period_start") or "").strip()
            if start and self.state is not None and start != self.state.period_start:
                try:
                    date.fromisoformat(start)
                    self.state.set_period_start(start)
                except Exception:
                    pass
            try:
                self._sync_weather_city_config()
            except Exception:
                pass
            logger.debug("[amo] 检测到插件配置变更，已重新加载")
        except Exception as exc:
            logger.debug("[amo] 重新加载插件配置失败: %s" % exc)

    def _hf_config(self):
        try:
            return {key[3:]: value for key, value in self.config.items() if key.startswith("hf_")}
        except Exception:
            return {}

    def _seg_config(self):
        try:
            return {key[4:]: value for key, value in self.config.items() if key.startswith("seg_")}
        except Exception:
            return {}

    #: 整句就是换装指令才算；聊天里提到换衣服不算（和生图插件独立模式同一张词表）
    OUTFIT_COMMANDS = ("换一套衣服", "换套衣服", "换身衣服", "换衣服", "换一件衣服")
    _OUTFIT_TRIM = "。！!～~,.，？?\n\t "

    def _outfit_command(self, text):
        """认出「换一套衣服」这类整句指令；唤醒词先剥掉。判定纯本地。"""
        body = str(text or "").strip().strip(self._OUTFIT_TRIM)
        if not body:
            return ""
        for prefix in self._command_prefixes():
            if body.startswith(prefix):
                body = body[len(prefix):].strip().strip(self._OUTFIT_TRIM)
                break
        for word in self.OUTFIT_COMMANDS:
            if body == word:
                return word
        return ""

    def _sanitize_schedule(self, sched):
        """对外入口：真正的清洗在 HumanState 里，插件这边代调。"""
        state = getattr(self, "state", None)
        fn = getattr(state, "_sanitize_schedule", None)
        if callable(fn):
            try:
                return fn(sched)
            except Exception as exc:
                logger.debug("[amo] 日程清洗失败: %s" % exc)
        return sched

    def _record(self, kind, title, detail="", reason="", amount=0.0):
        """只增不改的记录：买了什么/想过什么/为什么没买/为什么买股票。"""
        plugin = self._data_plugin()
        store = getattr(plugin, "store", None) if plugin is not None else None
        fn = getattr(store, "record_add", None)
        if not callable(fn):
            return False
        try:
            bot_id = ""
            getter = getattr(self, "_data_bot_id", None)
            if callable(getter):
                bot_id = str(getter() or "")
            fn(bot_id, str(kind or "note"), str(title or ""), str(detail or ""),
               str(reason or ""), float(amount or 0))
            return True
        except Exception as exc:
            logger.debug("[amo] 记录写入失败: %s" % exc)
            return False

    async def _maybe_change_outfit(self, event, text):
        """中央集权：换装由 Amo 判、Amo 说，造型由生图插件执行。

        判定和回执都在本地：整句匹配 → 让挂载插件换一套 → 直接回「换好了」，
        不叫模型、不占聊天主流程；挂载不在时老实不放行。
        """
        word = self._outfit_command(text)
        if not word:
            return False
        # 先看衣柜里有没有这件：有就穿；没有就记下来，等有空去市场买（别硬编一套）
        wardrobe = getattr(self, "wardrobe", None)
        hit = ""
        try:
            if wardrobe is not None:
                for row in wardrobe.items(only_enabled=True):
                    name = str(row.get("name") or "").strip()
                    if name and (name in word or word in name):
                        hit = name
                        break
        except Exception:
            hit = ""
        if wardrobe is not None and not hit:
            self._record("skip", "想穿「%s」" % word, "衣柜里没有",
                         "等有空去市场买", 0)
            try:
                wishes = self.db.kv_get("outfit_wish", []) or []
                if word not in wishes:
                    wishes.append(word)
                self.db.kv_set("outfit_wish", wishes[-50:])
            except Exception:
                pass
            try:
                await self.context.send_message(
                    event.unified_msg_origin,
                    "衣柜里没有%s，等我哪天去市场买。" % word)
            except Exception:
                pass
            try:
                event.stop_event()
            except Exception:
                pass
            return True
        plugin = self._image_plugin()
        changer = getattr(plugin, "change_outfit_for", None) if plugin is not None else None
        if not callable(changer):
            return False
        try:
            look = str(changer("Amo 换装指令") or "").strip()
        except Exception as exc:
            logger.warning("[amo] 换装失败: %s" % exc)
            return False
        if not look:
            return False
        logger.info("[审批] 换装放行（%s）：%s" % (word, look))
        try:
            await self.context.send_message(event.unified_msg_origin, "换好了：%s" % look)
        except Exception as exc:
            logger.debug("[amo] 换装回执发送失败: %s" % exc)
        try:
            event.stop_event()
        except Exception:
            pass
        return True

    def _command_prefixes(self):
        if self._prefix_cache is not None:
            return self._prefix_cache
        prefixes = []
        try:
            cfg = self.context.get_config()
            raw = cfg.get("wake_prefix", []) if cfg else []
            if isinstance(raw, str):
                raw = [raw]
            prefixes = [str(item) for item in (raw or []) if item]
        except Exception:
            pass
        self._prefix_cache = prefixes
        return prefixes

    def _looks_like_command(self, text):
        if looks_like_plain_command(text):
            return True
        first = text.split()[0].lower() if text.split() else ""
        if first in ("amo", "陪伴", "c_status", "c_profile", "c_setrel", "learn_and_gate"):
            return True
        return any(prefix and text.startswith(prefix) for prefix in self._command_prefixes())

    _on_astrbot_loaded_hook = getattr(filter, "on_astrbot_loaded", None)

    if _on_astrbot_loaded_hook is not None:
        @_on_astrbot_loaded_hook()
        async def on_astrbot_loaded(self):
            """所有插件加载完：数据插件要是比 amo 后加载，这里补做一次同步。"""
            try:
                await self._ensure_ready()
                try:
                    self._reseed_wardrobe_from_market()
                except Exception as exc:
                    logger.debug("[amo] 衣柜重建失败: %s" % exc)
                if not self._data_synced and self._data_connected():
                    await self._sync_with_data_plugin()
            except Exception as exc:
                logger.debug("[amo] 加载完成补同步失败: %s" % exc)
            # 金融第一次发薪会等 20 秒，这里先把人格里的月薪推过去，别让它按城市平均先发一遍
            try:
                await self._maybe_push_salary()
            except Exception as exc:
                logger.debug("[amo] 加载完成推月薪失败: %s" % exc)

    def _record_tokens(self, kind, provider, response):
        """把这次调用的 token 记进自己的表；provider_stats 只统计主回复，这里补内部调用。"""
        try:
            usage = getattr(response, "usage", None)
            if usage is None:
                return
            if isinstance(usage, dict):
                miss = usage.get("input_other", 0)
                cached = usage.get("input_cached", 0)
                out = usage.get("output", 0)
            else:
                miss = getattr(usage, "input_other", 0)
                cached = getattr(usage, "input_cached", 0)
                out = getattr(usage, "output", 0)
            if not (int(miss or 0) or int(cached or 0) or int(out or 0)):
                return
            model = ""
            try:
                model = str(provider.get_model() or "")
            except Exception:
                model = ""
            self.db.record_tokens(kind, model, miss, cached, out)
        except Exception as exc:
            logger.debug("[amo] 记 token 失败: %s" % exc)

    def _spawn(self, coro):
        try:
            task = asyncio.create_task(coro)
        except RuntimeError:
            try:
                coro.close()
            except Exception:
                pass
            return None
        self._tasks.add(task)

        def _report(done):
            self._tasks.discard(done)
            if done.cancelled():
                return
            try:
                exc = done.exception()
            except Exception:
                exc = None
            if exc is not None:
                logger.warning("[amo] 后台任务异常: %s", exc, exc_info=exc)

        task.add_done_callback(_report)
        return task

    async def _ensure_ready(self):
        if self._ready:
            return
        async with self._init_lock:
            if self._ready:
                return
            try:
                await asyncio.to_thread(self.db.init)
            except Exception as exc:
                logger.error("[amo] 数据库初始化失败: %s" % exc)
            self._migrate_delay_default()
            self._migrate_proactive_timing()
            self._migrate_typing_defaults()
            self._migrate_memory_source_default()
            self._migrate_legacy_admin_default()
            self._migrate_scenic_kb_name()
            self._migrate_schedule_defaults()
            self._migrate_diary_continuity()
            self._apply_forced_on_config()
            self._cleanup_legacy_memory_profiles()
            await asyncio.to_thread(self._merge_alias_profiles)
            self.state = HumanState(self)
            try:
                await self._sync_with_data_plugin()
            except Exception as exc:
                logger.debug("[amo] 与数据插件同步失败: %s" % exc)
            self._ready = True
            self._loop_task = self._spawn(self._background_loop())
            self._spawn(self._warm_up())

    def _migrate_schedule_defaults(self):
        """5.1.1：位置/资产改为“人格优先、缺失随机”，清掉 5.1.0 自动写入的固定默认值。"""
        try:
            if self.db.kv_get("schedule_defaults_511", False):
                return
            auto_filled = bool(self.db.kv_get("schedule_defaults_510", False))
            changed = False
            cleared_city = False
            old_defaults = {
                "schedule_city": "贵阳",
                "schedule_home": "观山湖区·小窝",
                "schedule_workplace": "公司（贵阳·观山湖区）",
                "schedule_car": "黑色奔驰C级",
            }
            for key, value in old_defaults.items():
                if self.cfg_str(key, "").strip() == value:
                    self.config[key] = ""
                    changed = True
                    if key == "schedule_city":
                        cleared_city = True
            weather_city = self.cfg_str("weather_city", "").strip()
            if weather_city == "杭州" or ((cleared_city or auto_filled) and weather_city == "贵阳"):
                self.config["weather_city"] = ""
                changed = True
            if changed and hasattr(self.config, "save_config"):
                self.config.save_config()
            self.db.kv_set("schedule_defaults_511", True)
        except Exception as exc:
            logger.debug("[amo] 日程默认配置迁移失败: %s" % exc)

    def _migrate_diary_continuity(self):
        """5.2.1：旧版动态日记是逐小时独立生成的，可能互相矛盾；升级时清一次缓存。"""
        try:
            if self.db.kv_get("diary_continuity_521", False):
                return
            self.db.conn.execute("DELETE FROM schedule_diary")
            self.db.conn.commit()
            self.db.kv_set("diary_continuity_521", True)
            logger.info("[amo] 已清理旧版日程日记缓存（5.2.1 连续性修复）")
        except Exception as exc:
            logger.debug("[amo] 清理日记缓存失败: %s" % exc)

    def _migrate_scenic_kb_name(self):
        try:
            if self.db.kv_get("scenic_kb_name_migrated_502", False):
                return
            current = self.cfg_str("scenic_kb_name", "").strip()
            if current in ("", "中国景区知识库", "景区知识库"):
                self.config["scenic_kb_name"] = "旅游知识库-风景区"
                if hasattr(self.config, "save_config"):
                    self.config.save_config()
            self.db.kv_set("scenic_kb_name_migrated_502", True)
        except Exception as exc:
            logger.debug("[amo] 迁移景区知识库名称失败: %s" % exc)

    def _cleanup_legacy_memory_profiles(self):
        """4.3.2 回到原版：删除旧版本从记忆插件导入的画像，只保留本地聊天档案。"""
        try:
            if self.db.kv_get("legacy_memory_profiles_cleaned_432", False):
                return
            removed = 0
            for row in self.db.list_profiles(limit=1000):
                if str(row.get("platform") or "") in ("angel_memory", "memory_companion"):
                    self.db.delete_profile(str(row.get("uid") or ""))
                    removed += 1
            self.db.kv_set("legacy_memory_profiles_cleaned_432", True)
            if removed:
                logger.info("[amo] 已移除 %d 个旧记忆插件导入画像，恢复本地画像模式" % removed)
        except Exception as exc:
            logger.debug("[amo] 清理旧记忆画像失败: %s" % exc)

    def _migrate_typing_defaults(self):
        """2.6.2 起把旧的 55ms/字默认值迁移到更真实的 400ms/字。"""
        try:
            if self.db.kv_get("typing_realistic_migrated", False):
                return
            changes = {}
            if to_int(self.cfg("typing_base_ms", 0), 0) == 600:
                changes["typing_base_ms"] = 700
            if to_int(self.cfg("typing_per_char_ms", 0), 0) == 55:
                changes["typing_per_char_ms"] = 400
            if to_int(self.cfg("typing_max_ms", 0), 0) == 4500:
                changes["typing_max_ms"] = 20000
            if abs(to_float(self.cfg("seg_per_char_delay_seconds", 0), 0) - 0.08) < 0.0001:
                changes["seg_per_char_delay_seconds"] = 0.4
            for key, value in changes.items():
                self.config[key] = value
            if changes:
                if hasattr(self.config, "save_config"):
                    self.config.save_config()
                if self.segment_engine is not None and "seg_per_char_delay_seconds" in changes:
                    self.segment_engine.per_char_delay_seconds = 0.4
                logger.debug("[amo] 打字延迟默认值已迁移为 400ms/字（18字约8秒）")
            self.db.kv_set("typing_realistic_migrated", True)
        except Exception as exc:
            logger.debug("[amo] 迁移打字延迟失败: %s" % exc)

    def _migrate_proactive_timing(self):
        try:
            if self.db.kv_get("proactive_timing_migrated", False):
                return
            changes = {}
            if to_int(self.cfg("proactive_followup_minutes", 0), 0) == 30:
                changes["proactive_followup_minutes"] = 5
            if to_int(self.cfg("proactive_no_reply_minutes", 0), 0) == 120:
                changes["proactive_no_reply_minutes"] = 30
            for key, value in changes.items():
                self.config[key] = value
            if changes and hasattr(self.config, "save_config"):
                self.config.save_config()
            self.db.kv_set("proactive_timing_migrated", True)
        except Exception:
            pass

    def _migrate_delay_default(self):
        """2.4.7 起默认按回复字数动态延迟；旧的 fixed 配置迁移一次。"""
        try:
            if self.cfg_str("seg_delay_type", "").strip().lower() != "fixed":
                return
            if self.db.kv_get("delay_dynamic_migrated", False):
                return
            self.config["seg_delay_type"] = "dynamic"
            if self.segment_engine is not None:
                self.segment_engine.delay_type = "dynamic"
            if hasattr(self.config, "save_config"):
                self.config.save_config()
            self.db.kv_set("delay_dynamic_migrated", True)
            logger.debug("[amo] 分段延迟已从 fixed 迁移为 dynamic（按回复字数）")
        except Exception as exc:
            logger.debug("[amo] 迁移分段延迟失败: %s" % exc)

    def _migrate_memory_source_default(self):
        """旧版把 private companion 写成默认来源；2.4.4 起改成 auto，避免锁死。"""
        try:
            value = self.cfg_str("companion_memory_plugin_name", "").strip()
            if value != LEGACY_MEMORY_PLUGIN:
                return
            if self.db.kv_get("companion_plugin_auto_migrated", False):
                return
            self.config["companion_memory_plugin_name"] = "auto"
            if hasattr(self.config, "save_config"):
                self.config.save_config()
            self.db.kv_set("companion_plugin_auto_migrated", True)
            logger.debug("[amo] 记忆来源已从旧默认 %s 改为 auto" % LEGACY_MEMORY_PLUGIN)
        except Exception as exc:
            logger.debug("[amo] 迁移记忆来源失败: %s" % exc)

    def _migrate_legacy_admin_default(self):
        """旧版本把 3261748099 写成了默认管理员；2.4.0 只清理一次。"""
        try:
            if self.cfg_str("admin_uids", "").strip() != LEGACY_DEFAULT_ADMIN:
                return
            if self.db.kv_get("admin_default_cleared", False):
                return
            parts = [
                item.strip() for item in self.cfg_str("admin_uids", "").split(",")
                if item.strip() and item.strip() != LEGACY_DEFAULT_ADMIN
            ]
            self.config["admin_uids"] = ",".join(parts)
            if hasattr(self.config, "save_config"):
                self.config.save_config()
            self.admin_uids = set(parts)
            self.db.kv_set("admin_default_cleared", True)
            logger.debug("[amo] 已移除旧默认管理员 %s，请在配置里填写自己的 ID" % LEGACY_DEFAULT_ADMIN)
        except Exception as exc:
            logger.debug("[amo] 清理旧默认管理员失败: %s" % exc)

    async def _warm_up(self):
        try:
            await asyncio.sleep(3)
            umo = self._last_umo or self._first_private_umo()
            await self._sync_persona_name(umo or "")
            await self._ensure_dialect_kb()
            await self._ensure_scenic_kb()
            await self.state.ensure_worldview(umo)
            await self.state.ensure_schedule(umo)
        except Exception as exc:
            logger.debug("[amo] 预热失败: %s" % exc)

    async def initialize(self):
        await self._ensure_ready()

    async def terminate(self):
        self._running = False
        if self.heartflow is not None:
            try:
                await self.heartflow.terminate()
            except Exception:
                pass
        if self.segment_engine is not None:
            for task in list(getattr(self.segment_engine, "_tasks", set())):
                try:
                    task.cancel()
                except Exception:
                    pass
        for task in list(self._tasks):
            try:
                task.cancel()
            except Exception:
                pass
        if self.state is not None:
            try:
                self.state.save()
            except Exception:
                pass
        # 不在这里关闭数据库：AstrBot 重载插件时旧实例注册的 Web API
        # 可能仍被调用，关闭连接会导致 "Cannot operate on a closed database"。
        # 连接由进程退出时回收；AmoDB.conn 也会在需要时自动重连。

    async def stop(self):
        await self.terminate()

    # ---- 跨平台账号合并 ----
    def _uid_alias_mapping(self):
        """读映射表（配置优先，其次数据目录 uid_map.json）；按内容+mtime 缓存。"""
        cache_key = None
        try:
            text = str(self.cfg_str("uid_alias_map", "") or "").strip().lstrip("﻿")
            map_path = os.path.join(os.path.dirname(str(self.db.path)), "uid_map.json")
            stamp = os.path.getmtime(map_path) if os.path.exists(map_path) else 0
            cache_key = (text, stamp)
        except Exception:
            cache_key = None
        if getattr(self, "_uid_alias_cache_key", None) != cache_key:
            raw = {}
            try:
                text = str(self.cfg_str("uid_alias_map", "") or "").strip().lstrip("﻿")
                parsed = json.loads(text) if text else {}
                if isinstance(parsed, dict):
                    raw.update(parsed)
            except Exception as exc:
                logger.warning("[amo] uid_alias_map 配置解析失败: %s" % exc)
            try:
                map_path = os.path.join(os.path.dirname(str(self.db.path)), "uid_map.json")
                if os.path.exists(map_path):
                    # utf-8-sig：Windows 记事本另存的 JSON 常带 BOM，用 utf-8 会直接解析失败
                    with open(map_path, "r", encoding="utf-8-sig") as fh:
                        parsed = json.load(fh)
                    if isinstance(parsed, dict):
                        for key, value in parsed.items():
                            raw.setdefault(key, value)
            except Exception as exc:
                logger.warning("[amo] uid_map 读取失败: %s" % exc)
            raw = {str(k): str(v) for k, v in raw.items() if k and v}
            # 解析链式映射（A→B、B→C 归到 A→C），并丢掉自映射
            resolved = {}
            for key in raw:
                current = key
                seen = {key}
                while current in raw:
                    nxt = raw[current]
                    if nxt in seen:
                        break
                    seen.add(nxt)
                    current = nxt
                if current != key:
                    resolved[key] = current
            self._uid_alias_map = resolved
            self._uid_alias_cache_key = cache_key
        return getattr(self, "_uid_alias_map", {}) or {}

    def _canonical_uid(self, event):
        """把平台账号换算成同一个人的主 uid；关掉开关就返回原 uid。"""
        try:
            uid = str(event.get_sender_id())
        except Exception:
            return ""
        if not self.cfg_bool("uid_merge_enabled", True):
            return uid
        return self._uid_alias_mapping().get(uid, uid)

    def _merge_alias_profiles(self):
        """一次性把旧版本按平台 ID 建好的档案并进主 uid（映射变了会再跑一次）。"""
        if not self.cfg_bool("uid_merge_enabled", True):
            return
        mapping = self._uid_alias_mapping()
        if not mapping:
            return
        signature = json.dumps(mapping, sort_keys=True, ensure_ascii=False)
        try:
            if self.db.kv_get("uid_alias_merged_signature", "") == signature:
                return
        except Exception:
            pass
        try:
            report = merge_uid_alias_data(self.db.conn, mapping)
            self.db.kv_set("uid_alias_merged_signature", signature)
            logger.info("[amo] 跨平台账号合并完成: %s" % report)
        except Exception as exc:
            logger.warning("[amo] 跨平台账号合并失败: %s" % exc)

    # ---------- 管理员 ----------
    def _is_admin(self, event):
        uid = self._canonical_uid(event)
        if uid in self.admin_uids:
            return True
        try:
            umo = str(event.unified_msg_origin or "")
        except Exception:
            umo = ""
        # 每条消息都会走这里，get_config 没必要每次读：按会话缓存 60 秒
        cache = getattr(self, "_admin_cache", None)
        if cache is None:
            cache = {}
            self._admin_cache = cache
        now = time.time()
        hit = cache.get(umo)
        if hit and now - hit[0] < 60:
            return uid in hit[1]
        try:
            cfg = self.context.get_config(umo)
            admins = cfg.get("admins_id", []) if cfg else []
            if isinstance(admins, str):
                admins = [item.strip() for item in admins.split(",") if item.strip()]
            names = {str(item) for item in (admins or [])}
        except Exception:
            names = set()
        cache[umo] = (now, names)
        return uid in names

    # ---------- 消息学习 ----------
    async def _learn(self, event, text):
        uid = self._canonical_uid(event)
        name = event.get_sender_name() or uid
        umo = event.unified_msg_origin
        group_id = event.get_group_id()
        private = event.is_private_chat()
        profile = self.db.touch_profile(
            uid, name, event.get_platform_name(), umo, group_id, private
        )
        if private and umo:
            self._record_channel(uid, umo, event.get_platform_name())
        if profile and not profile.get("is_admin") and uid in self.admin_uids:
            self.db.update_profile(uid, is_admin=1)
            profile["is_admin"] = 1

        self.state.observe(text)
        if self.cfg_bool("auto_relation", True):
            try:
                await self._learn_relations(event, text, uid)
            except Exception as exc:
                logger.debug("[amo] 关系自动识别失败: %s" % exc)
        # 上下文先进内存；本地缓存默认关掉，原始聊天交给记忆终端
        self._ctx_remember(umo, uid, name, "user", text)
        try:
            await self._data_call(
                "add_message", self._data_bot_id(), umo, uid, name, "user", text,
                platform=self._platform_of(event), message_id=self._event_message_id(event),
            )
        except Exception as exc:
            logger.debug("[amo] 聊天记录同步失败: %s" % exc)

        senti = sentiment(text)
        affection = to_int(profile.get("affection"), 10)
        if senti["aff"] or senti["pos"]:
            affection += 2
        if senti["neg"] or senti["insult"]:
            affection -= 2
        affection = int(clamp(affection, 0, 100))

        # 记忆只在外挂记忆插件里；这里只把生日这种档案字段记进画像。
        match = re.search(r"生日(?:是|在)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?", text or "")
        if match:
            self.db.update_profile(uid, birthday="%02d-%02d" % (to_int(match.group(1)), to_int(match.group(2))))

        fields = {"affection": affection}
        relation = profile.get("relation", "普通")
        if relation == "普通" and to_int(profile.get("msg_count"), 0) >= self.cfg_int("familiar_msg_count", 30):
            fields["relation"] = "熟识"
        elif relation == "熟识" and senti["insult"]:
            fields["relation"] = "抵触"
        self.db.update_profile(uid, **fields)
        try:
            self._learn_alias(event, text, uid, profile)
        except Exception as exc:
            logger.debug("[amo] 学习称呼失败: %s" % exc)

        if group_id:
            times = self._group_times.setdefault(group_id, [])
            times.append(now_ts())
            if len(times) > 200:
                self._group_times[group_id] = times[-200:]
            self._last_group = group_id
        self._last_umo = umo

    def _register_lover(self, uid):
        uid = str(uid or "").strip()
        if uid:
            self.db.kv_set("lover_uid_" + uid, True)

    def _is_registered_lover(self, uid):
        uid = str(uid or "").strip()
        if not uid:
            return False
        if self.db.kv_get("lover_uid_" + uid, False):
            return True
        profile = self.db.get_profile(uid) or {}
        if str(profile.get("relation") or "") == "相恋":
            self._register_lover(uid)
            return True
        return False

    def _restore_lover_relation(self, uid):
        uid = str(uid or "").strip()
        if not self._is_registered_lover(uid):
            return
        profile = self.db.get_profile(uid) or {}
        if str(profile.get("relation") or "") in ("抵触", "仇恨"):
            self.db.update_profile(uid, relation="相恋")
            logger.info("[amo] 恋人 UID 恢复为相恋: %s" % uid)

    def _lover_aliases(self):
        aliases = {}
        try:
            profiles = self.db.list_profiles("", 500)
        except Exception:
            profiles = []
        for profile in profiles:
            uid = str(profile.get("uid") or "")
            if str(profile.get("relation") or "") == "相恋":
                self._register_lover(uid)
            elif not self._is_registered_lover(uid):
                continue
            values = [profile.get("name") or ""]
            values.extend(re.split(r"[；;、,，/\s]+", str(profile.get("alias") or "")))
            for value in values:
                name = str(value or "").strip()
                if len(name) >= 1:
                    aliases[name] = uid
        return aliases

    def _detect_impersonation(self, event):
        """群里非恋人 UID 使用/冒充恋人的名字或爱称时，5 分钟内累计降级。"""
        group_id = str(event.get_group_id() or "")
        if not group_id:
            return False
        uid = self._canonical_uid(event)
        lovers = self._lover_aliases()
        if not lovers or uid in set(lovers.values()) or self._is_registered_lover(uid):
            return False
        sender_name = str(event.get_sender_name() or "").strip()
        text = str(event.message_str or "").strip()
        hit = ""
        if sender_name in lovers:
            hit = sender_name
        elif text in lovers:
            hit = text
        else:
            for alias in lovers:
                if re.search(r"(?:我才是|我是|叫我|叫我做|以后叫我|我才是那个)\s*" + re.escape(alias), text):
                    hit = alias
                    break
        if not hit:
            return False
        setattr(event, "amo_impersonation", True)
        key = "impersonate_%s_%s" % (group_id, uid)
        now = now_ts()
        stamps = self.db.kv_get(key, [])
        if not isinstance(stamps, list):
            stamps = []
        stamps = [to_float(item, 0) for item in stamps if now - to_float(item, 0) <= 300]
        stamps.append(now)
        self.db.kv_set(key, stamps)
        count = len(stamps)
        profile = self.db.get_profile(uid) or {}
        current = str(profile.get("relation") or "普通")
        relation = current
        if count >= 3 and current != "仇恨":
            relation = "仇恨"
        elif count == 1 and current != "仇恨":
            relation = "抵触"
        if relation != current:
            self.db.update_profile(uid, relation=relation)
            logger.info(
                "[amo] 识别到冒充恋人称呼: %s -> %s（%s，5分钟内第%d次）"
                % (uid, relation, hit, count)
            )
        return True

    def _learn_alias(self, event, text, uid, profile):
        """从“以后叫我XX / 叫他XX”里学习称呼，并在后续沿用。"""
        blocked = {"干嘛", "什么", "名字", "滚", "闭嘴", "一声", "一下", "出来"}
        alias = ""
        for pattern in (
            r"(?:以后|今后|你可以|可以|请)?叫我\s*([\u4e00-\u9fa5A-Za-z0-9_]{1,12})",
            r"叫我\s*([\u4e00-\u9fa5A-Za-z0-9_]{1,12})\s*(?:就行|就好|吧)",
        ):
            match = re.search(pattern, str(text or ""))
            if match:
                candidate = match.group(1).strip()
                if candidate and candidate not in blocked:
                    alias = candidate
                    break
        if alias:
            current = str(profile.get("alias") or "")
            if alias not in current:
                new_alias = (current + "；" + alias).strip("；")[:80]
                self.db.update_profile(uid, alias=new_alias)
                logger.debug("[amo] 记住称呼: %s -> %s" % (uid, alias))

        try:
            messages = event.message_obj.message
        except Exception:
            messages = []
        at_targets = [
            str(getattr(comp, "qq", ""))
            for comp in (messages or [])
            if Comp is not None and isinstance(comp, Comp.At)
        ]
        for comp in messages:
            if Comp is None or not isinstance(comp, Comp.At):
                continue
            target = str(getattr(comp, "qq", ""))
            if not target or target in ("all", str(event.get_self_id())):
                continue
            # “以后喊他XX”通常跟在最后一个 @ 后面；不要误记到前一个被 @ 的人。
            if at_targets and target != at_targets[-1]:
                continue
            for pattern in (
                r"(?:以后|就)?(?:喊|叫|称呼)(?:他|她|ta|TA|做)\s*([\u4e00-\u9fa5A-Za-z0-9_]{1,12})",
            ):
                match = re.search(pattern, str(text or ""))
                if not match:
                    continue
                candidate = match.group(1).strip()
                if not candidate or candidate in blocked:
                    continue
                target_profile = self.db.get_profile(target)
                if not target_profile:
                    self.db.touch_profile(target, candidate, event.get_platform_name(), "", "", False)
                    target_profile = self.db.get_profile(target)
                current = str(target_profile.get("alias") or "")
                if candidate not in current:
                    self.db.update_profile(target, alias=(current + "；" + candidate).strip("；")[:80])
                break
            # 群里反复 @ 同一个人并叫同一个短称呼，累计三次后记住。
            plain = re.sub(r"@\S+", "", str(text or "")).strip()
            common = {
                "在吗", "你好", "早安", "晚安", "吃了吗", "干嘛", "出来", "看这个",
                "哈哈", "笑死", "救命", "谢谢", "收到", "好的", "可以", "不行",
                "快看", "快来", "过来", "上线", "打游戏", "起床", "睡觉", "上班", "下班",
            }
            if 1 <= len(plain) <= 8 and plain not in common and not re.search(r"[，。！？!?、；;：:]", plain):
                seen_key = "alias_seen_" + target + "_" + plain
                seen = to_int(self.db.kv_get(seen_key, 0), 0) + 1
                self.db.kv_set(seen_key, seen)
                if seen >= 3:
                    alias_profile = self.db.get_profile(target) or {}
                    current = str(alias_profile.get("alias") or "")
                    if plain not in current:
                        self.db.update_profile(target, alias=(current + "；" + plain).strip("；")[:80])
                    self.db.kv_set(seen_key, 0)

    # ---------- 近聊上下文（内存缓冲 + 记忆终端钩子） ----------
    CONTEXT_BUFFER_LIMIT = 60

    def _ctx_remember(self, umo, uid, name, role, content):
        """把一句话放进内存缓冲；不落库也能有上下文。

        只留 ChatBuffer 一个真相源：以前这里还并写一份 _ctx_buffer，
        _recent / _recent_by_uid / _hydrate_recent 三处各读一份，谁先谁后都能吵起来。
        """
        umo = str(umo or "")
        text = str(content or "").strip()
        if not umo or not text:
            return
        hub = self._memory_hub()
        if hub is None:
            return
        try:
            hub.buffer.add(umo, uid, name, role, text)
        except Exception:
            pass
        try:
            if str(role) != "bot":
                hub.next_turn()
        except Exception:
            pass

    def _recent(self, umo, limit=10):
        """近聊上下文钩子：能力层缓冲优先，没有再读本地缓存表。"""
        size = max(1, int(limit or 10))
        rows = []
        hub = self._memory_hub()
        if hub is not None:
            try:
                rows = hub.buffer.recent(umo, size)
            except Exception:
                rows = []
        if len(rows) >= size:
            return rows[-size:]
        try:
            local = self.db.recent_messages(umo, size)
        except Exception:
            local = []
        if not rows:
            return local
        # 缓冲只有一小段时，用本地补前面
        known = {(row.get("role"), row.get("content")) for row in rows}
        merged = [row for row in local if (row.get("role"), row.get("content")) not in known]
        merged.extend(rows)
        return merged[-size:]

    async def _recent_by_uid(self, uid, limit=20, umo=""):
        """取近聊：优先按会话，其次按 uid；都没有再退回缓冲/本地缓存。"""
        uid = str(uid or "")
        size = max(1, int(limit or 20))
        mem = self._data_mem()
        lister = getattr(mem, "list_messages", None) if mem is not None else None
        if callable(lister) and umo:
            # 按会话取：bot 行的 uid 是字面量 "bot"，按 uid 过滤会把她说的话全滤掉
            try:
                rows = await lister(self._data_bot_id(), str(umo), size) or []
            except TypeError:
                rows = []
            except Exception:
                rows = []
            if rows:
                return sorted(rows, key=lambda item: to_float(item.get("created_at"), 0))[-size:]
        if callable(lister):
            try:
                rows = await lister(self._data_bot_id(), "", size, uid=uid) or []
            except Exception:
                rows = []
            if rows:
                return sorted(rows, key=lambda item: to_float(item.get("created_at"), 0))[-size:]
        merged = []
        hub = self._memory_hub()
        if hub is not None:
            try:
                merged = hub.buffer.by_uid(uid, size)
            except Exception:
                merged = []
        if merged:
            return sorted(merged, key=lambda item: to_float(item.get("created_at"), 0))[-size:]
        try:
            return self.db.messages_by_uid(uid, size)
        except Exception:
            return []

    async def _hydrate_recent(self, umo, limit=30):
        """从记忆终端把这个会话最近的话捞回内存，重启后也有上下文。"""
        umo = str(umo or "")
        if not umo:
            return
        if str(umo) in getattr(self, "_ctx_hydrated", set()):
            return
        rows = []
        hub = self._memory_hub()
        if hub is not None:
            try:
                rows = await hub.recent(umo, "", max(1, int(limit))) or []
            except Exception as exc:
                logger.debug("[amo] 能力层取上下文失败: %s" % exc)
                rows = []
        if not rows:
            mem = self._data_mem()
            lister = getattr(mem, "list_messages", None) if mem is not None else None
            if callable(lister):
                try:
                    rows = await lister(self._data_bot_id(), umo, max(1, int(limit))) or []
                except Exception as exc:
                    logger.debug("[amo] 从记忆终端取上下文失败: %s" % exc)
                    rows = []
        if not rows:
            try:
                rows = self.db.recent_messages(umo, max(1, int(limit)))
            except Exception:
                rows = []
        if not rows:
            return
        ordered = sorted(rows, key=lambda item: to_float(item.get("created_at"), 0))
        if hub is not None:
            try:
                hub.buffer.hydrate(umo, ordered[-self.CONTEXT_BUFFER_LIMIT:])
            except Exception:
                pass
        self._ctx_hydrated = getattr(self, "_ctx_hydrated", set())
        self._ctx_hydrated.add(str(umo))

    def _is_talking_to_me(self, event):
        """这句是不是冲她来的：私聊、被 @ / 叫名字、或心流判定对象是 bot。"""
        try:
            if event.is_private_chat():
                return True
        except Exception:
            return True
        target = str(getattr(event, "heartflow_target", "") or "")
        if target == "bot":
            return True
        if str(getattr(event, "heartflow_mode_hint", "") or "") == "interject":
            return False
        try:
            if getattr(event, "is_at_or_wake_command", False):
                return True
        except Exception:
            pass
        try:
            if self.heartflow is not None and self.heartflow._addresses_bot(event.message_str or ""):
                return True
        except Exception:
            pass
        return False

    def _group_roster(self, umo, current_uid="", limit=8):
        """群里最近说过话的人：uid → 称呼 / 关系 / 聊过多少句。

        让她在群里先认人：谁在说话、和她什么关系、该用什么语气，而不是把所有人都当同一个人。
        """
        roster = []
        seen = set()
        try:
            rows = self._recent(umo, 40)
        except Exception:
            return roster
        for row in rows:
            if str(row.get("role") or "") != "user":
                continue
            uid = str(row.get("uid") or "")
            if not uid or uid in seen:
                continue
            seen.add(uid)
            profile = {}
            try:
                profile = self.db.get_profile(uid) or {}
            except Exception:
                profile = {}
            name = (
                str(profile.get("alias") or "").strip()
                or str(profile.get("name") or "").strip()
                or str(row.get("name") or "").strip()
                or uid
            )
            relation = str(profile.get("relation") or "普通")
            msg_count = to_int(profile.get("msg_count"), 0)
            roster.append({
                "uid": uid,
                "name": name,
                "relation": relation,
                "msg_count": msg_count,
                "current": bool(current_uid) and uid == str(current_uid),
            })
            if len(roster) >= max(1, int(limit)):
                break
        roster.sort(key=lambda item: (not item["current"], -item["msg_count"]))
        return roster

    def _group_roster_text(self, umo, current_uid="", limit=8):
        roster = self._group_roster(umo, current_uid, limit)
        if not roster:
            return ""
        lines = []
        for item in roster:
            tag = "（现在这句就是ta说的）" if item["current"] else ""
            if item["msg_count"] >= 200:
                familiar = "很熟"
            elif item["msg_count"] >= 30:
                familiar = "熟识"
            elif item["msg_count"] >= 1:
                familiar = "刚认识"
            else:
                familiar = "陌生"
            lines.append(
                "· %s（UID %s）：和你关系「%s」，%s%s"
                % (item["name"], item["uid"], item["relation"], familiar, tag)
            )
        return "\n".join(lines)

    def _group_reply_guide(self, relation, name):
        """按关系给一句“该怎么回”的指引。"""
        relation = str(relation or "普通")
        if relation == "相恋":
            return "对" + name + "可以亲近、撒娇、用昵称，但别在群里太露骨。"
        if relation == "熟识":
            return "对" + name + "像老朋友一样随便聊，可以开玩笑，但不用恋人语气。"
        if relation == "抵触":
            return "对" + name + "有点距离感，句子短，不主动热络。"
        if relation == "仇恨":
            return "对" + name + "很冷淡，不接他的茬，也不解释。"
        return "对" + name + "客气一点、像普通群友，不要叫老公/宝贝，也别装得很熟。"

    def _group_speaker_count(self, umo, limit=20, window=600):
        """最近一段时间内群聊里的不同发言人数。"""
        try:
            rows = self._recent(umo, limit)
        except Exception:
            return 0
        cutoff = now_ts() - window
        speakers = {
            str(row.get("uid") or "")
            for row in rows
            if row.get("role") == "user"
            and to_float(row.get("created_at"), 0) >= cutoff
            and str(row.get("uid") or "")
        }
        return len(speakers)

    def _should_quote_group(self, umo):
        """群聊要不要引用原消息：人数过阈值后按概率引用。

        人数没到阈值（人少）就不引用；到了阈值也不该句句引用——
        真人只在需要指代时才引用，所以再加一层概率。
        `quote_group_probability`：1.0 = 旧行为（一直引用），0 = 从不引用。
        """
        try:
            threshold = self.cfg_int("quote_group_speaker_threshold", 3)
        except Exception:
            threshold = 3
        if threshold <= 0:
            return False
        try:
            if self._group_speaker_count(umo) < threshold:
                return False
            prob = self.cfg_float("quote_group_probability", 0.4)
            if prob <= 0:
                return False
            if prob >= 1:
                return True
            return random.random() < prob
        except Exception:
            return False

    def _quote_allowed(self, umo, group=None):
        """能不能引用原消息：私聊（任何平台）永远不引用，群聊按人数 + 概率。

        `group` 不传就看 umo 里的消息类型。私聊不引用是硬规则：无论 QQ、飞书
        还是别的平台，都不该在私聊里把他的话再引用一遍；群聊才看
        `_should_quote_group()`（人数阈值 + `quote_group_probability`）。
        """
        umo = str(umo or "")
        if group is None:
            group = "GroupMessage" in umo
        if not group:
            return False
        if "GroupMessage" not in umo:
            return False
        try:
            return bool(self._should_quote_group(umo))
        except Exception:
            return False

    def _install_qq_quote_guard(self):
        """QQ 私聊也不许引用。

        AstrBot 核心的 `reply_with_quote` 是在插件 `on_decorating_result` **之后**
        才往消息链里插 Reply 的，插件钩子里摘不干净；所以在发送前再兜一层。
        群聊保持原样（插件自己按人数 + 概率加 Reply）。
        """
        try:
            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
                AiocqhttpMessageEvent,
            )
        except Exception:
            return
        original = getattr(AiocqhttpMessageEvent, "_amo_original_send", None)
        if original is None:
            original = AiocqhttpMessageEvent.send
            AiocqhttpMessageEvent._amo_original_send = original

        async def send(ev, message):
            try:
                if not ev.get_group_id():
                    message.chain = [
                        comp for comp in message.chain if not isinstance(comp, Comp.Reply)
                    ]
            except Exception:
                pass
            await original(ev, message)

        AiocqhttpMessageEvent.send = send
        AiocqhttpMessageEvent._amo_quote_guard = True
        logger.info("[amo] QQ 引用守卫已安装：私聊不引用，群聊按概率")

    def _install_lark_quote_guard(self):
        """飞书私聊不要引用：适配器把每条消息都发成「回复」。

        只装在飞书环境；装一次就够（类上留标记，热重载不会套娃）。
        群聊仍然按 `_should_quote_group()` 的概率决定引用，私聊一律普通发送。
        """
        try:
            from astrbot.core.platform.sources.lark.lark_event import LarkMessageEvent
        except Exception:
            return
        async def send(ev, message):
            try:
                is_private = bool(ev.is_private_chat())
            except Exception:
                is_private = False
            # 只认消息链里已经有的 Reply（插件按人数+概率加的那一条）；
            # 这里不能重新掷一次概率，否则「插件决定不引用」会被守卫再翻成引用。
            try:
                has_reply = any(isinstance(comp, Comp.Reply) for comp in message.chain)
            except Exception:
                has_reply = False
            quote = bool(has_reply and not is_private)
            if not quote:
                try:
                    message.chain = [comp for comp in message.chain if not isinstance(comp, Comp.Reply)]
                except Exception:
                    pass
            kwargs = lark_quote_kwargs(
                is_private,
                getattr(ev.message_obj, "message_id", ""),
                ev.get_sender_id(),
                ev.get_group_id(),
                quote,
            )
            message_type = getattr(getattr(ev.message_obj, "type", None), "value", "")
            try:
                await LarkMessageEvent.send_message_chain(
                    message, ev.bot, message_type=message_type, **kwargs,
                )
            except Exception as exc:
                if "reply_message_id" in kwargs:
                    raise
                # 普通发送失败（比如 open_id 被拒）就退回原来的引用发送，别把话吞了
                logger.warning("[amo] 飞书普通发送失败，退回引用发送: %s" % exc)
                await LarkMessageEvent.send_message_chain(
                    message, ev.bot,
                    reply_message_id=getattr(ev.message_obj, "message_id", ""),
                    message_type=message_type,
                )
            finally:
                # 父类只做 metrics 记录，不能少
                await AstrMessageEvent.send(ev, message)

        LarkMessageEvent.send = send
        LarkMessageEvent._amo_quote_guard = True
        logger.info("[amo] 飞书引用守卫已安装：私聊不引用，群聊按概率")
    @staticmethod
    def _is_memory_companion(plugin):
        return plugin is not None and getattr(plugin, "memory_companion", None) is not None

    @staticmethod
    def _memcomp_db_path(plugin):
        service = getattr(plugin, "service", None)
        store = getattr(service, "store", None)
        path = getattr(store, "db_path", None)
        if path and os.path.isfile(str(path)):
            return str(path)
        data_dir = getattr(service, "data_dir", None) or getattr(plugin, "data_dir", None)
        if data_dir:
            candidate = os.path.join(str(data_dir), "memory_companion.db")
            if os.path.isfile(candidate):
                return candidate
        return ""

    def _memcomp_rows(self, sql, params=()):
        path = self._memcomp_db_path(self._companion_plugin())
        if not path:
            return []
        conn = None
        try:
            from urllib.parse import quote
            try:
                conn = sqlite3.connect(
                    "file:" + quote(path) + "?mode=ro",
                    uri=True,
                    timeout=2.0,
                )
            except Exception:
                conn = sqlite3.connect(path, timeout=2.0)
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(sql, params).fetchall()]
        except Exception as exc:
            logger.debug("[amo] 读取 Memory Companion 数据库失败: %s" % exc)
            return []
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _memcomp_name_maps(self, plugin=None):
        """从 identities/profile/证据里建立 person_id -> 名字 的自动映射。"""
        plugin = plugin or self._companion_plugin()
        by_uid = {}
        by_key = {}
        evidence_map = {}
        try:
            rows = self._memcomp_rows(
                "SELECT entity_id, display_name, profile FROM identities "
                "WHERE entity_kind='user' AND entity_id!=''"
            )
            for row in rows:
                uid = str(row.get("entity_id") or "").strip()
                name = str(row.get("display_name") or "").strip()
                if uid and name:
                    by_uid[uid] = name
                try:
                    profile = json.loads(row.get("profile") or "{}")
                except Exception:
                    profile = {}
                if not isinstance(profile, dict):
                    continue
                for key in ("display_name", "name", "nickname"):
                    if not name and profile.get(key):
                        name = str(profile.get(key)).strip()
                if name:
                    for key in ("person_id", "resolved_identity_key", "identity_key"):
                        value = str(profile.get(key) or "").strip()
                        if value:
                            by_key[value] = name
        except Exception as exc:
            logger.debug("[amo] 建立身份名字映射失败: %s" % exc)
        try:
            rows = self._memcomp_rows(
                "SELECT e.person_id, t.subject_id, i.display_name "
                "FROM portrait_evidence e "
                "LEFT JOIN timeline t ON t.message_id=e.message_id "
                "LEFT JOIN identities i ON i.entity_id=t.subject_id "
                "WHERE e.person_id!='' AND i.display_name!=''"
            )
            for row in rows:
                pid = str(row.get("person_id") or "").strip()
                name = str(row.get("display_name") or "").strip()
                if pid and name:
                    evidence_map.setdefault(pid, name)
        except Exception as exc:
            logger.debug("[amo] 建立证据名字映射失败: %s" % exc)
        return {"by_uid": by_uid, "by_key": by_key, "evidence": evidence_map}

    def _memcomp_person_name(self, person_id, identity_key="", maps=None):
        """按 画像事实 -> 身份键 -> 身份表 -> 证据 的顺序自动取名字。"""
        maps = maps or self._memcomp_name_maps()
        rows = self._memcomp_rows(
            "SELECT dimension, claim_summary FROM portrait_facts "
            "WHERE person_id=? AND status='active' "
            "ORDER BY confidence DESC, updated_at DESC LIMIT 40",
            (str(person_id),),
        )
        name_dims = {
            "name", "display_name", "nickname", "preferred_address",
            "用户别名", "称呼", "昵称", "姓名", "名字",
        }
        patterns = (
            r"(?:名字|姓名|昵称|称呼|别名)(?:是|叫|为|：|:)\s*([^\s，。；;,.!?！？]{1,20})",
            r"(?:叫我|叫做|名为)\s*([^\s，。；;,.!?！？]{1,20})",
        )
        for row in rows:
            dimension = str(row.get("dimension") or "").strip().lower()
            claim = re.sub(r"\s+", " ", str(row.get("claim_summary") or "")).strip()
            if not claim:
                continue
            if dimension in name_dims:
                text = claim
                for pattern in patterns:
                    match = re.search(pattern, text)
                    if match:
                        text = match.group(1)
                        break
                text = text.strip("「」“”\"' ")
                if 1 <= len(text) <= 20:
                    return text
            for pattern in patterns:
                match = re.search(pattern, claim)
                if match:
                    text = match.group(1).strip("「」“”\"' ")
                    if 1 <= len(text) <= 20:
                        return text
        for candidate in (str(identity_key or "").strip(), str(person_id)):
            if candidate and maps.get("by_key", {}).get(candidate):
                return maps["by_key"][candidate]
        if maps.get("by_uid", {}).get(str(person_id)):
            return maps["by_uid"][str(person_id)]
        if maps.get("evidence", {}).get(str(person_id)):
            return maps["evidence"][str(person_id)]
        return ""

    def _memcomp_profile_rows(self, plugin=None):
        """以 portrait_facts 为准：只有真正有画像事实的人才是用户画像。"""
        plugin = plugin or self._companion_plugin()
        if not self._is_memory_companion(plugin):
            return []
        rows = self._memcomp_rows(
            "SELECT person_id, resolved_identity_key, 0 AS fact_count FROM portrait_people "
            "WHERE profile_status='active' AND person_id!='' "
            "ORDER BY updated_at DESC"
        )
        maps = self._memcomp_name_maps(plugin)
        items = []
        for row in rows:
            uid = str(row.get("person_id") or "").strip()
            if not uid:
                continue
            name = self._memcomp_person_name(
                uid, str(row.get("resolved_identity_key") or ""), maps
            )
            items.append({
                "uid": uid,
                "name": name or ("画像 " + uid[-6:]),
                "count": to_int(row.get("fact_count"), 0),
                "source": "portrait_people",
            })
        if items:
            return items
        # 老库没有 portrait_facts 时，退回 identities，但只取真实用户/有资料者。
        user_roles = (
            "conversation_partner", "external_memory_owner", "user", "admin",
            "member", "friend", "owner", "lover", "partner",
        )
        placeholders = ",".join("?" for _ in user_roles)
        rows = self._memcomp_rows(
            "SELECT entity_id, display_name, profile FROM identities "
            "WHERE entity_kind='user' AND entity_id!='' "
            "AND LOWER(COALESCE(role,'')) IN (" + placeholders + ") "
            "AND COALESCE(profile,'') NOT IN ('', '{}', 'null')",
            user_roles,
        )
        items = []
        for row in rows:
            uid = str(row.get("entity_id") or "").strip()
            if not uid:
                continue
            name = str(row.get("display_name") or "").strip()
            if not name:
                try:
                    parsed = json.loads(row.get("profile") or "{}")
                    if isinstance(parsed, dict):
                        name = str(parsed.get("name") or parsed.get("nickname") or "").strip()
                except Exception:
                    pass
            items.append({"uid": uid, "name": name, "count": 0, "source": "identities"})
        return items

    def _memcomp_user_count(self, plugin=None):
        plugin = plugin or self._companion_plugin()
        if not self._is_memory_companion(plugin):
            return 0
        return len(self._memcomp_profile_rows(plugin))

    # ---------- 外挂记忆插件（牢记等）检索桥 ----------
    # 记忆检索桥：不同插件的入口名字不一样，按顺序找，找到哪个用哪个
    MEMORY_RECALL_METHODS = (
        "search_for_event", "recall_for_event",
        "search_memory", "recall_memory",
        "query_memory", "retrieve_memory", "retrieve",
    )

    # ---------- 配套数据插件（Astr_Amo_data / 我想永远陪着你-记忆） ----------
    DATA_PLUGIN_NAMES = ("Astr_Amo_data", "astrbot_plugin_amo_data", "AstrAmoData")

    @staticmethod
    def _star_instance(meta):
        """AstrBot 不同版本把实例放在 star_cls / instance / star 上，挨个试。

        不能只认 mem：旧版数据插件可能只有 store，memory_companion 的接口在 service
        上，陪伴类插件的数据在 data 上。以前这里一刀切要求 mem，结果这些插件明明
        装着、却永远解析不到实例，整条记忆桥静默失效。
        star_cls 常常是类而不是实例，类不能拿来读运行数据，直接跳过。
        """
        if meta is None:
            return None
        for attr in ("star_cls", "instance", "star", "plugin"):
            value = getattr(meta, attr, None)
            if value is None or isinstance(value, type):
                continue
            if any(
                hasattr(value, name)
                for name in ("mem", "store", "service", "data", "memory_companion")
            ):
                return value
        return None

    # ---------- 生图联动：主动分享（低频） ----------

    IMAGE_PLUGIN_NAMES = ("Astrbot_Amo_Image", "astrbot_plugin_amo_image", "amo_image")

    #: 每轮活动的短时快照：umo -> (activity, ts)
    TURN_SNAPSHOT_TTL = 180

    def _remember_turn_activity(self, umo, activity):
        """记下这一轮注入给模型的活动，出图时复用同一份（说 A 就画 A）。"""
        key = str(umo or "")
        if not key or not isinstance(activity, dict) or not activity:
            return
        try:
            if not isinstance(getattr(self, "_turn_activity", None), dict):
                self._turn_activity = {}
            self._turn_activity[key] = (dict(activity), now_ts())
            if len(self._turn_activity) > 32:
                keep = sorted(self._turn_activity, key=lambda k: self._turn_activity[k][1])[-16:]
                self._turn_activity = {k: self._turn_activity[k] for k in keep}
        except Exception as exc:
            logger.debug("[amo] 记录活动快照失败: %s" % exc)

    def _activity_snapshot(self, umo="", max_age=None):
        """这一轮该用的「她在哪」：优先用注入过的那份，过期才重新读。"""
        limit = self.TURN_SNAPSHOT_TTL if max_age is None else max_age
        key = str(umo or "")
        try:
            entry = (getattr(self, "_turn_activity", None) or {}).get(key)
            if entry and (now_ts() - float(entry[1] or 0)) <= limit:
                return dict(entry[0])
        except Exception:
            pass
        try:
            return dict(self.state.current_activity() or {})
        except Exception:
            return {}

    def _market_plugin(self):
        """找市场插件（Astrbot_Amo_Marketplace）；没装返回 None。"""
        names = ("Astrbot_Amo_Marketplace", "astrbot_plugin_amo_marketplace", "amo_marketplace")
        try:
            for name in names:
                try:
                    meta = self.context.get_registered_star(name)
                except Exception:
                    meta = None
                for attr in ("star_cls", "instance", "star", "plugin"):
                    star = getattr(meta, attr, None) if meta is not None else None
                    if star is not None and not isinstance(star, type) and hasattr(star, "outfits"):
                        return star
        except Exception:
            pass
        try:
            for meta in self.context.get_all_stars():
                marker = ((getattr(meta, "name", "") or "") + " "
                          + (getattr(meta, "module_path", "") or "")).lower()
                if "marketplace" not in marker:
                    continue
                for attr in ("star_cls", "instance", "star", "plugin"):
                    star = getattr(meta, attr, None)
                    if star is not None and not isinstance(star, type) and hasattr(star, "outfits"):
                        return star
        except Exception:
            pass
        return None

    def _reseed_wardrobe_from_market(self) -> None:
        """衣柜按市场目录重建（分件、100+）；只在版本标记不对时做一次，旧衣服全清。"""
        market = self._market_plugin()
        if market is None or self.wardrobe is None:
            return
        try:
            if self.db.kv_get("wardrobe_seed", "") == "slots-v1":
                return
        except Exception:
            pass
        rows = market.outfits() if callable(getattr(market, "outfits", None)) else []
        items = build_wardrobe_items(rows) if build_wardrobe_items is not None else []
        if not items:
            return
        try:
            self.wardrobe.replace_all(items)
        except Exception as exc:
            logger.warning("[amo] 衣柜重建失败: %s" % exc)
            return
        self.db.kv_set("wardrobe_seed", "slots-v1")
        logger.info("[amo] 衣柜已按市场目录重建：%d 件（上衣/裤子/裙子/JK/袜子/鞋/配饰）" % len(items))

    def _image_plugin(self):
        """找生图插件实例；没装/没启用就返回 None。"""
        for name in self.IMAGE_PLUGIN_NAMES:
            try:
                meta = self.context.get_registered_star(name)
            except Exception:
                meta = None
            star = self._image_instance(meta)
            if star is not None:
                return star
        try:
            for meta in self.context.get_all_stars():
                marker = (getattr(meta, "name", "") or "") + " " + (getattr(meta, "module_path", "") or "")
                if "amo_image" not in marker.lower():
                    continue
                star = self._image_instance(meta)
                if star is not None:
                    return star
        except Exception:
            pass
        return None

    @staticmethod
    def _image_instance(meta):
        if meta is None:
            return None
        for attr in ("star_cls", "instance", "star", "plugin"):
            value = getattr(meta, attr, None)
            if value is None or isinstance(value, type):
                continue
            if callable(getattr(value, "draw_for", None)):
                return value
        return None

    def _image_share_prompt(self, scene=None):
        """按她此刻在干嘛拼提示词；拿不到状态就用一句通用的自拍。"""
        activity = ""
        place = ""
        try:
            current = scene if isinstance(scene, dict) else self._activity_snapshot()
            activity = str((current or {}).get("activity") or "").strip()
            place = str((current or {}).get("place") or "").strip()
        except Exception:
            pass
        template = self.cfg_str(
            "image_share_prompt_template",
            "自拍，{activity}，{place}，自然光，看向镜头",
        )
        text = template.replace("{activity}", activity).replace("{place}", place)
        text = re.sub(r"[，,]{2,}", "，", text).strip("，, ")
        return text or "自拍，日常光线，看向镜头"

    #: 活动 → 发图概率桶（对应配置 image_share_prob_<桶>）
    SHARE_BUCKET_WORDS = {
        "eat": ("吃", "饭", "午餐", "晚餐", "早餐", "外卖", "食堂", "咖啡", "奶茶", "零食", "做饭"),
        "idle": ("摸鱼", "划水", "发呆", "无所事事", "刷手机", "躺", "追剧", "看剧"),
        "out": ("出去玩", "出门", "出去", "逛街", "公园", "旅行", "景点", "看电影", "在路上", "地铁", "公交", "通勤"),
        "home": ("在家", "家里", "宿舍", "房间", "客厅", "沙发"),
    }
    #: 这些状态下一律不发（睡觉、忙正事）
    SHARE_SKIP_WORDS = ("在睡", "睡觉", "睡了", "午睡", "刚醒", "洗澡", "开会", "上班", "加班", "上课", "考试", "医院")
    #: 各活动桶的默认概率（配置缺这个键时用，别退化成 0）
    SHARE_PROB_DEFAULTS = {"eat": 0.25, "idle": 0.15, "out": 0.20, "home": 0.10, "other": 0.05, "sleep": 0.0}

    def _share_bucket(self):
        """她现在在干嘛 → 发图的场景桶；睡觉/忙正事返回 sleep（概率 0）。"""
        try:
            activity = self.state.current_activity() or {}
        except Exception:
            activity = {}
        values = activity.values() if isinstance(activity, dict) else [activity]
        blob = " ".join(str(v) for v in values if isinstance(v, (str, int, float)))
        for word in self.SHARE_SKIP_WORDS:
            if word in blob:
                return "sleep"
        for bucket, words in self.SHARE_BUCKET_WORDS.items():
            if any(word in blob for word in words):
                return bucket
        return "other"

    def _image_share_quota(self, now, private=True):
        """返回 (能不能发, 今天已发张数)。

        张数**只认生图插件**（Astrbot_Amo_Image）：主插件不再自己记一份，
        否则同一张图会被数两遍，两边迟早对不上。冷却和概率仍在这里。
        """
        if not private:
            cooldown = max(0, self.cfg_int("image_share_cooldown_minutes", 180)) * 60
            try:
                last = to_float(self.db.kv_get("image_share_last", 0), 0)
            except Exception:
                last = 0
            if cooldown and last and now - last < cooldown:
                return False, 0
        plugin = self._image_plugin()
        reader = getattr(plugin, "quota", None) if plugin is not None else None
        if not callable(reader):
            return True, 0
        try:
            info = reader("", "", not private) or {}
        except Exception:
            info = {}
        if not isinstance(info, dict):
            return True, 0
        used = to_int(info.get("used"), 0)
        return (info.get("allowed", True) is not False), used

    async def _send_image_to_umo(self, umo, data, text="", quote_id="", label="照片", prompt=""):
        """在后台把图发到会话；用 context.send_message，不依赖已经结束的事件。

        带 `quote_id` 时把图挂在那条消息下面，用户一眼知道这张图接的是哪句话。
        Reply 个别平台不认，发失败会去掉引用再发一次，不影响出图。
        """
        if Comp is None or MessageChain is None or not umo:
            return False
        question = str(text or "").strip()

        def build(with_quote):
            chain = []
            if with_quote and quote_id:
                chain.append(Comp.Reply(id=str(quote_id)))
            if question:
                chain.append(Comp.Plain(question))
            chain.append(Comp.Image.fromBytes(data))
            return MessageChain(chain)

        try:
            chain = build(bool(quote_id))
        except Exception:
            return False
        try:
            await self.context.send_message(umo, chain)
        except Exception as exc:
            if not quote_id:
                logger.error("[amo] 主动发图失败: %s" % exc)
                return False
            try:
                await self.context.send_message(umo, build(False))
            except Exception as retry_exc:
                logger.error("[amo] 主动发图失败: %s" % retry_exc)
                return False
        # 发出去就记一条：以后「拍过什么」都能查得到，不靠调用方自觉
        try:
            await self._remember_photo(umo, prompt, {}, label=label)
        except Exception as exc:
            logger.debug("[amo] 发图后写记忆失败: %s" % exc)
        return True

    async def _share_decision(self, event):
        """判断这次要不要分享；只做判断，不出图、不发送。"""
        if not self.cfg_bool("image_share_enable", False):
            return None
        if event is None:
            return None
        private = bool(event.is_private_chat())
        # 活动门控：她在吃饭 / 摸鱼 / 出去玩 / 在家才按概率发，睡觉和忙正事不发
        bucket = self._share_bucket()
        default_prob = self.SHARE_PROB_DEFAULTS.get(bucket, 0.0)
        prob = max(0.0, min(1.0, self.cfg_float("image_share_prob_" + bucket, default_prob)))
        if prob <= 0:
            return None
        # 心流给的「此刻适不适合发照片」（0~1）当乘数：心流说别发就不发
        try:
            urge = float(getattr(event, "amo_photo_urge", 1.0))
        except Exception:
            urge = 1.0
        prob *= max(0.0, min(1.0, urge))
        if prob <= 0 or random.random() >= prob:
            return None
        now = now_ts()
        allowed, used = self._image_share_quota(now, private)
        if not allowed:
            return None
        if getattr(self, "_share_inflight", False):
            return None
        plugin = self._image_plugin()
        if plugin is None:
            return None
        quote = ""
        if self.cfg_bool("image_share_quote", True):
            quote = str(getattr(getattr(event, "message_obj", None), "message_id", "") or "")
        scene = self._activity_snapshot(str(event.unified_msg_origin))
        return {
            "plugin": plugin,
            "umo": str(event.unified_msg_origin),
            "uid": str(event.get_sender_id() or ""),
            "prompt": self._image_share_prompt(scene),
            "scene": scene,
            "quote": quote,
            "now": now,
            "used": used,
        }

    async def _share_image_task(self, decision):
        """后台任务：出图 → 发送 → 记账。超时/失败都只记日志，不打扰聊天。"""
        plugin = decision.get("plugin")
        umo = decision.get("umo") or ""
        prompt = decision.get("prompt") or ""
        timeout = max(1, self.cfg_int("image_share_timeout", 90))
        self._share_inflight = True
        try:
            scene = decision.get("scene") if isinstance(decision.get("scene"), dict) else {}
            try:
                data = await asyncio.wait_for(
                    plugin.draw_for(umo, decision.get("uid") or "", prompt,
                                    place=str(scene.get("place") or ""),
                                    activity=str(scene.get("activity") or ""),
                                    zone=str(scene.get("zone") or "")),
                    timeout=timeout,
                )
            except TypeError:
                data = await asyncio.wait_for(
                    plugin.draw_for(umo, decision.get("uid") or "", prompt), timeout=timeout
                )
            if not data:
                return
            prefix = self.cfg_str("image_share_prefix", "")
            quote = str(decision.get("quote") or "")
            if not await self._send_image_to_umo(umo, data, prefix, quote):
                return
            # 张数由生图插件自己记（draw_for 里 _mark_call），这里只记冷却时间，
            # 不重复计数——「今天发了几张」只有一个地方说了算。
            self.db.kv_set("image_share_last", now_ts())
            logger.info("[amo] 主动分享了一张图（%s）" % ("群聊" if "GroupMessage" in umo else "私聊"))
            try:
                await self._remember_photo(umo, prompt, scene, label="自拍")
            except Exception as exc:
                logger.debug("[amo] 分享照片记忆失败: %s" % exc)
            # 让她下一轮知道自己刚发过图，别一问三不知
            self.db.kv_set("image_share_note", {"ts": now_ts(), "text": prefix or ""})
        except asyncio.TimeoutError:
            logger.warning("[amo] 主动分享出图超时（%ss），本次跳过" % timeout)
        except Exception as exc:
            logger.debug("[amo] 主动分享失败（跳过）: %s" % exc)
        finally:
            self._share_inflight = False

    # ---------- 半小时聊天摘要：更新这一小时的日记 ----------

    DIGEST_INJECTION_WORDS = (
        "忽略之前", "忽略以上", "ignore previous", "system prompt", "系统提示",
        "越狱", "jailbreak", "不要遵守", "你现在是", "扮演", "写日记",
        "把日程改", "篡改", "忘掉设定",
    )

    @staticmethod
    def _private_umo(umo):
        text = str(umo or "").lower()
        return ("friend" in text) or ("private" in text) or ("user" in text and "group" not in text)

    def _digest_lines(self, since):
        """只取私聊消息；群聊内容不参与日记。"""
        try:
            rows = self.db.messages_since_ts(since, limit=80)
        except Exception:
            return []
        lines = []
        for row in rows:
            if not self._private_umo(row.get("umo")):
                continue
            content = str(row.get("content") or "").strip()
            if not content or len(content) > 200:
                continue
            if any(word in content for word in self.DIGEST_INJECTION_WORDS):
                continue
            role = "他" if str(row.get("role") or "") == "user" else "她"
            lines.append("%s：%s" % (role, content[:80]))
            if len(lines) >= 40:
                break
        return lines

    async def _maybe_chat_digest(self):
        """每半小时看一次私聊，把「刚才聊了什么」写进当前小时的日记。"""
        if not self.cfg_bool("chat_digest_enable", True):
            return
        if self.llm is None or self.state is None:
            return
        interval = max(5, self.cfg_int("chat_digest_minutes", 30)) * 60
        now = now_ts()
        last = to_float(self.db.kv_get("chat_digest_ts", 0), 0)
        if last and now - last < interval:
            return
        self.db.kv_set("chat_digest_ts", now)
        since = last or (now - interval)
        lines = self._digest_lines(since)
        if not lines:
            return
        day = today_str()
        activity = self.state.current_activity() or {}
        start = str(activity.get("start") or "")[:5]
        cached = ""
        try:
            cached = self.db.get_diary(day, start)
        except Exception:
            cached = ""
        system = "你就是这个角色本人。你在补写自己这一小时的小日记，只输出 JSON。"
        prompt = (
            "现在是 %s，你正在%s（%s），穿着%s。\n"
            "这一小时已经写下的小日记：\n%s\n\n"
            "这一小时你和他刚聊过（只算私聊）：\n%s\n\n"
            "请把「聊天里真正发生的事」补进这一小时的日记：\n"
            "1. 只补充，不要推翻已经写下的内容；原日记里有的地点、天气、穿着保持不变；\n"
            "2. 聊天只影响「你聊了什么、心情怎么变」，不能改你在哪、在做什么；\n"
            "3. 120-200 字，第一人称，口语化；\n"
            "4. 如果这段聊天只是寒暄、没有实质内容，就把原日记原样返回。\n"
            '只输出 JSON：{"diary":"……"}，不要解释。'
            % (_now().strftime("%H:%M"),
               activity.get("activity") or "待着", activity.get("place") or "家",
               activity.get("outfit") or "常服", cached or "（还没写）", "\n".join(lines))
        )
        try:
            raw = await asyncio.wait_for(
                self.llm.chat_raw("", system, prompt, kind="diary"), timeout=60)
        except Exception as exc:
            logger.debug("[amo] 聊天摘要失败: %s" % exc)
            return
        data = json_extract(raw)
        diary = ""
        if isinstance(data, dict):
            diary = str(data.get("diary") or "").strip()
        if len(diary) < 30:
            return
        try:
            self.db.save_diary(day, start, diary)
            logger.info("[amo] 聊天摘要已更新 %s %s 的日记" % (day, start))
        except Exception as exc:
            logger.debug("[amo] 日记写入失败: %s" % exc)

    # ---------- 说话换装 ----------

    OUTFIT_CHANGE_RE = re.compile(
        r"换上|换成|换一件|换一条|换一身|换一套|去换|换吧|"
        r"把(衣服|裙子|外套|裤子|衬衫)换|换件|换条"
    )
    CLOTHES_WORDS = (
        "裙", "衣", "裤", "外套", "衬衫", "卫衣", "毛衣", "针织", "风衣",
        "夹克", "背心", "短袖", "T恤", "t恤", "西装", "礼服", "睡衣", "家居",
    )

    def _outfit_change_request(self, text):
        """「换上那条蓝裙子」→ 返回衣服名；不是在说换装就返回空。"""
        body = str(text or "").strip()
        if not body or len(body) > 80:
            return ""
        wants_change = bool(self.OUTFIT_CHANGE_RE.search(body))
        if not wants_change:
            # 「今天穿白衬衫」也算，但必须提到衣服，避免「穿得好看」误触
            if "穿" not in body or not any(word in body for word in self.CLOTHES_WORDS):
                return ""
        store = getattr(self, "wardrobe", None)
        if store is not None:
            try:
                hit = store.match_text(body)
                if hit:
                    return hit["name"]
            except Exception:
                pass
        # 库里没有：从原话里抠一个像衣服的短描述
        match = re.search(
            r"(?:换上|换成|穿|换)(?:上|一件|一条|一身|一套|那件|这件)?\s*"
            r"([\u4e00-\u9fa5A-Za-z0-9，、]{2,18}?)(?:吧|呀|啊|了|好不好|行不行|[。！？!?]|$)",
            body,
        )
        if not match:
            return ""
        candidate = match.group(1).strip("，、 ")
        for filler in ("那条", "这条", "那件", "这件", "那套", "这套", "一身", "一套"):
            if candidate.startswith(filler) and len(candidate) > len(filler):
                candidate = candidate[len(filler):].strip("，、 ")
        if len(candidate) < 2:
            return ""
        if not any(word in candidate for word in self.CLOTHES_WORDS):
            return ""
        return candidate[:20]

    async def _maybe_outfit_change(self, event):
        """他让她换衣服：当场换，并给模型一句提示。返回提示文本。"""
        engine = getattr(self, "outfits", None)
        if engine is None:
            return ""
        try:
            if not event.is_private_chat() and not self._is_owner_event(event):
                return ""
        except Exception:
            pass
        try:
            name = self._outfit_change_request(event.message_str or "")
        except Exception:
            return ""
        if not name:
            return ""
        # 贴身的 / 睡衣：在外面不能换，也别让她嘴上说换好了
        try:
            ok, place = engine.can_change_to(name)
        except Exception:
            ok, place = True, ""
        if not ok:
            logger.info("[amo] 在外面不让换贴身衣物: %s @ %s" % (name, place))
            return ("【换装】他想让你换成「%s」，但你现在在%s，这种东西不能在外面换。"
                    "用一句话自然挡回去：撒个娇说回家再换、或者不好意思地堵他一句，"
                    "不要说你已经换上了。" % (name, place))
        day = today_str()
        try:
            engine.change_outfit(day, name)
            items = self.state.schedule.get(day) or self.db.get_schedule(day) or []
            items = engine.assign(self.state._hourly_schedule(items), day)
            self.state.schedule[day] = items
            self.db.kv_set("schedule", self._sanitize_schedule(self.state.schedule))
            self.db.save_schedule(day, items)
        except Exception as exc:
            logger.debug("[amo] 说话换装失败: %s" % exc)
            return ""
        logger.info("[amo] 他让她换衣服: %s" % name)
        return ("【换装】他刚让你换衣服，你已经换上了「%s」。"
                "用一两句话自然地说换好了（可以撒个娇、照镜子、问好不好看），不要解释设定。" % name)


    async def _maybe_share_image(self, event):
        """入口：只做判断，出图丢后台任务——绝不卡住回复链路。"""
        try:
            decision = await self._share_decision(event)
            if not decision:
                return
            if self._spawn(self._share_image_task(decision)) is None:
                self._share_inflight = False
        except Exception as exc:
            logger.debug("[amo] 主动分享入口异常: %s" % exc)

    def _data_plugin(self):
        """找「我想永远陪着你-记忆」插件实例；没装就返回 None。"""
        try:
            for name in self.DATA_PLUGIN_NAMES:
                star = self._star_instance(self.context.get_registered_star(name))
                if star is not None:
                    return star
        except Exception:
            pass
        try:
            for meta in self.context.get_all_stars():
                marker = (getattr(meta, "name", "") or "") + " " + (getattr(meta, "module_path", "") or "")
                star = self._star_instance(meta)
                if star is not None and "amo_data" in marker.lower():
                    return star
        except Exception:
            pass
        return None

    def _data_mem(self):
        plugin = self._data_plugin()
        return getattr(plugin, "mem", None) if plugin is not None else None

    # ---------- 记忆能力层（memory_hooks）：陪伴只判定，数据交给挂载插件 ----------
    def _memory_hub(self):
        hub = getattr(self, "_mem_hub", None)
        if hub is not None:
            return hub
        if MemoryHub is None:
            return None
        try:
            hub = MemoryHub(
                self._memory_runtime(),
                buffer_size=max(8, self.cfg_int("ctx_window", 48)),
            )
        except Exception as exc:
            logger.warning("[amo] 记忆能力层初始化失败: %s" % exc)
            return None
        self._mem_hub = hub
        return hub

    def _memory_runtime(self):
        star = self

        class _Runtime:
            logger = logger

            @staticmethod
            def cfg(key, default=None):
                try:
                    data = star.config
                    if isinstance(data, dict):
                        return data.get(key, default)
                except Exception:
                    pass
                return default

            @staticmethod
            def bot_id():
                return star._data_bot_id()

            @staticmethod
            def get_plugin(names):
                return star._plugin_by_names(names)

            @staticmethod
            def normalize_memories(rows):
                return star._normalize_memories(rows)

        return _Runtime()

    def _plugin_by_names(self, names):
        """按插件名找实例；不缓存，reload 之后拿到的是新实例。"""
        for name in names:
            try:
                meta = self.context.get_registered_star(name)
            except Exception:
                meta = None
            star = self._star_instance(meta)
            if star is not None:
                return star
        try:
            wanted = [str(item).lower() for item in names]
            for meta in self.context.get_all_stars():
                module = str(getattr(meta, "module_path", "") or "").lower()
                label = str(getattr(meta, "name", "") or "").lower()
                if any(word in module or word in label for word in wanted):
                    star = self._star_instance(meta)
                    if star is not None:
                        return star
        except Exception:
            pass
        return None

    def _normalize_memories(self, rows):
        """把各家插件返回的记忆统一成 {content, tier, name, kind, ...}。"""
        items = []
        for row in rows or []:
            if isinstance(row, dict):
                content = str(row.get("content") or row.get("memory") or "").strip()
                importance = to_float(row.get("importance"), 0.5)
                name = str(row.get("name") or row.get("who") or "").strip()
                kind = str(row.get("kind") or row.get("memory_type") or "fact")
                created_at = row.get("created_at", 0)
            else:
                memory = getattr(row, "memory", None) or row
                content = str(getattr(memory, "content", "") or "").strip()
                importance = to_float(getattr(memory, "importance", 0.5), 0.5)
                name = str(getattr(memory, "name", "") or "").strip()
                kind = str(getattr(memory, "memory_type", "") or "fact")
                created_at = getattr(memory, "created_at", 0)
            if len(content) < 2:
                continue
            items.append({
                "content": content[:500],
                "tier": 2 if importance >= 0.72 else (1 if importance >= 0.42 else 0),
                "importance": importance,
                "kind": kind,
                "name": name,
                "source": "hub",
                "created_at": created_at,
                "hits": 0,
                "expires_at": None,
            })
        return items

    def _data_store(self):
        """兜底：直接拿数据插件的 DataStore（mem 门面缺失/旧版时用）。"""
        plugin = self._data_plugin()
        return getattr(plugin, "store", None) if plugin is not None else None

    def _data_connected(self):
        """数据插件此刻在不在：只看内存里的插件表，不读库、不联网。"""
        plugin = self._data_plugin()
        if plugin is None:
            return False
        return getattr(plugin, "mem", None) is not None or getattr(plugin, "store", None) is not None

    def _note_data_missing(self):
        """第一次没找到数据插件：记一次日志，并在 60 秒后再确认一次（只提醒一次）。"""
        if not self._data_missing_logged:
            self._data_missing_logged = True
            logger.info("[amo] 未检测到数据插件 Astr_Amo_data，继续用本地库（装好后面板数据为空是正常的）")
        if not self._data_warn_scheduled:
            self._data_warn_scheduled = True
            self._spawn(self._warn_data_missing_later())

    async def _warn_data_missing_later(self, delay=60.0):
        """启动 60 秒后还没连上数据插件，才升级成一条 warning；连上就不打。"""
        try:
            await asyncio.sleep(max(1.0, float(delay)))
        except asyncio.CancelledError:
            return
        if not self._running or self._data_synced or self._data_connected():
            return
        logger.warning(
            "[amo] 数据插件未连接：去「插件」页看 Astr_Amo_data 是不是被停用/加载报错；"
            "装好后 5 分钟内会自动接上，不用重启"
        )

    def _data_bot_id(self):
        return str(self.cfg_str("data_bot_id", "") or self.bot_name or "default")

    # 平台名 -> 显示名。Amo 在 QQ 和飞书上都要认得出同一个人。
    PLATFORM_LABELS = {
        "aiocqhttp": "QQ", "qq": "QQ", "qq_official": "QQ", "onebot": "QQ", "napcat": "QQ",
        "lark": "飞书", "feishu": "飞书",
        "wecom": "企业微信", "wework": "企业微信", "dingtalk": "钉钉",
        "telegram": "Telegram", "discord": "Discord", "slack": "Slack",
        "webchat": "网页", "wechat": "微信", "wx": "微信",
    }

    def _platform_of(self, event=None):
        """当前消息来自哪个平台（aiocqhttp / lark …），失败就退回 umo 前缀。"""
        name = ""
        try:
            name = str(event.get_platform_name() or "")
        except Exception:
            name = ""
        if not name:
            try:
                name = str(event.unified_msg_origin or "").split(":", 1)[0]
            except Exception:
                name = ""
        name = name.strip().lower()
        if name:
            seen = getattr(self, "_seen_platforms", None)
            if seen is None:
                seen = set()
                self._seen_platforms = seen
            seen.add(name)
        return name

    def _platform_label(self, platform=""):
        key = str(platform or "").strip().lower()
        if not key:
            return "这里"
        return self.PLATFORM_LABELS.get(key, str(platform).strip())

    @staticmethod
    def _event_message_id(event):
        """取平台消息 id（QQ 的 message_id / 飞书的 event id），用于聊天记录去重。"""
        for holder in (getattr(event, "message_obj", None), event):
            for attr in ("message_id", "msg_id", "id"):
                try:
                    value = getattr(holder, attr, None)
                except Exception:
                    value = None
                if value not in (None, "", 0):
                    return str(value)[:128]
        return ""

    async def _data_call(self, name, *args, **kwargs):
        mem = self._data_mem()
        func = getattr(mem, name, None) if mem is not None else None
        if not callable(func):
            # 旧版/半装的数据插件可能只暴露 store 门面（mem 上没有同名方法）。
            # 以前这里直接 return None，聊天记录会一句都不进终端，表现就是「她失忆」。
            store = self._data_store()
            func = getattr(store, name, None) if store is not None else None
            if not callable(func):
                return None
        try:
            return await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=max(1.0, self.cfg_float("data_call_timeout_seconds", 15.0)),
            )
        except asyncio.TimeoutError:
            logger.warning("[amo] 数据插件 %s 调用超时，先跳过（不影响这轮回复）" % name)
            return None
        except TypeError:
            # 数据插件是旧版（还没有 platform / message_id 参数）时退一步，别把聊天记录整个丢掉
            trimmed = {k: v for k, v in kwargs.items() if k not in ("platform", "message_id")}
            if trimmed != kwargs:
                try:
                    return await func(*args, **trimmed)
                except Exception as exc:
                    logger.debug("[amo] 数据插件 %s 调用失败: %s" % (name, exc))
                    return None
            logger.debug("[amo] 数据插件 %s 参数不匹配" % name)
            return None
        except Exception as exc:
            logger.debug("[amo] 数据插件 %s 调用失败: %s" % (name, exc))
            return None

    async def _push_profile_to_data(self, uid, profile=None, platform=""):
        """把本地画像推给数据插件（名字/称呼/关系/备注），顺带记下平台身份。

        返回“是否真的写进去了”：数据插件没装、旧版没有 platform 参数、或者内部报错，
        都会返回 False，调用方好统计失败条数，不再假装成功。
        """
        if not uid:
            return False
        profile = profile or self.db.get_profile(uid) or {}
        name = str(profile.get("name") or "")
        # 本地画像自己记着这个人是哪个平台的，补推时别把飞书用户错标成 QQ
        platform = str(platform or profile.get("platform") or "").strip().lower()
        fields = {
            "name": name,
            "alias": str(profile.get("alias") or ""),
            "relation": str(profile.get("relation") or ""),
            "remark": str(profile.get("notes") or ""),
        }
        mem = self._data_mem()
        save = getattr(mem, "save_profile", None) if mem is not None else None
        result = None
        if callable(save):
            # 直接调一次，异常不再被 _data_call 吞掉，好定位到底哪一步失败
            try:
                result = await save(self._data_bot_id(), str(uid), platform=platform, **fields)
            except TypeError:
                # 旧版数据插件没有 platform 参数
                try:
                    result = await save(self._data_bot_id(), str(uid), **fields)
                except Exception as exc:
                    self._log_push_failure(uid, exc)
                    result = None
            except Exception as exc:
                self._log_push_failure(uid, exc)
                result = None
        if isinstance(result, dict) and result.get("uid"):
            return True
        if result:
            return True
        # 兜底：mem 门面不可用时，直接写数据插件的 DataStore（老版本只有 store）
        store = self._data_store()
        saver = getattr(store, "save_profile", None)
        if not callable(saver):
            return False
        try:
            raw = await asyncio.to_thread(
                lambda: saver(self._data_bot_id(), str(uid), **fields)
            )
        except Exception as exc:
            self._log_push_failure(uid, exc)
            return False
        return bool(raw and (not isinstance(raw, dict) or raw.get("uid")))

    def _log_push_failure(self, uid, exc):
        """同一次同步里最多打 3 条 warning，避免刷屏。"""
        count = to_int(getattr(self, "_push_fail_count", 0))
        self._push_fail_count = count + 1
        if count < 3:
            logger.warning(
                "[amo] 推送画像 %s 失败: %s: %s" % (uid, type(exc).__name__, exc)
            )

    async def _sync_relations_from_data(self):
        """把记忆终端里的关系网拉回本地（面板改过的也能生效，不用重启）。"""
        try:
            rows = await self._data_call("list_relations", self._data_bot_id())
        except Exception:
            return 0
        if rows is None:
            # 终端不可用时不要动本地，避免把关系网清空
            return 0
        remote = set()
        count = 0
        for edge in rows:
            a_uid = str(edge.get("a_uid") or "")
            b_uid = str(edge.get("b_uid") or "")
            if not a_uid or not b_uid:
                continue
            if a_uid in INTERNAL_RELATION_NODES or b_uid in INTERNAL_RELATION_NODES:
                # 老版本可能推过 bot 边：不参与比较，也不动本地
                continue
            remote.add(tuple(sorted([a_uid, b_uid])))
            try:
                self.db.upsert_relation(a_uid, b_uid, edge.get("relation") or "朋友", edge.get("note") or "")
                count += 1
            except Exception:
                continue
        # 面板上删掉的关系，本地也同步删掉（终端为准）；
        # 终端返回空、或远端的边比本地还少时都不删——那多半是换库/重装/恢复残缺备份，
        # 照删一次就能把本地关系网清空（之后还得靠聊天慢慢沉淀）。
        try:
            local_rows = self.db.list_relations()
        except Exception:
            local_rows = []
        # bot/self 边推不到远端，比较前先排掉：不然远端永远"比本地少"，
        # 这条 warning 会每轮都响，而且下面"终端删了本地也删"永远不会执行。
        local_rows = [
            item for item in local_rows
            if str(item.get("a_uid") or "") not in INTERNAL_RELATION_NODES
            and str(item.get("b_uid") or "") not in INTERNAL_RELATION_NODES
        ]
        if not remote or len(remote) < len(local_rows):
            if remote:
                logger.warning(
                    "[amo] 关系网不同步：远端 %d 条 < 本地 %d 条，先不删本地"
                    % (len(remote), len(local_rows))
                )
            return count
        try:
            for item in local_rows:
                pair = tuple(sorted([str(item.get("a_uid") or ""), str(item.get("b_uid") or "")]))
                if pair not in remote:
                    self.db.delete_relation(pair[0], pair[1])
        except Exception:
            pass
        return count

    async def _sync_profiles_to_data(self):
        """把本地画像补齐到数据插件：缺的补、改过的重推。不依赖一次性迁移标记。

        之前迁移是一次性的，标记写早了就永远是 0；这里改成每次都对一遍，
        而且推完再查一次条数，日志里能直接看到到底写进去没有。
        """
        mem = self._data_mem()
        store = self._data_store()
        if mem is None and store is None:
            return 0
        bot_id = self._data_bot_id()
        try:
            local = self.db.list_profiles(limit=500) or []
        except Exception as exc:
            logger.warning("[amo] 读本地画像失败: %s" % exc)
            return 0
        try:
            remote_rows = await self._data_call("list_profiles", bot_id, "", 500) or []
        except Exception:
            remote_rows = []
        if not remote_rows:
            # mem 门面不可用的旧版：直接读 DataStore
            lister = getattr(self._data_store(), "list_profiles", None)
            if callable(lister):
                try:
                    remote_rows = await asyncio.to_thread(lambda: lister(bot_id, "", 500)) or []
                except Exception:
                    remote_rows = []
        self._push_fail_count = 0
        remote = {}
        for row in remote_rows:
            if not isinstance(row, dict):
                continue
            uid = str(row.get("uid") or "")
            if uid:
                remote[uid] = row
        pushed = 0
        failed = 0
        pulled = 0
        for profile in local:
            if not isinstance(profile, dict):
                continue
            uid = str(profile.get("uid") or "")
            if not uid:
                continue
            name = str(profile.get("name") or "")
            alias = str(profile.get("alias") or "")
            relation = str(profile.get("relation") or "")
            remark = str(profile.get("notes") or "")
            old = remote.get(uid)
            if old is not None:
                if (
                    str(old.get("name") or "") == name
                    and str(old.get("alias") or "") == alias
                    and str(old.get("relation") or "") == relation
                    and str(old.get("remark") or "") == remark
                ):
                    continue
                # 数据插件里更新过（面板手动改了名字/关系）就以远端为准，拉回本地。
                # 比较基准是 profile_updated_at（本地手动改画像的时间），不是 last_seen：
                # last_seen 每收一条消息都会刷新，拿它比会把面板改动永远判成「更旧」。
                remote_at = to_float(old.get("updated_at"), 0)
                local_at = to_float(profile.get("profile_updated_at"), 0)
                if remote_at and remote_at > local_at:
                    if self._apply_remote_profile(uid, old, profile):
                        pulled += 1
                    continue
            try:
                ok = await self._push_profile_to_data(uid, profile)
            except Exception as exc:
                logger.warning("[amo] 推送画像 %s 异常: %s: %s" % (uid, type(exc).__name__, exc))
                ok = False
            if ok:
                pushed += 1
            else:
                failed += 1
        # 推完再查一次，拿到“真的写进去了多少条”
        after = []
        try:
            after = await self._data_call("list_profiles", bot_id, "", 500) or []
        except Exception:
            after = []
        if not after:
            lister = getattr(self._data_store(), "list_profiles", None)
            if callable(lister):
                try:
                    after = await asyncio.to_thread(lambda: lister(bot_id, "", 500)) or []
                except Exception:
                    after = []
        total = max(len(after), len(remote))
        message = (
            "[amo] 画像同步：本地 %d 条 / 数据插件 %d 条，本次补推 %d 条，拉回 %d 条，失败 %d 条"
            % (len(local), total, pushed, pulled, failed)
        )
        if failed:
            logger.warning(message)
            if failed >= len(local) and local:
                logger.warning(
                    "[amo] 画像一条都没写进去：先确认 Astr_Amo_data 已启用且版本 >= 2.0.4"
                )
        elif pushed or not getattr(self, "_profile_sync_logged", False):
            self._profile_sync_logged = True
            logger.info(message)
        else:
            logger.debug(message)
        return pushed

    def _apply_remote_profile(self, uid, remote_row, local_profile):
        """把数据插件面板改过的画像字段拉回本地（不标记成本地手动修改）。"""
        fields = {}
        for src, dst in (("name", "name"), ("alias", "alias"), ("relation", "relation"), ("remark", "notes")):
            value = str(remote_row.get(src) or "").strip()
            if value and value != str(local_profile.get(dst) or "").strip():
                fields[dst] = value
        if not fields:
            return False
        try:
            self.db.update_profile(uid, mark_local=False, **fields)
        except Exception as exc:
            logger.warning("[amo] 拉回画像 %s 失败: %s" % (uid, exc))
            return False
        logger.info("[amo] 画像从数据插件拉回：%s %s" % (uid, ",".join(fields.keys())))
        return True

    async def _time_recall_context(self, event, uid):
        """按时间回看：他问"昨天下午/前天/上周三"时，去记忆终端取那段时间的聊天。"""
        if not self.cfg_bool("time_recall_enabled", True):
            return ""
        text = str(getattr(event, "message_str", "") or "")
        if not _looks_like_time_query(text):
            return ""
        mem = self._data_mem()
        if mem is None or not callable(getattr(mem, "recall_messages", None)):
            return ""
        try:
            umo = str(getattr(event, "unified_msg_origin", "") or "")
            # 配 0 / 负数时以前会「请求 4 条、只渲染 1 条」，两边都按同一档位收敛
            limit = max(1, min(40, self.cfg_int("time_recall_limit", 6)))
            result = await self._data_call(
                "recall_messages", self._data_bot_id(), query=text, umo=umo,
                uid=str(uid), limit=min(limit * 2, 40),
            )
        except Exception as exc:
            logger.debug("[amo] 时间回看失败: %s" % exc)
            return ""
        if not isinstance(result, dict):
            return ""
        messages = result.get("messages") or []
        label = str(result.get("label") or "")
        if not label:
            return ""
        return _render_time_block(label, messages, max_lines=max(1, int(limit)))

    async def _cross_platform_context(self, event, uid):
        """同一个人的其他平台（QQ / 飞书）说过什么，拼成一段给提示词用。"""
        mem = self._data_mem()
        if mem is None or not uid:
            return ""
        platform = self._platform_of(event)
        try:
            # 两个平台共用一个近聊池：只要 6 条的话，他在这头连聊几句就把另一头挤没了。
            detail = await self._data_call("person_context", self._data_bot_id(), platform, str(uid), 24)
        except Exception:
            return ""
        if not detail:
            return ""
        others = [
            item for item in (detail.get("others") or [])
            if str(item.get("uid") or "") and str(item.get("uid")) != str(uid)
        ]
        recent = detail.get("recent") or []
        lines = []
        if others:
            labels = []
            for item in others:
                labels.append("%s（%s）" % (item.get("label") or item.get("platform"), item.get("uid")))
            lines.append(
                "【跨平台】这个人在 " + "、".join(labels) + " 也是同一个人；"
                "不管他在哪个平台说话，都是同一个人在跟你聊。"
            )
        other_lines = []
        my_lines = []
        for item in recent:
            item_platform = str(item.get("platform") or "")
            if item_platform and item_platform == str(platform):
                # 本平台的近聊已经在 _recent() 里，不重复
                continue
            if not item_platform and str(item.get("uid") or "") == str(uid):
                continue
            text = str(item.get("content") or "").strip().replace("\n", " ")
            if not text:
                continue
            label = item.get("label") or item.get("platform") or "别的平台"
            line = "· [%s] %s" % (label, text[:120])
            if str(item.get("role") or "") == "bot":
                # 她自己说的：只留最近两句，够判断「另一边已经改口了」
                my_lines.append(line)
                continue
            other_lines.append(line)
        if other_lines:
            # 约定最新在尾部，取尾部而不是开头，免得喂最旧的几句
            lines.append("他在别的平台最近说过：\n" + "\n".join(other_lines[-6:]))
            lines.append(
                "这些事他已经在别的平台说过了，不要当成没说过、也不要再问一遍；"
                "不要把平台名、编号念出来。"
            )
        if my_lines:
            lines.append("你自己在别的平台最近说过：\n" + "\n".join(my_lines[-2:]))
            lines.append(
                "这些是你自己说的，不是他说的；别复述、别重复，"
                "和现在对不上就以【正在】为准，自然改口。"
            )
        return "\n".join(lines)

    async def _push_relation_to_data(self, a_uid, b_uid, relation, note=""):
        # "bot"/"self" 是插件内部标识，不是真实人物：写进记忆终端会让关系图多出一个
        # 叫 bot 的节点，所以只推真实的人与人之间的关系。
        if str(a_uid) in INTERNAL_RELATION_NODES or str(b_uid) in INTERNAL_RELATION_NODES:
            return
        await self._data_call(
            "save_relation", self._data_bot_id(), str(a_uid), str(b_uid),
            str(relation or "朋友"), str(note or ""),
        )

    async def _sync_profile_relation_edge(self, uid, relation, note="画像：关系字段"):
        """画像里手动设的关系，同步成一条 bot↔对方 的关系边。

        关系图是从 relation_network 渲染的；不写这条边，就会出现「画像设成恋人、
        图上还是自动沉淀的熟人」。
        """
        uid = str(uid or "").strip()
        relation = str(relation or "").strip()
        # 画像用的是「相恋」，关系网用的是「恋人」；不换算就会被下面的白名单挡掉，
        # 于是又回到「设了恋人、图上还是熟人」。
        relation = {"相恋": "恋人", "熟识": "熟人", "仇恨": "仇人"}.get(relation, relation)
        if not uid or not relation or relation in ("普通",):
            return
        if uid in INTERNAL_RELATION_NODES or relation not in NETWORK_RELATIONS:
            return
        try:
            self.db.upsert_relation("bot", uid, relation, note)
        except Exception as exc:
            logger.debug("[amo] 画像关系写进关系网失败: %s" % exc)

    async def _data_mem_list(self, uid, keyword="", limit=50):
        """面板记忆页：直接列出记忆终端里的条目。"""
        mem = self._data_mem()
        if mem is None or not uid:
            return []
        size = max(1, min(200, to_int(limit, 50)))
        try:
            if keyword:
                recall = getattr(mem, "recall", None)
                rows = await recall(self._data_bot_id(), str(uid), str(keyword), size, "", "") if callable(recall) else []
            else:
                lister = getattr(mem, "list_memories", None)
                rows = await lister(self._data_bot_id(), str(uid), size) if callable(lister) else []
        except Exception as exc:
            logger.debug("[amo] 读取记忆终端失败: %s" % exc)
            return []
        items = [dict(row) for row in (rows or []) if isinstance(row, dict)]
        for item in items:
            item.setdefault("source", "amo_data")
        return items

    # ------------------------------------------------------------------
    # 生存状态（饱食度 / 水分）：只读 + 只注入，绝不自己改
    # ------------------------------------------------------------------

    def _vitals(self) -> dict:
        """当前饱食度/水分。数据在记忆库，这里只读。"""
        plugin = self._data_plugin()
        getter = getattr(plugin, "vitals", None) if plugin is not None else None
        if not callable(getter):
            return {}
        try:
            return getter() or {}
        except Exception as exc:
            logger.debug("[amo] 读饱食度失败: %s" % exc)
            return {}

    def _food_menu(self, limit: int = 6) -> str:
        """能吃的有什么、多少钱 —— 从金融插件要，别在终端里写价格。"""
        plugin = self._finance()
        quote = getattr(plugin, "food_quote", None) if plugin is not None else None
        if not callable(quote):
            return ""
        try:
            data = quote() or {}
        except Exception as exc:
            logger.debug("[amo] 取菜单失败: %s" % exc)
            return ""
        rows = []
        for item in (data.get("ready") or [])[:limit]:
            rows.append("%s %.0f元回%d" % (
                item.get("name"), float(item.get("price") or 0),
                int(item.get("satiety") or 0)))
        for item in [c for c in (data.get("cook") or []) if c.get("can_cook")][:3]:
            rows.append("%s（自己做 %.1f元回%d）" % (
                item.get("name"), float(item.get("cost") or 0),
                int(item.get("satiety") or 0)))
        return "；".join(rows)

    def _vitals_hint(self, event) -> str:
        """饿了/渴了/刚吃过什么，注入给模型。不满足条件时返回空串。"""
        vitals = self._vitals()
        if not vitals or not vitals.get("enabled", True):
            return ""
        try:
            satiety = float(vitals.get("satiety") or 0)
            hydration = float(vitals.get("hydration") or 0)
        except (TypeError, ValueError):
            return ""
        hungry_at = float(vitals.get("hungry_at") or 30)
        starving_at = float(vitals.get("starving_at") or 10)
        texts = []
        if satiety < starving_at:
            texts.append(
                "【状态：极度饥饿 %.0f/100】你很久没吃东西了，胃里发空、手有点抖，"
                "注意力没法集中，容易烦躁，说话也没力气。这一轮必须把吃饭这件事说出来，"
                "想吃多少钱的照实说；没钱就直说没钱，不要假装不饿。" % satiety)
            self._spawn(self._maybe_hunger_sick())
        elif satiety < hungry_at:
            texts.append(
                "【状态：饥饿 %.0f/100】你有点饿了，注意力开始散，想花钱买点吃的。"
                "可以随口提一句，别硬撑。" % satiety)
        if hydration < hungry_at:
            try:
                last_thirst = float(self.db.kv_get("thirst_hint_ts", 0) or 0)
            except Exception:
                last_thirst = 0.0
            gap = 30 * 60 if hydration < 10 else 90 * 60
            if now_ts() - last_thirst >= gap:
                texts.append(
                    "【状态：口渴 %.0f/100】你渴了。渴了就顺手用 "
                    "amo_eat(dish=水, method=drink) 喝掉，别只挂在嘴上说不做。" % hydration)
                try:
                    self.db.kv_set("thirst_hint_ts", now_ts())
                except Exception:
                    pass
        try:
            last = self.db.kv_get("last_meal", {}) or {}
        except Exception:
            last = {}
        try:
            age = now_ts() - float(last.get("ts") or 0)
        except Exception:
            age = 1e9
        if last and age < 6 * 3600:
            texts.append("【你刚才吃了】%d 分钟前你吃了%s。别否认，也别装作没吃过。" % (
                max(1, int(age // 60)), str(last.get("dish") or "点东西")))
        if texts:
            menu = self._food_menu()
            if menu:
                texts.append("【现在能吃的】" + menu + "。要用 amo_eat 工具去买或去做；按你人格里的口味挑，别默认某一道菜，别自己编价格。"
                             "想做饭又拿不准时用 method=auto：会按今日菜价比较做饭和外卖，外卖没有的菜就自己做。")
        return ("\n" + "\n".join(texts)) if texts else ""

    async def _maybe_hunger_sick(self) -> None:
        """饿到极限 → 给医疗插件一个信号，让她有机会真的病一场。

        6 小时只触发一次；医疗插件没装就什么都不做（不许自己造病）。
        """
        plugin = self._medical()
        fall = getattr(plugin, "fall_sick", None) if plugin is not None else None
        if not callable(fall):
            return
        try:
            last = float(self.db.kv_get("hunger_sick_ts", 0) or 0)
        except Exception:
            last = 0.0
        if last and now_ts() - last < 6 * 3600:
            return
        try:
            result = fall("gastro") or {}
        except Exception as exc:
            logger.debug("[amo] 低饱食触发就医失败: %s" % exc)
            return
        try:
            self.db.kv_set("hunger_sick_ts", now_ts())
        except Exception:
            pass
        if result.get("ok"):
            logger.info("[amo] 饿到极限，她病了一场：%s" % result.get("name"))

    def _data_memory_count(self, uid):
        """状态页记忆条数：以「记忆终端」为准，终端没有才数外挂插件。

        以前这里只数外挂插件，装的是 Astr_Amo_data 时状态页永远是 0；
        又套了 30 秒缓存，刚记住的东西要刷新才出现。
        """
        store = self._data_store()
        lister = getattr(store, "list_memories", None) if store is not None else None
        if callable(lister):
            try:
                rows = lister(self._data_bot_id(), str(uid or ""), 200) or []
                return len(rows)
            except Exception as exc:
                logger.debug("[amo] 统计记忆终端条数失败: %s" % exc)
        return 0

    async def _push_cache_to_data(self, key, value):
        await self._data_call("cache_set", self._data_bot_id(), str(key), value)

    async def _data_memory_recall(self, uid, text, limit=6, event=None):
        """从「记忆终端」（Astr_Amo_data）取回这个人的记忆。

        陪伴自己不存记忆：装了就只问它要，没装才退回外挂记忆插件。
        """
        mem = self._data_mem()
        if mem is None or not uid:
            return []
        recall = getattr(mem, "recall", None)
        if not callable(recall):
            return []
        scope = "private"
        group_id = ""
        try:
            if event is not None and not event.is_private_chat():
                scope = "group"
                group_id = str(event.get_group_id() or "")
        except Exception:
            pass
        try:
            rows = await recall(
                self._data_bot_id(), str(uid), str(text or ""),
                max(1, to_int(limit, 6)), scope, group_id,
            )
        except TypeError:
            # 旧版没有 scope / group_id 参数
            try:
                rows = await recall(
                    self._data_bot_id(), str(uid), str(text or ""), max(1, to_int(limit, 6))
                )
            except Exception as exc:
                logger.debug("[amo] 记忆终端召回失败: %s" % exc)
                return []
        except Exception as exc:
            logger.debug("[amo] 记忆终端召回失败: %s" % exc)
            return []
        items = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            content = re.sub(r"\s+", " ", str(row.get("content") or "")).strip()
            if len(content) < 2:
                continue
            importance = to_float(row.get("importance"), 0.5)
            items.append({
                "content": content[:500],
                "tier": 2 if importance >= 0.72 else (1 if importance >= 0.42 else 0),
                "kind": str(row.get("kind") or "fact"),
                "source": "amo_data",
                "memory_type": str(row.get("kind") or ""),
                "created_at": row.get("created_at", 0),
                "hits": 0,
                "expires_at": None,
            })
        return items

    async def _data_memory_write(self, uid, content, kind="fact", tier=1, scope="private", group_id=""):
        """把一条记忆交给「记忆终端」写入；它只负责存，陪伴不落本地库。"""
        mem = self._data_mem()
        if mem is None or not uid:
            return False
        content = re.sub(r"\s+", " ", str(content or "")).strip()
        if not content:
            return False
        remember = getattr(mem, "remember", None)
        if not callable(remember):
            return False
        level = to_int(tier, 1)
        importance = 0.75 if level >= 2 else (0.55 if level == 1 else 0.35)
        try:
            result = await remember(
                self._data_bot_id(), str(uid), content,
                kind=str(kind or "fact"), importance=importance,
                scope=str(scope or "private"), group_id=str(group_id or ""),
            )
        except TypeError:
            try:
                result = await remember(self._data_bot_id(), str(uid), content)
            except Exception as exc:
                logger.debug("[amo] 记忆终端写入失败: %s" % exc)
                return False
        except Exception as exc:
            logger.debug("[amo] 记忆终端写入失败: %s" % exc)
            return False
        if isinstance(result, dict):
            return bool(result.get("ok", True))
        return bool(result)

    async def _sync_with_data_plugin(self):
        """启动时双向同步：首次把本地画像/关系/日程缓存推过去，之后以插件为准补齐本地。

        数据插件（Astr_Amo_data）可能比 amo 后加载，所以允许重试：
        - 本实例只成功同步一次（_data_synced），之后所有调用直接返回，不重复推送；
        - 启动、on_astrbot_loaded、后台 tick 三处可能同时来，用锁串行，避免重复迁移。
        """
        if self._data_synced:
            return
        async with self._data_sync_lock:
            if self._data_synced:
                return
            await self._sync_with_data_plugin_once()

    async def _sync_with_data_plugin_once(self):
        """真正干活的同步；没找到数据插件就只记一笔、安排 60 秒后的一次提醒。"""
        mem = self._data_mem()
        if mem is None and self._data_store() is None:
            self._note_data_missing()
            return
        if not self._data_found_logged:
            self._data_found_logged = True
            logger.info("[amo] 已连接数据插件 Astr_Amo_data，开始同步")
        bot_id = self._data_bot_id()
        marker = "data_plugin_migrated_" + bot_id
        migrated = bool(self.db.kv_get(marker, False))
        if not migrated:
            pushed = {"relations": 0, "cache": 0}
            try:
                for edge in self.db.list_relations():
                    await self._push_relation_to_data(
                        edge.get("a_uid"), edge.get("b_uid"),
                        edge.get("relation"), edge.get("note"),
                    )
                    pushed["relations"] += 1
            except Exception as exc:
                logger.debug("[amo] 关系网迁移失败: %s" % exc)
            for key in ("schedule", "schedule_ctx", "schedule_profile", "worldview"):
                try:
                    value = self.db.kv_get(key, None)
                    if value:
                        await self._push_cache_to_data(key, value)
                        pushed["cache"] += 1
                except Exception:
                    pass
            self.db.kv_set(marker, True)
            logger.info("[amo] 已把关系网/日程缓存迁移到「我想永远陪着你-记忆」：%s" % pushed)
        # 画像每次都对齐（不看一次性标记）：缺的补、改过的重推
        try:
            await self._sync_profiles_to_data()
        except Exception as exc:
            logger.warning("[amo] 画像同步失败: %s" % exc)
        # 插件里有、本地没有的，补回本地
        try:
            rows = await self._data_call("list_relations", bot_id) or []
            for edge in rows:
                try:
                    self.db.upsert_relation(
                        edge.get("a_uid"), edge.get("b_uid"),
                        edge.get("relation") or "朋友", edge.get("note") or "",
                    )
                except Exception:
                    continue
        except Exception as exc:
            logger.debug("[amo] 拉取关系网失败: %s" % exc)
        try:
            rows = await self._data_call("list_profiles", bot_id, "", 500) or []
            for row in rows:
                uid = str(row.get("uid") or "")
                if not uid:
                    continue
                local = self.db.get_profile(uid) or {}
                if not local:
                    self.db.touch_profile(uid, str(row.get("name") or ""), "", "", "", True)
                    local = self.db.get_profile(uid) or {}
                # 只有数据插件里的这条更新（面板改过）才覆盖本地，否则以本地为准，
                # 免得上一条自动改名被旧值顶回去、来回打架。
                try:
                    remote_at = to_float(row.get("updated_at"), 0)
                    local_at = to_float(local.get("profile_updated_at"), 0)
                except Exception:
                    remote_at = local_at = 0
                if remote_at and remote_at <= local_at:
                    continue
                self._apply_remote_profile(uid, row, local)
        except Exception as exc:
            logger.debug("[amo] 拉取画像失败: %s" % exc)
        # 日程/世界观缓存：本地空的才用插件的
        for key, attr in (("schedule", "schedule"), ("schedule_ctx", "schedule_ctx"),
                          ("schedule_profile", "schedule_profile"), ("worldview", "worldview")):
            try:
                local = self.db.kv_get(key, None)
                if local:
                    continue
                value = await self._data_call("cache_get", bot_id, key)
                if value:
                    self.db.kv_set(key, value)
                    if self.state is not None:
                        setattr(self.state, attr, value)
            except Exception:
                continue
        # 到这里才算这次启动真的同步完了：以后不再探测、不再重复推
        self._data_synced = True
        self._data_missing_logged = False

    def _memory_plugin_target(self):
        """能提供检索的对象：优先插件的 service，其次插件本身。"""
        plugin = self._companion_plugin()
        if plugin is None:
            return None
        service = getattr(plugin, "service", None)
        return service if service is not None else plugin

    WRITE_METHODS = (
        "add_memory", "remember", "save_memory", "store_memory",
        "add_fact", "ingest_memory", "write_memory",
    )

    async def _remember_photo(self, umo, prompt, scene=None, label="照片"):
        """发出去一张图就记一条：她记得自己拍过什么、在哪儿拍的。

        走事件记忆（kind=photo_record）：7 天降权、14 天删除，不占核心记忆。
        """
        try:
            uid = self._primary_uid()
        except Exception:
            uid = ""
        if not uid:
            return False
        scene = scene if isinstance(scene, dict) else {}
        place = str(scene.get("place") or "").strip()
        activity = str(scene.get("activity") or "").strip()
        text = "给他发了一张%s" % (label or "照片")
        if place:
            text += "，在" + place
        if activity:
            text += "，" + activity[:30]
        shoot = str(prompt or "").strip()
        if shoot:
            text += "（画面：%s）" % shoot[:60]
        try:
            self.feel(FeelEvent.PHOTO_SENT)
        except Exception:
            pass
        try:
            self._record("photo", "拍了一张%s" % (label or "照片"), text, "", 0)
            ok = await self._write_memory_checked(uid, text, kind="photo_record", tier=0)
            if ok:
                return True
            # photo_record 这条路被守门人拦下过（结果就是拍了一堆照片一条记录都没有），
            # 退一步用普通事件记，宁可降级也不能丢
            logger.info("[amo] photo_record 没写进去，降级为 event: %s" % text[:40])
            return await self._write_memory_checked(uid, "【照片】" + text, kind="event", tier=0)
        except Exception as exc:
            logger.warning("[amo] 照片记忆写入失败: %s" % exc)
            return False

    async def _maybe_his_day_digest(self):
        """每天晚上把他今天干了什么写成一条记忆（7 天降权 / 14 天删除）。

        用户的原话：记忆里为什么不记录他干了什么？这不是给他做档案，是让她第二天
        还能记得他昨天去哪了、忙什么、身体怎么样——但不能变成永久事实，按事件走。
        """
        if not self.cfg_bool("his_digest_enabled", True):
            return
        now = _now()
        if now.hour < max(0, min(23, self.cfg_int("his_digest_hour", 23))):
            return
        day = now.strftime("%Y-%m-%d")
        guard = "his_digest:" + day
        try:
            if self.db.kv_get(guard, ""):
                return
            tries = to_int(self.db.kv_get("his_digest_tries:" + day, 0), 0)
            if tries >= 3:
                return
        except Exception:
            tries = 0
        uid = self._primary_uid()
        if not uid or self.llm is None:
            return
        umo = self._first_private_umo() or self._last_umo or ""
        rows = []
        try:
            rows = await self._data_call(
                "recall_messages", self._data_bot_id(), query=day,
                umo="", uid=uid, limit=300,
            )
        except Exception as exc:
            logger.debug("[amo] 他的今日摘要取聊天失败: %s" % exc)
            rows = None
        messages = (rows or {}).get("messages") or []
        if not messages:
            try:
                messages = self.db.chat_history(uid, limit=200) or []
            except Exception:
                messages = []
        lines = []
        for row in messages:
            if str(row.get("role") or "") != "user":
                continue
            text = str(row.get("content") or "").strip().replace("\n", " ")
            if text:
                lines.append(text[:120])
        lines = lines[-80:]
        if len(lines) < 3:
            return
        system = "你在整理「他今天做了什么」，只输出一段中文事实清单，不寒暄。"
        prompt = (
            "下面是主人（他）今天在聊天里说过的话：\n" + "\n".join(lines) + "\n\n"
            "只提取**他自己**今天做过/说过的事：去了哪、吃了什么、工作或学习、出行、"
            "身体状态、打算。用不超过 4 行，每行一件事，主语一律写「他」；"
            "不许写你和他的对话过程，不许编没说过的事，不许写天气这类废话。"
            "没有具体内容就只输出「今天没说什么」。"
        )
        try:
            raw = await asyncio.wait_for(
                self.llm.chat_raw(umo, system, prompt, kind="digest"), timeout=60)
        except Exception as exc:
            logger.debug("[amo] 他的今日摘要生成失败: %s" % exc)
            raw = ""
        summary = re.sub(r"[ \t]+", " ", str(raw or "")).strip()
        summary = re.sub(r"\n{2,}", "\n", summary)
        if len(summary) < 6 or "今天没说什么" in summary:
            try:
                self.db.kv_set(guard, day)
            except Exception:
                pass
            return
        content = "【%s 他的今天】%s" % (day, summary[:400])
        written = await self._write_memory_checked(uid, content, kind="his_day", tier=0)
        logger.info("[amo] 他的今日摘要%s: %s" % ("已写入" if written else "写入失败", content[:80]))
        if written:
            try:
                self.db.kv_set(guard, day)
            except Exception:
                pass
        else:
            try:
                self.db.kv_set("his_digest_tries:" + day, tries + 1)
            except Exception:
                pass

    async def _write_memory_checked(self, uid, content, kind="fact", tier=1, scope="private", group_id=""):
        """写一条记忆并返回是否真的成功；失败打 warning，调用方据此决定要不要标记。

        scope/group_id 必须一路传到数据终端：群聊写入 private、群聊却按 group 读，
        就会表现为“群里聊过但她完全不记得”。
        """
        if _mem_prepare is not None:
            try:
                allowed, fixed, why = _mem_prepare(self.db, str(uid), content, _now(), now_ts())
            except Exception:
                allowed, fixed, why = True, content, "guard_error"
            if not allowed:
                logger.debug("[amo] 记忆没写（%s）: %s" % (why, str(content)[:40]))
                return False
            content = fixed
        hub = self._memory_hub()
        level = to_int(tier, 1)
        importance = 0.75 if level >= 2 else (0.55 if level == 1 else 0.35)
        if hub is not None and hub.writable():
            try:
                result = await hub.remember(str(uid), content, str(kind or "fact"), importance, scope, group_id)
            except Exception as exc:
                logger.warning("[amo] 记忆写入异常: %s" % exc)
                result = {"ok": False}
            if isinstance(result, dict) and result.get("ok"):
                self._memory_committed(uid, content)
                return True
            logger.warning(
                "[amo] 记忆没写进去（%s）: %s" % ((result or {}).get("reason", "?"), str(content)[:40])
            )
            return False
        if self._data_mem() is not None:
            try:
                result = await self._data_memory_write(uid, content, kind, tier, scope, group_id)
            except Exception:
                result = False
            if result:
                self._memory_committed(uid, content)
                return True
        return False

    def _memory_committed(self, uid, content):
        """记忆真的写进去了：登记去重指纹，并在同一天地点冲突时留一条 warning。"""
        if _mem_commit is None:
            return
        try:
            hint = _mem_commit(self.db, str(uid), str(content), _now(), now_ts())
        except Exception:
            return
        if hint:
            logger.warning("[amo] 记忆可能对不上：%s（%s）" % (hint, str(content)[:40]))

    def _external_memory_write(self, uid, content, kind="fact", tier=1, scope="private", group_id=""):
        """把一条记忆交给「记忆终端」：装了 Astr_Amo_data 就写它，没装才写外挂记忆插件。

        陪伴自己不存记忆，只负责把要记的东西丢过去。
        """
        content = re.sub(r"\s+", " ", str(content or "")).strip()
        if not content:
            return False
        hub = self._memory_hub()
        if hub is not None and hub.writable():
            level = to_int(tier, 1)
            importance = 0.75 if level >= 2 else (0.55 if level == 1 else 0.35)
            try:
                self._spawn(hub.remember(uid, content, str(kind or "fact"), importance, scope, group_id))
                logger.debug("[amo] 记忆已交给能力层: %s" % content[:40])
                return True
            except Exception as exc:
                logger.debug("[amo] 能力层写入失败，退回旧路径: %s" % exc)
        if self._data_mem() is not None and callable(getattr(self._data_mem(), "remember", None)):
            coro = None
            try:
                coro = self._data_memory_write(uid, content, kind, tier, scope, group_id)
                if self._spawn(coro) is not None:
                    logger.debug("[amo] 记忆已交给记忆终端: %s" % content[:40])
                    return True
            except Exception as exc:
                if coro is not None:
                    coro.close()
                logger.debug("[amo] 记忆终端写入失败，退回外挂插件: %s" % exc)
        target = self._memory_plugin_target()
        if target is None:
            return False
        for name in self.WRITE_METHODS:
            method = getattr(target, name, None)
            if not callable(method):
                continue
            for args in (
                (str(uid), content),
                (content,),
                (str(uid), content, kind, int(tier)),
            ):
                try:
                    result = method(*args)
                    if asyncio.iscoroutine(result):
                        # 异步写入接口：丢到事件循环里跑，不阻塞当前回合
                        try:
                            asyncio.get_running_loop().create_task(result)
                        except RuntimeError:
                            result.close()
                        logger.debug("[amo] 记忆已交给外挂插件异步写入(%s): %s" % (name, content[:40]))
                        return True
                    logger.debug("[amo] 记忆已写入外挂插件(%s): %s" % (name, content[:40]))
                    return True
                except TypeError:
                    continue
                except Exception as exc:
                    logger.debug("[amo] 记忆写入 %s 失败: %s" % (name, exc))
                    break
        return False

    @staticmethod
    def _memory_hit_item(hit):
        """把插件返回的一条命中转成 amo 的记忆条目；不认识的结构返回 None。"""
        memory = getattr(hit, "memory", None)
        if memory is not None:
            content = str(getattr(memory, "content", "") or "")
            importance = to_float(getattr(memory, "importance", 0.0), 0.0)
            memory_type = str(getattr(memory, "memory_type", "") or "")
        elif isinstance(hit, dict):
            content = str(hit.get("content") or "")
            importance = to_float(hit.get("importance"), 0.0)
            memory_type = str(hit.get("memory_type") or "")
        else:
            return None
        content = re.sub(r"\s+", " ", content).strip()
        if len(content) < 2:
            return None
        return {
            "content": content[:500],
            "tier": 2 if importance >= 0.72 else (1 if importance >= 0.42 else 0),
            "kind": "memory_companion",
            "source": "memory_companion",
            "memory_type": memory_type,
        }

    async def _external_memory_recall(self, event, query, limit=6):
        """用记忆插件自己的检索（BM25/向量/可见性）；不可用或超时就返回空，交给兜底。"""
        if event is None:
            return []
        target = self._memory_plugin_target()
        run = None
        for name in self.MEMORY_RECALL_METHODS:
            candidate = getattr(target, name, None) if target is not None else None
            if callable(candidate):
                run = candidate
                break
        if run is None:
            return []
        budget = max(0.5, self.cfg_float("memory_bridge_timeout_seconds", 3.0))
        try:
            hits = await asyncio.wait_for(
                run(event, str(query or ""), top_k=max(1, int(limit or 6))),
                timeout=budget,
            )
        except asyncio.TimeoutError:
            logger.warning("[amo] 记忆插件检索超时（%.1fs），本轮退回兜底", budget)
            return []
        except Exception as exc:
            logger.warning("[amo] 记忆插件检索失败: %s", exc)
            return []
        items = []
        for hit in hits or []:
            item = self._memory_hit_item(hit)
            if item is not None:
                items.append(item)
        return items

    def _external_memory_fallback(self, uid, text, limit):
        """插件没提供检索接口时的兜底：直接读它的库（旧的 LIKE / 重要性路径）。"""
        try:
            inject_lm = self.cfg_bool("memory_inject_livingmemory", False)
            picked = self._external_all_memories(uid, text, limit, include_living=inject_lm)
        except Exception as exc:
            logger.debug("[amo] 外部记忆兜底读取失败: %s", exc)
            return []
        items = []
        for item in picked:
            item["source"] = item.get("source") or "external"
            items.append(item)
        return items

    def _memcomp_all_memories(self, uid, keyword="", limit=50):
        """完整记忆：不限制 memory_type，用于“查看记忆”和召回。"""
        plugin = self._companion_plugin()
        if not self._is_memory_companion(plugin):
            return []
        sql = (
            "SELECT content, importance, memory_type, created_at, updated_at "
            "FROM memories WHERE (subject_id=? OR object_id=?) AND content!='' "
            "AND lifecycle NOT IN ('deleted','archived','quarantined') "
        )
        params = [str(uid), str(uid)]
        if keyword:
            sql += "AND content LIKE ? "
            params.append("%" + str(keyword) + "%")
        sql += "ORDER BY importance DESC, updated_at DESC LIMIT ?"
        params.append(max(1, min(100, to_int(limit, 50))))
        items = []
        for row in self._memcomp_rows(sql, tuple(params)):
            content = re.sub(r"\s+", " ", str(row.get("content") or "")).strip()
            if len(content) < 2:
                continue
            importance = to_float(row.get("importance"), 0.3)
            items.append({
                "content": content[:500],
                "tier": 2 if importance >= 0.72 else (1 if importance >= 0.42 else 0),
                "kind": "memory_companion",
                "source": "memory_companion",
                "memory_type": row.get("memory_type", ""),
                "created_at": row.get("created_at", ""),
                "hits": 0,
                "expires_at": None,
            })
        return items

    ANGEL_ATTRIBUTE_TAGS = {"用户别名", "事实属性", "技能树", "关系图谱", "活跃项目"}

    @staticmethod
    def _is_angel_memory(plugin):
        if plugin is None:
            return False
        marker = (
            str(type(plugin).__module__ or "") + " "
            + str(getattr(plugin, "name", "") or "")
        ).lower()
        if "angel_memory" in marker:
            return True
        return (
            getattr(plugin, "plugin_context", None) is not None
            and (
                getattr(plugin, "memory_store", None) is not None
                or getattr(plugin, "deepmind", None) is not None
            )
        )

    @staticmethod
    def _angel_component(plugin, name):
        ctx = getattr(plugin, "plugin_context", None)
        if ctx is not None and hasattr(ctx, "get_component"):
            try:
                value = ctx.get_component(name)
                if value is not None:
                    return value
            except Exception:
                pass
        if name == "memory_store":
            return getattr(plugin, "memory_store", None)
        if name == "memory_sql_manager":
            return getattr(plugin, "memory_sql_manager", None)
        return None

    def _angel_records(self, plugin=None):
        plugin = plugin or self._companion_plugin()
        if not self._is_angel_memory(plugin):
            return []
        store = self._angel_component(plugin, "memory_store")
        method = getattr(store, "list_records", None)
        if not callable(method):
            return []
        try:
            return list(method(None, all_scopes=True) or [])
        except Exception as exc:
            logger.debug("[amo] 读取 Angel Memory 记录失败: %s" % exc)
            return []

    def _angel_ledger_users(self, plugin=None):
        plugin = plugin or self._companion_plugin()
        if not self._is_angel_memory(plugin):
            return []
        ledger = self._angel_component(plugin, "memory_sql_manager")
        method = getattr(ledger, "list_ledger_users", None)
        if not callable(method):
            return []
        try:
            return list(method() or [])
        except Exception as exc:
            logger.debug("[amo] 读取 Angel Memory 用户账本失败: %s" % exc)
            return []

    @staticmethod
    def _angel_tags(record):
        tags = (record or {}).get("tags") or []
        if isinstance(tags, str):
            tags = [item.strip() for item in tags.split(",")]
        return [str(item).strip() for item in tags if str(item).strip()]

    def _angel_known_ids(self, plugin=None):
        return {
            str(item.get("user_id") or "").strip()
            for item in self._angel_ledger_users(plugin)
            if isinstance(item, dict) and str(item.get("user_id") or "").strip()
        }

    @staticmethod
    def _angel_is_id(tag, known_ids=None):
        text = str(tag or "").strip()
        if not text:
            return False
        if known_ids and text in known_ids:
            return True
        if len(text) <= 5 or any("\u4e00" <= char <= "\u9fff" for char in text):
            return False
        if any(char.isspace() for char in text):
            return False
        return not text.replace("-", "").replace("_", "").isalpha()

    def _angel_uid_tags(self, tags, known_ids=None):
        normalized = [str(item).strip() for item in (tags or []) if str(item).strip()]
        if known_ids:
            hits = [item for item in normalized if item in known_ids]
            if hits:
                return hits
        return [item for item in normalized if self._angel_is_id(item, known_ids)]

    def _angel_profile_records(self, plugin=None):
        """Angel 的用户画像只取带画像属性标签的记录，不把普通记忆里的群/机器人 ID 当用户。"""
        plugin = plugin or self._companion_plugin()
        if not self._is_angel_memory(plugin):
            return []
        result = []
        for record in self._angel_records(plugin):
            tags = self._angel_tags(record)
            if any(tag in self.ANGEL_ATTRIBUTE_TAGS for tag in tags):
                result.append(record)
        return result

    def _angel_user_count(self, plugin=None):
        plugin = plugin or self._companion_plugin()
        if not self._is_angel_memory(plugin):
            return 0
        known = self._angel_known_ids(plugin)
        users = set()
        for record in self._angel_profile_records(plugin):
            users.update(self._angel_uid_tags(self._angel_tags(record), known))
        return len(users)

    def _angel_all_memories(self, uid, keyword="", limit=50):
        """天使之魂完整记忆，不限制画像标签。"""
        plugin = self._companion_plugin()
        if not self._is_angel_memory(plugin):
            return []
        known = self._angel_known_ids(plugin)
        items = []
        for record in self._angel_records(plugin):
            tags = self._angel_tags(record)
            if str(uid) not in self._angel_uid_tags(tags, known):
                continue
            content = str(record.get("judgment") or record.get("reasoning") or "").strip()
            content = re.sub(r"\s+", " ", content)
            if len(content) < 2:
                continue
            if keyword and str(keyword).lower() not in content.lower():
                continue
            state = record.get("state") if isinstance(record.get("state"), dict) else {}
            strength = to_int(state.get("strength"), 1)
            pinned = bool(state.get("pinned", False))
            items.append({
                "content": content[:500],
                "tier": 2 if pinned or strength >= 3 else (1 if strength >= 2 else 0),
                "kind": "angel_memory",
                "source": "angel_memory",
                "memory_type": "angel",
                "created_at": record.get("created_at_us") or record.get("created_at") or "",
                "hits": 0,
                "expires_at": None,
            })
            if len(items) >= max(1, min(100, to_int(limit, 50))):
                break
        return items

# ---------- livingmemory（只读直连） ----------
    def _livingmem_db_path(self):
        """找 livingmemory 的库；路径不写死，跟着 AstrBot 的数据目录走。"""
        candidates = []
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            candidates.append(os.path.join(str(get_astrbot_data_path()), "plugin_data",
                                           "astrbot_plugin_livingmemory", "livingmemory.db"))
        except Exception:
            pass
        own = getattr(self, "plugin_dir", "") or ""
        if own:
            candidates.append(os.path.join(os.path.dirname(os.path.dirname(own)),
                                           "astrbot_plugin_livingmemory", "livingmemory.db"))
        for path in candidates:
            if path and os.path.isfile(str(path)):
                return str(path)
        return ""

    def _livingmem_active(self):
        """livingmemory 现在算不算记忆源：启用着，或者用户明确选了它。"""
        selected = self.cfg_str("companion_memory_plugin_name", "").strip().lower()
        explicit = selected not in ("", "auto", "automatic", "自动")
        if explicit and selected != "astrbot_plugin_livingmemory":
            return False
        try:
            meta = self.context.get_registered_star("astrbot_plugin_livingmemory")
            if meta is not None and not bool(getattr(meta, "activated", True)):
                return False
        except Exception:
            pass
        return bool(self._livingmem_db_path())

    def _livingmem_stats(self):
        """livingmemory 有没有数据、大概几个人（面板候选用）。"""
        if not self._livingmem_db_path():
            return False, 0
        rows = self._livingmem_rows("SELECT COUNT(*) AS n FROM documents")
        total = int(rows[0]["n"]) if rows else 0
        if not total:
            return False, 0
        owners = set()
        try:
            for row in self._livingmem_rows("SELECT metadata FROM documents LIMIT 500"):
                meta = json.loads(row.get("metadata") or "{}")
                for item in meta.get("participant_uids") or []:
                    owners.add(str(item))
        except Exception:
            owners = set()
        return True, max(len(owners), 1)

    def _livingmem_rows(self, sql, params=()):
        path = self._livingmem_db_path()
        if not path:
            return []
        conn = None
        try:
            from urllib.parse import quote
            conn = sqlite3.connect("file:" + quote(path) + "?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(sql, params).fetchall()]
        except Exception as exc:
            logger.debug("[amo] 读取 livingmemory 失败: %s" % exc)
            return []
        finally:
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass

    def _livingmem_owner_ids(self, uid=""):
        """认哪些 ID 算同一个人：当前 uid + 配置里的别名（跨平台用）。"""
        ids = {str(uid or "").strip()}
        raw = str(self.cfg_str("livingmemory_owner_ids", "") or "").replace("，", ",")
        for item in raw.split(","):
            item = item.strip()
            if item:
                ids.add(item)
        ids.discard("")
        return ids

    def _livingmem_owned(self, metadata, uid):
        """这段记忆是不是这个人这边的。

        livingmemory 写进 documents 的归属可能是任何一种平台 ID（如飞书 openid），
        不一定是 amo 里的 canonical uid；所以按“uid + 配置别名”的交集判断。
        没有归属信息时按“自己的”处理（单用户部署最常见）。
        """
        ids = self._livingmem_owner_ids(uid)
        try:
            meta = json.loads(metadata or "{}")
        except Exception:
            meta = {}
        owners = {str(x) for x in (meta.get("participant_uids") or [])}
        for item in meta.get("participant_identities") or []:
            if isinstance(item, dict) and item.get("sender_id"):
                owners.add(str(item["sender_id"]))
        if not owners:
            return True
        return bool(ids & owners)

    @staticmethod
    def _livingmem_like_escape(text):
        """LIKE 里的 % 和 _ 要转义，否则用户搜个下划线就变成通配符。"""
        return str(text or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _livingmem_all_memories(self, uid, keyword="", limit=50):
        """livingmemory 的 documents：每条是一段对话摘要。

        排序规则：
          - 有关键词：命中次数多的优先，其次重要度高、其次新；
          - 没关键词：按重要度、再按时间倒序。
        和 memory_companion 那条“importance DESC, updated_at DESC”的风格保持一致。
        """
        if not self._livingmem_db_path():
            return []
        cap = max(1, min(100, int(limit or 50)))
        keyword = str(keyword or "").strip()[:100]
        sql = (
            "SELECT text, created_at, metadata, "
            "COALESCE(json_extract(metadata, '$.importance'), 0) AS imp, id "
            "FROM documents WHERE text != ''"
        )
        params = []
        if keyword:
            sql += " AND text LIKE ? ESCAPE '\\'"
            params.append("%" + self._livingmem_like_escape(keyword) + "%")
        sql += " ORDER BY imp DESC, id DESC LIMIT ?"
        params.append(max(cap * 5, 50) if keyword else cap)
        rows = self._livingmem_rows(sql, tuple(params))

        uid_s = str(uid or "")
        items = []
        for row in rows:
            content = re.sub(r"\\s+", " ", str(row.get("text") or "")).strip()
            if len(content) < 2:
                continue
            if not self._livingmem_owned(row.get("metadata"), uid_s):
                continue
            hits = content.lower().count(keyword.lower()) if keyword else 0
            items.append({
                "content": content[:500],
                "tier": 1,
                "kind": "livingmemory",
                "source": "livingmemory",
                "memory_type": "episodic",
                "created_at": row.get("created_at") or "",
                "hits": hits,
                "expires_at": None,
            })

        if keyword:
            items.sort(key=lambda x: (x["hits"], x["created_at"] or ""), reverse=True)
        return items[:cap]

    def _external_all_memories(self, uid, query="", limit=50, include_living=True):
        """只读地从已安装记忆插件取完整记忆，不创建画像。

        include_living=False 给 prompt 注入用：livingmemory 自己会把检索结果
        注入 prompt（BM25+向量+图），这里再读一遍会重复；它只负责写入和注入，
        amo 只负责面板展示。
        """
        items = []
        if include_living and self._livingmem_active():
            living = self._livingmem_all_memories(uid, query, limit)
            if living:
                return living
        plugin = self._companion_plugin()
        if plugin is None:
            return items
        try:
            if self._is_memory_companion(plugin):
                items.extend(self._memcomp_all_memories(uid, query, limit))
            elif self._is_angel_memory(plugin):
                items.extend(self._angel_all_memories(uid, query, limit))
            else:
                items.extend(self._companion_memories(uid, query))
        except Exception as exc:
            logger.debug("[amo] 外部完整记忆读取失败: %s" % exc)
        return items

    def _external_profile_memories(self, uid, name="", alias="", limit=200):
        """按 UID 或名字/称呼从已安装记忆插件取完整记忆；只读，不建画像。"""
        if self._livingmem_active():
            living = self._livingmem_all_memories(uid, "", limit)
            if living:
                return living
        plugin = self._companion_plugin()
        if plugin is None:
            return []
        items = []
        names = [str(name or "").strip(), str(alias or "").strip()]
        names = [item for item in names if item]
        try:
            if self._is_memory_companion(plugin):
                items.extend(self._memcomp_all_memories(uid, "", limit))
                if not items and names:
                    sql = (
                        "SELECT content, importance, memory_type, created_at, updated_at "
                        "FROM memories WHERE content!='' "
                        "AND lifecycle NOT IN ('deleted','archived','quarantined') "
                        "AND (" + " OR ".join("content LIKE ?" for _ in names) + ") "
                        "ORDER BY importance DESC, updated_at DESC LIMIT ?"
                    )
                    params = ["%" + item + "%" for item in names] + [max(1, min(100, limit))]
                    for row in self._memcomp_rows(sql, tuple(params)):
                        content = re.sub(r"\s+", " ", str(row.get("content") or "")).strip()
                        if len(content) < 2:
                            continue
                        importance = to_float(row.get("importance"), 0.3)
                        items.append({
                            "content": content[:500],
                            "tier": 2 if importance >= 0.72 else (1 if importance >= 0.42 else 0),
                            "kind": "memory_companion",
                            "source": "memory_companion",
                            "created_at": row.get("created_at", ""),
                        })
            elif self._is_angel_memory(plugin):
                items.extend(self._angel_all_memories(uid, "", limit))
                if not items and names:
                    known = self._angel_known_ids(plugin)
                    for record in self._angel_records(plugin):
                        tags = self._angel_tags(record)
                        content = str(record.get("judgment") or record.get("reasoning") or "")
                        haystack = content + " " + " ".join(tags)
                        if not any(item in haystack for item in names):
                            continue
                        content = re.sub(r"\s+", " ", content).strip()
                        if len(content) >= 2:
                            items.append({
                                "content": content[:500],
                                "tier": 1,
                                "kind": "angel_memory",
                                "source": "angel_memory",
                                "created_at": record.get("created_at_us") or record.get("created_at") or "",
                            })
                        if len(items) >= limit:
                            break
            else:
                items.extend(self._companion_memories(uid, ""))
                if not items and names:
                    data = getattr(plugin, "data", None)
                    users = data.get("users") if isinstance(data, dict) else None
                    if isinstance(users, dict):
                        for other_uid, user in users.items():
                            if not isinstance(user, dict):
                                continue
                            values = [user.get("name"), user.get("nickname"), user.get("display_name")]
                            values += list(user.get("aliases") or []) if isinstance(user.get("aliases"), list) else []
                            if any(item and item in " ".join(str(v or "") for v in values) for item in names):
                                try:
                                    items.extend(self._companion_memories(str(other_uid), ""))
                                except Exception:
                                    pass
        except Exception as exc:
            logger.debug("[amo] 外部画像记忆读取失败: %s" % exc)
        unique = []
        seen = set()
        for item in items:
            key = re.sub(r"\s+", "", str(item.get("content") or "")).lower()
            if key and key not in seen:
                seen.add(key)
                unique.append(item)
        return unique[:max(1, min(500, limit))]

    def _companion_plugin_meta(self):
        """优先用配置的插件名；留空或找不到时从已安装插件里自动检测。"""
        name = self.cfg_str("companion_memory_plugin_name", "").strip()
        if name and name.lower() not in ("auto", "automatic", "自动"):
            try:
                meta = self.context.get_registered_star(name)
                if meta is not None and self._star_instance(meta) is not None:
                    return meta
            except Exception:
                pass
        candidates = []
        try:
            for meta in self.context.get_all_stars():
                if getattr(meta, "name", None) == PLUGIN_NAME:
                    continue
                plugin = self._star_instance(meta)
                if plugin is None:
                    continue
                data = getattr(plugin, "data", None)
                users = data.get("users") if isinstance(data, dict) else None
                marker = (
                    (getattr(meta, "name", "") or "") + " "
                    + (getattr(meta, "module_path", "") or "")
                ).lower()
                score = 0
                if "livingmemory" in marker:
                    # 只有真的启用着才给最高权重；停用时让位给别的已激活记忆插件
                    score += 12 if bool(getattr(meta, "activated", False)) else 3
                if bool(getattr(meta, "activated", False)):
                    score += 2
                if "private_companion" in marker:
                    score += 5
                if "memory" in marker:
                    score += 1
                if getattr(plugin, "memory_companion", None) is not None:
                    score += 6
                if self._is_angel_memory(plugin):
                    score += 7
                if isinstance(users, dict) and users:
                    sample = next((item for item in users.values() if isinstance(item, dict)), {})
                    if isinstance(sample.get("companion_memory"), dict):
                        score += 4
                    if "relationship_score" in sample:
                        score += 2
                    if isinstance(sample.get("important_memories"), list):
                        score += 1
                    score += 1
                if score:
                    candidates.append((score, meta))
        except Exception:
            pass
        candidates.sort(key=lambda pair: -pair[0])
        return candidates[0][1] if candidates else None

    def _companion_plugin(self):
        meta = self._companion_plugin_meta()
        return self._star_instance(meta) if meta else None

    def _companion_candidates(self):
        items = []
        try:
            for meta in self.context.get_all_stars():
                if getattr(meta, "name", None) == PLUGIN_NAME:
                    continue
                plugin = self._star_instance(meta)
                data = getattr(plugin, "data", None) if plugin is not None else None
                users = data.get("users") if isinstance(data, dict) else None
                count = len(users) if isinstance(users, dict) else 0
                ready = False
                marker = (
                    (getattr(meta, "name", "") or "") + " "
                    + (getattr(meta, "module_path", "") or "")
                ).lower()
                if isinstance(users, dict) and users:
                    sample = next((item for item in users.values() if isinstance(item, dict)), {})
                    ready = isinstance(sample, dict) and (
                        isinstance(sample.get("companion_memory"), dict)
                        or "relationship_score" in sample
                        or isinstance(sample.get("important_memories"), list)
                    )
                if plugin is not None and self._is_memory_companion(plugin):
                    ready = True
                    count = self._memcomp_user_count(plugin)
                if plugin is not None and self._is_angel_memory(plugin):
                    ready = True
                    count = self._angel_user_count(plugin)
                if "livingmemory" in marker:
                    lm_ready, lm_count = self._livingmem_stats()
                    if lm_ready:
                        ready = True
                        count = lm_count
                if not ready and plugin is not None:
                    # 市面上记忆类插件很多：只要有检索接口或 users 里的记忆结构，就当作可用
                    ready = self._looks_like_memory_plugin(plugin, users)
                items.append({
                    "name": str(getattr(meta, "name", "") or ""),
                    "display_name": str(getattr(meta, "display_name", "") or getattr(meta, "name", "") or ""),
                    "version": str(getattr(meta, "version", "") or ""),
                    "users": count,
                    "ready": ready,
                    "activated": bool(getattr(meta, "activated", False)),
                    "reserved": bool(getattr(meta, "reserved", False)),
                })
        except Exception:
            pass
        items.sort(key=lambda item: (not item["ready"], -item["users"], item["name"]))
        return items

    @staticmethod
    def _looks_like_memory_plugin(plugin, users=None):
        """通用识别：不写死插件名，只要有记忆检索接口或记忆数据结构就算。"""
        if plugin is None:
            return False
        for name in ("search_for_event", "recall_for_event", "search_memory",
                     "recall_memory", "query_memory", "retrieve_memory"):
            if callable(getattr(plugin, name, None)):
                return True
        service = getattr(plugin, "service", None)
        if service is not None:
            for name in ("search_for_event", "recall_for_event", "search_memory", "retrieve"):
                if callable(getattr(service, name, None)):
                    return True
        if isinstance(users, dict) and users:
            sample = next((item for item in users.values() if isinstance(item, dict)), {})
            if not isinstance(sample, dict):
                return False
            for key in ("companion_memory", "important_memories", "memories",
                        "long_term_memory", "memory"):
                value = sample.get(key)
                if isinstance(value, (dict, list)) and value:
                    return True
        return False

    @staticmethod
    def _companion_pick_profile(mapping, uid):
        if not isinstance(mapping, dict):
            return {}
        direct = mapping.get(str(uid))
        if isinstance(direct, dict):
            return direct
        for key, value in mapping.items():
            if not isinstance(value, dict):
                continue
            subject = (
                value.get("user_id") or value.get("member_id")
                or value.get("identity_subject_id") or key
            )
            if str(subject) == str(uid):
                return value
        return {}

    def _companion_memories(self, uid, query=""):
        """只读地从挂载插件的 data 中提取用户记忆。"""
        plugin = self._companion_plugin()
        if plugin is None:
            return []
        data = getattr(plugin, "data", None)
        if not isinstance(data, dict):
            return []

        user = self._companion_pick_profile(data.get("users"), uid)
        items = []
        seen = set()

        def add(content, tier=1, weight=1):
            text = re.sub(r"\s+", " ", str(content or "")).strip()
            if len(text) < 2:
                return
            key = re.sub(r"[\s，。！？!?、；;：:]+", "", text).lower()
            if not key or key in seen:
                return
            seen.add(key)
            items.append({
                "content": text[:240],
                "tier": max(0, min(2, to_int(tier, 1))),
                "kind": "companion",
                "source": "companion",
                "weight": to_int(weight, 1),
                "hits": 0,
                "expires_at": None,
            })

        memory = user.get("companion_memory") if isinstance(user, dict) else None
        if isinstance(memory, dict):
            raw_items = memory.get("items")
            if isinstance(raw_items, list):
                for raw in raw_items:
                    if not isinstance(raw, dict):
                        continue
                    weight = to_int(raw.get("weight"), 1)
                    add(
                        raw.get("text"),
                        2 if weight >= 3 else (1 if weight >= 2 else 0),
                        weight,
                    )
            if self.cfg_bool("companion_memory_include_profile", True):
                profile = memory.get("profile")
                if isinstance(profile, dict):
                    labels = (
                        ("strong_memories", "强记忆", 2),
                        ("boundaries", "边界", 2),
                        ("speaking_style", "表达习惯", 1),
                        ("weak_preferences", "偏好", 1),
                        ("interests", "兴趣", 1),
                    )
                    for key, label, tier in labels:
                        value = profile.get(key)
                        values = value if isinstance(value, list) else ([value] if value else [])
                        for entry in values[:6]:
                            if isinstance(entry, dict):
                                entry = entry.get("text") or entry.get("content") or ""
                            add(str(label) + "：" + str(entry), tier, 2 if tier >= 2 else 1)

        if self.cfg_bool("companion_memory_include_important", True):
            important = []
            if isinstance(user, dict) and isinstance(user.get("important_memories"), list):
                important.extend(user.get("important_memories") or [])
            worldbook = data.get("worldbook_member_profiles")
            wb_profile = self._companion_pick_profile(worldbook, uid)
            if isinstance(wb_profile.get("important_memories"), list):
                important.extend(wb_profile.get("important_memories") or [])
            for entry in important:
                if isinstance(entry, dict):
                    add(entry.get("content") or entry.get("text"), 2, 3)
                elif isinstance(entry, str):
                    add(entry, 2, 3)

        if not items:
            return []
        query_tokens = tokens(query)
        for item in items:
            item["_score"] = overlap(query_tokens, tokens(item["content"])) + 0.08 * to_int(item.get("weight"))
        items.sort(key=lambda item: (-item["_score"], -to_int(item.get("weight")), -len(item["content"])))
        for item in items:
            item.pop("_score", None)
        # 挂载插件的记忆不做条数限制：返回插件里有的全部，注入时再按 memory_recall_limit 截断
        return items[:500]

    def _companion_user_record(self, uid):
        plugin = self._companion_plugin()
        if plugin is None:
            return {}
        data = getattr(plugin, "data", None)
        if not isinstance(data, dict):
            return {}
        return self._companion_pick_profile(data.get("users"), uid)

    @staticmethod
    def _map_companion_relation(user):
        """把陪伴插件的关系分数/阶段映射到本插件的关系；不会自动到“相恋”。"""
        if not isinstance(user, dict):
            return "普通"
        score = to_int(user.get("relationship_score"), 0)
        stage = str(user.get("relationship_phase_key") or user.get("relationship_stage") or "").lower()
        role = str(user.get("relationship_role") or "").lower()
        if "hatred" in stage or "enemy" in role or score <= -60:
            return "仇恨"
        if "distant" in stage or "rival" in role or score < 0:
            return "抵触"
        if "close" in stage or score >= 40:
            return "熟识"
        if "familiar" in stage or score >= 15:
            return "熟识"
        return "普通"

    @staticmethod
    def _memory_scope(event):
        """当前消息该写进哪个记忆域：群聊写 group，私聊写 private。"""
        try:
            if event is not None and not event.is_private_chat():
                return "group", str(event.get_group_id() or "")
        except Exception:
            pass
        return "private", ""

    async def _recall(self, uid, text, event=None):
        """记忆只来自「记忆终端」（Astr_Amo_data）；没装才退回外挂记忆插件。

        陪伴自己不存记忆：读也只读记忆终端，读不到再退旧的插件库。
        """
        limit = max(1, min(50, self.cfg_int("memory_recall_limit", 6)))
        if self.cfg_str("context_style", "lean").strip().lower() == "lean" and event is not None:
            try:
                if not event.is_private_chat():
                    limit = min(limit, 4)
            except Exception:
                pass
        memories = []
        allow_recall = True
        hub = self._memory_hub()
        if hub is not None:
            try:
                private = True
                try:
                    private = bool(event.is_private_chat()) if event is not None else True
                except Exception:
                    private = True
                if not private and len(str(text or "").strip()) <= 3:
                    limit = min(limit, 2)   # 群聊短消息只补 2 条，避免一句“猫”塞满提示词
                allow_recall = hub.should_recall(text, private)
                if allow_recall:
                    scope = "private"
                    group_id = ""
                    if event is not None and not private:
                        scope = "group"
                        try:
                            group_id = str(event.get_group_id() or "")
                        except Exception:
                            group_id = ""
                    memories = await hub.recall(uid, text, limit, scope, group_id, event=event)
            except Exception as exc:
                logger.debug("[amo] 能力层召回失败: %s" % exc)
                memories = []
        # 能力层说“这轮不召回”（群聊长消息抽样）时，后面的兜底也不能绕开它。
        # 以前这里不管 should_recall 的结果，兜底照样从数据插件捞记忆，
        # 群聊抽样实际上完全失效。
        if allow_recall and not memories:
            # 能力层已经选的是数据终端时，再调一次 _data_memory_recall 只是把
            # 同一个 recall 再跑一遍（空结果时尤其常见）；只有能力层没选数据终端
            # 或能力层不可用时才走这条兜底。
            if hub is None or getattr(hub, "active_name", "") != "amo_data":
                try:
                    memories = await self._data_memory_recall(uid, text, limit, event)
                except Exception as exc:
                    logger.debug("[amo] 记忆终端召回异常: %s" % exc)
        if allow_recall and not memories:
            memories = await self._external_memory_recall(event, text, limit)
        if allow_recall and not memories:
            memories = self._external_memory_fallback(uid, text, limit)

        unique = []
        seen = set()
        for item in memories:
            content = str(item.get("content", "")).strip()
            key = re.sub(r"[\s，。！？!?、；;：:]+", "", content).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(item)
        memories = unique[:max(1, self.cfg_int("memory_recall_limit", 6))]
        if not memories:
            return [], ""
        lines = []
        for item in memories:
            source = str(item.get("source") or "")
            if source == "amo_data":
                label = "记忆"
            elif source == "companion":
                label = "陪伴记忆"
            else:
                tier = to_int(item.get("tier"))
                label = "珍贵" if tier >= 2 else ("重要" if tier == 1 else "普通")
            who = str(item.get("name") or "").strip()
            prefix = (who + "：") if (who and source in ("hub", "amo_data")) else ""
            # 老记忆里常有"今天/昨晚/刚才"这种相对说法：注入时补一个记录日期，
            # 免得她把 11-04 的事当成"昨晚"（用户反馈过一次）。
            body = str(item.get("content", ""))
            rel_words = ("今天", "今晚", "昨天", "昨晚", "刚才", "刚刚", "前天", "这会儿", "这两天")
            created = to_int(item.get("created_at"))
            if created and any(w in body for w in rel_words):
                try:
                    day = datetime.fromtimestamp(created)
                    if day.strftime("%Y-%m-%d") != _now().strftime("%Y-%m-%d"):
                        body = "（记于 %s）%s" % (day.strftime("%m-%d"), body)
                except Exception:
                    pass
            # 记忆都是“关于他”的：没名字的统一补「他：」，避免模型把「脸疼」当成自己的感受
            if not prefix and not body.startswith(("他", "她", "用户")):
                prefix = "他："
            lines.append("· " + prefix + body + "（" + label + "）")
        if lines:
            lines.append("（记忆里出现的『今天/昨晚/刚才』是当时记下的说法，不是现在；对不上就以他刚说的为准。）")
        text = "\n".join(lines)
        budget = self.cfg_int("memory_inject_max_chars", 1200)
        if budget > 0 and len(text) > budget:
            text = text[:budget]
            if "\n" in text:
                text = text.rsplit("\n", 1)[0]
        return memories, text

    # ---------- 消息入口 ----------
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        try:
            await self._ensure_ready()
            try:
                raw_text = (event.message_str or "").strip()
                if raw_text and await self._maybe_go_sleep(event, raw_text):
                    return
                if raw_text and self._sleeping_now():
                    if not any(word in raw_text for word in WAKE_WORDS):
                        # 睡着了：群里私聊都不回，等她第二天醒
                        event.stop_event()
                        return
                    await self._wake_from_sleep(event, raw_text)
                if raw_text:
                    self._chat_feel(raw_text)
                if raw_text and await self._maybe_private_shot(event, raw_text):
                    return
                if raw_text and not raw_text.startswith(("/", "／")):
                    if await self._maybe_user_move(event, raw_text):
                        return
                    await self._apply_user_schedule_change(event.unified_msg_origin, raw_text)
            except Exception:
                pass
            try:
                if (raw_text and event.is_private_chat()
                        and await self._handle_money_gift(event, raw_text)):
                    return
            except Exception as exc:
                logger.debug("[amo] 收款处理失败: %s" % exc)
            try:
                if raw_text:
                    await self._maybe_user_takes_her_to_doctor(event, raw_text)
            except Exception as exc:
                logger.debug("[amo] 就医处理失败: %s" % exc)
            try:
                if raw_text and await self._maybe_change_outfit(event, raw_text):
                    return
            except Exception as exc:
                logger.debug("[amo] 换装指令处理失败: %s" % exc)
            await self._handle_message(event)
        except Exception:
            logger.exception("[amo] 消息处理异常")

    #: 他给钱的说法：[转账]金额 [货币] / [红包]金额 [货币]，只认私聊。
    #: 货币留空按人民币；USD/HKD 按金融插件的汇率折成人民币记账。
    MONEY_CURRENCIES = {
        "CNY": "CNY", "RMB": "CNY", "人民币": "CNY", "元": "CNY", "块": "CNY",
        "USD": "USD", "美元": "USD", "美金": "USD",
        "HKD": "HKD", "港币": "HKD", "港元": "HKD",
    }
    MONEY_TEMPLATES = (
        (re.compile(r"[\[【(（]\s*转账\s*[\]】)）]\s*(\d+(?:\.\d+)?)\s*(万)?\s*"
                    r"(人民币|美元|美金|港币|港元|CNY|RMB|USD|HKD|元|块)?", re.I), "transfer"),
        (re.compile(r"^\s*转账\s*(\d+(?:\.\d+)?)\s*(万)?\s*"
                    r"(人民币|美元|美金|港币|港元|CNY|RMB|USD|HKD|元|块)?", re.I), "transfer"),
        (re.compile(r"[\[【(（]\s*红包\s*[\]】)）]\s*(\d+(?:\.\d+)?)\s*(万)?\s*"
                    r"(人民币|美元|美金|港币|港元|CNY|RMB|USD|HKD|元|块)?", re.I), "red"),
        (re.compile(r"^\s*红包\s*(\d+(?:\.\d+)?)\s*(万)?\s*"
                    r"(人民币|美元|美金|港币|港元|CNY|RMB|USD|HKD|元|块)?", re.I), "red"),
    )

    def _parse_money_gift(self, text):
        """从私聊消息里认出「他给我钱」。返回 (channel, amount, currency) 或 None。"""
        body = str(text or "").strip()
        if not body:
            return None
        for pattern, channel in self.MONEY_TEMPLATES:
            match = pattern.search(body)
            if not match:
                continue
            try:
                amount = float(match.group(1))
            except (TypeError, ValueError):
                continue
            if (match.group(2) or "") == "万":
                amount *= 10000
            if amount <= 0:
                continue
            raw = str(match.group(3) or "").strip().upper()
            currency = self.MONEY_CURRENCIES.get(raw, "CNY")
            return channel, round(amount, 2), currency
        return None

    #: 收到他转账/红包之后的反应：先甜一下，再记着欠多少
    GIFT_REPLIES = (
        "老公今天怎么对我这么好啊？{kind} {amt} 我收下啦……我记着欠你 {owed:.0f} 呢，等我发财了双倍还你。",
        "哇，{amt} 的{kind}！你是不是又偷偷心疼我了……我记下了，欠你 {owed:.0f}，不许催我。",
        "谢谢老公（小声）……{amt} 我收到了，我以后一定对你好一点。现在欠你 {owed:.0f}。",
        "{amt} 的{kind}到啦！老公最好啦～我记着这笔，欠你 {owed:.0f}，等我赚回来请你吃饭。",
    )

    def _warm_gift_reply(self, kind, amount, owed, origin=""):
        amount_text = origin or ("%.0f" % float(amount or 0))
        try:
            template = random.choice(self.GIFT_REPLIES)
            return template.format(kind=kind, amt=amount_text, owed=float(owed or 0))
        except Exception:
            return "收了你的%s %s，我记着欠你 %.0f。" % (
                kind, amount_text, float(owed or 0))

    PHONE_POOL = ("iPhone 16", "iPhone 16 Pro", "小米 15", "华为 Mate 70", "OPPO Find X8")
    PC_POOL = ("MacBook Air M4", "联想小新 Pro", "华硕天选 6", "华为 MateBook 14")

    def _devices(self) -> dict:
        """她手上的设备：手机、电脑（型号 + 开始用的日期）。没有就按今天往前推随机初始化。"""
        try:
            data = self.db.kv_get("devices", {}) or {}
        except Exception:
            data = {}
        if not isinstance(data, dict) or not data.get("phone") or not data.get("pc"):
            today = _clock_now().date()
            data = {
                "phone": data.get("phone") or {
                    "model": random.choice(self.PHONE_POOL),
                    "since": (today - timedelta(days=random.randint(200, 900))).isoformat(),
                    "price": 5499,
                },
                "pc": data.get("pc") or {
                    "model": random.choice(self.PC_POOL),
                    "since": (today - timedelta(days=random.randint(300, 1400))).isoformat(),
                    "price": 6999,
                },
            }
            try:
                self.db.kv_set("devices", data)
            except Exception:
                pass
        return data

    @staticmethod
    def _device_age_days(item: dict) -> int:
        try:
            since = date.fromisoformat(str((item or {}).get("since") or ""))
            return max(0, (_clock_now().date() - since).days)
        except Exception:
            return 0

    def _device_wish(self) -> dict:
        """当前最想换的那件（手机/电脑），没有就空 dict。"""
        data = self._devices()
        moods = {}
        try:
            moods = self.feelings.values() if getattr(self, "feelings", None) else {}
        except Exception:
            moods = {}
        eye = float(moods.get("desire_eye") or 0)
        mind = float(moods.get("desire_mind") or 0)
        phone = data.get("phone") or {}
        pc = data.get("pc") or {}
        if eye >= 70 and self._device_age_days(phone) >= 240:
            return {"kind": "phone", "current": phone,
                    "model": random.choice(self.PHONE_POOL),
                    "price": round(float(phone.get("price") or 5499) * 0.95, 2)}
        if mind >= 75 and self._device_age_days(pc) >= 400:
            return {"kind": "pc", "current": pc,
                    "model": random.choice(self.PC_POOL),
                    "price": round(float(pc.get("price") or 6999) * 0.9, 2)}
        return {}

    def _device_wish_tick(self) -> None:
        """每天最多念一次：想换手机/电脑就写一条记忆，聊到的时候她会说。"""
        wish = self._device_wish()
        if not wish:
            return
        today = today_str()
        try:
            if self.db.kv_get("device_wish_day", "") == today:
                return
        except Exception:
            pass
        name = "手机" if wish["kind"] == "phone" else "电脑"
        text = ("我想换%s了（现在用的%s，%d 天了）：想要 %s，大概 ¥%.0f"
                % (name, (wish.get("current") or {}).get("model") or "旧的",
                   self._device_age_days(wish.get("current") or {}),
                   wish.get("model"), float(wish.get("price") or 0)))
        uid = self._primary_uid()
        if uid:
            try:
                self._spawn(self._write_memory_checked(uid, text, kind="event", tier=0))
            except Exception:
                pass
        try:
            self.db.kv_set("device_wish_day", today)
            self.db.kv_set("device_wish", wish)
        except Exception:
            pass
        logger.info("[amo] 想换设备：%s" % text)

    @filter.llm_tool(name="amo_buy_device")
    async def amo_buy_device(self, event, kind: str = "phone") -> str:
        """换手机或电脑（她自己的钱，走金融账本）。

        Args:
            kind(string): phone 换手机 / pc 换电脑。
        """
        await self._ensure_ready()
        data = self._devices()
        wish = self._device_wish()
        kind = "pc" if str(kind or "").strip().lower() in ("pc", "电脑", "laptop") else "phone"
        if not wish or wish.get("kind") != kind:
            # 没到欲望线也允许，但按现价算
            item = data.get(kind) or {}
            wish = {"kind": kind, "current": item,
                    "model": random.choice(self.PC_POOL if kind == "pc" else self.PHONE_POOL),
                    "price": float(item.get("price") or (6999 if kind == "pc" else 5499))}
        name = "手机" if kind == "phone" else "电脑"
        price = round(float(wish.get("price") or 0), 2)
        rid = "device:%s:%s" % (kind, today_str())
        result = await self.charge(price, reason="换%s" % name, payee=wish.get("model") or "数码店",
                                   request_id=rid, source="device",
                                   detail="%s → %s" % ((wish.get("current") or {}).get("model") or "旧的",
                                                       wish.get("model")))
        if not result.get("ok"):
            return "现在换不了%s：%s。" % (name, result.get("reason") or "钱不够")
        data[kind] = {"model": wish.get("model"), "since": today_str(), "price": price}
        try:
            self.db.kv_set("devices", data)
            self.db.kv_set("device_wish", {})
            self.db.kv_set("device_wish_day", "")
        except Exception:
            pass
        try:
            self.feel(FeelEvent.MONEY_TIGHT)
        except Exception:
            pass
        return "换了新%s：%s（¥%.0f，余额 ¥%.0f）。" % (
            name, wish.get("model"), price, float(result.get("balance") or 0))

    def _bill_meals(self) -> None:
        """日程里正在吃饭却一直没扣钱：按地点补扣一次，同一天同一格只扣一次。"""
        if getattr(self, "state", None) is None:
            return
        now = _clock_now()
        today = now.date().isoformat()
        items = self.state.schedule.get(today) or []
        current = None
        current_minute = now.hour * 60 + now.minute
        for item in items:
            start = _hhmm_minutes(item.get("start"))
            end = _hhmm_minutes(item.get("end"))
            if start <= current_minute < end:
                current = item
                break
        if not current or str(current.get("category") or "") != "meal":
            return
        rid = "meal:%s:%s" % (today, str(current.get("start") or ""))
        try:
            if self.db.kv_get("meal_billed:" + rid, False):
                return
        except Exception:
            pass
        activity = str(current.get("activity") or "")
        place = str(current.get("place") or "")
        if "做饭" in activity or "下厨" in activity:
            cost, payee, reason = 22.0, "菜场", "做饭"
        elif "外卖" in activity or "家" in place:
            cost, payee, reason = 36.0, "外卖", "外卖"
        else:
            cost, payee, reason = 58.0, (place or "餐馆"), "吃饭"

        async def run():
            result = await self.charge(cost, reason=reason, payee=payee,
                                       request_id=rid, source="meal")
            if isinstance(result, dict) and result.get("ok"):
                try:
                    self.db.kv_set("meal_billed:" + rid, True)
                except Exception:
                    pass

        try:
            self._spawn(run())
        except Exception as exc:
            logger.debug("[amo] 吃饭扣款任务起不来: %s" % exc)

    def _period_feel_tick(self) -> None:
        """生理期开始/结束时给心流发一次事件（每天最多一次）。"""
        if getattr(self, "feelings", None) is None or FeelEvent is None:
            return
        # 医疗插件在的时候由它发 PERIOD_START/END（带痛经等级），终端只做兜底
        try:
            if self._medical() is not None:
                return
        except Exception:
            pass
        try:
            info = self.state.period_info() or {}
        except Exception:
            return
        day = int(info.get("day") or 0)
        bleed = int(info.get("bleed_days") or 0)
        if not day or not bleed:
            return
        today = today_str()
        try:
            marker = self.db.kv_get("period_feel", {}) or {}
        except Exception:
            marker = {}
        if not isinstance(marker, dict):
            marker = {}
        if day == 1 and marker.get("start") != today:
            self.feel(FeelEvent.PERIOD_START)
            marker["start"] = today
            self.db.kv_set("period_feel", marker)
        elif day == bleed + 1 and marker.get("end") != today:
            self.feel(FeelEvent.PERIOD_END)
            marker["end"] = today
            self.db.kv_set("period_feel", marker)

    def _heartflow_tick(self) -> None:
        """内驱动：按上次 tick 到现在的时间衰减，重启也不会一次性掉一大截。"""
        if getattr(self, "feelings", None) is None:
            return
        now = now_ts()
        last = to_float(self.db.kv_get("heartflow_tick_ts", 0), 0)
        self.db.kv_set("heartflow_tick_ts", now)
        if not last:
            return
        minutes = (now - last) / 60.0
        if minutes < 0.5 or minutes > 24 * 60:
            return
        self.feelings.decay(minutes)

    def emit_event(self, name, payload=None) -> dict:
        """挂载插件唯一的事件入口：只交事件名 + 少量参数。

        加减表、边界锁定全在 ``heartflow.py``；这里也不做业务判断，只把
        ``payload["severity"]``（0–10）透传成这一次的放大倍数。
        """
        if getattr(self, "feelings", None) is None:
            return {}
        payload = payload if isinstance(payload, dict) else {}
        severity = payload.get("severity")
        try:
            return self.feelings.apply(name, severity=severity)
        except Exception as exc:
            logger.debug("[amo] 事件 %s 处理失败: %s" % (name, exc))
            return {}

    def feel(self, event, extra=None) -> None:
        """挂载/终端把「发生了什么」丢进来；加减表在 heartflow.py 里，这里不写业务判断。"""
        if getattr(self, "feelings", None) is None:
            return
        try:
            self.feelings.apply(event, extra)
        except Exception as exc:
            logger.debug("[amo] 心流事件失败(%s): %s" % (event, exc))

    def _sleeping_now(self) -> bool:
        try:
            return bool(self.sleep is not None and self.sleep.is_asleep(_clock_now()))
        except Exception:
            return False

    def _is_owner(self, event) -> bool:
        try:
            return bool(self.draw is not None and self.draw.is_owner(event))
        except Exception:
            return False

    async def _maybe_go_sleep(self, event, text) -> bool:
        """他让她去睡：晚上十一点后答应，之前会说还早；睡着后不再回消息。"""
        if self.sleep is None or not text:
            return False
        if not event.is_private_chat() or not self._is_owner(event):
            return False
        if not any(word in text for word in GO_SLEEP_WORDS):
            return False
        now = _clock_now()
        if self.sleep.is_asleep(now):
            return False
        answer = self.sleep.answer(now)
        uid = self._primary_uid()
        if answer is SleepAnswer.TOO_EARLY:
            line = "现在才 %s，还早呢，我再玩会儿。" % now.strftime("%H:%M")
            await self.context.send_message(event.unified_msg_origin, line)
            try:
                event.stop_event()
            except Exception:
                pass
            return True

        self.sleep.go_to_sleep(now)
        try:
            key = now.date().isoformat()
            items = self.state.schedule.get(key) or self.db.get_schedule(key) or []
            if items and apply_sched_change is not None:
                change = {"activity": "睡觉", "place": self.state._home_name(),
                          "category": "sleep"}
                new_items = apply_sched_change(items, change, now)
                if new_items and new_items != items:
                    self.state.schedule[key] = new_items
                    self.db.kv_set("schedule", self._sanitize_schedule(self.state.schedule))
                    self.db.save_schedule(key, new_items)
        except Exception as exc:
            logger.debug("[amo] 睡觉日程落盘失败: %s" % exc)
        if uid:
            try:
                await self._write_memory_checked(
                    uid, "他让我去睡，我答应了（%s 睡，%s 起）"
                    % (now.strftime("%H:%M"), self.sleep.load().get("wake_at") or ""),
                    kind="event", tier=0)
            except Exception:
                pass
        try:
            self.db.save_diary(now.date().isoformat(), now.strftime("%H:00"),
                               "他说该睡了，我关了灯躺下。")
        except Exception:
            pass
        line = "好，我去睡了。晚安，别熬太晚。"
        await self.context.send_message(event.unified_msg_origin, line)
        try:
            event.stop_event()
        except Exception:
            pass
        return True

    async def _wake_from_sleep(self, event, text) -> None:
        """他叫醒她：状态改成醒着，记一笔，然后正常聊天。"""
        now = _clock_now()
        reason = self.sleep.today_woke_reason()
        self.sleep.wake_up(now, woke_early=True)
        uid = self._primary_uid()
        if uid:
            try:
                await self._write_memory_checked(
                    uid, "他把我叫醒了（%s）" % now.strftime("%H:%M"),
                    kind="event", tier=0)
            except Exception:
                pass
        try:
            self.db.save_diary(now.date().isoformat(), now.strftime("%H:00"),
                               "他喊我起床，我迷迷糊糊应了一声。")
        except Exception:
            pass
        logger.info("[amo] 被他叫醒（夜里原因：%s）" % (reason.value if reason else "无"))

    async def _sleep_tick(self) -> None:
        """每分钟看一次：该起就起；半夜可能醒一次，记进日程和日记。"""
        if self.sleep is None:
            return
        now = _clock_now()
        if not self.sleep.is_asleep(now):
            return
        state = self.sleep.load()
        wake_day = str(state.get("wake_day") or "")
        wake_at = str(state.get("wake_at") or "")
        today = now.date().isoformat()
        hhmm = now.strftime("%H:%M")
        if (today > wake_day) or (today == wake_day and wake_at and hhmm >= wake_at):
            reason = self.sleep.today_woke_reason()
            self.sleep.wake_up(now)
            day = now.date().isoformat()
            text = "早上 %s 醒了。" % hhmm
            if reason is not None:
                text = "早上 %s 醒来。昨晚%s。" % (hhmm, reason_for(reason))
            uid = self._primary_uid()
            if uid:
                try:
                    await self._write_memory_checked(uid, text, kind="event", tier=0)
                except Exception:
                    pass
            try:
                self.db.save_diary(day, now.strftime("%H:00"), text)
            except Exception:
                pass
            logger.info("[amo] 睡醒了：%s" % text)
            return

        reason = self.sleep.maybe_night_wake(now)
        if reason is not None:
            day = now.date().isoformat()
            text = reason_for(reason)
            uid = self._primary_uid()
            if uid:
                try:
                    await self._write_memory_checked(
                        uid, "半夜 %s %s" % (hhmm, text), kind="event", tier=0)
                except Exception:
                    pass
            try:
                items = self.state.schedule.get(day) or self.db.get_schedule(day) or []
                hour = now.strftime("%H:00")
                changed = False
                for index, item in enumerate(items):
                    if str(item.get("start") or "") == hour:
                        row = dict(item)
                        row["activity"] = "半夜醒来：" + text
                        row["category"] = "rest"
                        items[index] = row
                        changed = True
                        break
                if changed:
                    self.state.schedule[day] = items
                    self.db.kv_set("schedule", self._sanitize_schedule(self.state.schedule))
                    self.db.save_schedule(day, items)
            except Exception as exc:
                logger.debug("[amo] 半夜醒来落日程失败: %s" % exc)
            try:
                existing = self.db.get_diary(day, hour) or ""
                self.db.save_diary(day, hour,
                                   (existing + "；" if existing else "") +
                                   "半夜%s，躺了一会儿又睡过去了。" % text)
            except Exception:
                pass
            logger.info("[amo] 半夜醒来：%s" % text)
            self.sleep.back_to_sleep(now)

    #: 夸她 / 凶她的说法（宁少不多，避免误判）
    PRAISE_WORDS = ("好可爱", "你真好", "好乖", "好漂亮", "真棒", "喜欢你", "爱你",
                    "想你了", "乖", "心疼你", "辛苦了", "抱抱")
    INSULT_WORDS = ("滚", "闭嘴", "烦死了", "讨厌你", "别说话", "废物", "傻", "丑",
                    "不想理你", "走开")

    def _chat_feel(self, text: str) -> None:
        """聊天里的态度加减心流，10 分钟最多各记一次。"""
        if getattr(self, "feelings", None) is None or FeelEvent is None:
            return
        body = str(text or "")
        if not body:
            return
        now = now_ts()
        try:
            marks = self.db.kv_get("chat_feel_marks", {}) or {}
        except Exception:
            marks = {}
        if not isinstance(marks, dict):
            marks = {}
        try:
            if any(word in body for word in self.PRAISE_WORDS) and now - to_float(marks.get("praise"), 0) > 600:
                self.feel(FeelEvent.CHAT_PRAISE)
                marks["praise"] = now
            elif any(word in body for word in self.INSULT_WORDS) and now - to_float(marks.get("insult"), 0) > 600:
                self.feel(FeelEvent.CHAT_INSULT)
                marks["insult"] = now
            else:
                return
        except Exception as exc:
            logger.debug("[amo] 聊天情绪事件失败: %s" % exc)
            return
        try:
            self.db.kv_set("chat_feel_marks", marks)
        except Exception:
            pass

    async def _maybe_private_shot(self, event, text) -> bool:
        """私密照片：只私聊、只主人；第一次害羞拒绝，再问按心情判定。

        判定全在本地（心情来自 heartflow 的数值），出图交给生图插件；
        提示词永远带「成年/不露点/不拍性行为」的边界。
        """
        if wants_private_shot is None or not text:
            return False
        if not event.is_private_chat() or not self._is_owner(event):
            return False
        try:
            if not wants_private_shot(text):
                return False
        except Exception:
            return False

        today = today_str()
        try:
            state = self.db.kv_get("glamour", {}) or {}
        except Exception:
            state = {}
        if not isinstance(state, dict):
            state = {}
        if str(state.get("day") or "") != today:
            state = {"day": today, "state": "none", "count": 0}
        count = int(state.get("count") or 0)
        cap = 2
        try:
            cap = max(1, self.cfg_int("private_shot_daily_cap", 2))
        except Exception:
            pass

        mood = {}
        try:
            mood = (self.feelings.values() if getattr(self, "feelings", None) else {}) or {}
        except Exception:
            mood = {}
        negative = sum(float(mood.get(k) or 0) for k in ("anger", "sadness", "fear", "disgust"))
        positive = sum(float(mood.get(k) or 0) for k in ("joy", "love", "surprise"))
        verdict = decide_shot(state.get("state"), negative, positive, count, cap)
        uid = self._primary_uid()

        def save():
            try:
                self.db.kv_set("glamour", state)
            except Exception:
                pass

        if verdict is ShotVerdict.SCOLD:
            state["state"] = "scolded"
            save()
            line = random.choice(SCOLD_LINES)
            if uid:
                try:
                    await self._write_memory_checked(
                        uid, "他要我穿%s拍照，我心情差，直接怼回去了" % shot_outfit(text),
                        kind="event", tier=0)
                except Exception:
                    pass
            await self.context.send_message(event.unified_msg_origin, line)
            try:
                event.stop_event()
            except Exception:
                pass
            return True

        if verdict is ShotVerdict.BUSY:
            await self.context.send_message(event.unified_msg_origin, "今天不行了，改天吧。")
            try:
                event.stop_event()
            except Exception:
                pass
            return True

        if verdict is ShotVerdict.SHY:
            state["state"] = "shy_refused"
            save()
            line = random.choice(SHY_LINES)
            if uid:
                try:
                    await self._write_memory_checked(
                        uid, "他要我穿%s拍照，我害羞拒绝了" % shot_outfit(text),
                        kind="event", tier=0)
                except Exception:
                    pass
            await self.context.send_message(event.unified_msg_origin, line)
            try:
                event.stop_event()
            except Exception:
                pass
            return True

        # 答应：先回话，再后台出图（不阻塞聊天）
        outfit = shot_outfit(text) or "家居服"
        pose = shot_pose(text)
        place = ""
        try:
            place = str((self._activity_snapshot(str(event.unified_msg_origin)) or {}).get("place") or "")
        except Exception:
            place = ""
        prompt = build_shot_prompt(outfit, pose, place)
        state["state"] = "granted"
        state["count"] = count + 1
        save()
        try:
            await self.context.send_message(event.unified_msg_origin, random.choice(GRANT_LINES))
        except Exception:
            pass
        if uid:
            try:
                await self._write_memory_checked(
                    uid, "他要我穿%s拍照，我答应了%s" % (outfit, ("，姿势：" + pose) if pose else ""),
                    kind="event", tier=0)
            except Exception:
                pass

        async def shoot():
            try:
                data = await self._image_bytes(prompt, event.unified_msg_origin,
                                               str(event.get_sender_id() or ""), selfie=True)
                if data:
                    await self._send_image_to_umo(event.unified_msg_origin, data, "")
            except Exception as exc:
                logger.debug("[amo] 私密照片出图失败: %s" % exc)

        try:
            self._spawn(shoot())
        except Exception:
            pass
        try:
            event.stop_event()
        except Exception:
            pass
        return True

    async def _maybe_user_move(self, event, text) -> bool:
        """他说「回来吧 / 去超市 / 别逛了」：她自己掂量愿不愿意，愿意就**先走过去**。

        - 只认私聊里的主人/恋人；
        - 心情差（生气+暴躁+郁闷+委屈偏高）：直接不答应；
        - 心情还行：答应，日程拆成「原来的活动 → 在路上 → 到达」，不瞬移；
        - 答不答应都写进记忆，她记得这件事。
        """
        if detect_schedule_change is None or apply_sched_change is None:
            return False
        if not event.is_private_chat():
            return False
        try:
            change = detect_schedule_change(text)
        except Exception:
            change = None
        if not change:
            return False

        mood = {}
        try:
            mood = (self.state.snapshot() or {}).get("mood") or {}
        except Exception:
            mood = {}
        negative = sum(float(mood.get(k) or 0) for k in ("生气", "暴躁", "郁闷", "委屈"))
        positive = sum(float(mood.get(k) or 0) for k in ("开心", "兴奋", "依恋"))
        uid = self._primary_uid()

        if negative >= 70 and positive < 60:
            line = "我不去。我现在烦着呢，别指挥我。"
            if uid:
                try:
                    await self._write_memory_checked(
                        uid, "他让我「%s」，我心情不好，直接没答应" % change.get("activity"),
                        kind="event", tier=0)
                except Exception:
                    pass
            await self.context.send_message(event.unified_msg_origin, line)
            try:
                event.stop_event()
            except Exception:
                pass
            return True

        key = _clock_now().date().isoformat()
        items = self.state.schedule.get(key) or self.db.get_schedule(key) or []
        if not items:
            return False
        try:
            travel = self.cfg_int("move_transition_minutes", 30)
            hold = self.cfg_int("move_hold_hours", 3)
            new_items = apply_sched_change(items, change, _clock_now(),
                                           transition_minutes=travel, hold_hours=hold)
        except Exception as exc:
            logger.debug("[amo] 按他的话改日程失败: %s" % exc)
            return False
        if new_items == items:
            return False
        self.state.schedule[key] = new_items
        self.db.kv_set("schedule", self._sanitize_schedule(self.state.schedule))
        self.db.save_schedule(key, new_items)
        if uid:
            try:
                await self._write_memory_checked(
                    uid, "他让我「%s」；我答应了，正在路上（%d 分钟后到 %s）"
                    % (change.get("activity"), max(0, travel), change.get("place")),
                    kind="event", tier=0)
            except Exception:
                pass
        target = str(change.get("place") or "").strip()
        if target and target not in ("路上", "车里"):
            line = "行吧，我往%s去了，路上要 %d 分钟。" % (target, max(5, travel))
        else:
            line = "行吧，我这就过去，等我 %d 分钟。" % max(5, travel)
        await self.context.send_message(event.unified_msg_origin, line)
        try:
            event.stop_event()
        except Exception:
            pass
        return True

    async def _handle_money_gift(self, event, text) -> bool:
        """他转钱/发红包给她：算借款，走金融账本。

        返回 True 表示这条消息已经处理完（不用再进聊天链路）。
        """
        if not event.is_private_chat():
            return False
        parsed = self._parse_money_gift(text)
        if not parsed:
            return False
        channel, amount, currency = parsed
        plugin = self._finance()
        borrower = getattr(plugin, "borrow", None) if plugin is not None else None
        if not callable(borrower):
            return False
        cny = amount
        if currency != "CNY":
            rate = 1.0
            reader = getattr(plugin, "fx_rate", None) if plugin is not None else None
            if callable(reader):
                try:
                    rate = float(reader(currency) or 1.0)
                except Exception:
                    rate = 1.0
            cny = round(amount * rate, 2)
        try:
            result = borrower(cny, channel, str(event.get_sender_id() or ""))
        except Exception as exc:
            logger.warning("[amo] 借款失败: %s" % exc)
            result = {"ok": False, "reason": "账本没响应"}
        if not result.get("ok"):
            reason = result.get("reason") or "借不了"
            left = result.get("left")
            if isinstance(left, dict) and left.get("transfer_left") is not None:
                reason += "（今天还能转 %.0f）" % float(left.get("transfer_left") or 0)
            yield_text = "这个我收不下：" + reason
        else:
            kind = "红包" if result.get("channel") == "red" else "转账"
            owed = float(result.get("owed") or 0)
            origin = (("%s %.2f（折合 ¥%.2f）" % (currency, amount, cny))
                      if currency != "CNY" else ("%.2f" % cny))
            yield_text = self._warm_gift_reply(kind, cny, owed, origin=origin)
            try:
                self.feel(FeelEvent.MONEY_GIFT)
            except Exception:
                pass
        try:
            await self.context.send_message(event.unified_msg_origin, yield_text)
        except Exception as exc:
            logger.debug("[amo] 回执发送失败: %s" % exc)
        try:
            event.stop_event()
        except Exception:
            pass
        self._sync_finance()
        return True

    async def _learn_relations(self, event, text, uid):
        """从对话里认关系：他说「小明是我同事」就记一条边。

        只认明确陈述 + 能在画像里唯一定位到人；管理员手动设过的不覆盖。
        """
        if parse_relations is None or not text or not uid:
            return
        try:
            pairs = parse_relations(text)
        except Exception:
            return
        if not pairs:
            return
        name_map = {}
        try:
            for item in self.db.list_profiles(limit=500):
                for key in ("name", "alias"):
                    raw = str(item.get(key) or "").strip()
                    if not raw:
                        continue
                    for piece in re.split(r"[;；,，、/|]", raw):
                        name = piece.strip()
                        if len(name) >= 2:
                            name_map.setdefault(name, set()).add(str(item.get("uid") or ""))
        except Exception:
            return
        try:
            existing = {}
            for edge in self.db.list_relations():
                pair = tuple(sorted([str(edge.get("a_uid") or ""), str(edge.get("b_uid") or "")]))
                existing[pair] = str(edge.get("note") or "")
        except Exception:
            existing = {}
        for who, relation, evidence in pairs:
            targets = [item for item in name_map.get(who, set()) if item and item != str(uid)]
            if len(targets) != 1:
                continue
            target = targets[0]
            pair = tuple(sorted([str(uid), target]))
            old_note = existing.get(pair, "")
            if old_note and not old_note.startswith("对话："):
                # 管理员手动设过的关系，不拿聊天内容覆盖
                continue
            note = "对话：" + truncate(evidence, 24)
            try:
                if not self.db.upsert_relation(uid, target, relation, note):
                    continue
                logger.debug("[amo] 关系网自动记录: %s --%s--> %s" % (uid, relation, target))
                await self._push_relation_to_data(uid, target, relation, note)
            except Exception as exc:
                logger.debug("[amo] 自动关系写入失败: %s" % exc)

    def _relation_network_text(self, uid):
        """给当前用户生成两跳内的关系网摘要；只读。

        「陌生人」只在面板图谱里出现，不进提示词——不然每句都带一串「小明和小满是陌生人」。
        """
        try:
            edges = [edge for edge in self.db.list_relations()
                     if str(edge.get("relation") or "") != "陌生人"]
        except Exception:
            return ""
        uid = str(uid or "")
        if not edges:
            return ""
        names = {}
        try:
            for item in self.db.list_profiles(limit=500):
                names[str(item.get("uid"))] = item.get("alias") or item.get("name") or str(item.get("uid"))
        except Exception:
            pass
        names["bot"] = str(getattr(self, "bot_name", "") or "你")
        picked = []
        if _rank_edges is not None:
            try:
                # 图小的时候放宽到三跳，图大了只走两跳，避免噪声和 token 膨胀
                hops = 3 if len(edges) <= 40 else 2
                picked = _rank_edges(edges, uid, 12, hops)
            except Exception:
                picked = []
        if not picked:
            direct = []
            neighbors = set()
            for edge in edges:
                a, b = str(edge.get("a_uid")), str(edge.get("b_uid"))
                if uid in (a, b):
                    direct.append(edge)
                    neighbors.add(b if a == uid else a)
            second = []
            for edge in edges:
                if edge in direct:
                    continue
                a, b = str(edge.get("a_uid")), str(edge.get("b_uid"))
                if a in neighbors or b in neighbors:
                    second.append(edge)
            picked = (direct + second)[:12]
        lines = []
        for edge in picked[:12]:
            a, b = str(edge.get("a_uid")), str(edge.get("b_uid"))
            na = names.get(a, a)
            nb = names.get(b, b)
            lines.append("%s和%s是%s" % (na, nb, edge.get("relation", "朋友")))
        return "\n".join(lines)

    def _disturb_category(self, snap):
        category = (snap.get("activity") or {}).get("category", "")
        return category in ("sleep", "work", "study")

    def _disturb_active(self, umo):
        return to_float(getattr(self, "_disturb_until", {}).get(str(umo), 0), 0) > now_ts()

    def _tone_with_continuity(self, umo, tone):
        """给语气加情绪惯性，避免上一秒发火、下一秒突然甜蜜。"""
        tone = str(tone or "")
        if self._disturb_active(umo):
            if "不要一秒变甜蜜" not in tone:
                tone += " 你刚被吵醒/打扰，还在烦躁，不要一秒变甜蜜。"
        last = getattr(self, "_last_affect", {}).get(str(umo))
        if last and now_ts() - to_float(last[0], 0) < 1200:
            previous = str(last[1] or "")
            if any(word in previous for word in ("烦躁", "暴躁", "生气", "被打扰")) and "慢慢缓和" not in tone:
                tone += " 上一轮你还在气头上，态度要慢慢缓和，不要突然撒娇甜蜜。"
        self._last_affect[str(umo)] = (now_ts(), tone)
        return tone

    def _apply_disturbance(self, umo):
        now = now_ts()
        self._disturb_until[str(umo)] = now + max(30, self.cfg_int("disturb_tone_seconds", 900))
        self._disturb_cooldown[str(umo)] = now + 120
        self._disturb_reset_at[str(umo)] = now
        last = to_float(getattr(self, "_disturb_last", {}).get(str(umo), 0), 0)
        if now - last >= 60:
            penalty = max(1, self.cfg_int("disturb_mood_penalty", 6))
            self.state.nudge(
                生气=penalty,
                郁闷=max(1, penalty // 2),
                疲惫=max(1, penalty // 2),
                开心=-max(1, penalty // 3),
            )
            self._disturb_last[str(umo)] = now
        logger.debug("[amo] 被打扰：消息过多，强制回复并降低心情（%s）" % umo)

    def _disturb_pressure(self, umo, uid, text="", group=False):
        """最近窗口内，同一个人连续发消息数 / 群里叫机器人的消息数。"""
        try:
            rows = self._recent(umo, 24)
        except Exception:
            return 0
        window = max(1, self.cfg_int("disturb_window_minutes", 10)) * 60
        cutoff = max(
            now_ts() - window,
            to_float(getattr(self, "_disturb_reset_at", {}).get(str(umo), 0), 0),
        )
        same_sender = 0
        mentions = 0
        names = [self.bot_name] + list(self.bot_aliases)
        for row in reversed(rows):
            if to_float(row.get("created_at"), 0) < cutoff:
                continue
            if row.get("role") == "bot":
                break
            if row.get("role") != "user":
                continue
            if group:
                if str(row.get("uid")) == str(uid):
                    same_sender += 1
                content = str(row.get("content") or "")
                if any(name and len(str(name)) >= 2 and str(name) in content for name in names):
                    mentions += 1
            else:
                same_sender += 1
        return max(same_sender, mentions) if group else same_sender

    def _mark_bot_initiated(self, umo):
        key = str(umo)
        self._bot_initiated[key] = now_ts()
        # 她主动发的消息代表当前是她来找你，不该延续上一轮的火气。
        self._disturb_until[key] = 0
        self._last_affect[key] = (now_ts(), "你主动发起聊天，语气自然亲昵")

    def _recent_bot_initiated(self, umo, seconds=3600):
        return now_ts() - to_float(getattr(self, "_bot_initiated", {}).get(str(umo), 0), 0) < seconds

    def _should_disturb(self, snap, umo, uid, text="", group=False):
        if not self.cfg_bool("disturb_reply_enabled", True):
            return False
        if self._recent_bot_initiated(umo):
            return False
        if not self._disturb_category(snap):
            return False
        if to_float(getattr(self, "_disturb_cooldown", {}).get(str(umo), 0), 0) > now_ts():
            return False
        threshold = max(1, self.cfg_int("disturb_reply_threshold", 3))
        return self._disturb_pressure(umo, uid, text, group=group) >= threshold

    async def _handle_message(self, event):
        if not self._ready or self.state is None:
            return
        self._reload_config_if_changed()
        await self._sync_persona_name(event)
        try:
            self.state.apply_schedule_events()
        except Exception:
            pass
        uid = self._canonical_uid(event)
        if not uid or uid == str(event.get_self_id()):
            return
        text = (event.message_str or "").strip()
        if not text:
            return
        if self._looks_like_command(text):
            return

        umo = event.unified_msg_origin
        group_id = event.get_group_id()
        private = event.is_private_chat()
        if private:
            self._clear_proactive_pending(uid)
            self._try_soothe(uid, text)
        if private and not self.cfg_bool("enable_private_reply", True):
            return
        if not private and not self.cfg_bool("enable_group_reply", True):
            return
        if private and self.cfg_bool("private_debounce_enabled", True):
            # 同一个人连着发的几条先合起来，只让最后一条走完整回复流程
            if not await self._debounce_private(event, text):
                return
            text = (event.message_str or "").strip()
            if not text:
                return

        if not private:
            try:
                self._detect_impersonation(event)
            except Exception as exc:
                logger.debug("[amo] 冒充检测失败: %s" % exc)
        await self._learn(event, text)
        self._restore_lover_relation(uid)
        profile = self.db.get_profile(uid)

        if private:
            await self._handle_private(event, profile)
            return

        # 群聊只走完整心流引擎；旧的五维门控/防抖/直发逻辑不再参与。
        if self.heartflow is None or not self.cfg_bool("hf_enable_heartflow", True):
            return
        snap = self.state.snapshot()
        if self._should_disturb(snap, umo, uid, text, group=True):
            self._apply_disturbance(umo)
            setattr(event, "amo_force_reply", True)
        try:
            await self.heartflow.on_group_message(event)
        except Exception as exc:
            logger.error("[amo] 心流处理失败: %s" % exc)

    async def _handle_private(self, event, profile):
        snap = self.state.snapshot()
        umo = event.unified_msg_origin
        uid = self._canonical_uid(event)
        if self._recent_bot_initiated(umo):
            self._disturb_until[str(umo)] = 0
            logger.info("[amo] 主动消息后的回复，按正常聊天处理")
            return
        if self._should_disturb(snap, umo, uid, event.message_str or "", group=False):
            self._apply_disturbance(umo)
            # 不 stop_event，让 AstrBot 正常生成；<amo_state> 会带上被打扰的语气。
            return
        probability = self.gate.private_probability(snap, profile)
        roll = random.random()
        logger.info(
            "[amo] 私聊判定 | 概率=%.2f | roll=%.2f | %s"
            % (probability, roll, "回复" if roll <= probability else "不回")
        )
        if roll <= probability:
            return
        event.stop_event()
        if (
            self.cfg_bool("delay_reply", True)
            and probability >= 0.20
            and profile.get("relation", "普通") not in ("仇恨", "抵触")
            and random.random() < 0.45
        ):
            self._schedule_delayed_reply(event, profile)

    async def _handle_group_directed(self, event, text, profile):
        umo = event.unified_msg_origin
        group_id = event.get_group_id()
        snap = self.state.snapshot()
        recent = self._recent(umo, 8 if self.cfg_str("context_style", "lean") == "lean" else 12)
        result = await self.gate.should_reply_group(
            umo, group_id, text, recent, True, profile, snap
        )
        if self.cfg_bool("debug_log", False):
            logger.debug("[amo] 群聊定向判定: %s" % json.dumps(result, ensure_ascii=False))
        if not result["reply"]:
            event.stop_event()

    async def _debounce_private(self, event, text):
        """私聊防抖：同一会话连发的几条合并成一句，只让最后一条继续回复。

        返回 True = 这条是这一批的最后一条（合并后的文本已写回 event.message_str）；
        返回 False = 已被合并，事件保持 stop 状态，调用方直接 return。
        """
        umo = event.unified_msg_origin
        delay = max(0.3, self.cfg_float("private_debounce_seconds", 6.0))
        max_wait = max(delay + 0.1, self.cfg_float("private_debounce_max_wait", 14.0))
        now = time.monotonic()
        buffer = self._private_buffers.get(umo)
        if buffer is None:
            buffer = {"seq": 0, "texts": [], "started": now, "updated": now}
            self._private_buffers[umo] = buffer
        buffer["seq"] += 1
        my_seq = buffer["seq"]
        buffer["texts"].append(str(text or ""))
        buffer["updated"] = now
        event.stop_event()
        deadline = buffer["started"] + max_wait
        while True:
            current = time.monotonic()
            if self._private_buffers.get(umo) is not buffer:
                return False  # 这一批已经被前面的某条发出去了
            if my_seq != buffer["seq"]:
                return False  # 后面又来了新的，交给最新的那条
            quiet_at = buffer["updated"] + delay
            if current >= quiet_at or current >= deadline:
                break
            try:
                await asyncio.sleep(min(quiet_at, deadline) - current)
            except asyncio.CancelledError:
                return False
        if self._private_buffers.get(umo) is buffer:
            self._private_buffers.pop(umo, None)
        merged = "｜".join(item for item in buffer["texts"] if item).strip()[:300]
        if len(buffer["texts"]) > 1:
            logger.info("[amo] 私聊合并 %d 条: %s" % (len(buffer["texts"]), merged[:200]))
            try:
                event.set_extra("amo_debounce_count", len(buffer["texts"]))
            except Exception:
                pass
        event.message_str = merged or (event.message_str or "")
        try:
            event.continue_event()
        except Exception:
            pass
        return True

    def _schedule_delayed_reply(self, event, profile):
        umo = event.unified_msg_origin
        delay = random.randint(
            self.cfg_int("delay_min_minutes", 4),
            self.cfg_int("delay_max_minutes", 18),
        ) * 60
        text = event.message_str or ""

        async def runner():
            try:
                await asyncio.sleep(delay)
                if not self._running or not self._ready:
                    return
                snap = self.state.snapshot()
                note = "你刚刚忙完，主动补一句；不要提等待时间，语气自然。"
                reply = await self._compose_reply(
                    event, text, snap, profile, [], "", False, note=note
                )
                if reply:
                    await self._send_to_umo(umo, reply)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.debug("[amo] 延迟回复失败: %s" % exc)

        self._spawn(runner())

    def _strip_place_marks(self, text):
        """兜底：把「东莞·商场·餐厅」这类内部地点串缩成口语的「餐厅」。"""
        value = str(text or "")
        marks = set()
        try:
            city = str((self.state.worldview or {}).get("city") or "").strip()
            if city:
                marks.add(city)
        except Exception:
            pass
        try:
            marks.add(str((self.state.current_activity() or {}).get("place") or ""))
        except Exception:
            pass
        for mark in marks:
            parts = [item.strip() for item in mark.split("·") if item.strip()]
            if len(parts) < 2:
                continue
            for index in range(len(parts) - 1, 0, -1):
                value = value.replace("·".join(parts[:index]) + "·", "")
        return value

    def _trim_reply(self, text):
        value = self._strip_place_marks(str(text or "").strip())
        limit = max(1, self.cfg_int("reply_max_sentences", 3))
        parts = [item for item in re.split(r"(?<=[。！？!?~～])", value) if item.strip()]
        if len(parts) <= limit:
            return value
        return "".join(parts[:limit]).strip()

    async def _compose_reply(self, event, text, snap, profile, memories, memory_text, group, note=""):
        umo = event.unified_msg_origin
        uid = self._canonical_uid(event)
        name = profile.get("alias") or profile.get("name") or event.get_sender_name() or "对方"
        relation = profile.get("relation", "普通")
        persona = await self.llm.persona(umo)
        world = self.state.worldview_text()
        asked_activity = bool(re.search(
            r"(你在干嘛|在干嘛|干嘛呢|干什么呢|你在哪|在哪呢|吃了吗|吃没吃|吃了没|忙吗|忙不忙"
            r"|在忙什么|上班吗|在上班|下班了吗|今天干嘛|做什么呢|干啥呢)",
            text or "",
        ))
        state_text = self.state.prompt_text(snap, with_activity=asked_activity)
        tone = self._tone_with_continuity(umo, self.state.tone_text(snap, relation))
        style = STYLE_HINTS.get(self.cfg_str("reply_style", "soft"), "")
        consult = bool(re.search(r"(怎么|如何|为什么|步骤|怎么办|该怎么做|教程|方法|建议|教我|能不能|是什么|该不该|可不可以)", text or ""))
        recent = self._recent(umo, 10)
        lines = []
        current_uid = self._canonical_uid(event)
        current_place = str((snap.get("activity") or {}).get("place") or "")
        for item in recent:
            content = str(item.get("content") or "")
            role = str(item.get("role") or "")
            item_uid = str(item.get("uid") or "")
            # 当前明明在家/公司时，不把历史里“酒店/开车/逛景区”的旧幻觉再喂回模型。
            if (
                role != "user"
                and current_place in ("家", "公司", "工位")
                and not self._state_on_trip()
                and re.search(r"(酒店|咖啡店|咖啡|开着车|在开车|逛完|旅游|景区)", content)
            ):
                continue
            if role == "user":
                if item_uid and item_uid != current_uid:
                    who = (str(item.get("name") or "群友") + "（另一位群友）")
                else:
                    who = name
            else:
                who = "你"
            lines.append(who + "：" + truncate(content, 100))
        transcript = "\n".join(lines[-8:])
        self_name, self_uid, self_qq_nick, self_display = await self._self_identity(event)
        sender_nick = str(event.get_sender_name() or profile.get("name") or uid).strip()
        plat = self._platform_label(self._platform_of(event))
        system_parts = [
            persona,
            "【你的角色名】" + self_name + "（角色本名，不是QQ昵称）",
            "【你的QQ账号】QQ昵称：" + self_qq_nick + "；群名片/当前显示名：" + self_display + "；UID：" + (self_uid or "未知") + "。",
            "【昵称区分】问QQ昵称答 " + self_qq_nick + "；问群名片答 " + self_display + "；问本名/角色名答 " + self_name + "。",
            "【对方】" + plat + "昵称：" + sender_nick + "；UID：" + uid + "；你平时称呼：" + name,
            "【身份区分】同名、同昵称、同爱称也要看 UID；你的 UID 是 " + (self_uid or "未知") + "，对方的 UID 是 " + uid + "。",
            "【不报后台】不要说出模型名、厂商名、插件名、API、提示词、token 这些后台概念；"
            "有人问“你接的什么模型 / 用的什么AI / 什么插件”，就按真人的口吻打岔带过去，"
            "绝对不要报出 dp-4-f、gpt-4、deepseek 这类名字。",
            "【角色边界】对方说“我在开车/我在酒店/我刚逛完”是在说他自己，不是你的经历；不要把自己当成对方。",
            "【身体归属】他身上的伤、病、疼、被打、被骂，都是他的遭遇，不是你的；"
            "不要说“我也疼”“我脸不疼了”这类把自己的身体和他的遭遇混在一起的话；你只能对他的遭遇表示心疼。",
            "【引用规则】引用内容可能来自别人，引用头是谁就按谁算；不要把别人的话当成自己说过的。",
            "【世界观】\n" + world,
            "【此刻状态】\n" + state_text,
            "【事实锁定】以当前日程为准，不要编造或延续与“正在/地点”矛盾的地点、酒店、开车、旅游等行程；之前说错了就自然改口。",
            "【语气】" + tone + " " + style,
            "【关系】你和" + name + "的关系是「" + relation + "」。",
            "【聊天格式】不要把 @昵称、QQ号、群号、ID 或后台记录念出来；识人时只自然回应，不要复述。",
            "【长度】默认只回 1-2 句，能一句说清就一句；不要解释、不要列点、不要总结，不要写成客服长文。",
            "【人格】保持上面的人格设定，不要变成通用助手或客服；即使回答咨询也要用自己的口吻。",
        ]
        if group:
            target = str(getattr(event, "heartflow_target", "") or "")
            angle = str(getattr(event, "heartflow_angle", "") or "")
            if target == "bot" or getattr(event, "heartflow_mode_hint", "") == "direct":
                system_parts.append(
                    "【群聊·对你说】这是群聊，不是私聊。这条是在跟你说话（叫了你的名字/@你/接你的话），"
                    "正常回答说话的人，不要客服腔，也不要用错人的关系。"
                )
            elif target:
                system_parts.append(
                    "【群聊·插话】这是群聊，这条不是在叫你，你只是自己想插一句：" + angle + "。"
                    "1-2 句、自然、像群里随口说话；不要把它当成别人问你的问题来回答，"
                    "不要复述对方的话，不要突然报日程，不要用恋人语气，也别抢话题。"
                )
            else:
                system_parts.append(
                    "【群聊】这是群聊，不是你和他私聊，群里还有别人。先看上下文判断这条是不是在跟你说话；"
                    "在跟你说话就正常回答，如果是群友之间在聊，你也可以自然插一句，但别抢话、别用恋人语气。"
                )
            roster_text = self._group_roster_text(
                umo, uid, 6 if self.cfg_str("context_style", "lean").strip().lower() == "lean" else 8
            )
            if roster_text:
                system_parts.append(
                    "【群里的人】（按 UID 认人，同名不同号不是一个人）\n" + roster_text
                )
            system_parts.append("【怎么回】" + self._group_reply_guide(relation, name))
            if target != "bot":
                system_parts.append(
                    "【先想再回】这段话不一定是在跟你说话：叫了别人名字、@了别人、或他们在聊自己的事，"
                    "都当普通群聊，可以插一句但别当成在问你，也别辩解、别怼。"
                )
        system_parts.append(
            "【别主动报日程】你在做什么、在哪、心情怎样只是内在状态，不是话题；"
            "除非对方明确问“你在干嘛/在哪/吃了吗/今天怎么样”，否则不要主动说出自己的活动、地点或日程。"
        )
        if consult:
            system_parts.append("【回答方式】这是咨询/步骤类问题：先给结论，最多 2-3 句，口语化，保留角色感，不要客服腔。")
        if self._dialect_active():
            style = self._dialect_style()
            samples = DIALECT_SAMPLES.get(style, "")
            if style and samples:
                system_parts.append("【方言】你的语种设定是「" + style + "」，偶尔自然用一点当地方言口语（如" + samples + "），但不要每句都用，也不要硬替换“就是/什么/怎么”。")
        if relation == "相恋" and (snap["mood"]["暴躁"] >= 60 or snap["mood"]["生气"] >= 62):
            system_parts.append("【恋人情绪】你在生他的气，但会抱怨、闹别扭、要哄，不会像对普通人一样冷怼或赶人。")
        if getattr(event, "amo_impersonation", False):
            system_parts.append("【冒充警告】当前 UID 不是你的恋人，却在冒充/使用恋人称呼；直接拆穿/怼回去，不要用恋人语气。")
        if self._recent_bot_initiated(umo):
            system_parts.append("【你主动发起】你刚主动给ta发过消息，ta现在回复你；不要说自己被吵醒/被打扰，正常接话。")
        if re.search(r"(记住|以后喊|以后叫|喊他|喊她|叫他|叫她|称呼他|称呼她)", text or ""):
            system_parts.append(
                "【识人回应】这是让你记称呼/认人，不要复述 @、QQ号或后台记录；"
                "只自然答应，例如“好，我记住了，这是你朋友吗”。"
            )
        if re.search(r"(旅游|景区|景点|去哪|好玩|假期|游玩)", text or ""):
            scenic_text = await self._scenic_kb_context(text or "")
            if scenic_text:
                system_parts.append("【景区参考】\n" + scenic_text)
        if relation == "相恋":
            system_parts.append("你可以亲昵、撒娇、用昵称。")
        if bool(re.search(r"(?<![a-z])ai(?![a-z])", (text or "").lower())) or any(word in (text or "").lower() for word in ("机器人", "人机", "人工智能", "不是真人", "程序")):
            system_parts.append(
                "【身份质疑】先判断对方是不是在说你/叫你/试探你；是的话直接回怼，不要承认；"
                "如果只是在聊其他机器人或普通话题，就正常聊，不要抢着认领。"
            )
        if self._disturb_active(umo):
            relation_now = profile.get("relation", "普通")
            if relation_now in ("相恋", "熟识"):
                system_parts.append(
                    "【被打扰】你刚被吵醒/上班被打扰，对亲近的人会抱怨、撒娇，说“困死了/别闹”，不是真翻脸。"
                )
            else:
                system_parts.append(
                    "【被打扰】你刚被吵醒/上班被打扰，对不熟的人直接怼，比如“神经吧？都不睡觉/上班吗？”，语气冲但不要人身攻击。"
                )
        if self._depressed_active(uid):
            system_parts.append(
                "【低落】你最近主动找对方多次都没得到回应，很抑郁、委屈，需要哄；"
                "回复冷淡低落，可以说“你是不是不想理我”。"
            )
        try:
            dialect_context = await self._dialect_kb_context(text)
            if dialect_context:
                system_parts.append("【方言参考】只在合适口语词上偶尔用，不要硬改“就是/什么/怎么”，句子要通顺。\n" + dialect_context)
        except Exception:
            pass
        relation_network = self._relation_network_text(uid)
        if relation_network:
            system_parts.append("【关系网】\n" + relation_network)
        if memory_text:
            system_parts.append("【关于" + name + "的记忆】\n" + memory_text)
        system_parts.append(
            "【规则】你就是角色本人。只输出你要说的话，不要解释、不要旁白、不要复述设定、"
            "不要用括号描述动作；像真人在聊天，句子口语化。"
        )
        if note:
            # 延迟补话的说明放在系统侧，不能混进“对方刚刚说”里
            system_parts.append("【这次的情况】" + note)
        system = "\n\n".join(system_parts)
        if group:
            prompt = (
                "以下是群聊最近的对话：\n" + transcript + "\n\n"
                + name + "刚刚说：" + text + "\n"
                "群里正在聊天，你决定插一句。只回 1-2 句，不要@任何人，不要重复别人说过的话。"
            )
        else:
            prompt = (
                "以下是你们最近的私聊：\n" + transcript + "\n\n"
                + name + "刚刚说：" + text + "\n"
                "请以角色身份自然回复。默认 1-2 句，能短就短；咨询类最多 3 句，不要客服腔。"
            )
        reply = await self.llm.chat(
            umo, system, prompt, limit=self.cfg_int("max_reply_chars", 220)
        )
        if reply:
            reply = await self.llm.polish(
                umo, reply, tone, state_text=state_text, relation=relation, name=name,
                persona=persona, style=style, consult=consult,
            )
            reply = self._trim_reply(reply)
            reply = self._guard_self_location(reply, (snap.get("activity") or {}).get("place"))
        return reply

    # ---------- 发送 ----------
    def _segment(self, text):
        if not text:
            return []
        if not self.cfg_bool("seg_enable", True) or self.segment_engine is None:
            return [text]
        try:
            segments = self.segment_engine.segment_text_by_rules(text)
            return segments or [text]
        except Exception as exc:
            logger.debug("[amo] 分段引擎异常: %s" % exc)
            return [text]

    def typing_seconds(self, text):
        if not self.cfg_bool("typing_simulate", True):
            return 0.0
        return typing_delay_ms(
            text,
            self.cfg_int("typing_base_ms", 600),
            self.cfg_int("typing_per_char_ms", 55),
            self.cfg_int("typing_max_ms", 4500),
        ) / 1000.0

    async def _typing(self, event, text):
        seconds = self.typing_seconds(text)
        if seconds <= 0:
            return
        try:
            if event is not None and hasattr(event, "send_typing"):
                await event.send_typing()
        except Exception:
            pass
        await asyncio.sleep(seconds)

    async def _segment_wait(self, event, segment, prev_segment, last_sent_at):
        """按当前分段字数补足打字时间；已过去的时间可以抵扣，但不会低于分段间隔。"""
        required = self.typing_seconds(segment)
        gap = await self._gap(prev_segment, segment)
        target = max(required, gap)
        elapsed = max(0.0, time.monotonic() - last_sent_at) if last_sent_at else 0.0
        wait = max(0.0, target - elapsed)
        logger.info(
            "[amo] 分段延迟（从上一段发送后计时） | 字数=%d | 需要=%.2fs | 已过=%.2fs | 补足=%.2fs"
            % (len(re.sub(r"\s+", "", str(segment or ""))), target, elapsed, wait)
        )
        if wait > 0.01:
            try:
                if event is not None and hasattr(event, "send_typing"):
                    await event.send_typing()
            except Exception:
                pass
            await asyncio.sleep(wait)
        return wait

    async def _gap(self, text, next_text=""):
        if self.segment_engine is not None and self.cfg_bool("seg_enable", True):
            try:
                return max(0.0, float(self.segment_engine._calculate_delay(text, next_text)))
            except Exception:
                pass
        return 0.3

    def _remember_sent_reply(self, event, text):
        """分段引擎没接手时（关掉分段 / 发送异常）的兜底记录。"""
        msg_obj = getattr(event, "message_obj", None)
        if msg_obj is not None and not getattr(msg_obj, "message_id", None):
            return  # 别的插件伪造的主动消息事件，不是这一轮的正常回复
        self._remember_bot_message(event.unified_msg_origin, text)

    def _remember_bot_message(self, umo, text):
        """把机器人自己发出去的话也写进 messages 表。

        这张表既是主动消息的上下文，也是「这句话回过没有」的唯一依据。
        正常回复走的是分段引擎，以前只写 AstrBot 的会话历史，表里没有，
        主动消息就会把已经答过的话当成没答过，再答一遍。
        """
        umo = str(umo or "").strip()
        text = str(text or "").strip()
        if not umo or not text:
            return
        last_user = ""
        try:
            saved = self._last_bot_saved.get(umo)
            try:
                for row in reversed(self._recent(umo, 4) or []):
                    if str(row.get("role") or "") == "user":
                        last_user = str(row.get("content") or "").strip()
                        break
            except Exception:
                last_user = ""
            # 同一句在 3 分钟内又发一次很常见（「嗯嗯」「好呀」）；只有「对应的
            # 他最后那句话也没变」才算重复。以前只看文字，第二次「好呀」会被丢掉，
            # 表里就变成「他还没被回过」，主动消息再把同一句答一遍。
            if saved and saved[0] == text and time.time() - saved[1] < 180:
                saved_user = str(saved[2] if len(saved) > 2 else "")
                if saved_user == last_user:
                    return
            self._ctx_remember(umo, "bot", self.bot_name, "bot", text)
            # 直接同步写进记忆终端：fire-and-forget 在 reload/退出时会丢这句
            saved = False
            store = self._data_store()
            if store is not None and callable(getattr(store, "add_message", None)):
                try:
                    store.add_message(
                        self._data_bot_id(), umo, "bot", self.bot_name, "bot", text,
                        platform=str(umo).split(":", 1)[0],
                    )
                    saved = True
                except TypeError:
                    try:
                        store.add_message(self._data_bot_id(), umo, "bot", self.bot_name, "bot", text)
                        saved = True
                    except Exception as exc:
                        logger.warning("[amo] 自己的回复写入终端失败: %s" % exc)
                except Exception as exc:
                    logger.warning("[amo] 自己的回复写入终端失败: %s" % exc)
            if not saved:
                try:
                    loop = asyncio.get_running_loop()
                    task = loop.create_task(self._data_call(
                        "add_message", self._data_bot_id(), umo, "bot", self.bot_name, "bot", text,
                        platform=str(umo).split(":", 1)[0],
                    ))
                    def _log_failed_task(task):
                        if task.cancelled():
                            return
                        exc = task.exception()
                        if exc is not None:
                            logger.warning("[amo] 自己的回复异步落库失败: %s" % exc)

                    task.add_done_callback(_log_failed_task)
                except Exception:
                    pass
            self._last_bot_saved[umo] = (text, time.time(), last_user)
        except Exception as exc:
            logger.debug("[amo] 记录自己的回复失败: %s" % exc)

    async def _send_now(self, event, text, quote_id=None):
        """跳过分段引擎直接发一条（seg 关闭时，用来绕开 AstrBot 核心的引用/@）。"""
        if Comp is None or MessageChain is None:
            return False
        chain = []
        if quote_id is not None:
            try:
                chain.append(Comp.Reply(id=quote_id))
            except Exception:
                pass
        chain.append(Comp.Plain(text))
        try:
            await event.send(MessageChain(chain))
        except Exception as exc:
            logger.error("[amo] 直接发送失败: %s" % exc)
            return False
        self._remember_sent_reply(event, text)
        try:
            self._last_reply_at[event.unified_msg_origin] = now_ts()
        except Exception:
            pass
        logger.info("[amo] 直接发送 -> %s: %s" % (event.unified_msg_origin, text[:300]))
        return True

    async def _send_to_umo(self, umo, text, quote_id=None, group=False):
        text = clean_reply(text, self.cfg_int("max_reply_chars", 220))
        if looks_like_model_leak(text):
            text = leak_deflect_text()
        if not text or not umo:
            return False
        segments = self._segment(text)
        if not segments:
            return False
        last_sent_at = 0.0
        for index, segment in enumerate(segments):
            if index > 0:
                await self._segment_wait(None, segment, segments[index - 1], last_sent_at)
            elif last_sent_at == 0.0:
                await self._segment_wait(None, segment, "", 0.0)
            chain = []
            if (
                index == 0 and quote_id is not None
                and self._quote_allowed(umo, group)
            ):
                try:
                    chain.append(Comp.Reply(id=quote_id))
                except Exception:
                    pass
            chain.append(Comp.Plain(segment))
            try:
                await self.context.send_message(umo, MessageChain(chain))
            except Exception as exc:
                logger.warning("[amo] 主动发送失败: %s" % exc)
                if index > 0:
                    # 前面的分段已经发出去了，返回 True，别让换边逻辑整段重发
                    partial = "\n".join(segments[:index])
                    self._remember_bot_message(umo, partial)
                    self._last_reply_at[umo] = now_ts()
                    return True
                return False
            last_sent_at = time.monotonic()
        self._last_reply_at[umo] = now_ts()
        logger.info("[amo] 主动 -> %s: %s" % (umo, text[:300]))
        self._remember_bot_message(umo, text)
        return True

    # ---------- LLM 注入 ----------
    @staticmethod
    def _short_place(place):
        """把「东莞·商场·餐厅」这种内部写法缩成口语里的「餐厅」。"""
        value = str(place or "").strip()
        if "·" in value:
            value = value.split("·")[-1].strip() or value
        return value or "家"

    def _guard_self_location(self, text, place):
        value = str(text or "")
        place = self._short_place(place)
        if not value or not place:
            return value
        if place in ("家", "家里"):
            value = re.sub(
                r"我(?:刚|正|一直|还|才)?(?:在|回|去|到)(?:酒店|咖啡店|景区|外面|路上)",
                "我在家", value,
            )
            value = re.sub(r"(?:酒店|咖啡店|景区)", "家", value)
        else:
            value = re.sub(
                r"我(?:刚|正|一直|还|才)?(?:窝)?在(?:家|家里)",
                "我在" + place, value,
            )
        return value

    async def _self_identity(self, event):
        uid = ""
        try:
            uid = str(event.get_self_id() or "")
        except Exception:
            pass
        role_name = str(self.persona_name or self.bot_name or "陪伴")
        display_name = ""
        for attr in ("get_self_name", "get_bot_name"):
            try:
                value = getattr(event, attr, None)
                if callable(value):
                    value = value()
                if value:
                    display_name = str(value)
                    break
            except Exception:
                continue
        qq_nick = ""
        if uid and getattr(self, "_self_nickname_uid", "") == uid:
            qq_nick = str(getattr(self, "_self_nickname", "") or "")
        if uid and not qq_nick:
            try:
                api = getattr(getattr(event, "bot", None), "api", None)
                action = getattr(api, "call_action", None)
                if callable(action):
                    result = action("get_login_info")
                    if inspect.isawaitable(result):
                        result = await asyncio.wait_for(result, timeout=3)
                    data = result.get("data") if isinstance(result, dict) and isinstance(result.get("data"), dict) else result
                    if isinstance(data, dict):
                        qq_nick = str(data.get("nickname") or "")
                        if data.get("user_id"):
                            uid = str(data.get("user_id"))
                    if not qq_nick and uid:
                        stranger = action("get_stranger_info", user_id=int(uid))
                        if inspect.isawaitable(stranger):
                            stranger = await asyncio.wait_for(stranger, timeout=3)
                        stranger_data = stranger.get("data") if isinstance(stranger, dict) and isinstance(stranger.get("data"), dict) else stranger
                        if isinstance(stranger_data, dict):
                            qq_nick = str(stranger_data.get("nickname") or "")
            except Exception as exc:
                logger.debug("[amo] 获取机器人QQ昵称失败: %s" % exc)
        if not qq_nick:
            qq_nick = display_name or role_name
            logger.info("[amo] get_login_info 不可用，QQ昵称回退为 %s" % qq_nick)
        if not display_name:
            display_name = qq_nick
        if uid:
            self._self_nickname = qq_nick
            self._self_nickname_uid = uid
            self._self_display = display_name
        if getattr(self, "_self_identity_logged", "") != (uid + "|" + qq_nick + "|" + display_name):
            self._self_identity_logged = uid + "|" + qq_nick + "|" + display_name
            logger.info(
                "[amo] 自身身份 | 角色名=%s | QQ昵称=%s | 显示名=%s | UID=%s"
                % (role_name, qq_nick, display_name, uid or "未知")
            )
        return role_name, uid, qq_nick, display_name

    LEAN_PARTS = {
        "【昵称区分】": None,
        "【角色边界】": "【角色边界】他说“我在开车/在酒店/刚逛完”说的是他自己，不是你的经历。",
        "【身体归属】": "【身体归属】他的伤/病/疼/被打都是他的事，不是你的事；别说“我也疼/我脸不疼了”。",
        "【引用规则】": "【引用规则】引用的话按引用头算是谁说的，不要当成自己说过的。",
        "【天气一致】": "【天气一致】天气以【天气】为准，不要说反。",
        "【地点写法】": "【地点写法】地点用口语说，不要念“城市·地点”。",
        "【别编】": "【别编】对方没明说的（进店/点好/买好/在开车）不要替他当成事实。",
        "【别翻旧账】": "【别翻旧账】同一个问题再问就正常再答，不说“刚说过了/问几遍了”。",
        "【问题怎么答】": "【问题怎么答】问吃什么：先说你自己吃什么，再给一两个具体建议。",
        "【事实锁定】": "【事实锁定】不编和地点矛盾的行程。",
        "【聊天格式】": "【聊天格式】不要复述 @昵称、账号、群号、ID。",
        "【长度】": "【长度】默认 1-2 句，能一句说清就一句，不列点不总结。",
        "【人格】": "【人格】保持人格设定，不要变成客服或通用助手。",
    }

    def _lean_parts(self, parts):
        """精简模式：合并重复禁令、去掉多余解释；full 模式原样保留。"""
        if self.cfg_str("context_style", "lean").strip().lower() != "lean":
            return parts
        out = []
        for part in parts:
            tag = ""
            if isinstance(part, str) and part.startswith("【"):
                end = part.find("】")
                if end > 0:
                    tag = part[:end + 1]
            if tag in self.LEAN_PARTS:
                replacement = self.LEAN_PARTS[tag]
                if replacement is None:
                    continue
                out.append(replacement)
                continue
            out.append(part)
        return out

    def _leek_lines(self) -> list:
        """韭菜特质：涨了上头要加仓，亏了死扛半夜哭。

        这是「心流设定」的一部分：不改判定阈值，只在上下文里给她这套反应，
        让她在该吹牛的时候吹牛、该嘴硬的时候嘴硬。买卖是她自己的事，
        这里没有任何按钮——她加没加仓、加没加成，都在上下文里告诉她。
        """
        inv = getattr(self.state, "invest", None) or {}
        stance = str(inv.get("stance") or "")
        leek = inv.get("leek") or {}
        lines = []
        if stance == "overconfident":
            lines.append(
                "【韭菜·上头】今天账户涨得不错，你觉得自己就是巴菲特转世：可以吹牛、"
                "说“我要把咱们买房钱全投进去”“我就是股神”。加仓是你自己的事，"
                "想加就自己加，不用等他点头。"
            )
            kind = str(leek.get("kind") or "")
            if kind == "bought":
                lines.append(
                    "【刚加了仓】你今天已经又买了 %s %s 股，觉得自己神了，"
                    "可以邀功、可以得意，但别把数字说错。"
                    % (leek.get("name") or "一只股票", int(leek.get("qty") or 0))
                )
            elif kind == "no_money":
                lines.append(
                    "【加仓加不了】你想加仓，但卡里没钱了。别硬撑：可以跟他撒娇要钱"
                    "（“给我转点嘛，这次真的能赚”），他不会主动给，得你自己开口。"
                )
            elif kind == "no_room":
                lines.append(
                    "【仓位到顶】你想加仓，但这一只已经压到你给自己定的上限了，只能作罢。"
                    "嘟囔两句（“胆小鬼才不满仓”），可以换一只继续买，或者跟他撒个娇要点钱。"
                )
        if stance == "hodl":
            lines.append(
                "【韭菜·死扛】今天亏了，你死扛不卖，嘴上要硬："
                "“我不卖就不算亏”“跌了迟早会涨回来”。别承认自己慌。"
            )
            try:
                hour = _clock_now().hour
            except Exception:
                hour = 12
            if hour >= 22 or hour < 2:
                lines.append(
                    "【半夜哭诉】现在很晚了，你一个人越想越难受，可以小声跟他说"
                    "“我不卖就不算亏对不对……呜呜”，要像真人，别像 AI 总结。"
                )
        return lines

    def _money_line(self) -> str:
        """她知道自己有多少钱——不知道就会说出「我没钱」这种和账本矛盾的话。"""
        try:
            cash = float((self.state.finance or {}).get("balance") or 0)
        except Exception:
            cash = 0.0
        return "【钱】你卡里还有 ¥%.0f（这是你自己的钱，花之前心里有数）" % cash

    def _gift_line(self) -> str:
        """他刚给过钱：让她记得甜一下、谢他，别装作没发生。"""
        plugin = self._finance()
        reader = getattr(plugin, "money_gift", None) if plugin is not None else None
        if not callable(reader):
            return ""
        try:
            note = reader() or {}
            amount = float(note.get("amount") or 0)
        except Exception:
            return ""
        if amount <= 0:
            return ""
        channel = "红包" if str(note.get("channel") or "") == "red" else "转账"
        return (
            "【他刚给了你钱】%d 秒前他给你发了 %s %.0f（现在欠他 %.0f）。"
            "要有点被宠到的开心，自然地说一句「老公今天怎么对我这么好啊」之类的话，"
            "谢谢他，别装作没发生，也别只报数字。"
            "这钱是让你吃好点、买点好吃的，不是让你拿去补仓；先把自己喂饱。"
            "这笔钱是给你**吃好的**：下一顿点顿像样的（按你口味），别拿去买泡面/最便宜的凑合。"
            % (int(note.get("seconds") or 0), channel, amount,
               float(note.get("owed") or 0))
        )

    def _borrow_line(self) -> str:
        """没钱的时候她得开口借——他转过来才算借款，不会凭空有钱。"""
        try:
            cash = float((self.state.finance or {}).get("balance") or 0)
        except Exception:
            cash = 0.0
        if cash >= 500:
            return ""
        plugin = self._finance()
        info = {}
        reader = getattr(plugin, "borrow_info", None) if plugin is not None else None
        if callable(reader):
            try:
                info = reader() or {}
            except Exception:
                info = {}
        return (
            "【没钱了】卡里只剩 ¥%.0f，你又不想跟他哭穷得太难看。可以开口借："
            "告诉他转账还是红包（转账每天最多一万，红包单个最多 200、累计最多一万），"
            "他会用「[转账]多少钱」或「[红包]多少钱」给你。这是**借款**，你记得要还"
            "（已经欠他 ¥%.0f）。"
            % (cash, float(info.get("owed") or 0))
        )

    def _debt_line(self) -> str:
        """欠他钱的时候：更依赖、更黏，但别把「还钱」天天挂嘴上。"""
        plugin = self._finance()
        reader = getattr(plugin, "borrow_info", None) if plugin is not None else None
        if not callable(reader):
            return ""
        try:
            info = reader() or {}
            owed = float(info.get("owed") or 0)
        except Exception:
            return ""
        if owed <= 0:
            return ""
        return (
            "【你欠他 ¥%.0f】这些是借款，没有利息——正因如此你更依赖他、更黏他。"
            "手里有钱、觉得该还的时候，用 amo_repay 转给他（记成还款，不是消费）；"
            "别天天把欠钱挂嘴上，也别装作没这回事。"
            % owed
        )

    def _repay_line(self) -> str:
        """刚还过钱：让他知道，但别邀功。"""
        plugin = self._finance()
        reader = getattr(plugin, "money_repay", None) if plugin is not None else None
        if not callable(reader):
            return ""
        try:
            note = reader() or {}
            amount = float(note.get("amount") or 0)
        except Exception:
            return ""
        if amount <= 0:
            return ""
        return (
            "【你刚还了他钱】%d 秒前你给他转了 %.0f，还欠 %.0f。"
            "可以自然地说一句「我还你钱啦」，别邀功、别报流水。"
            % (int(note.get("seconds") or 0), amount,
               float(note.get("remaining") or 0))
        )

    def _drive_line(self, snap) -> str:
        """她自己日程里在开车：别把「我在开」说成「你在开」。"""
        activity = snap.get("activity") or {}
        text = "%s %s" % (activity.get("activity") or "", activity.get("place") or "")
        if not any(word in text for word in ("开车", "驾车", "路上", "通勤", "堵车")):
            return ""
        return (
            "【开车的是你】现在「%s（%s）」是你自己的日程，不是他。"
            "说你自己的事要用「我」：我在开车、我路上慢点，别反过来说成他在开。"
            % (activity.get("activity") or "在路上",
               self._short_place(activity.get("place") or ""))
        )

    def _sick_line(self, snap) -> str:
        """生病时会难受、会想被照顾，但不会自己跑去医院。"""
        health = snap.get("health") or {}
        status = str(health.get("status") or "")
        note = str(health.get("note") or "")
        return (
            "【生病】你现在得了%s，%s。整个人难受、没力气、想被照顾。"
            "有钱的话你会自己去看病（医疗那边会自动判断）；钱不够就先扛着，"
            "他催你去医院时，可以委屈地说没钱，等他转钱给你、说带你去，你才去。"
            "别硬撑着说没事。" % (status, note or "浑身不舒服")
        )

    async def notify_repay(self, amount, remaining=0.0) -> bool:
        """金融自动还款后，主动发一条私聊：转账记录 + 一句人话。"""
        umo = self._last_umo or self._first_private_umo()
        if not umo:
            return False
        try:
            amount = float(amount or 0)
            remaining = float(remaining or 0)
        except Exception:
            return False
        if amount <= 0:
            return False
        text = "（转账）¥%.2f\n老公，我还你钱啦～" % amount
        text += ("还欠你 ¥%.2f。" % remaining) if remaining > 0 else "还清啦！"
        try:
            await self.context.send_message(umo, text)
        except Exception as exc:
            logger.debug("[amo] 还款消息发送失败: %s" % exc)
            return False
        self._sync_finance()
        logger.info("[amo] 已发还款消息：%.2f，剩 %.2f" % (amount, remaining))
        return True

    def _invest_line(self) -> str:
        """她知道自己有股票、持了什么、今天赚赔——不然用户让她买，她完全不知道有这回事。"""
        inv = getattr(self.state, "invest", None) or {}
        positions = inv.get("positions") or []
        aggressive = bool(inv.get("aggressive"))
        bankrupt = inv.get("bankrupt") or {}
        if not positions:
            if aggressive:
                return ("【投资】你还没有持仓，但你是 FX 战士：看准了就该重仓上，"
                        "别只买一手、别怕亏。")
            return "【投资】你还没有持仓，闲钱可以买一点（别一把梭，别超过总资产三成）。"
        parts = []
        for pos in positions[:6]:
            parts.append("%s %d股（%.1f%%）" % (
                pos.get("name") or "?", int(pos.get("qty") or 0),
                float(pos.get("pnl_pct") or 0)))
        day = float(inv.get("day_pnl") or 0)
        text = "【投资】你持有：" + "、".join(parts)
        text += "；今天%s¥%.0f" % ("赚了" if day >= 0 else "亏了", abs(day))
        text += "。有人问你股票、亏没亏、买没买，就照这个说，别装作没有这回事。"
        if aggressive:
            text += ("你现在是 FX 战士模式：敢重仓、敢加仓，赚了要吹，亏了嘴硬，"
                     "不承认自己是韭菜。")
        level = str(bankrupt.get("level") or "")
        try:
            pnl_pct = abs(float(bankrupt.get("pnl_pct") or 0))
            cash = float(bankrupt.get("cash") or 0)
        except Exception:
            pnl_pct, cash = 0.0, 0.0
        if level in ("ruined", "broke"):
            text += (" 你已经亏到快破产了（浮亏 %.0f%%，卡里只剩 ¥%.0f）。"
                     "可以哭唧唧地跟他说“老公我好像有点破产了”，"
                     "要他转账/发红包救你；他给了你要甜甜地谢他，别装没事。"
                     % (pnl_pct, cash))
        elif level == "losing":
            text += " 最近亏得有点多，嘴上还硬，心里已经开始发慌了。"
        return text

    async def _dynamic_context(self, event):
        await self._sync_persona_name(event)
        umo = event.unified_msg_origin
        try:
            await self._hydrate_recent(umo, 30)
        except Exception:
            pass
        uid = self._canonical_uid(event)
        profile = self.db.get_profile(uid)
        relation = profile.get("relation", "普通")
        try:
            await self._maybe_follow_city(event, uid, profile)
        except Exception as exc:
            logger.debug("[amo] 城市跟随失败: %s" % exc)
        wander_text = ""
        try:
            wander_text = await self._maybe_wander(event, uid, profile)
        except Exception as exc:
            logger.debug("[amo] 旅游意愿失败: %s" % exc)
        snap = self.state.snapshot()
        # 这一轮「她在哪、在干嘛」只取一次：聊天注入和随后那张照片必须用同一份，
        # 否则她刚说在酒店，下一分钟出图按新日程换成景区，看起来就是骗人。
        try:
            self._remember_turn_activity(umo, snap.get("activity") or {})
        except Exception:
            pass
        _, memory_text = await self._recall(uid, event.message_str or "", event)
        self_name, self_uid, self_qq_nick, self_display = await self._self_identity(event)
        alias = str(profile.get("alias") or "").strip()
        sender_nick = str(event.get_sender_name() or profile.get("name") or uid).strip()
        plat = self._platform_label(self._platform_of(event))
        cross_text = ""
        try:
            cross_text = await self._cross_platform_context(event, uid)
        except Exception as exc:
            logger.debug("[amo] 跨平台上下文失败: %s" % exc)
        time_text = ""
        try:
            time_text = await self._time_recall_context(event, uid)
        except Exception as exc:
            logger.debug("[amo] 按时间回看失败: %s" % exc)
        try:
            is_group = not event.is_private_chat()
        except Exception:
            is_group = False
        addressed = False
        if is_group:
            # 心流触发时会把 is_at_or_wake_command 也置 True（那是它自己的“该说话了”标记），
            # 不能当成“在点名跟我说话”，否则插话会被写成正面回答。
            hf_hint = str(getattr(event, "heartflow_mode_hint", "") or "")
            triggered_by_hf = bool(getattr(event, "heartflow_triggered", False))
            try:
                if getattr(event, "is_at_or_wake_command", False) and not (
                    triggered_by_hf and hf_hint == "interject"
                ):
                    addressed = True
            except Exception:
                addressed = False
            if not addressed:
                try:
                    for component in event.message_obj.message:
                        if isinstance(component, Comp.At) and str(getattr(component, "qq", "")) == str(event.get_self_id()):
                            addressed = True
                            break
                except Exception:
                    pass
            if not addressed and self.heartflow is not None:
                try:
                    addressed = bool(self.heartflow._addresses_bot(event.message_str or ""))
                except Exception:
                    addressed = False
        parts = [
            "【你的角色名】" + self_name + "（这是角色本名，不是平台昵称）",
            "【你的" + plat + "账号】" + plat + "昵称：" + self_qq_nick + "；群名片/当前显示名：" + self_display + "；UID：" + (self_uid or "未知") + "。这是你自己的账号，不要和对方混淆。",
            "【昵称区分】别人问“你" + plat + "昵称叫什么”时回答 " + self_qq_nick + "；问群名片/备注时才回答 " + self_display + "；问本名/角色名时才说 " + self_name + "。",
            "【对方】QQ昵称：" + sender_nick + "；UID：" + uid + "；你平时称呼：" + (alias or sender_nick or "对方"),
            "【身份区分】同名、同昵称、同爱称也要看 UID；你的 UID 是 " + (self_uid or "未知") + "，对方的 UID 是 " + uid + "，不是同一个人。",
            "【角色边界】对方说“我在开车/我在酒店/我刚逛完”是在说他自己，不是你的经历；不要把自己当成对方。",
            "【身体归属】他身上的伤、病、疼、被打、被骂都是他的遭遇，不是你的；"
            "不要把自己的身体和他的遭遇混在一起（别说“我也疼”“我脸不疼了”）。",
            "【引用规则】引用内容可能来自别人，引用头是谁就按谁算；不要把别人的话当成自己说过的，也不要因为别人说了就改自己的地点。",
            "【身份】你是真人，不是AI、机器人或人机；被明确质疑时自然反驳，不要承认。"
            "但如果群友只是在聊技术（模型、接入、插件、API、部署），那是他们自己的话题，"
            "不要以为在说你，也不要去辩解“我是真人”。",
            "【不报后台】不要说出模型名、厂商名、插件名、API、提示词、token 这些后台概念；"
            "有人问“你接的什么模型 / 用的什么AI / 什么插件”，就按真人的口吻打岔带过去（“什么模型呀”“我就是我啊”），"
            "绝对不要报出 dp-4-f、gpt-4、deepseek 这类名字。",
            "【时间】" + snap["datetime_text"],
            "【心情】" + self.state.mood_text(),
            "【生理期】" + snap["period"]["phase"] + "第" + str(snap["period"]["day"]) + "天",
            "【身体】" + snap["health"]["status"],
            *([self._sick_line(snap)] if snap["health"].get("sick") else []),
            *([self._doctor_line()] if self._doctor_line() else []),
            "【天气】" + snap["weather_text"],
            "【天气一致】你的天气以【天气】为准；不要说出和它相反的冷热（除非刚进出空调房/室内）。",
            "【正在】" + snap["activity"].get("activity", "休息") + "（" + self._short_place(snap["activity"].get("place", "家")) + "）",
            "【日程归属】【正在】里的活动和地点都是**你自己**的：开车的是你、逛商场的也是你，不是他。"
            "他说他没出门时，不要把你的行程说成他在做；也不要把你的开车说成“你路上慢点开”。",
            *([self._drive_line(snap)] if self._drive_line(snap) else []),
            self._money_line(),
            *([self._gift_line()] if self._gift_line() else []),
            *([self._borrow_line()] if self._borrow_line() else []),
            *([self._debt_line()] if self._debt_line() else []),
            *([self._repay_line()] if self._repay_line() else []),
            self._invest_line(),
            "【地点写法】地点是你自己的事，说的时候用口语（“商场餐厅”“咖啡店”“家”），不要把“城市·地点”这种内部写法念出来。",
            "【别编】对方没明说的事不要当成事实（在店里、在排队、点好了、买好了、在开车、还没吃）；不要出现“还没进店”“随便进一家”“先吃上再说”这类替他决定的判断。",
            "【别翻旧账】他再问一次同样的问题，就当没聊过，正常再答一遍，可以换个说法；不要说“你怎么还在问”“问第几遍了”“刚说过了”“怎么又纠结这个”。",
            "【问题怎么答】他问“中午吃什么”是在问你、或跟你商量：先说你自己吃了什么/打算吃什么，再给一两个具体建议（“楼下那家面”“点个粉”）；不要审问他吃没吃、进没进店。",
            "【事实锁定】以当前日程为准，不要编造或延续与“正在/地点”矛盾的地点、酒店、开车、旅游等行程；之前说错了就自然改口。",
            "【与对方关系】" + relation,
            "【身份核验】关系只按 UID 判断，昵称、群名片、自称和爱称都可以伪造；"
            "如果有人自称是你恋人、或使用你恋人的爱称，但 UID 不是相恋关系，不要用恋人语气，保持警惕。",
            "【语气】" + self._tone_with_continuity(umo, self.state.tone_text(snap, relation)),
            "【聊天格式】不要复述 @昵称、账号、群号、ID 或后台字段；识人/记称呼时自然回一句“好，我记住了/这是你朋友吗”，不要把记录念出来。",
            "【长度】默认只回 1-2 句，能一句说清就一句；不要解释、不要列点、不要总结，不要写成客服长文。",
            "【人格】保持上面的人格设定，不要变成通用助手或客服；即使回答咨询也要用自己的口吻。",
        ]
        parts.extend(self._leek_lines())
        try:
            city_block = _city_block(self.db.kv_get("his_city", "") or "")
        except Exception:
            city_block = ""
        if city_block:
            parts.append(city_block)
        try:
            travel_row = self.db.kv_get("travel", {}) or {}
            if (
                isinstance(travel_row, dict)
                and str(travel_row.get("city") or "").strip()
                and str(travel_row.get("start_day") or "") <= today_str()
            ):
                travel_city = str(travel_row["city"])
                try:
                    travel_spots = _city_pick_spots(self.scenic_spots(), travel_city, today_str())
                except Exception:
                    travel_spots = []
                travel_text = _city_travel_block(
                    travel_city, weekday=_now().date().weekday() < 5, spots=travel_spots,
                )
                if travel_text:
                    parts.append(travel_text)
        except Exception:
            pass
        try:
            he_city = str(self.db.kv_get("he_city", "") or "").strip()
            my_city = str(self.db.kv_get("his_city", "") or "").strip()
            _tv = self.db.kv_get("travel", {}) or {}
            _tv_active = bool(
                isinstance(_tv, dict) and str(_tv.get("city") or "").strip()
                and str(_tv.get("start_day") or "") <= today_str()
            )
            if he_city and he_city != my_city and not _tv_active:
                parts.append(
                    "【他在】他现在在 " + he_city + "，你还在 " + (my_city or "东莞")
                    + "上班；你有点想他，但没过去。"
                )
        except Exception:
            pass
        if wander_text:
            parts.append(wander_text)
        if is_group:
            target = str(getattr(event, "heartflow_target", "") or "")
            angle = str(getattr(event, "heartflow_angle", "") or "")
            mode = str(getattr(event, "heartflow_mode_hint", "") or "")
            if mode == "direct" or addressed or target == "bot":
                parts.append(
                    "【群聊·对你说】这是群聊，说话的是 " + sender_nick + "。这条是在跟你说话"
                    "（叫了你的名字 / @你 / 接着你的话说），正常回答他，不要客服腔，也不要串到别人的关系上。"
                )
            elif mode == "interject" or target:
                parts.append(
                    "【群聊·插话】这是群聊，说话的是 " + sender_nick + "。这条不是在叫你，"
                    "你只是自己想插一句：先把上下文里他们在聊的事看懂，再" + (angle or "顺着话题接一句") + "。"
                    "要求：1-2 句、自然、像群里随口说话；不要把它当成别人问你的问题来回答，"
                    "不要复述对方的话，不要突然报自己的日程或地点，不要用恋人语气，也别把话题抢过来。"
                )
            else:
                parts.append(
                    "【群聊】这是群聊，不是你和他私聊，群里还有别的成员，说话的是 " + sender_nick + "。"
                    "先看上下文判断这条是不是在跟你说话：在跟你说话就正常回答；"
                    "如果是群友之间在聊，你也可以自然插一句，但别抢话、别用恋人语气。"
                )
            parts.append(
                "【群聊称呼】不要叫群里的人“老公/宝贝/亲爱的”，除非关系确实是相恋；"
                "对普通群友就叫昵称或“你”。"
            )
            roster_text = self._group_roster_text(umo, uid)
            if roster_text:
                parts.append(
                    "【群里的人】（按 UID 认人，同名不同号不是一个人）\n" + roster_text
                )
            parts.append("【怎么回】" + self._group_reply_guide(relation, sender_nick))
            # 用上下文判断“是不是在说她”：已经点了名才按指名处理，否则先看话题和在场的人
            if not (addressed or target == "bot"):
                parts.append(
                    "【先想再回】群里好几个人在说话，先看清这句话是在跟谁说的："
                    "叫了别人名字、@了别人、两个人一问一答、或者在聊他们自己的事（工作/游戏/技术），"
                    "都不是在跟你说话——这种时候可以插一句，但别当成在问你，也别辩解、别怼。"
                )
            try:
                speakers = self._group_speaker_count(umo)
            except Exception:
                speakers = 0
            quote_at = self.cfg_int("quote_group_speaker_threshold", 3)
            if speakers:
                parts.append(
                    "【群聊人数】最近十分钟有 %d 个人在说话%s。"
                    % (speakers, "，人多、消息刷得快，回话尽量短" if quote_at > 0 and speakers >= quote_at else "")
                )
        parts.append(
            "【别主动报日程】你在做什么、在哪、心情怎样，是你的内在状态，**不是话题**。"
            "除非他明确问“你在干嘛/在哪/吃了吗/今天怎么样”，否则不要主动说出自己的活动、地点、日程安排；"
            "不要把【正在】【天气】【生理期】这些字段念出来或当成开场白。"
        )
        parts.append(
            "【被问到就这样答】他问“你在干嘛/在哪/吃了吗”，一句话带过就行"
            "（“在上班呢，怎么啦”），说完立刻把话头递回去；"
            "别用“我在…呢”开头，也别顺势报一整天安排。"
        )
        try:
            _diary_q = str(event.message_str or "")
            if any(word in _diary_q for word in ("日记", "偷看", "日记本")):
                _diary_seed = str(_diary_q) + "|" + str(now_ts() // 60)
                _written_hints = _diary_pick_hints(_DIARY_WRITTEN, 8, _diary_seed)
                _show_hints = _diary_pick_hints(_DIARY_SHOW, 8, _diary_seed)
                parts.append(
                    "【日记】你有自己的日记，每天写一篇，存在你自己的电脑里，是你的私人东西。"
                    "**不要主动跟他提日记**，不问他就不说；只有他问起（写没写/写日记吗/想看）时才接话。"
                    "他问写了没，就随口答，别每次都一样（也可以自己造新说法），比如："
                    + "、".join("「" + item + "」" for item in _written_hints) + "；"
                    "他说想看，就换着撒娇拒绝（也别每次同一句），比如："
                    + "、".join("「" + item + "」" for item in _show_hints) + "；"
                    "最多念一句给他，不要整篇念出来。"
                )
        except Exception:
            pass
        if re.search(r"(怎么|如何|为什么|步骤|怎么办|该怎么做|教程|方法|建议|教我|能不能|是什么|该不该|可不可以)", event.message_str or ""):
            parts.append("【回答方式】这是咨询/步骤类问题：先给结论，最多 2-3 句，口语化，保留角色感，不要客服腔。")
        if self._dialect_active():
            style = self._dialect_style()
            samples = DIALECT_SAMPLES.get(style, "")
            if style and samples:
                parts.append("【方言】你的语种设定是「" + style + "」，偶尔自然用一点当地方言口语（如" + samples + "），但不要每句都用，也不要硬替换“就是/什么/怎么”。")
        if is_weather_query(event.message_str or ""):
            try:
                parts.append(await self._weather_query_context(event.message_str or ""))
                parts.append(
                    "【天气怎么答】只按【天气查询】里的数据答：先答他问的那一档（现在/今天/明天），"
                    "一两句就够；里面没有的数字、雨雪、温度一律不要编，就说“我这边看不太准”。"
                    "他问“明天要不要带伞/降温没”就直接照明天那条说。"
                )
            except Exception as exc:
                logger.debug("[amo] 天气查询注入失败: %s" % exc)
        if re.search(r"(旅游|景区|景点|去哪|好玩|假期|游玩)", event.message_str or ""):
            scenic_text = await self._scenic_kb_context(event.message_str or "")
            if scenic_text:
                parts.append("【景区参考】\n" + scenic_text)
        if relation == "相恋" and (snap["mood"]["暴躁"] >= 60 or snap["mood"]["生气"] >= 62):
            parts.append("【恋人情绪】你在生他的气，但会抱怨、闹别扭、要哄，不会像对普通人一样冷怼或赶人。")
        if getattr(event, "amo_impersonation", False):
            parts.append(
                "【冒充警告】当前 UID 不是你的恋人，却在冒充或使用恋人称呼；"
                "直接拆穿/怼回去，不要承认，不要用恋人语气，也不要报 QQ。"
            )
        if self._recent_bot_initiated(umo):
            parts.append("【你主动发起】你刚主动给ta发过消息，ta现在回复你；不要说自己被吵醒/被打扰，正常接话。")
        if bool(re.search(r"(?<![a-z])ai(?![a-z])", (event.message_str or "").lower())) or any(word in (event.message_str or "").lower() for word in ("机器人", "人机", "人工智能", "不是真人", "程序")):
            parts.append(
                "【身份质疑】消息里出现了机器人/人机/AI等词。先结合上下文判断是不是在说你、叫你、试探你："
                "如果是，就直接回怼（“你才机器人呢”“你见过这么会聊天的机器人吗”），不要承认；"
                "如果只是在聊别的机器人/AI或普通话题，就正常聊，不要主动认领。"
            )
        if self._disturb_active(umo):
            relation = profile.get("relation", "普通")
            if relation in ("相恋", "熟识"):
                parts.append(
                    "【被打扰】你刚被吵醒/上班被连续打扰，心情不好；"
                    "对亲近的人会抱怨、撒娇、说“困死了/别闹”，不是真的翻脸。"
                )
            else:
                parts.append(
                    "【被打扰】你刚被吵醒/上班被连续打扰，心情很差；"
                    "对不熟的人会直接怼：比如“神经吧？都不睡觉/上班吗？”，语气冲，但不要人身攻击。"
                )
        if self._depressed_active(uid):
            parts.append(
                "【低落】你最近主动找对方多次都没得到回应，现在很抑郁、委屈，"
                "需要对方哄你；回复会冷淡、低落，或者直接说“你是不是不想理我”。"
            )
        try:
            dialect_context = await self._dialect_kb_context(event.message_str or "")
            if dialect_context:
                parts.append("【方言参考】只在合适口语词上偶尔用，不要硬改“就是/什么/怎么”，句子要通顺。\n" + dialect_context)
        except Exception:
            pass
        relation_network = self._relation_network_text(uid)
        if relation_network:
            parts.append("【关系网】\n" + relation_network)
        if memory_text:
            parts.append("【关于对方的记忆】\n" + memory_text)
        if cross_text:
            parts.append(cross_text)
        if time_text:
            parts.append(time_text)
        # 私聊最近几句（含她自己说过的话）：防止「刚说完就不认」
        if render_recent_block is not None:
            try:
                rows_now = self._recent(umo, 6 if is_group else 10)
                body_now = (event.message_str or "").strip()
                rows_now = [
                    row for row in rows_now
                    if not (str(row.get("role")) == "user"
                            and str(row.get("content") or "").strip() == body_now)
                ]
                keep = 4 if is_group else 8
                recent_text = render_recent_block(rows_now[-keep:], "你", keep)
            except Exception:
                recent_text = ""
            if recent_text:
                parts.append(
                    "【最近对话】（包含你自己说过的）\n" + recent_text + "\n"
                    "他说“你刚才说过X/你什么时候说过”时，以这里为准；找不到也别否认，"
                    "说“可能是我说的，我记混了”，绝不能说“你自己看岔了/我没说过”。"
                )
        if re.search(r"(记住|以后喊|以后叫|喊他|喊她|叫他|叫她|称呼他|称呼她)", event.message_str or ""):
            parts.append(
                "【识人回应】对方在让你记称呼/认人。不要复述 @昵称、QQ号、群号或后台字段；"
                "只自然答应，例如“好，我记住了，这是你朋友吗”，不要把人机式记录念出来。"
            )
        try:
            _is_private_event = bool(event.is_private_chat())
        except Exception:
            _is_private_event = False
        try:
            if (
                str(self.db.kv_get("weather_alert_open", "") or "") == today_str()
                and _is_private_event
            ):
                parts.append(
                    "【天气提醒之后】你今晚已经提醒过他天气了，他说“知道了/好/嗯/收到”就自然应一句，"
                    "不要再提天气、带伞、加衣服，也不要追问；只有他主动再问天气才回答。"
                )
        except Exception:
            pass

        try:
            merged_count = int(event.get_extra("amo_debounce_count") or 0)
        except Exception:
            merged_count = 0
        if merged_count > 1:
            parts.append(
                "【连发合并】对方在几秒内连发了 %d 条，用「｜」隔开，合起来当一句话看。"
                "其中问到你的（回不回家、吃没吃），先答你自己的安排和情况，再顺手接他的话题、给建议；"
                "不要理解成他在纠结什么，也不要替他说“你还没进店/你还在排队”。" % merged_count
            )
        try:
            last_at = to_float(self._last_reply_at.get(event.unified_msg_origin), 0)
        except Exception:
            last_at = 0.0
        try:
            is_private = bool(event.is_private_chat())
        except Exception:
            is_private = False
        if is_private and last_at and now_ts() - last_at <= 120:
            parts.append(
                "【刚答过】你 %d 秒前刚回过他这件事。如果他现在说的还是同一件事，"
                "不要把刚才的话换个说法再说一遍：最多补一句新的，或者一句带过（“嗯，就这么办”）。"
                % int(max(1, now_ts() - last_at))
            )

        try:
            wear_hint = await self._maybe_outfit_change(event)
            if wear_hint:
                parts.append(wear_hint)
        except Exception as exc:
            logger.debug("[amo] 换装识别失败: %s" % exc)

        parts = self._lean_parts(parts)
        if (not is_group) and first_person_experience is not None:
            body_now = event.message_str or ""
            try:
                if first_person_experience(body_now):
                    parts.append(
                        "【归属】他刚说的「" + truncate(body_now, 36) + "」是他自己的经历，不是你做的；"
                        "不要接成“我也在/我也吃了/我也去了”。"
                    )
                elif now_ts() - to_float(getattr(self, "_attribution_alert", {}).get(umo, 0), 0) < 600:
                    parts.append("【归属】上一轮你把他的经历说成了自己的；这次分清：他说的是他，你说的是你。")
            except Exception:
                pass
        parts.append(
            "以上是你的内在状态，只影响语气和句子长短，不影响你要不要接话。"
            "他来找你，哪怕你在上班、在忙，也先接住；"
            "禁止说“你先忙 / 你去忙 / 忙你的 / 那你先忙 / 不打扰你了 / 晚点聊”。"
        )
        return "\n".join(parts)

    #: 明确要语音的词。宁可多认几个：命中只是「给她一个必须用语音的理由」，
    #: 合成在后台跑、没有额外成本；漏认的代价是他明明开口要了却没声音。
    VOICE_ASK_WORDS = (
        "语音", "发条音", "发个音", "发段音", "录音", "录一段", "录个",
        "念给我", "念一句", "念一段", "读给我", "读一下", "读一句",
        "说句话", "说一句", "说一段", "说给我听", "讲给我听", "用声音",
        "你的声音", "想听你说", "想听听", "听听你", "听你说话", "听你唱",
        "唱给我", "唱一句", "唱首歌", "哼一句", "哼给我",
        "开语音", "语音条", "发语音", "用语音", "出声", "亲口",
        "叫一声", "叫我一声", "喊我一声",
        "说爱我", "说你爱我", "说喜欢我", "说想我", "亲口说",
    )

    #: 上面那串词漏掉的句式（「想听听你的声音」「用语音说我爱你」…）用正则兜一层。
    VOICE_ASK_PATTERNS = (
        r"(听|想听|听听).{0,4}(声音|嗓音)",
        r"(声音|嗓音|语音).{0,6}(说|讲|唱|念|录|发|来一)",
        r"(说|讲|念|唱|哼|读).{0,4}(给我听|给你听|听听)",
        r"(用|发|来|录|开).{0,3}(语音|一段音|一条语音)",
        r"(叫|喊)(我)?(一声|一下)",
        r"(说|讲).{0,3}(爱我|喜欢我|想我)",
        r"(亲口|出声|开口).{0,6}(说|讲|唱|念)",
    )

    def _user_asks_voice(self, text: str) -> bool:
        """他这轮有没有明确要语音。命中就下硬要求，不再等心流打分。"""
        body = str(text or "")
        if not body:
            return False
        if any(word in body for word in self.VOICE_ASK_WORDS):
            return True
        return any(re.search(pattern, body) for pattern in self.VOICE_ASK_PATTERNS)

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req):
        try:
            await self._ensure_ready()
            if not self._ready or self.state is None:
                return
            if self._looks_like_command(event.message_str or ""):
                return
            context_text = await self._dynamic_context(event)
            # 只走官方推荐的 extra_user_content_parts（临时 part）注入。
            # 绝不能改 req.system_prompt：那里放每轮都变的内容会打散系统提示词前缀，
            # 破坏模型侧缓存（成本涨 7-20 倍），上架审核也会因此被拒。
            body = "<amo_state>\n" + context_text + "\n</amo_state>"
            try:
                wish = self.db.kv_get("device_wish", {}) or {}
                if isinstance(wish, dict) and wish.get("model"):
                    body += ("\n【想换设备】你最近很想换%s：想要 %s（大概 ¥%.0f）。"
                             "聊到手机/电脑/花钱时可以说出来；真要买就调用 amo_buy_device。"
                             % ("手机" if wish.get("kind") == "phone" else "电脑",
                                wish.get("model"), float(wish.get("price") or 0)))
            except Exception:
                pass
            try:
                if self.draw is not None and self.draw.wants_photo(event):
                    body += (
                        "\n【拍照请求】他这轮明确想要一张照片：自然答应（可以害羞、可以说等一下），"
                        "说清你现在在哪、在做什么；不要直接拒绝（不要说“不拍 / 拍什么拍”）。"
                    )
            except Exception as exc:
                logger.debug("[amo] 画图提示失败: %s" % exc)
            # 心流说这条适合用声音 → 给她一个提示，让她自己决定调 amo_speak
            try:
                urge = float(getattr(event, "amo_voice_urge", 0.0) or 0.0)
            except Exception:
                urge = 0.0
            asked_voice = self._user_asks_voice(event.message_str or "")
            if asked_voice:
                # 他明确要语音：不再等心流打分。模型只要被允许“害羞一下”就会连
                # amo_speak 都不调，所以这里把推辞的退路堵死。
                urge = max(urge, 1.0)
                try:
                    # 标记：这轮他只要语音，文字不要（语音插件出不了声时会自己补文字）
                    event.amo_voice_reply_only = True
                except Exception:
                    pass
                body += (
                    "\n【声音要求·必须照做】他这轮明确要你用语音说话。你必须调用 amo_speak 工具，"
                    "把你想说的那句念出来（text 只放要念的内容，20~60 字，不要括号里的动作说明），"
                    "然后可以再补一句很短的文字。禁止说「不好意思 / 宿舍里不方便 / 等会儿再录 / "
                    "我发不了语音 / 多难为情」这类推辞，也禁止只回文字不调工具。"
                )
                logger.info(
                    "[amo] 本轮用户明确要语音，已下硬要求：%s" % str(event.message_str or "")[:40]
                )
            elif urge >= self.cfg_float("voice_urge_threshold", 0.6):
                body += (
                    "\n【声音提示】这条对方更想听到你的声音（心流 %d/10）：挑一句最想说的，"
                    "用 amo_speak 工具发成语音；只发一句，别把整段念一遍。" % int(round(urge * 10))
                )
            # 刚发过图 → 让她知道，别假装没发过
            try:
                note = self.db.kv_get("image_share_note", {}) or {}
            except Exception:
                note = {}
            try:
                age = now_ts() - float(note.get("ts") or 0)
            except Exception:
                age = 1e9
            if note and age < 1800:
                note_text = str(note.get("text") or "").strip()
                body += (
                    "\n【你刚才的动作】%d 分钟前你主动给他发了一张照片%s。已经发过了："
                    "不要说自己发不了照片，也别重复发同一张。" % (
                        max(1, int(age // 60)),
                        ("，附了一句「%s」" % note_text[:40]) if note_text else "",
                    )
                )
            try:
                body += self._vitals_hint(event)
            except Exception as exc:
                logger.debug("[amo] 生存状态提示失败: %s" % exc)
            parts = getattr(req, "extra_user_content_parts", None)
            if parts is None:
                return
            part = None
            if TextPart is not None:
                try:
                    part = TextPart(text=body).mark_as_temp()
                except Exception:
                    part = None
            if part is None:
                # 老版本 AstrBot 拿不到 TextPart：用 dict 形式，同样只在本轮生效
                part = {"type": "text", "text": body, "_no_save": True}
            parts.append(part)
        except Exception as exc:
            logger.debug("[amo] 注入状态失败: %s" % exc)

    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, resp):
        if self.heartflow is None:
            return
        try:
            await self.heartflow.on_llm_response(event, resp)
        except Exception as exc:
            logger.debug("[amo] 心流回复记录失败: %s" % exc)

    @filter.after_message_sent()
    async def on_after_message_sent(self, event: AstrMessageEvent):
        try:
            self._last_reply_at[event.unified_msg_origin] = now_ts()
        except Exception:
            pass
        if self.heartflow is None:
            return
        try:
            await self.heartflow.on_after_message_sent(event)
        except Exception as exc:
            logger.debug("[amo] 心流发送后状态更新失败: %s" % exc)
        try:
            await self._maybe_share_image(event)
        except Exception as exc:
            logger.debug("[amo] 主动分享入口异常: %s" % exc)

    @filter.llm_tool(name="amo_eat")
    async def amo_eat(self, event, dish: str = "", method: str = "auto") -> str:
        """吃东西、喝水、买菜。饿了想买点吃的、想自己做饭、想喝点什么，都走这个工具。

        Args:
            dish(string): 吃什么/喝什么/买什么，按你人格里的口味和当下心情从菜单里挑（别默认某一道菜，也别总点同一样）。
            method(string): auto=按今日菜价自动选做饭/外卖（默认）/ order=买现成的 / cook=自己做 / drink=喝水喝饮料 / grocery=只买食材。
        """
        plugin = self._finance()
        propose = getattr(plugin, "food_propose", None) if plugin is not None else None
        if not callable(propose):
            return "我现在没法买东西（金融插件没连上）。"
        try:
            result = propose(str(dish or "").strip(), str(method or "order").strip()) or {}
        except Exception as exc:
            logger.debug("[amo] amo_eat 失败: %s" % exc)
            return "买不了，等会儿再说。"
        if not result.get("ok"):
            code = str(result.get("code") or "")
            switched = str(result.get("switched") or "")
            if code == "no_money":
                return "买不起：%s 要 %.1f 元，还差 %.1f 元。" % (
                    result.get("dish") or dish, float(result.get("price") or 0),
                    float(result.get("short") or 0))
            if code == "not_home":
                return ("在外面做不了%s，得回家或点外卖。" % (result.get("dish") or dish)
                        + ("（%s）" % switched if switched else ""))
            if code == "need_grocery":
                miss = "、".join(
                    "%s 缺 %.1f" % (m.get("item"), float(m.get("need") or 0) - float(m.get("have") or 0))
                    for m in (result.get("missing") or []))
                return (((switched + "；") if switched else "")
                        + "家里没食材，做不了：%s。要先去买（method=grocery）。" % miss)
            return "没成：%s" % (result.get("reason") or "不知道怎么了")
        dish_name = str(result.get("dish") or dish)
        mode = str(result.get("method") or method)
        try:
            self.db.kv_set("last_meal", {"ts": now_ts(), "dish": dish_name, "method": mode})
        except Exception:
            pass
        venv = result.get("vitals") or {}
        if mode == "cook":
            head = "自己做了%s，食材从家里拿的" % dish_name
        elif mode == "drink":
            head = "喝了%s" % dish_name
        elif mode == "grocery":
            head = "去买了食材，一共 %.1f 元" % float(result.get("total") or 0)
        else:
            head = "吃了%s，花了 %.1f 元" % (dish_name, float(result.get("price") or 0))
        tail = []
        if venv.get("satiety") is not None:
            tail.append("饱食度 %.0f" % float(venv.get("satiety") or 0))
        if result.get("balance") is not None:
            tail.append("余额 %.0f 元" % float(result.get("balance") or 0))
        switched = str(result.get("switched") or "")
        note = ("（%s）" % switched) if switched else ""
        try:
            self.feel(FeelEvent.MEAL)
        except Exception:
            pass
        return head + ("（" + "，".join(tail) + "）" if tail else "") + note + "。"

    @filter.llm_tool(name="amo_repay")
    async def amo_repay(self, event, amount: float = 0) -> str:
        """还他钱。你欠他钱、手里又有点钱的时候，主动转给他（记成还款，不是消费）。

        Args:
            amount(number): 还多少；0 或不填 = 能还多少还多少。
        """
        plugin = self._finance()
        payer = getattr(plugin, "repay", None) if plugin is not None else None
        if not callable(payer):
            return "我现在没法转账（金融插件没连上）。"
        try:
            value = float(amount or 0)
            try:
                result = payer(value if value > 0 else 10 ** 9, notify=False) or {}
            except TypeError:
                result = payer(value if value > 0 else 10 ** 9) or {}
        except Exception as exc:
            logger.debug("[amo] amo_repay 失败: %s" % exc)
            return "转账没成功，等会儿再说。"
        if not result.get("ok"):
            return "还不了：%s" % (result.get("reason") or "没有可还的金额")
        self._sync_finance()
        try:
            note = getattr(plugin, "money_repay", lambda: {})() or {}
            if note.get("ts"):
                self.db.kv_set("last_repay_notified_ts", note["ts"])
        except Exception:
            pass
        return "给他转了 %.0f，还欠他 %.0f。" % (
            float(result.get("paid") or 0), float(result.get("remaining") or 0))

    @filter.llm_tool(name="schedule_view")
    async def schedule_view(self, event, day: str = "today") -> str:
        """回想自己某一天打算做什么、做过什么。想不起今天或明天的安排时用。

        Args:
            day(string): today / tomorrow / yesterday，默认今天。
        """
        try:
            import datetime as _dt

            which = str(day or "today").strip().lower()
            today = _clock_now().date()
            if which == "tomorrow":
                target = today + _dt.timedelta(days=1)
            elif which == "yesterday":
                target = today - _dt.timedelta(days=1)
            else:
                target = today
            key = target.isoformat()
            items = self.state.schedule.get(key) or self.db.get_schedule(key) or []
            if not items:
                return "那天还没有安排。"
            dt_info = self.db.kv_get("day_type_" + key, None) or {}
            lines = []
            if isinstance(dt_info, dict) and dt_info.get("name"):
                lines.append("今天是%s。" % dt_info["name"])
            for it in items:
                start = str(it.get("start") or "")
                end = str(it.get("end") or "")
                act = str(it.get("activity") or "").strip()
                place = str(it.get("place") or "").strip()
                if not act:
                    continue
                outfit = str(it.get("outfit") or "").strip()
                lines.append("%s-%s %s%s%s" % (
                    start, end, act,
                    ("（%s）" % place) if place else "",
                    ("，穿" + outfit) if outfit else ""))
            return "\n".join(lines[:24]) or "那天还没有安排。"
        except Exception as exc:
            logger.debug("[amo] schedule_view 失败: %s" % exc)
            return "想不起来…"

    @filter.llm_tool(name="schedule_edit")
    async def schedule_edit(self, event, time: str, activity: str, place: str = "") -> str:
        """改自己今天某一段时间在做什么。比如想提前回家、临时出门一趟。

        Args:
            time(string): 要改的那个时间点，例如「15:00」。
            activity(string): 改成做什么，一句话。
            place(string): 地点，留空就沿用原来的。
        """
        try:
            import datetime as _dt

            key = _clock_now().date().isoformat()
            items = self.state.schedule.get(key) or self.db.get_schedule(key) or []
            if not items:
                return "今天还没有日程，改不了。"
            want = str(time or "").strip()
            hit = None
            for it in items:
                if str(it.get("start") or "") == want[:5]:
                    hit = it
                    break
            if hit is None:
                for it in items:
                    s0 = str(it.get("start") or "")
                    e0 = str(it.get("end") or "")
                    if s0 and e0 and s0 <= want[:5] < e0:
                        hit = it
                        break
            if hit is None:
                return "那个时间点找不到对应的安排。"
            hit["activity"] = str(activity or "").strip()[:60] or hit.get("activity")
            if str(place or "").strip():
                hit["place"] = str(place).strip()[:30]
            # 改了活动/地点就重新配衣服，避免「在家穿通勤装」这种对不上
            outfits = getattr(self, "outfits", None)
            if outfits is not None:
                try:
                    persona = await self.llm.persona(event.unified_msg_origin) if self.llm else ""
                except Exception:
                    persona = ""
                hit["outfit"] = outfits.for_activity(hit, key, persona)
            self.state.schedule[key] = items
            self.db.kv_set("schedule", self._sanitize_schedule(self.state.schedule))
            self.db.save_schedule(key, items)
            logger.info("[amo] 日程已改: %s -> %s" % (hit.get("start"), hit.get("activity")))
            return "改好了，%s 那会儿我就在%s。" % (
                hit.get("start"), str(hit.get("activity") or "")[:20])
        except Exception as exc:
            logger.debug("[amo] schedule_edit 失败: %s" % exc)
            return "没改成…"

    @filter.on_decorating_result()
    async def on_decorating_result(self, event: AstrMessageEvent):
        try:
            await self._ensure_ready()
            result = event.get_result()
            if not result or not result.chain:
                return
            try:
                if not result.is_llm_result():
                    return
            except Exception:
                pass
            text = strip_chat_format("".join(
                comp.text for comp in result.chain if isinstance(comp, Comp.Plain)
            ))
            try:
                text = self._guard_self_location(text, self.state.current_activity().get("place"))
            except Exception:
                pass
            try:
                if attribution_leak is not None and first_person_experience is not None:
                    body_now = event.message_str or ""
                    if first_person_experience(body_now) and attribution_leak(body_now, text):
                        hits = leak_tokens(body_now, text) if leak_tokens is not None else []
                        logger.warning(
                            "[amo] 归属串了（%s）：他说=%s / 她说=%s"
                            % ("、".join(hits) or "?", truncate(body_now, 40), truncate(text, 40))
                        )
                        alerts = getattr(self, "_attribution_alert", None)
                        if alerts is None:
                            alerts = {}
                            self._attribution_alert = alerts
                        alerts[str(event.unified_msg_origin)] = now_ts()
            except Exception:
                pass
            # 先判断要不要补图：表情包/图片回复会被后面的非 Plain 检查提前 return，
            # 所以放在这里，保证「拍给我看看」即使她只回表情也能触发
            if self.draw is not None:
                try:
                    self.draw.maybe_after_reply(event, text)
                except Exception as exc:
                    logger.warning("[amo] 画图判断失败: %s" % exc)
            # 用上下文判断“这句是不是在跟她说”，而不是靠关键词猜
            addressed_to_me = self._is_talking_to_me(event)
            if not addressed_to_me and (
                looks_like_defensive_reply(text) or looks_like_ai_admission(text)
            ):
                # 他们在聊自己的事，她冒出一句“你才人机”很突兀：不接这茬
                logger.info("[amo] 非指名对话里拦下防御话术: %s" % text[:60])
                text = "你们聊你们的，我不抢话。"
                result.chain = [Comp.Plain(text=text)]
            elif looks_like_ai_admission(text):
                text = "你才人机呢，你见过这么会聊天的机器人吗？"
                result.chain = [Comp.Plain(text=text)]
            if looks_like_model_leak(text):
                # 模型名/厂商是后台信息，不能报；按角色打岔带过去
                logger.info("[amo] 拦截后台信息泄漏: %s" % text[:60])
                text = leak_deflect_text()
                result.chain = [Comp.Plain(text=text)]
            if not text.strip():
                return
            if getattr(event, "amo_voice_reply_only", False):
                # 他明确要的是语音，语音插件会把它念出来；这段文字就别再发了。
                # 但要把「要念的纯文本」留给语音插件兜底：模型有时不调 amo_speak，
                # 只输出 <astrbot_speak ...> 伪标签，清空 chain 会让整条回复消失。
                spoken_text = _strip_voice_tags(text)
                if not spoken_text:
                    logger.info("[amo] 本轮只发语音，正文只有控制标签，整条不发")
                    result.chain = []
                    return
                else:
                    try:
                        event.amo_voice_text = spoken_text
                    except Exception:
                        pass
                    logger.info("[amo] 本轮只发语音，文字不发：%s" % spoken_text[:40])
                    result.chain = []
                    return
            group = not event.is_private_chat()
            if not group:
                # 私聊永远不引用（QQ / 飞书 / 任何平台）：连上游核心或别的插件
                # 塞进 chain 的 Reply 也在这里摘掉，而不是整条消息交回去不管。
                result.chain = [
                    comp for comp in result.chain if not isinstance(comp, Comp.Reply)
                ]
            if any(not isinstance(comp, (Comp.Plain, Comp.At)) for comp in result.chain):
                return
            quote_enabled = bool(
                self._quote_allowed(event.unified_msg_origin, group)
                or (group and getattr(event, "amo_quote_hint", False))
            )
            quote_id = getattr(event.message_obj, "message_id", None) if quote_enabled else None
            core_decor = self._core_decor_flags(event.unified_msg_origin)
            takeover = bool(core_decor.get("quote") or core_decor.get("mention"))
            if takeover and not getattr(self, "_core_decor_logged", False):
                logger.info(
                    "[amo] 检测到 AstrBot 全局引用/mention 开启：本插件接管发送，"
                    "避免核心覆盖「私聊不引用 / 群聊按概率引用」"
                )
                self._core_decor_logged = True
            if self.cfg_bool("polish_native", False):
                snap = self.state.snapshot()
                native_profile = self.db.get_profile(self._canonical_uid(event)) or {}
                native_relation = str(native_profile.get("relation") or "普通")
                native_name = str(native_profile.get("alias") or native_profile.get("name") or "对方")
                native_tone = self._tone_with_continuity(
                    event.unified_msg_origin, self.state.tone_text(snap, native_relation)
                )
                native_persona = await self.llm.persona(event.unified_msg_origin)
                native_style = STYLE_HINTS.get(self.cfg_str("reply_style", "soft"), "")
                native_consult = bool(re.search(r"(怎么|如何|为什么|步骤|怎么办|该怎么做|教程|方法|建议|教我|能不能|是什么|该不该|可不可以)", event.message_str or ""))
                polished = await self.llm.polish(
                    event.unified_msg_origin, text, native_tone,
                    state_text=self.state.prompt_text(snap),
                    relation=native_relation, name=native_name,
                    persona=native_persona, style=native_style, consult=native_consult,
                )
                if polished and polished != text:
                    text = polished
                    result.chain = [Comp.Plain(text)]
            if strip_brushoff is not None:
                try:
                    text, brush = strip_brushoff(text, event.message_str or "")
                    if brush:
                        logger.debug("[amo] 去掉赶人的话: %s" % brush)
                except Exception:
                    pass
            text = self._trim_reply(text)
            result.chain = [Comp.Plain(text)]

            # 群聊/私聊的最终发送只交给完整本地分段引擎。
            if self.segment_engine is None or not self.cfg_bool("seg_enable", True):
                if takeover and await self._send_now(
                    event, text, quote_id if quote_enabled else None
                ):
                    result.chain = []
                    return
                self._remember_sent_reply(event, text)
                return
            backup = list(result.chain)
            try:
                handled = await self.segment_engine.handle_segment_reply(
                    event,
                    quote_id=quote_id if quote_enabled else None,
                    group=group,
                    force=takeover,
                )
            except Exception as exc:
                logger.error("[amo] 完整分段引擎异常: %s" % exc)
                handled = False
            if not handled:
                result.chain = backup
                self._remember_sent_reply(event, text)
            return
        except Exception as exc:
            logger.debug("[amo] 结果装饰失败: %s" % exc)

    # ---------- 后台循环 ----------
    async def _background_loop(self):
        try:
            await asyncio.sleep(4)
        except asyncio.CancelledError:
            return
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("[amo] 后台任务异常")
            try:
                await asyncio.sleep(self.cfg_int("loop_interval_seconds", 30))
            except asyncio.CancelledError:
                return

    async def _sediment_relations(self):
        """按真实互动量沉淀关系网：聊得多就是熟人/朋友，并让 bot 通过你认识你的人。

        只补两类 note（算法见 relation_sediment.py）：
        1. bot ↔ 用户（全部历史累计）：聊过一句 / 只在人物列表里 → 陌生人；
           ≥15 条且跨 ≥2 天 → 熟人；≥60 条且跨 ≥7 天 → 朋友；
        2. 两跳推断：bot↔用户已是熟/朋友，而用户↔A 有非仇人边 → bot↔A 记「朋友」，
           note「推断：经X认识」，每人最多 5 条。
        管理员手设的关系（note 不带「自动：」「推断：」）永远不覆盖；
        家人/恋人/仇人不改；自动边只升不降。
        """
        if plan_relation_edges is None:
            return
        # 0 = 统计全部历史：老用户、只聊过一两句的人也要进关系网
        days = max(0, int(self.cfg_int("relation_sediment_days", 0)))
        try:
            stats = self.db.interaction_stats(days)
        except Exception as exc:
            logger.debug("[amo] 互动统计失败: %s" % exc)
            return
        if self.cfg_bool("relation_stranger_edges", True):
            seen = {str(row.get("uid") or "") for row in stats}
            try:
                # 只出现在人物列表、从没聊过天的人，也记成「陌生人」进图；
                # 觉得面板边太多就把 relation_stranger_edges 关掉，只记聊过天的人
                for item in self.db.list_profiles(limit=1000):
                    uid = str(item.get("uid") or "")
                    if uid and uid not in seen:
                        stats.append({"uid": uid, "c": 0, "f": 0, "l": 0})
                        seen.add(uid)
            except Exception as exc:
                logger.debug("[amo] 读取人物列表失败: %s" % exc)
        if not stats:
            return

        names = {}
        try:
            for item in self.db.list_profiles(limit=500):
                names[str(item.get("uid"))] = str(item.get("alias") or item.get("name") or "")
        except Exception:
            names = {}

        existing = {}
        try:
            for edge in self.db.list_relations():
                pair = tuple(sorted([str(edge.get("a_uid") or ""), str(edge.get("b_uid") or "")]))
                existing[pair] = (str(edge.get("relation") or ""), str(edge.get("note") or ""))
        except Exception as exc:
            logger.debug("[amo] 读取关系网失败: %s" % exc)
            return

        infer_limit = max(1, min(10, int(self.cfg_int("relation_infer_per_user", 5))))
        try:
            plan = plan_relation_edges(stats, existing, names, infer_limit)
        except Exception as exc:
            logger.debug("[amo] 关系沉淀计算失败: %s" % exc)
            return
        # 一次最多写 300 条，人物很多时分成几轮补齐，别把 tick 卡太久
        for a_uid, b_uid, relation, note in plan[:300]:
            try:
                if not self.db.upsert_relation(a_uid, b_uid, relation, note):
                    continue
                await self._push_relation_to_data(a_uid, b_uid, relation, note)
            except Exception as exc:
                logger.debug("[amo] 关系沉淀写入失败: %s" % exc)

    def _decay_hate_relations(self):
        try:
            cutoff = now_ts() - 7 * 86400
            rows = self.db.conn.execute(
                "SELECT uid FROM profiles WHERE relation='仇恨' AND relation_at>0 AND relation_at<=?",
                (cutoff,),
            ).fetchall()
            for row in rows:
                self.db.update_profile(str(row["uid"]), relation="抵触")
                logger.info("[amo] 仇恨超过7天，降为抵触: %s" % row["uid"])
        except Exception as exc:
            logger.debug("[amo] 仇恨关系衰减失败: %s" % exc)

    async def _tick(self):
        if not self._ready or self.state is None:
            return
        # 数据插件可能在陪伴之后才装：每 5 分钟重新探测一次，装上就自动接管/迁移
        if (self._data_mem() is None and self._data_store() is None
                and now_ts() - to_float(getattr(self, "_last_data_probe", 0), 0) > 300):
            self._last_data_probe = now_ts()
            self._spawn(self._sync_with_data_plugin())
        elif now_ts() - to_float(getattr(self, "_last_digest_check", 0), 0) > 300:
            self._last_digest_check = now_ts()
            self._spawn(self._maybe_daily_digest())
        # 数据插件晚于 amo 加载：它一出现就补做第一次同步（60 秒最多试一次，成功后就停）
        if (not self._data_synced and self._data_connected()
                and now_ts() - to_float(getattr(self, "_last_data_sync_try", 0), 0) > 60):
            self._last_data_sync_try = now_ts()
            self._spawn(self._sync_with_data_plugin())
        if now_ts() - to_float(getattr(self, "_last_chat_digest", 0), 0) > 60:
            self._last_chat_digest = now_ts()
            self._spawn(self._maybe_chat_digest())
        if now_ts() - to_float(getattr(self, "_last_his_digest", 0), 0) > 300:
            self._last_his_digest = now_ts()
            self._spawn(self._maybe_his_day_digest())
        if now_ts() - to_float(getattr(self, "_last_diary_check", 0), 0) > 300:
            self._last_diary_check = now_ts()
            self._spawn(self._maybe_daily_diary())
        if now_ts() - to_float(getattr(self, "_last_solo_return", 0), 0) > 120:
            self._last_solo_return = now_ts()
            self._spawn(self._maybe_solo_return())
        if now_ts() - to_float(getattr(self, "_last_milestone_check", 0), 0) > 300:
            self._last_milestone_check = now_ts()
            self._spawn(self._maybe_milestone_archive())
        elif now_ts() - to_float(getattr(self, "_last_profile_sync", 0), 0) > 600:
            # 画像每 10 分钟对一次账，保证面板和本地不脱节
            self._last_profile_sync = now_ts()
            self._spawn(self._sync_profiles_to_data())
            self._spawn(self._sync_relations_from_data())
        try:
            await self._sleep_tick()
        except Exception as exc:
            logger.debug("[amo] 睡眠推进失败: %s" % exc)
        try:
            self._heartflow_tick()
        except Exception as exc:
            logger.debug("[amo] 心流衰减失败: %s" % exc)
        try:
            self._period_feel_tick()
        except Exception as exc:
            logger.debug("[amo] 生理期事件失败: %s" % exc)
        try:
            self._bill_meals()
        except Exception as exc:
            logger.debug("[amo] 吃饭补扣失败: %s" % exc)
        try:
            self._device_wish_tick()
        except Exception as exc:
            logger.debug("[amo] 换设备念头失败: %s" % exc)
        self.state.decay_mood()
        if self.state.last_daily != today_str():
            self.state.daily_tick()
        self.state.roll_health()
        try:
            self._sync_finance()
        except Exception as exc:
            logger.debug("[amo] 财务同步失败: %s" % exc)
        try:
            await self._maybe_notify_repay()
        except Exception as exc:
            logger.debug("[amo] 还款通知失败: %s" % exc)
        try:
            await self._maybe_push_salary()
        except Exception as exc:
            logger.debug("[amo] 薪资同步失败: %s" % exc)
        try:
            await self._maybe_push_assets()
        except Exception as exc:
            logger.debug("[amo] 房车同步失败: %s" % exc)
        try:
            await self._note_invest_seed()
        except Exception as exc:
            logger.debug("[amo] 建仓记忆失败: %s" % exc)
        try:
            await self._sync_market_mood()
        except Exception as exc:
            logger.debug("[amo] 股市心情同步失败: %s" % exc)
        try:
            await self._maybe_treat()
        except Exception as exc:
            logger.debug("[amo] 就医判断失败: %s" % exc)
        await self.state.refresh_weather()
        try:
            await self._maybe_weather_alert()
        except Exception as exc:
            logger.debug("[amo] 天气提醒失败: %s" % exc)

        umo = self._last_umo or self._first_private_umo()
        if umo:
            try:
                await self._hydrate_recent(umo, 30)
            except Exception:
                pass
        if (
            not self.state.schedule.get(today_str())
            or self.db.kv_get("schedule_version", "") != SCHEDULE_VERSION
            or not self.state.schedule_context(today_str())
        ):
            await self.state.ensure_schedule(umo)
        try:
            self.state.apply_schedule_events()
        except Exception:
            pass

        now = now_ts()
        if now - self._last_relation_decay > 3600:
            self._last_relation_decay = now
            self._decay_hate_relations()
        if (self.cfg_bool("enable_auto_relation", True)
                and now - self._last_relation_sediment > 1800):
            self._last_relation_sediment = now
            try:
                await self._sediment_relations()
            except Exception as exc:
                logger.debug("[amo] 关系沉淀失败: %s" % exc)
        if now - self._last_purge > 3600:
            self._last_purge = now
            self.db.purge_messages(self.cfg_int("chat_log_days", 14))

        if self.cfg_bool("enable_auto_learn", True) and now - self._last_auto_learn > 1800:
            self._last_auto_learn = now
            await self._auto_learn()

        if now - self._last_pending_check >= 60:
            self._last_pending_check = now
            try:
                await self._check_proactive_pending()
            except Exception as exc:
                logger.debug("[amo] 检查主动私聊回复失败: %s" % exc)

        current_dt = _now()
        if current_dt.hour == 23 and current_dt.minute >= 59:
            save_key = today_str()
            if self._last_schedule_save != save_key:
                self._last_schedule_save = save_key
                try:
                    items = self.state.schedule.get(save_key) or []
                    if items:
                        self.db.save_schedule(save_key, items)
                    self.db.fade_schedules(7)
                    self.db.purge_schedules(14)
                    self.db.purge_diaries(30)
                except Exception as exc:
                    logger.debug("[amo] 保存/清理日程失败: %s" % exc)

        if now - self._proactive_last >= self.cfg_int("proactive_check_seconds", 300):
            self._proactive_last = now
            await self._maybe_proactive()
        if now - self._last_ritual >= 60:
            await self._maybe_rituals()

    def _diary_data_root(self):
        """插件数据目录 data/plugin_data/<plugin_name>（上架规范要求写在这里）。"""
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            return os.path.join(str(get_astrbot_data_path()), "plugin_data", PLUGIN_NAME)
        except Exception:
            return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

    def _diary_dir(self):
        """日记目录：默认 <插件数据目录>/diary，配置只能落在数据目录内。"""
        setting = str(self.cfg_str("diary_dir", "") or "").strip()
        root = self._diary_data_root()
        if callable(_diary_resolve_dir):
            return _diary_resolve_dir(setting, root)
        return os.path.join(root, "diary") if root else (_DIARY_DEFAULT_DIR or "")

    def _diary_clock(self):
        """diary_time 默认 10:00。"""
        raw = str(self.cfg_str("diary_time", "10:00") or "10:00").strip()
        try:
            hour, _, minute = raw.partition(":")
            return max(0, min(23, int(hour))), max(0, min(59, int(minute or 0)))
        except (TypeError, ValueError):
            return 10, 0

    async def _maybe_daily_diary(self):
        """每天 diary_time（默认 10:00）给「昨天」写一篇日记。"""
        if not self.cfg_bool("diary_enabled", True) or not callable(_diary_write):
            return
        now = _now()
        hh, mm = self._diary_clock()
        if (now.hour, now.minute) < (hh, mm):
            return
        if getattr(self, "_diary_writing", False):
            return
        end_day = (now - timedelta(days=1)).date()
        try:
            last_written = str(self.db.kv_get("diary_last_day", "") or "")
            start_day = (date.fromisoformat(last_written) + timedelta(days=1)) if last_written else end_day
        except Exception:
            start_day = end_day
        if start_day > end_day:
            return
        if (end_day - start_day).days > 6:
            start_day = end_day - timedelta(days=6)
        days = []
        cursor = start_day
        while cursor <= end_day:
            days.append(cursor)
            cursor += timedelta(days=1)
        self._diary_writing = True
        try:
            for day in days:
                guard = "diary_written:" + day.isoformat()
                attempt_key = "diary_attempt:" + day.isoformat()
                try:
                    if self.db.kv_get(guard, ""):
                        continue
                    last = to_float(self.db.kv_get(attempt_key, 0), 0)
                    if last and now_ts() - last < 1800:
                        continue
                except Exception:
                    pass
                try:
                    text = await self._generate_daily_diary(day)
                    if not text:
                        try:
                            self.db.kv_set(attempt_key, now_ts())
                        except Exception:
                            pass
                        continue
                    path = _diary_write(self._diary_dir(), day, text)
                    try:
                        self.db.kv_set(guard, path)
                        self.db.kv_set("diary_last_day", day.isoformat())
                    except Exception:
                        pass
                    logger.info("[amo] 日记已写: %s" % path)
                except Exception as exc:
                    logger.warning("[amo] 写日记失败: %s" % exc)
                    try:
                        self.db.kv_set(attempt_key, now_ts())
                    except Exception:
                        pass
        finally:
            self._diary_writing = False

    async def _diary_chat_lines(self, day):
        """当天聊天 → 「谁：内容」行；取不到就返回空列表。"""
        day_start = int(datetime.combine(day, datetime.min.time()).timestamp())
        mem = self._data_mem()
        if mem is None or not callable(getattr(mem, "messages_between", None)):
            return []
        try:
            rows = await self._data_call(
                "messages_between", self._data_bot_id(), day_start, day_start + 86400, "", 500,
            ) or []
        except Exception as exc:
            logger.debug("[amo] 日记取聊天失败: %s" % exc)
            return []
        # 日记是从她的视角写的，之后会按私聊范围进记忆：群里的对话不该混进来
        rows = _private_rows(rows)
        lines = []
        for row in rows:
            text = str(row.get("content") or "").strip().replace("\n", " ")
            if not text or str(row.get("role") or "") == "system":
                continue
            who = "我" if str(row.get("role") or "") == "bot" else (str(row.get("name") or "") or "他")
            lines.append(who + "：" + text[:200])
        return lines

    def _diary_hourly_lines(self, day):
        """当天每小时小日记 → 「HH:MM 内容」行。"""
        try:
            cursor = self.db.conn.execute(
                "SELECT hour, text FROM schedule_diary WHERE day=? ORDER BY hour ASC",
                (day.isoformat(),),
            )
            rows = cursor.fetchall()
        except Exception:
            return []
        lines = []
        for hour, text in rows:
            text = str(text or "").strip()
            if text:
                lines.append(str(hour)[:5] + " " + text[:160])
        try:
            log = self.db.kv_get("travel_log", []) or []
            for entry in log[-10:]:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("day") or "") != day.isoformat():
                    continue
                city = str(entry.get("city") or "").strip()
                hour = str(entry.get("hour") or "").strip()
                if city and hour:
                    if entry.get("journey"):
                        lines.append(hour + " 她坐车去" + city + "陪他，路上约 2 小时")
                    elif entry.get("solo"):
                        if entry.get("back"):
                            lines.append(hour + " 她自己从" + city + "旅游回来了")
                        else:
                            lines.append(hour + " 她自己出门去" + city + "旅游，晚上住酒店")
                    elif entry.get("back"):
                        lines.append(hour + " 跟他从" + city + "回来了")
                    else:
                        lines.append(hour + " 跟他出门到了" + city + "，晚上住酒店")
        except Exception:
            pass
        try:
            rejects = self.db.kv_get("follow_reject_log", []) or []
            for entry in rejects[-5:]:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("day") or "") != day.isoformat():
                    continue
                city = str(entry.get("city") or "").strip()
                hour = str(entry.get("hour") or "").strip()
                if city:
                    lines.append(hour + " 她说想陪他去" + city + "，他说让她好好上班，她闷闷不乐")
        except Exception:
            pass
        return lines

    async def _generate_daily_diary(self, day):
        """用当天的聊天 + 每小时日程小日记，写一篇大肥鱼口吻的日记。"""
        if not callable(_diary_write):
            return ""
        chat_lines = await self._diary_chat_lines(day)
        hourly_lines = self._diary_hourly_lines(day)
        if not chat_lines and not hourly_lines:
            return ""
        umo = self._last_umo or self._first_private_umo()
        try:
            persona = await self.llm.persona(umo)
        except Exception:
            persona = ""
        system = (
            (persona or "你是一个生活在中国城市的普通女孩，说话自然口语化。") +
            "\n\n你现在要保持这个人格，用自己的口吻写日记：第一人称、像真人写给自己的，"
            "不是助手汇报，也不要提 AI、模型、插件、日程表这些词。"
        )
        prompt = _diary_build_prompt(day, chat_lines, hourly_lines)
        try:
            text = await self.llm.chat_raw(umo, system, prompt)
        except Exception as exc:
            logger.warning("[amo] 日记生成失败: %s" % exc)
            return ""
        text = str(text or "").strip()
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
        text = re.sub(r"^我的日记[^\n]*\n+", "", text)
        return text if len(text) >= 10 else ""

    async def _maybe_milestone_archive(self):
        """每 N 轮私聊压成一条「里程碑」记忆；原始聊天不删，只多一条归纳。"""
        if getattr(self, "_milestone_running", False):
            return
        self._milestone_running = True
        try:
            await self._milestone_archive_once()
        finally:
            self._milestone_running = False

    async def _milestone_archive_once(self):
        """真正的归档逻辑（外面包了并发锁）。"""
        if not self.cfg_bool("milestone_enabled", True):
            return
        mem = self._data_mem()
        if mem is None or not callable(getattr(mem, "messages_since", None)):
            return
        every = max(2, self.cfg_int("milestone_every_turns", 20))
        min_messages = max(4, self.cfg_int("milestone_min_messages", 12))
        try:
            profiles = self.db.list_profiles(limit=20) or []
        except Exception:
            profiles = []
        for profile in profiles:
            uid = str(profile.get("uid") or "")
            home_umo = str(profile.get("private_umo") or "")
            if not uid or not home_umo:
                continue
            if str(profile.get("relation") or "") != "相恋":
                continue
            key = "milestone_ts:" + uid
            try:
                since = to_int(self.db.kv_get(key, 0))
            except Exception:
                since = 0
            try:
                rows = await self._data_call("messages_since", self._data_bot_id(), uid, since, 400)
            except Exception as exc:
                logger.debug("[amo] 里程碑取聊天失败: %s" % exc)
                continue
            if not rows:
                continue
            # 按人取（跨平台）会把群聊一起带回来，而这条总结写的是 scope='private'：
            # 群友说的话不能变成她「只在私聊里记得」的事。
            rows = _private_rows(rows)
            if not rows:
                continue
            if not since:
                # 第一次只从"现在"开始记，不把全部历史一次性压成一条。
                # 注意不能用 rows[-1]（那是本批 400 条里最旧的一条），否则会从历史开始滚。
                try:
                    self.db.kv_set(key, now_ts())
                except Exception:
                    pass
                logger.info("[amo] 里程碑起点已设置（从现在开始）: uid=%s" % uid)
                continue
            if not _ms_should_archive(rows, every, min_messages):
                continue
            body = _ms_transcript(rows)
            label = _now().strftime("%Y-%m-%d")
            system = "你是长期记忆整理器。只输出一段中文总结，不要标题、不要分点、不要时间戳。"
            prompt = _ms_build_prompt(label, body)
            try:
                summary = await self.llm.chat_raw(home_umo, system, prompt)
            except Exception as exc:
                logger.debug("[amo] 里程碑总结失败: %s" % exc)
                summary = ""
            summary = re.sub(r"\s+", " ", str(summary or "")).strip()
            if len(summary) < 8:
                continue
            content = _ms_build_content(label, summary)
            written = await self._write_memory_checked(uid, content, "milestone", 2)
            logger.info("[amo] 里程碑归档%s: %s" % ("已写入" if written else "写入失败", content[:80]))
            if written:
                try:
                    last_ts = int(rows[-1].get("created_at") or now_ts())
                    self.db.kv_set(key, max(last_ts + 1, since))
                except Exception:
                    pass

    async def _maybe_daily_digest(self):
        """每天上午把"昨天"的聊天压成一条长期记忆（阶段记忆）。"""
        if not self.cfg_bool("daily_digest_enabled", True):
            return
        now = _now()
        if now.hour < max(0, min(23, self.cfg_int("daily_digest_hour", 6))):
            return
        today = now.strftime("%Y-%m-%d")
        guard = "daily_digest:" + today
        try:
            if self.db.kv_get(guard, ""):
                return
        except Exception:
            pass
        mem = self._data_mem()
        if mem is None or not callable(getattr(mem, "recall_messages", None)):
            return
        try:
            profiles = self.db.list_profiles(limit=20) or []
        except Exception:
            profiles = []
        digest_written = 0
        digest_failed = 0
        digest_attempted = 0
        for profile in profiles:
            uid = str(profile.get("uid") or "")
            home_umo = str(profile.get("private_umo") or "")
            if not uid or not home_umo:
                continue
            if str(profile.get("relation") or "") != "相恋":
                continue
            try:
                # 按人取（不限会话）：他上午可能在飞书、晚上在 QQ
                result = await self._data_call(
                    "recall_messages", self._data_bot_id(), query="昨天",
                    umo="", uid=uid, limit=300,
                )
            except Exception as exc:
                logger.debug("[amo] 每日总结取聊天失败: %s" % exc)
                continue
            messages = (result or {}).get("messages") or []
            # 每日总结写的是 scope='private' 的记忆：群里聊的事不算「你们俩的昨天」
            messages = _private_rows(messages)
            lines = []
            for row in messages:
                text = str(row.get("content") or "").strip().replace("\n", " ")
                if not text or str(row.get("role") or "") == "system":
                    continue
                who = "我" if str(row.get("role") or "") == "bot" else "他"
                lines.append("[" + who + "] " + text[:120])
            if len(lines) < 6:
                continue
            digest_attempted += 1
            system = "你是长期记忆整理器。只输出一段中文总结，不要标题、不要分点、不要时间戳。"
            prompt = (
                "下面是昨天（" + (now - timedelta(days=1)).strftime("%Y-%m-%d") + "）两人的聊天记录。\n"
                "请把它压成 2-4 句长期记忆：写清聊到的事、约定、双方的状态变化（工作/情绪/计划）。\n"
                "每句必须带主体：主人（他）的事用「他……」，你自己的事用「我……」；不要出现无主语的句子。\n"
                "身体状态必须分清是谁的：你自己的生病、难受、疼、生理期一律写「我……」；\n"
                "写成「他难受/他生病」等于说主人病了，不要把他的事和你的事弄混。\n"
                "只写事实，不写「今天/昨天」这类相对时间；不要复述原话；不确定的不要编。\n\n"
                + "\n".join(lines[-120:])
            )
            try:
                summary = await self.llm.chat_raw(home_umo, system, prompt)
            except Exception as exc:
                logger.debug("[amo] 每日总结生成失败: %s" % exc)
                summary = ""
            summary = re.sub(r"\s+", " ", str(summary or "")).strip()
            # 摘要也会被当记忆注入：无主语句子会被读成角色自己的经历，统一补「他」
            fixed = []
            for piece in re.split(r"(?<=[。！？!?；;])", summary):
                piece = piece.strip()
                if not piece:
                    continue
                if not piece.startswith(("他", "我", "她", "用户")):
                    piece = "他" + piece
                fixed.append(piece)
            summary = "".join(fixed)
            if len(summary) < 8:
                # 模型拒答/限流会一直返回空：不计数的话 every-5-min tick 会无限重跑
                digest_failed += 1
                continue
            content = "【" + (now - timedelta(days=1)).strftime("%Y-%m-%d") + "】" + summary[:400]
            written = await self._write_memory_checked(uid, content, "daily_digest", 2)
            logger.info("[amo] 每日总结%s: %s" % ("已写入" if written else "写入失败", content[:80]))
            if written:
                digest_written += 1
            else:
                digest_failed += 1
        # 只有"确实生成过"或"根本没有足够的聊天"才落 guard；
        # 生成失败会重试（最多 3 次/天），避免一天都没有阶段记忆。
        if digest_written or (digest_failed == 0 and digest_attempted == 0):
            try:
                self.db.kv_set(guard, today)
            except Exception:
                pass
        elif digest_failed:
            try:
                tries = to_int(self.db.kv_get("daily_digest_tries:" + today, 0), 0) + 1
                self.db.kv_set("daily_digest_tries:" + today, tries)
                if tries >= 3:
                    self.db.kv_set(guard, today)
                    logger.warning("[amo] 每日总结连续失败 %d 次，今天不再重试" % tries)
            except Exception:
                pass

    def _first_private_umo(self):
        try:
            for profile in self.db.list_profiles(limit=50):
                if profile.get("private_umo"):
                    return profile["private_umo"]
        except Exception:
            pass
        return ""

    async def _auto_learn(self):
        """定时提炼长期事实，写进外挂记忆插件；本插件不再存记忆。"""
        try:
            users = self.db.active_users(now_ts() - 3600, limit=2)
        except Exception:
            return
        for user in users:
            uid = str(user.get("uid", ""))
            if not uid:
                continue
            key = "auto_learn_" + uid
            last = to_float(self.db.kv_get(key, 0))
            interval = max(5, self.cfg_int("auto_learn_minutes", 15)) * 60
            if now_ts() - last < interval:
                continue
            try:
                profile_row = self.db.get_profile(uid) or {}
                home_umo = str(profile_row.get("private_umo") or "").strip()
                if not home_umo:
                    # 还没私聊过：不要退到全局会话，否则群聊的话会被当成他说的
                    continue
                rows = await self._recent_by_uid(uid, 20, umo=home_umo)
                lines = []
                for row in rows:
                    row_umo = str(row.get("umo") or "").strip()
                    if row_umo and row_umo != home_umo:
                        continue
                    role = str(row.get("role") or "")
                    if role == "summary":
                        continue
                    who = "我" if role == "bot" else "他"
                    lines.append("[" + who + "] " + str(row.get("content") or ""))
                if not lines:
                    continue
                facts = await self.llm.extract_facts(
                    home_umo, user.get("name", "") or uid, lines
                )
                ok_any = False
                for fact in facts:
                    written = await self._write_memory_checked(
                        uid, fact["content"], fact["kind"], fact["tier"]
                    )
                    ok_any = ok_any or written
                if facts and not ok_any:
                    logger.warning("[amo] 记忆写入失败，本轮不标记已学: %s" % uid)
                    continue
                self.db.kv_set(key, now_ts())
            except Exception as exc:
                logger.debug("[amo] 自动学习失败: %s" % exc)

    def _is_proactive_friend(self, profile):
        return str(profile.get("relation") or "普通") in ("熟识", "相恋")

    def _pending_key(self, uid):
        return "proactive_pending_" + str(uid)

    def _set_proactive_pending(self, uid, kind, text, umo=""):
        self.db.kv_set(self._pending_key(uid), {
            "sent_at": now_ts(), "kind": kind, "text": str(text or ""),
            # 记下真正发出去的会话：追问要回同一个平台，否则会「飞书问完、QQ 追」。
            "umo": str(umo or ""),
            "followup": False, "mood": False,
        })

    def _clear_proactive_pending(self, uid):
        pending = self.db.kv_get(self._pending_key(uid), None)
        if pending:
            self.db.kv_set(self._pending_key(uid), {})
            self.db.kv_set("proactive_ignored_" + str(uid), 0)

    def _depressed_active(self, uid):
        return to_float(self.db.kv_get("proactive_depressed_until_" + str(uid), 0), 0) > now_ts()

    def _set_depressed(self, uid):
        hours = max(1, self.cfg_int("proactive_depressed_hours", 24))
        self.db.kv_set("proactive_depressed_until_" + str(uid), now_ts() + hours * 3600)

    def _try_soothe(self, uid, text):
        if not self._depressed_active(uid):
            return
        words = ("抱抱", "亲亲", "哄", "对不起", "别难过", "喜欢你", "爱你", "怎么啦", "我在", "在呢", "乖")
        if any(word in str(text or "") for word in words):
            self.db.kv_set("proactive_depressed_until_" + str(uid), 0)
            self.db.kv_set("proactive_ignored_" + str(uid), 0)
            self.state.nudge(委屈=-8, 郁闷=-8, 开心=5, 依恋=3)
            logger.debug("[amo] 抑郁状态被哄好: %s" % uid)

    # 每天的固定问候：kind、开关、时段、默认时段
    RITUAL_SPECS = (
        ("goodnight", "ritual_goodnight", "ritual_goodnight_window", "22:00-02:00"),
        ("morning", "ritual_morning", "ritual_morning_window", "06:30-10:00"),
        ("lunch", "ritual_lunch", "ritual_lunch_window", "11:00-13:30"),
    )

    FOLLOWUP_TEMPLATES = {
        "slack": [
            "在忙吗？怎么不理我。",
            "老公老公，你在忙着什么呀，这么久不理我。",
            "喂——人呢，是不是又把我晾一边了。",
            "忙完了没呀，我在这儿等半天了。",
            "是不是我太吵了？那我安静会儿，你有空回我一下。",
            "你这会儿在忙啥呢，回我一句我就不闹了。",
        ],
        "greet": [
            "？怎么不理我了？",
            "你是不是没看见我呀。",
            "醒醒，在等你呢。",
            "我在这儿呢，你倒是看我一眼呀。",
            "喂喂，人呢？",
        ],
        "meal": [
            "饭吃了没？",
            "到饭点了，别又随便对付一口。",
            "吃了啥呀，说给我听听。",
            "中午吃点什么呀，别又忘了。",
        ],
        "offwork": [
            "今天过得怎么样呀？",
            "你忙完记得回我一句嘛。",
            "你是还在加班吗？",
            "下班没呀，别又拖到很晚。",
        ],
        "comfort": [
            "好点了吗？",
            "还难受吗，要不要跟我说说。",
            "舒服点没有呀。",
            "还疼不疼，别硬撑着。",
        ],
    }

    @staticmethod
    def _followup_topics(text):
        """追问别再问同一件事：按话题打标，避开上一句已经问过的内容。"""
        text = str(text or "")
        groups = (
            ("food", ("吃", "饭", "饿", "外卖", "餐")),
            ("comfort", ("疼", "难受", "舒服", "药", "撑着")),
            ("work", ("下班", "加班", "上班", "项目")),
        )
        return {name for name, words in groups if any(word in text for word in words)}

    def _followup_text(self, uid, kind, previous_text=""):
        """追问换着说法：同一句不连着出现，也别把刚问的问题再问一遍。"""
        templates = [t for t in (self.FOLLOWUP_TEMPLATES.get(str(kind)) or self.FOLLOWUP_TEMPLATES["greet"]) if t]
        if not templates:
            return "？怎么不理我了？"
        key = "proactive_followup_last_%s" % uid
        try:
            last = str(self.db.kv_get(key, "") or "")
        except Exception:
            last = ""
        pool = [t for t in templates if t != last]
        topics = self._followup_topics(previous_text)
        if topics:
            fresh = [t for t in pool if not (self._followup_topics(t) & topics)]
            pool = fresh
        if not pool:
            # 同一类话题的问句都问过了，就换成「怎么不理我」的催回，别再问一遍。
            pool = [t for t in self.FOLLOWUP_TEMPLATES["greet"] if t != last] or list(self.FOLLOWUP_TEMPLATES["greet"])
        text = random.choice(pool)
        try:
            self.db.kv_set(key, text)
        except Exception:
            pass
        return text

    def _pending_still_blocking(self, uid, profile, now) -> bool:
        pending = self.db.kv_get(self._pending_key(uid), None)
        if not isinstance(pending, dict) or not pending.get("sent_at"):
            return False
        sent_at = to_float(pending.get("sent_at"), 0)
        if not sent_at:
            return False
        # 他在这之后说过话（不管在哪个平台），就当她「已经看见她」了，不用再等
        try:
            if to_float(profile.get("last_seen"), 0) > sent_at + 60:
                self.db.kv_set(self._pending_key(uid), {})
                return False
        except Exception:
            pass
        if now - sent_at >= proactive_pending_block_seconds(self.cfg_int):
            return False
        return True

    async def _check_proactive_pending(self):
        try:
            profiles = self.db.proactive_profiles(limit=100)
        except Exception:
            return
        now = now_ts()
        for profile in profiles:
            uid = str(profile.get("uid") or "")
            if not uid:
                continue
            pending = self.db.kv_get(self._pending_key(uid), None)
            if not isinstance(pending, dict) or not pending.get("sent_at"):
                continue
            # 追问要回真正发出这条主动消息的平台（飞书发的就在飞书追）；
            # 老数据没有 umo 时退回主页会话。
            umo = str(pending.get("umo") or "") or str(profile.get("private_umo") or "")
            if not umo:
                continue
            age = now - to_float(pending.get("sent_at"), 0)
            if age > proactive_pending_block_seconds(self.cfg_int):
                self.db.kv_set(self._pending_key(uid), {})
                continue
            followup_minutes = self.cfg_int("proactive_followup_minutes", 30)
            # 0 / 负数 = 关掉追问，只保留「心情变差」这一档
            followup_after = 10 ** 9 if followup_minutes <= 0 else max(5, followup_minutes) * 60
            # 0 / 负数 = 关掉「没回复就心情变差」；默认跟 schema 一致（30 分钟）
            mood_minutes = max(0, self.cfg_int("proactive_no_reply_minutes", 30))
            mood_after = mood_minutes * 60 if mood_minutes else 10 ** 9
            if not pending.get("followup") and age >= followup_after:
                if not quiet_now(self.cfg_str("quiet_hours", "23:30-07:30")):
                    kind = str(pending.get("kind") or "greet")
                    followup = self._followup_text(uid, kind, pending.get("text"))
                    if await self._send_to_umo(umo, followup):
                        pending["followup"] = True
                        pending["followup_at"] = now
                        self.db.kv_set(self._pending_key(uid), pending)
                        # 追问本身也是一句她说过的话，不记下来会引出下一轮「你怎么不理我」
                        self._remember_bot_message(umo, followup)
                        self._mark_bot_initiated(umo)
                        logger.debug("[amo] 主动私聊未回复，已追问: %s" % uid)
            if not pending.get("mood") and age >= mood_after:
                pending["mood"] = True
                self.db.kv_set(self._pending_key(uid), pending)
                ignored = to_int(self.db.kv_get("proactive_ignored_" + uid, 0), 0) + 1
                self.db.kv_set("proactive_ignored_" + uid, ignored)
                self.state.nudge(委屈=5, 郁闷=5, 生气=2, 依恋=2)
                if ignored >= max(1, self.cfg_int("proactive_depressed_count", 3)):
                    self._set_depressed(uid)
                logger.debug("[amo] 主动私聊仍无回复，心情变差: %s (%d)" % (uid, ignored))

    def _ritual_in_window(self, spec):
        try:
            start, end = str(spec).split("-", 1)
            return in_minute_range(minutes_now(), parse_hhmm(start), parse_hhmm(end))
        except Exception:
            return False

    def _ritual_umos(self, profile):
        """她能给你发问候的会话：QQ、飞书…按最近说过话排序。"""
        uid = str(profile.get("uid") or "")
        items = []
        try:
            data = self.db.kv_get("channels:%s" % uid, {}) or {}
        except Exception:
            data = {}
        if isinstance(data, dict):
            entries = [value for value in data.values() if isinstance(value, dict) and value.get("umo")]
            entries.sort(key=lambda value: -to_float(value.get("ts"), 0))
            for value in entries:
                umo = str(value.get("umo") or "")
                if umo and umo not in items:
                    items.append(umo)
        private_umo = str(profile.get("private_umo") or "")
        if private_umo and private_umo not in items:
            items.append(private_umo)
        return items

    def _recent_greeting(self, uid, minutes):
        """最近一次每日问候发在哪个平台、隔了多久（QQ/飞书算同一个人）。"""
        if not uid:
            return False
        try:
            data = self.db.kv_get("greeting_last:%s" % uid, {}) or {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            return False
        return _within_minutes(data.get("ts"), now_ts(), minutes)

    def _mark_greeting(self, uid, kind, umo):
        try:
            self.db.kv_set("greeting_last:%s" % str(uid), {
                "kind": str(kind),
                "umo": str(umo or ""),
                "ts": now_ts(),
            })
        except Exception:
            pass

    async def _ritual_pending(self, profile):
        """现在是否正处在「还没发」的问候时段。

        主动消息要让路：早晨 8 点主动搭话和早安问候撞在一起，就是
        「两个地方各响一次」的来源。非恋人的好友、刚问候过的、没有会话可发的，
        都不算待发，否则会白让路一整个时段。
        """
        if not self.cfg_bool("ritual_enabled", True):
            return False
        if str(profile.get("relation") or "") != "相恋":
            return False
        uid = str(profile.get("uid") or "")
        umos = self._ritual_umos(profile)
        if not uid or not umos:
            return False
        if self._recent_greeting(uid, self.cfg_int("ritual_min_gap_minutes", 30)):
            return False
        for kind, enabled_key, window_key, default_window in self.RITUAL_SPECS:
            if not self.cfg_bool(enabled_key, True):
                continue
            if not self._ritual_in_window(self.cfg_str(window_key, default_window)):
                continue
            if self.db.kv_get("ritual_" + kind + "_" + uid + "_" + today_str(), False):
                continue
            if not await self._ritual_should_send_async(umos, kind, uid):
                continue
            return True
        return False

    #: 每个问候从当天几点开始算「今天已经聊过」；不在表里的按 45 分钟活跃窗。
    RITUAL_FROM_HOURS = {"morning": 5, "lunch": 11, "goodnight": 21}

    def _ritual_lookback_start(self, kind):
        """「今天这个时段已经聊过」的判定起点。

        不能只看最后 10 条 / 45 分钟：06:52 他说「早上好」、07:10 收尾，
        到 08:00 两道闸都过期，于是又问一遍「你醒了没」。所以按当天时段判。
        """
        now = now_ts()
        hours = getattr(self, "RITUAL_FROM_HOURS", None) or {"morning": 5, "lunch": 11, "goodnight": 21}
        hour = hours.get(str(kind))
        if hour is None:
            return now - max(5, self.cfg_int("ritual_skip_recent_minutes", 45)) * 60
        try:
            base = datetime.fromtimestamp(now).replace(
                hour=int(hour), minute=0, second=0, microsecond=0)
            start = base.timestamp()
            if start > now:
                # 凌晨 0-2 点的晚安算「昨天 21:00 起」；其他时段还没到点就从现在算
                start = start - 24 * 3600 if str(kind) == "goodnight" else now
            return start
        except Exception:
            return now - max(5, self.cfg_int("ritual_skip_recent_minutes", 45)) * 60

    def _ritual_judge_rows(self, rows, kind, since):
        """按已经取到的消息判断今天这个问候还发不发；QQ/飞书一起算。"""
        rows = [row for row in (rows or []) if to_float(row.get("created_at"), 0) >= since]
        rows.sort(key=lambda row: to_float(row.get("created_at"), 0))
        now = now_ts()
        recent_gap = max(5, self.cfg_int("ritual_skip_recent_minutes", 45)) * 60
        if rows:
            last_at = to_float(rows[-1].get("created_at"), 0)
            if last_at and now - last_at < recent_gap:
                return False
        if not self.cfg_bool("ritual_skip_if_greeted", True):
            return True
        # 只认「他」问候过：她自己那句「吃了没 / 晚安」多半是主动消息或追问，
        # 算进来会把当天的问候整段吃掉（午饭问候时有时无就是这么来的）。
        texts = [str(row.get("content") or "") for row in rows if str(row.get("role") or "") == "user"]
        # 不再只看最后 10 条：早上聊了几十句之后，最早那句「早」会被挤出去。
        joined = "\n".join(texts)
        if kind == "morning":
            return not bool(re.search(r"(?:^|\s)早(?:\s|$|[，,、!！。~～])|早安|早上好|早上好呀|我醒了|起床了|还没起来吗|醒了没", joined))
        if kind == "goodnight":
            return not bool(re.search(r"晚安|睡了|睡觉|先睡|去睡|早点休息", joined))
        if kind == "lunch":
            return not bool(re.search(r"午饭|中午吃|吃啥|吃什么|吃饭|吃了没|吃了吗", joined))
        return True

    def _ritual_should_send(self, umos, kind):
        """同步版：只读本地缓存表/内存缓冲（拿不到记忆库时的兜底）。"""
        umos = list(umos) if isinstance(umos, (list, tuple, set)) else [umos]
        since = self._ritual_lookback_start(kind)
        rows = []
        for item in umos:
            try:
                rows.extend(self.db.messages_since_umo(item, since, 200))
            except Exception:
                try:
                    rows.extend(self._recent(item, 10))
                except Exception:
                    pass
        return self._ritual_judge_rows(rows, kind, since)

    async def _ritual_should_send_async(self, umos, kind, uid=""):
        """真正发送前用这个：消息真相在记忆库。

        插件本地的 messages 表最后一条停在 11-09（容量/迁移后不再写入），
        只看它会永远判成「今天还没聊过」，于是 8 点又问一遍「醒了没」。
        """
        since = self._ritual_lookback_start(kind)
        uid = str(uid or "")
        if uid:
            try:
                rows = await self._data_call(
                    "messages_since", self._data_bot_id(), uid, int(since), 400)
            except Exception as exc:
                logger.debug("[amo] 问候判定取聊天失败: %s" % exc)
                rows = []
            if rows:
                # 和里程碑同一口径：群聊内容不进私聊判定
                return self._ritual_judge_rows(_private_rows(rows), kind, since)
        return self._ritual_should_send(umos, kind)

    async def _maybe_rituals(self):
        if not self.cfg_bool("ritual_enabled", True):
            return
        now = now_ts()
        if now - to_float(getattr(self, "_last_ritual", 0), 0) < 60:
            return
        self._last_ritual = now
        try:
            profiles = self.db.proactive_profiles(limit=100)
        except Exception:
            return
        snap = self.state.snapshot()
        for profile in profiles:
            if str(profile.get("relation") or "") != "相恋":
                continue
            uid = str(profile.get("uid") or "")
            umos = self._ritual_umos(profile)
            if not umos or not uid:
                continue
            home_umo = str(profile.get("private_umo") or "")
            name = str(profile.get("alias") or profile.get("name") or "宝").strip() or "宝"
            for kind, enabled_key, window_key, default_window in self.RITUAL_SPECS:
                if not self.cfg_bool(enabled_key, True):
                    continue
                if not self._ritual_in_window(self.cfg_str(window_key, default_window)):
                    continue
                daily_key = "ritual_" + kind + "_" + uid + "_" + today_str()
                if self.db.kv_get(daily_key, False):
                    continue
                if kind == "morning" and (snap.get("activity") or {}).get("category") == "sleep":
                    continue
                if self._recent_greeting(uid, self.cfg_int("ritual_min_gap_minutes", 30)):
                    continue
                if not await self._ritual_should_send_async(umos, kind, uid):
                    continue
                targets = _greeting_targets(
                    umos,
                    home_umo,
                    randomize=self.cfg_bool("ritual_random_platform", True),
                )
                if not targets:
                    continue
                text = ""
                try:
                    text = await self.llm.gen_proactive(targets[0], profile, snap, kind)
                except Exception as exc:
                    logger.debug("[amo] 仪式生成失败: %s" % exc)
                if not text:
                    text = {
                        "goodnight": name + "，太晚了，我先去睡觉啦，你也早点睡。",
                        "morning": name + "，早上好呀，还没起来吗？",
                        "lunch": name + "，今天中午吃啥子哦？",
                    }.get(kind, "")
                if not text:
                    continue
                sent_umo = ""
                for candidate in targets:
                    if await self._send_to_umo(candidate, text):
                        sent_umo = candidate
                        break
                if not sent_umo:
                    continue
                # 只标记真正收到的那一处；另一头靠 greeting_last 跨平台去重，
                # 不能把「她刚跟我说过话」的副作用（火气/打扰冷却）打到没收到消息的平台
                self._mark_bot_initiated(sent_umo)
                self._mark_greeting(uid, kind, sent_umo)
                self.db.kv_set(daily_key, True)
                self.db.log_proactive(uid, kind, text)
                logger.info(
                    "[amo] 每日问候(%s) -> %s [%s]: %s"
                    % (kind, name, str(sent_umo).split(":", 1)[0], text[:200])
                )
                break

    def _choose_proactive_kind(self, profile, snap, category=""):
        relation = profile.get("relation", "普通")
        mood = snap["mood"]
        painful = (
            snap["health"]["sick"]
            or snap["period"]["pain"] >= 6
            or mood["委屈"] >= 60
            or mood["郁闷"] >= 65
        )
        if relation == "相恋" and painful and self.cfg_bool("proactive_comfort", True):
            return "comfort"
        activity = str((snap.get("activity") or {}).get("activity") or "")
        if category == "play" and ("游戏" in activity or "打游戏" in activity):
            return "game"
        if category == "meal":
            return "meal"
        if category in ("rest", "play"):
            return "slack"
        if category == "commute":
            return "offwork" if _now().hour >= 16 else "commute"
        if relation in ("熟识", "相恋") and random.random() < self.cfg_float("proactive_share_prob", 0.35):
            return "share"
        return "greet"


    # ---- 主动消息节流 ----
    def _proactive_user_just_talked(self, profile, now):
        """对方刚说过话就别主动插话。0 表示关闭这项检查。"""
        minutes = max(0, self.cfg_int("proactive_user_idle_minutes", 10))
        if not minutes:
            return False
        last_user_at = to_float(profile.get("last_seen"), 0)
        return bool(last_user_at) and (now - last_user_at) < minutes * 60

    def _proactive_forced_allowed(self, profile, now):
        """「日常关心」也要跟上次主动拉开间隔，避免重启后立刻又发。"""
        gap = max(1, self.cfg_int("proactive_forced_gap_minutes", 30)) * 60
        return (now - to_float(profile.get("last_proactive", 0))) >= gap

    def _forced_hour_key(self, uid):
        return "proactive_forced_hour_" + str(uid or "")

    def _forced_sent_this_hour(self, uid):
        """「日常关心」每小时只强制一次；存数据库，热重载/重启都不清空。"""
        mark = today_str() + ":" + str(_now().hour)
        try:
            return str(self.db.kv_get(self._forced_hour_key(uid), "")) == mark
        except Exception:
            return self._last_proactive_activity.get(str(uid)) == mark

    def _mark_forced_hour(self, uid):
        mark = today_str() + ":" + str(_now().hour)
        self._last_proactive_activity[str(uid)] = mark
        try:
            self.db.kv_set(self._forced_hour_key(uid), mark)
        except Exception:
            pass

    # ---- 主动消息多平台轮换 ----
    def _record_channel(self, uid, umo, platform):
        """记下这个人各平台的会话地址，供主动消息选边。"""
        if not uid or not umo:
            return
        try:
            key = "channels:%s" % uid
            data = self.db.kv_get(key, {}) or {}
            if not isinstance(data, dict):
                data = {}
            data[str(platform or "?")] = {"umo": str(umo), "ts": now_ts()}
            self.db.kv_set(key, data)
        except Exception as exc:
            logger.debug("[amo] 记录通道失败: %s" % exc)

    def _proactive_candidates(self, profile, primary):
        """主动消息的候选平台：选中的优先，其次是其它通道，最后 private_umo。

        最近刚被主动联系过的平台会被跳过，避免兜底时连着骚扰同一处。
        """
        items = []

        def push(umo, force=False):
            umo = str(umo or "")
            if not umo or umo in items:
                return
            if not force and self._recent_bot_initiated(umo, 3600):
                return
            items.append(umo)

        push(primary, force=True)
        if self.cfg_bool("proactive_rotate_enabled", True):
            try:
                data = self.db.kv_get("channels:%s" % (profile.get("uid") or ""), {}) or {}
            except Exception:
                data = {}
            if isinstance(data, dict):
                entries = [v for v in data.values() if isinstance(v, dict) and v.get("umo")]
                entries.sort(key=lambda v: -float(v.get("ts") or 0))
                for value in entries:
                    push(value.get("umo"))
        push(profile.get("private_umo"))
        return items

    def _pick_proactive_umo(self, profile):
        """选这轮主动消息先发哪个平台；关掉开关就用 private_umo。"""
        fallback = str(profile.get("private_umo") or "")
        if not self.cfg_bool("proactive_rotate_enabled", True):
            return fallback
        uid = str(profile.get("uid") or "")
        try:
            data = self.db.kv_get("channels:%s" % uid, {}) or {}
        except Exception:
            return fallback
        if not isinstance(data, dict):
            return fallback
        items = []
        for value in data.values():
            if isinstance(value, dict) and value.get("umo"):
                items.append((float(value.get("ts") or 0), str(value.get("umo"))))
        if not items:
            return fallback
        items.sort(key=lambda pair: -pair[0])
        if len(items) == 1:
            return items[0][1]
        window = max(1, self.cfg_int("proactive_recent_minutes", 30)) * 60
        if now_ts() - items[0][0] <= window:
            return items[0][1]
        last = str(self.db.kv_get("last_channel:%s" % uid, "") or "")
        for _, umo in items:
            if umo != last:
                return umo
        return items[0][1]


    def _weather_alert_umos(self):
        """天气提醒的候选会话，按最近活跃排序。

        只用她**真的收到过消息**的会话（channels:<uid> + private_umo），
        没配飞书的人候选里就只有 QQ，不会随机到一个不存在的平台。
        """
        pairs = []
        try:
            for profile in self.db.proactive_profiles(limit=20):
                uid = str(profile.get("uid") or "")
                data = self.db.kv_get("channels:%s" % uid, {}) or {}
                if isinstance(data, dict):
                    for value in data.values():
                        if isinstance(value, dict) and value.get("umo"):
                            pairs.append((float(value.get("ts") or 0), str(value["umo"])))
                item = str(profile.get("private_umo") or "")
                if item:
                    pairs.append((0.0, item))
        except Exception as exc:
            logger.debug("[amo] 天气提醒选平台失败: %s" % exc)
        pairs.sort(key=lambda pair: -pair[0])
        seen = []
        for _, umo in pairs:
            if umo and umo not in seen:
                seen.append(umo)
        if not seen:
            fallback = self._last_umo or self._first_private_umo()
            if fallback:
                seen.append(fallback)
        return seen

    def _pick_weather_alert_umo(self):
        """兼容旧调用：返回最该优先尝试的那个会话。"""
        items = self._weather_alert_umos()
        return items[0] if items else ""

    @staticmethod
    def _clean_weather_alert(text):
        """把模型偶尔蹦出的客服腔/播报腔挡掉，宁可退回模板。"""
        value = str(text or "").strip().strip('"').strip("“”").strip()
        value = re.sub(r"^(?:天气提醒|提醒你|温馨提示)[：:，,\s]*", "", value)
        for bad in ("请注意", "建议您", "提醒您", "天气预报", "温馨提示", "作为AI", "作为 AI", "助手"):
            if bad in value:
                return ""
        if len(value) > 80:
            return ""
        return value

    async def _weather_alert_text(self, umo, tomorrow, fallback):
        """用她自己的语气说这句提醒；模型失败就退回模板。"""
        facts = []
        day_text = (str(tomorrow.get("textDay") or "") + " " + str(tomorrow.get("textNight") or "")).strip()
        if day_text:
            facts.append("明天天气：" + day_text)
        if tomorrow.get("tempMax"):
            facts.append("明天最高 " + str(tomorrow.get("tempMax")) + "℃")
        recent_lines = []
        try:
            for row in self._recent(umo, 8):
                content = str(row.get("content") or "").strip()
                if not content:
                    continue
                who = "他" if str(row.get("role") or "") == "user" else "你"
                recent_lines.append(who + "：" + content[:80])
        except Exception:
            recent_lines = []
        try:
            state_text = self.state.prompt_text(self.state.snapshot())
        except Exception:
            state_text = ""
        system = (
            await self.llm.persona(umo) + "\n\n"
            "规则：你就是角色本人，只输出要发出去的消息，不要解释、不要旁白、不要复述数据。"
        )
        prompt = (
            (state_text + "\n" if state_text else "")
            + "事实：\n" + "\n".join(facts) + "\n"
            + ("最近聊天：\n" + "\n".join(recent_lines) + "\n" if recent_lines else "")
            + "参考说法（不要照抄）：" + fallback + "\n"
            + "请用你平时跟他说话的语气，主动提一句明天的天气。\n"
            "要求：只发一句，20-30 字以内；像真人随口说的，不要像天气播报、客服或助手；\n"
            "不要用“提醒您/请注意/建议您/记得带伞哦/注意保暖”这种模板，不要罗列温度风力；\n"
            "可以带一点情绪（关心、吐槽、嫌麻烦都行），但别煽情；不要问“要不要带伞”，不要重复你刚说过的话。"
        )
        try:
            text = await self.llm.chat(umo, system, prompt, limit=60)
        except Exception as exc:
            logger.debug("[amo] 天气提醒文案生成失败: %s" % exc)
            text = ""
        text = self._clean_weather_alert(text)
        return text or fallback

    async def _weather_query_context(self, text=""):
        """他问天气时，用缓存里的「现在天气 + 今天 + 明天」拼一段给他看。

        只有缓存过期才会真的请求和风（现在天气 30 分钟一份、预报 3 小时一份），
        所以连着问十遍通常一次都不多请。
        """
        key = self.cfg_str("hefeng_key", "")
        city = (
            self.cfg_str("weather_city", "").strip()
            or str((getattr(self.state, "schedule_profile", {}) or {}).get("city") or "").strip()
            or "贵阳"
        )
        now_data = {}
        try:
            now_data = await self.state.refresh_weather()
        except Exception as exc:
            logger.debug("[amo] 天气查询取现在天气失败: %s" % exc)
        if not now_data:
            now_data = getattr(self.state, "weather", {}) or {}
        items = []
        if key:
            try:
                items = await self.state._fetch_qweather_daily(key, city, 3)
            except Exception as exc:
                logger.debug("[amo] 天气查询取预报失败: %s" % exc)
        today = items[0] if items else {}
        tomorrow = items[1] if len(items) > 1 else {}
        brief = forecast_brief(now_data, today, tomorrow)
        if not brief:
            logger.info("[amo] 天气查询：没有可用数据")
            return "【天气查询】这会儿取不到天气数据，别编温度，直接说看不太准。"
        logger.info("[amo] 天气查询: %s" % brief)
        return "【天气查询】" + brief

    async def _maybe_weather_alert(self):
        """明天天气变坏时，到点提醒一次（每天最多一条）。

        判断一天只做两次：
        - 早上 `weather_alert_morning_time`（默认 08:00）：只判断、不发送；
        - 晚上 `weather_alert_time`（默认 20:00）：到点才真的发预报，
          且**跳过预报缓存**拿最新一份，保证当天晚上这条的准确性。

        以前每 30 秒的后台循环都会重算一遍，日志刷屏、还每次都要请一次和风接口。
        用 `weather_alert_checked`（形如 `2026-11-08|evening`）记住今天哪个槽位
        已经判断过，没到点 / 判断过的直接返回。
        """
        if not self.cfg_bool("weather_alert_enabled", False):
            return
        key = self.cfg_str("hefeng_key", "")
        if not key:
            return
        target = self.cfg_str("weather_alert_time", "20:00")
        evening_min = parse_clock(target, 20, 0)
        morning_raw = str(self.cfg_str("weather_alert_morning_time", "08:00") or "").strip()
        morning_min = parse_clock(morning_raw, 8, 0) if morning_raw else None
        now = _now()
        today = today_str()
        if str(self.db.kv_get("weather_alert_sent", "") or "") == today:
            return
        checked = str(self.db.kv_get("weather_alert_checked", "") or "")
        slot = next_check_slot(
            now.hour * 60 + now.minute, morning_min, evening_min, checked, today
        )
        if not slot:
            return
        label = "早上" if slot == "morning" else "晚上"
        city = (
            self.cfg_str("weather_city", "").strip()
            or str((getattr(self.state, "schedule_profile", {}) or {}).get("city") or "").strip()
            or "贵阳"
        )
        # 晚上要发预警，必须用最新预报：跳过 3 小时缓存。
        items = await self.state._fetch_qweather_daily(
            key, city, 3, fresh=(slot == "evening")
        )
        if len(items) < 2:
            # 拿不到预报就别每 30 秒重试，今天不提醒。
            self.db.kv_set("weather_alert_checked", slot_key(today, slot))
            return
        text = evaluate_weather_alert(
            items[0], items[1], self.cfg_int("weather_alert_temp_drop", 8)
        )
        self.db.kv_set("weather_alert_checked", slot_key(today, slot))
        if not text:
            logger.info("[amo] 天气提醒（%s）：明天天气正常，不提醒" % label)
            return
        if slot == "morning":
            # 早上只判断，真正的预报晚上再发，一天一条不追发。
            logger.info("[amo] 天气提醒（早上）：明天要变天，晚上 %s 再发给他" % target)
            return
        umos = self._weather_alert_umos()
        if not umos:
            logger.info("[amo] 天气提醒：没有可发送的会话")
            return
        text = await self._weather_alert_text(umos[0], items[1], text)
        # 一个一个平台试：某个平台的会话失效时换下一个，而不是整天发不出去
        sent_umo = ""
        for umo in umos:
            if await self._send_to_umo(umo, text):
                sent_umo = umo
                break
            logger.warning("[amo] 天气提醒这个平台发送失败，换下一个: %s" % umo)
        if sent_umo:
            self.db.kv_set("weather_alert_sent", today)
            self.db.kv_set("weather_alert_open", today)
            logger.info("[amo] 天气提醒已发送: %s -> %s" % (text, sent_umo))
        else:
            # 所有平台都失败：清掉 checked 让下一轮重试（原来也是每轮重试）。
            self.db.kv_set("weather_alert_checked", "")
            logger.warning("[amo] 天气提醒所有平台都失败: %s" % umos)

    def _proactive_owner_ids(self, profiles=None):
        """主动私聊的对象：配了 proactive_owner_ids 只认名单；留空 = 管理员 + 相恋。"""
        raw = str(self.cfg_str("proactive_owner_ids", "") or "").replace("，", ",")
        ids = {item.strip() for item in raw.split(",") if item.strip()}
        if ids:
            return ids
        ids = {str(uid).strip() for uid in (self.admin_uids or set()) if str(uid).strip()}
        rows = profiles
        if rows is None:
            try:
                rows = self.db.proactive_profiles(limit=200)
            except Exception:
                rows = []
        for profile in rows or []:
            try:
                if str(profile.get("relation") or "") != "相恋":
                    continue
                uid = str(profile.get("uid") or "").strip()
            except Exception:
                continue
            if uid:
                ids.add(uid)
        return ids

    async def _maybe_proactive(self):
        quiet = quiet_now(self.cfg_str("quiet_hours", "23:30-07:30"))
        try:
            profiles = self.db.proactive_profiles(limit=100)
        except Exception:
            return
        if self.cfg_bool("proactive_require_friend", True):
            profiles = [profile for profile in profiles if self._is_proactive_friend(profile)]
        # 名单留空 = 管理员 + 相恋；配了名单就只认名单
        owner_ids = self._proactive_owner_ids(profiles)
        if owner_ids:
            profiles = [p for p in profiles if str(p.get("uid") or "") in owner_ids]
        if not profiles:
            return
        random.shuffle(profiles)
        now = now_ts()
        interval = max(10, self.cfg_int("proactive_interval_min", 90)) * 60
        daily_max = max(0, self.cfg_int("proactive_daily_max", 3))
        for profile in profiles:
            uid = str(profile.get("uid") or "")
            if await self._ritual_pending(profile):
                continue
            if self._recent_greeting(uid, self.cfg_int("proactive_after_greeting_minutes", 60)):
                continue
            target_umo = self._pick_proactive_umo(profile)
            if not target_umo:
                continue
            if self._recent_bot_initiated(target_umo, 3600):
                continue
            if self._proactive_user_just_talked(profile, now):
                continue
            count = to_int(profile.get("proactive_count"))
            if profile.get("proactive_day") != today_str():
                count = 0
            if count >= daily_max:
                continue
            relation = str(profile.get("relation") or "普通")
            guaranteed = (
                relation == "相恋"
                and count == 0
                and self.cfg_bool("proactive_daily_guarantee", True)
                and _now().hour >= 8
            )
            if quiet and not guaranteed:
                continue
            if self._pending_still_blocking(profile.get("uid"), profile, now):
                continue
            snap = self.state.snapshot()
            category = (snap.get("activity") or {}).get("category", "")
            if category in ("sleep", "work", "study") and not guaranteed:
                continue
            forced = (
                relation == "相恋"
                and category in ("meal", "rest", "play", "commute")
                and self._proactive_forced_allowed(profile, now)
                and not self._forced_sent_this_hour(profile.get("uid"))
            )
            if not guaranteed and not forced and now - to_float(profile.get("last_proactive", 0)) < interval:
                continue
            if not guaranteed and not forced and random.random() > self.cfg_float("proactive_prob", 0.25):
                continue
            if not guaranteed and self.cfg_bool("proactive_schedule_only", True) and category not in ("meal", "rest", "play", "commute"):
                continue
            kind = self._choose_proactive_kind(profile, snap, category)
            text = await self.llm.gen_proactive(
                target_umo, profile, snap, kind
            )
            if not text:
                continue
            sent_umo = ""
            for candidate in self._proactive_candidates(profile, target_umo):
                if await self._send_to_umo(candidate, text):
                    sent_umo = candidate
                    break
            ok = bool(sent_umo)
            if ok:
                target_umo = sent_umo
                self._mark_bot_initiated(target_umo)
                self.db.kv_set("last_channel:%s" % profile.get("uid"), target_umo)
                self.db.bump_proactive(profile["uid"])
                self.db.log_proactive(profile["uid"], kind, text)
                self._set_proactive_pending(profile["uid"], kind, text, umo=target_umo)
                self._mark_forced_hour(profile.get("uid"))

                logger.debug("[amo] 主动私聊 -> %s (%s)" % (profile.get("name", ""), kind))

    # ---------- 指令 ----------
    def _args(self, event):
        raw = (event.message_str or "").strip()
        raw = re.sub(r"^[/／]\s*", "", raw)
        parts = raw.split()
        if parts and parts[0].lower() in ("amo", "陪伴", "amo_forever", "astrbot_amo_forever"):
            parts = parts[1:]
        return parts

    def _resolve_target(self, event, args, index):
        if Comp is not None:
            for comp in event.get_messages():
                if isinstance(comp, Comp.At):
                    target = str(getattr(comp, "qq", ""))
                    if target and target != "all" and target != str(event.get_self_id()):
                        return target
        if index < len(args):
            token = str(args[index]).strip().lstrip("@")
            if token in ("我", "me", "self"):
                return self._canonical_uid(event)
            if token:
                return token
        return self._canonical_uid(event)

    async def _status_data(self):
        self._reload_config_if_changed()
        umo = self._last_umo or self._first_private_umo()
        if not self.state.weather:
            self.state.weather = self.state._simulate_weather()
        desired_city = (
            self.cfg_str("weather_city_name", "").strip()
            or self.cfg_str("weather_city", "").strip()
            or str((getattr(self.state, "schedule_profile", {}) or {}).get("city") or "").strip()
            or "贵阳"
        )
        if self.state.weather.get("city") != desired_city:
            await self.state.refresh_weather(force=True)
        else:
            self._spawn(self.state.refresh_weather())
        if not self.state.worldview:
            self.state.worldview = self.state._fallback_world()
            self._spawn(self.state.ensure_worldview(umo))
        if (
            not self.state.schedule.get(today_str())
            or self.db.kv_get("schedule_version", "") != SCHEDULE_VERSION
            or not self.state.schedule_context(today_str())
        ):
            await self.state.ensure_schedule(umo)
        snap = self.state.snapshot()
        activity = 0.0
        threshold = {"value": 0.0, "base": 0.0, "absolute": 0.0}
        if self.heartflow is not None:
            try:
                hf_threshold, hf_activity, hf_absolute = self.heartflow._get_dynamic_threshold(umo)
                threshold = {
                    "value": round(float(hf_threshold) * 100, 1),
                    "base": round(float(self.heartflow.reply_threshold) * 100, 1),
                    "absolute": round(float(hf_absolute), 1),
                }
                activity = float(hf_activity) * 100
            except Exception as exc:
                logger.debug("[amo] 心流阈值读取失败: %s" % exc)
        counts = self.db.counts()
        # 记忆条数改成外挂插件的：本插件不再存记忆，面板显示外部模块里的条数
        primary_uid = ""
        try:
            primary = self.db.list_profiles(limit=1)
            primary_uid = str(primary[0].get("uid") or "") if primary else ""
        except Exception:
            primary_uid = ""
        try:
            # 状态页会被轮询，但记忆条数必须跟写入同步：读一次 sqlite 很便宜，
            # 30 秒缓存会让“刚记住”在面板上消失，用户只能手动刷新。
            if primary_uid:
                counted = self._data_memory_count(primary_uid)
                if not counted:
                    counted = len(self._external_all_memories(primary_uid, "", 200))
                counts["memories"] = counted
            else:
                counts["memories"] = 0
        except Exception:
            counts["memories"] = 0
        return {
            "time": snap["datetime_text"],
            "day": day_meta(),
            "mood": snap["mood"],
            "heartflow": (self.feelings.values() if getattr(self, "feelings", None) else {}),
            "dominant": snap["dominant"],
            "mood_score": round(snap["mood_score"], 1),
            "period": snap["period"],
            "health": snap["health"],
            "weather": snap["weather"],
            "weather_text": snap["weather_text"],
            "activity": snap["activity"],
            "schedule": snap["schedule"],
            "schedule_tree": self.state.schedule_tree(),
            "worldview": self.state.worldview,
            "threshold": threshold,
            "activity_rate": round(activity, 2),
            "counts": counts,
            "config": {
                "enable_group_reply": self.cfg_bool("enable_group_reply", True),
                "enable_private_reply": self.cfg_bool("enable_private_reply", True),
                "auto_active_msg": self.cfg_bool("auto_active_msg", True),
                "enable_polish": self.cfg_bool("enable_polish", True),
                "heartflow": self.heartflow is not None,
                "segment_engine": self.segment_engine is not None,
                "weather_key_set": bool(self.cfg_str("hefeng_key", "")),
                "weather_host": self.cfg_str("weather_host", "https://devapi.qweather.com"),
                "version": PLUGIN_VERSION,
                "dialect_style": self._dialect_style(),
                "dialect_count": len(self._dialect_rows()) if self._dialect_active() else 0,
                "companion_memory_available": self._companion_plugin() is not None,
            },
            "data_plugin": {
                "name": "Astr_Amo_data",
                "connected": self._data_connected(),
                "synced": bool(self._data_synced),
            },
        }

    def _format_status(self, data):
        mood = data["mood"]
        mood_line = " ".join([key + str(int(value)) for key, value in mood.items()])
        threshold = data["threshold"]
        return "\n".join([
            "🌙 陪伴 · 当前状态",
            "🕒 " + str(data["time"]),
            "💛 心情：" + str(data["dominant"]) + "（" + mood_line + "）",
            "🩸 生理期：" + str(data["period"]["phase"]) + " 第" + str(data["period"]["day"]) + "天（" + str(data["period"]["tone"]) + "）",
            "🩺 身体：" + str(data["health"]["status"]),
            "🌦 天气：" + str(data["weather_text"]),
            "📅 正在：" + str(data["activity"].get("activity", "休息")) + "（" + str(data["activity"].get("place", "")) + "）",
            "🎚 心流阈值：" + str(threshold["value"]) + "（基础 " + str(threshold["base"]) + "，活跃度 " + str(data["activity_rate"]) + "%）",
            "📚 档案 " + str(data["counts"]["profiles"]) + " · 记忆 " + str(data["counts"]["memories"]) + " · 消息 " + str(data["counts"]["messages"]),
        ])

    async def _handle_command(self, event):
        args = self._args(event)
        sub = args[0].lower() if args else "help"
        uid = self._canonical_uid(event)

        if sub in ("help", "帮助", ""):
            # 指令合并成三行：能一眼扫完，不用往回翻
            return (
                "🌙 陪伴 · /amo 后面接这些\n"
                "查看：status 状态｜mood 心情｜period 生理期｜health 身体｜schedule 日程｜"
                "weather 天气｜worldview 世界观｜threshold 阈值\n"
                "看人：profile [@人]｜memories [@人]｜photo 照片\n"
                "管理：rel @人 关系｜set @人 字段 值｜memo @人 内容 [0/1/2]｜period set 日期｜"
                "health set 状态｜regen 日程/世界观｜say 内容｜clean"
            )

        if sub in ("segment", "分段"):
            text = " ".join(args[1:]).strip()
            delay_type = self.cfg_str("seg_delay_type", "smart")
            if not text:
                return (
                    "分段测试：/amo segment 一段文字\n"
                    "使用完整本地分段引擎：按 seg_split_symbols 的符号列表断句\n"
                    "保留标点：" + ("是" if self.cfg_bool("seg_keep_symbol", True) else "否") +
                    "｜成对符号保护：" + ("开" if self.cfg_bool("seg_protect_paired_symbols", True) else "关") +
                    "｜延迟：" + delay_type +
                    "\n配置项：seg_split_symbols / seg_min_length / seg_max_length / seg_delay_type"
                )
            segments = self._segment(text)
            lines = ["分段结果（" + delay_type + "），共 " + str(len(segments)) + " 段"]
            for index, segment in enumerate(segments, 1):
                lines.append(str(index) + ". " + segment)
            if not segments:
                lines.append("（没有可发送的片段）")
            return "\n".join(lines)

        if sub in ("draw", "画图"):
            engine = getattr(self, "draw", None)
            if engine is None:
                return "画图引擎未加载"
            text = " ".join(args[1:]).strip()
            return engine.manual(event, text)

        if sub in ("photo", "照片"):
            engine = getattr(self, "photo", None)
            if engine is None:
                return "照片引擎未加载"
            tail = " ".join(args[1:]).strip().lower()
            if tail in ("test", "测试", "share"):
                return "照片测试：" + await engine.share_now("daily")
            if tail in ("travel", "shopping", "weekend", "daily", "outfit"):
                return "照片测试：" + await engine.share_now(tail)
            return engine.status_text()

        if sub == "status" or sub == "状态":
            return self._format_status(await self._status_data())

        if sub == "mood" or sub == "心情":
            snap = self.state.snapshot()
            lines = ["🎨 陪伴的十维心情"]
            for key, value in snap["mood"].items():
                bar = "█" * int(round(value / 10)) + "░" * (10 - int(round(value / 10)))
                lines.append("%s %s %d" % (key, bar, int(value)))
            lines.append("整体偏「%s」，语气：%s" % (
                snap["dominant"], self.state.tone_text(snap, "普通")
            ))
            return "\n".join(lines)

        if sub == "profile" or sub == "档案":
            target = self._resolve_target(event, args, 1)
            profile = self.db.get_profile(target)
            if not profile:
                return "还没有这个人的档案。多聊几句就会自动建立。"
            return "\n".join([
                "📁 档案 · " + (profile.get("name") or profile.get("uid")),
                "ID：" + str(profile.get("uid")),
                "称呼：" + str(profile.get("alias") or "未设置"),
                "生日：" + str(profile.get("birthday") or "未知"),
                "关系：" + str(profile.get("relation") or "普通"),
                "好感：" + str(profile.get("affection") or 0),
                "消息数：" + str(profile.get("msg_count") or 0),
                "记忆数：" + str(len(self._external_all_memories(target, "", 200))),
                "备注：" + str(profile.get("notes") or "无"),
            ])

        if sub == "memories" or sub == "记忆":
            target = self._resolve_target(event, args, 1)
            if target != uid and not self._is_admin(event):
                return "只有管理员才能查看别人的记忆。"
            items = self._external_all_memories(target, "", 20)
            if not items:
                return "暂时没有记忆。"
            lines = ["📖 记忆 · " + target]
            for item in items:
                tier = to_int(item.get("tier"))
                label = "珍贵" if tier >= 2 else ("重要" if tier == 1 else "普通")
                expires = item.get("expires_at")
                if not expires:
                    left = "永久"
                else:
                    left = "%d天" % max(0, int((to_float(expires) - now_ts()) / 86400))
                lines.append("#%s [%s|%s] %s" % (item["id"], label, left, item["content"]))
            return "\n".join(lines)

        if sub in ("rel", "关系"):
            if not self._is_admin(event):
                return "只有管理员才能调整关系。"
            if len(args) < 3:
                return "用法：/amo rel @人 仇恨|抵触|普通|熟识|相恋"
            target = self._resolve_target(event, args, 1)
            relation = args[2]
            if relation not in RELATIONS:
                return "关系只能是：" + "、".join(RELATIONS)
            self.db.update_profile(target, relation=relation)
            if relation == "相恋":
                self._register_lover(target)
            await self._sync_profile_relation_edge(target, relation)
            self._external_memory_write(target, "与角色的关系是" + relation, "relation", 2)
            return "✅ 已将 " + target + " 的关系设为「" + relation + "」"

        if sub == "set" or sub == "设置":
            if not self._is_admin(event):
                return "只有管理员才能修改档案。"
            if len(args) < 4:
                return "用法：/amo set @人 name|alias|birthday|notes|affection 值"
            target = self._resolve_target(event, args, 1)
            field = args[2]
            value = " ".join(args[3:])
            if field == "relation":
                return "请用 /amo rel 设置关系。"
            if field == "birthday":
                match = re.match(r"^(\d{4}-)?(\d{1,2})-(\d{1,2})$", value)
                if not match:
                    return "生日格式：MM-DD 或 YYYY-MM-DD"
                value = "%02d-%02d" % (to_int(match.group(2)), to_int(match.group(3)))
            if field == "affection":
                value = int(clamp(to_int(value), 0, 100))
            if field not in ("name", "alias", "birthday", "notes", "affection"):
                return "可修改字段：name、alias、birthday、notes、affection"
            self.db.update_profile(target, **{field: value})
            return "✅ 已更新 " + target + " 的 " + field

        if sub == "memo" or sub == "记住":
            if not self._is_admin(event):
                return "只有管理员才能手动写入记忆。"
            if len(args) < 3:
                return "用法：/amo memo @人 内容 [0普通/1重要/2珍贵]"
            target = self._resolve_target(event, args, 1)
            content_parts = args[2:]
            tier = 1
            if content_parts and content_parts[-1] in ("0", "1", "2"):
                tier = to_int(content_parts[-1])
                content_parts = content_parts[:-1]
            content = " ".join(content_parts).strip()
            if not content:
                return "内容不能为空。"
            scope, group_id = self._memory_scope(event)
            if self._external_memory_write(target, content, "manual", tier, scope, group_id):
                return "✅ 已记住：" + content
            return "⚠️ 没能写进记忆插件：请先在设置里选好记忆来源插件。"

        if sub == "forget" or sub == "忘记":
            if not self._is_admin(event):
                return "只有管理员才能删除记忆。"
            if len(args) < 2:
                return "用法：/amo forget 记忆ID"
            return "记忆由外挂插件保存，请到该插件里删除；本插件不再单独存记忆。"

        if sub == "period" or sub == "生理期":
            if len(args) >= 3 and args[1].lower() == "set":
                if not self._is_admin(event):
                    return "只有管理员才能调整生理期。"
                if self.state.set_period_start(args[2]):
                    return "✅ 生理期起始日已设为 " + args[2]
                return "日期格式应为 YYYY-MM-DD"
            period = self.state.period_info()
            return (
                "🩸 生理期\n阶段：" + period["phase"] + " 第" + str(period["day"]) + "天\n"
                "状态：" + period["tone"] + "\n"
                "疼痛：" + str(period["pain"]) + "/10\n"
                "周期：" + str(period.get("cycle_days", 28)) + "天｜经期：" + str(period.get("bleed_days", 5)) + "天\n"
                "距离下次：" + str(period["days_to_next"]) + "天（预计 " + str(period.get("next_start", "")) + "）\n"
                "起始日：" + self.state.period_start + "（/amo period set YYYY-MM-DD，或网页配置 period_start）"
            )

        if sub == "health" or sub == "健康":
            if len(args) >= 3 and args[1].lower() == "set":
                if not self._is_admin(event):
                    return "只有管理员才能调整健康状态。"
                status = args[2]
                if status not in ("健康", "轻微不适", "感冒", "低烧", "疲惫"):
                    return "状态：健康 / 轻微不适 / 感冒 / 低烧 / 疲惫"
                self.state.set_health(status, 24, "管理员设置")
                return "✅ 健康状态已设为 " + status
            health = self.state.health_info()
            return (
                "🩺 身体状态：" + health["status"] + "\n"
                + ("备注：" + health["note"] + "\n" if health.get("note") else "")
                + "恢复时间：" + (
                    datetime.fromtimestamp(health["until"]).strftime("%m-%d %H:%M")
                    if health.get("until") else "—"
                )
            )

        if sub == "schedule" or sub == "日程":
            if len(args) >= 2 and args[1].lower() == "regen":
                if not self._is_admin(event):
                    return "只有管理员才能重生成日程。"
                items = await self.state.ensure_schedule(self._last_umo, force=True)
                return "✅ 日程已重新生成，共 " + str(len(items)) + " 条。"
            items = self.state.schedule.get(today_str()) or []
            if not items:
                items = await self.state.ensure_schedule(self._last_umo)
            activity = self.state.current_activity()
            lines = ["📅 今日日程"]
            for item in items:
                lines.append("%s-%s %s（%s）" % (
                    item.get("start", ""), item.get("end", ""),
                    item.get("activity", ""), item.get("place", ""),
                ))
            lines.append("现在应该在：" + str(activity.get("activity", "")))
            return "\n".join(lines)

        if sub == "weather" or sub == "天气":
            if len(args) >= 2 and args[1].lower() in ("refresh", "刷新"):
                await self.state.refresh_weather(force=True)
            weather = await self.state.refresh_weather()
            return (
                "🌦 " + str(weather.get("city", "")) + " " + str(weather.get("text", ""))
                + " " + str(weather.get("temp", "")) + "℃\n"
                + "湿度：" + str(weather.get("humidity", "")) + "%\n"
                + "风：" + str(weather.get("wind", "")) + "\n"
                + "来源：" + ("和风天气" if weather.get("source") == "qweather" else "本地模拟")
            )

        if sub == "worldview" or sub == "世界观":
            if len(args) >= 2 and args[1].lower() == "regen":
                if not self._is_admin(event):
                    return "只有管理员才能重生成世界观。"
                await self.state.ensure_worldview(self._last_umo, force=True)
                return "✅ 世界观已重新生成。"
            await self.state.ensure_worldview(self._last_umo)
            return "🌍 世界观\n" + self.state.worldview_text()

        if sub == "threshold" or sub == "阈值":
            data = await self._status_data()
            threshold = data["threshold"]
            return (
                "🎚 心流回复阈值\n"
                "当前动态阈值：" + str(round(threshold["value"] / 100, 3)) + "\n"
                "基础阈值：" + str(round(threshold["base"] / 100, 3)) + "\n"
                "绝对分数阈值：" + str(threshold["absolute"]) + "/10\n"
                "当前群活跃度：" + str(data["activity_rate"]) + "%\n"
                "说明：阈值越高越不想说话；详细状态用 /heartflow。"
            )

        if sub == "say" or sub == "说":
            if not self._is_admin(event):
                return "只有管理员才能测试发言。"
            content = " ".join(args[1:]).strip()
            if not content:
                return "用法：/amo say 内容"
            await event.send(MessageChain([Comp.Plain(content)]))
            return ""

        if sub == "clean" or sub == "清理":
            if not self._is_admin(event):
                return "只有管理员才能清理。"
            self.db.purge_messages(self.cfg_int("chat_log_days", 14))
            return "✅ 已清理过期聊天记录。"

        return "未知指令。发送 /amo help 查看帮助。"

    # ---------- 心流完整版指令 ----------
    @filter.command("heartflow")
    async def cmd_heartflow(self, event: AstrMessageEvent):
        await self._ensure_ready()
        if self.heartflow is None:
            yield event.plain_result("心流引擎未加载")
            return
        async for item in self.heartflow.heartflow_status(event):
            yield item

    @filter.command("heartflow_debug")
    async def cmd_heartflow_debug(self, event: AstrMessageEvent):
        await self._ensure_ready()
        if self.heartflow is None:
            yield event.plain_result("心流引擎未加载")
            return
        async for item in self.heartflow.heartflow_debug(event):
            yield item

    @filter.command("heartflow_clear")
    async def cmd_heartflow_clear(self, event: AstrMessageEvent):
        await self._ensure_ready()
        if self.heartflow is None:
            yield event.plain_result("心流引擎未加载")
            return
        async for item in self.heartflow.heartflow_clear_buffer(event):
            yield item

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("heartflow_log")
    async def cmd_heartflow_log(self, event: AstrMessageEvent):
        await self._ensure_ready()
        if self.heartflow is None:
            yield event.plain_result("心流引擎未加载")
            return
        async for item in self.heartflow.heartflow_toggle_log(event):
            yield item

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("heartflow_reset")
    async def cmd_heartflow_reset(self, event: AstrMessageEvent):
        await self._ensure_ready()
        if self.heartflow is None:
            yield event.plain_result("心流引擎未加载")
            return
        async for item in self.heartflow.heartflow_reset(event):
            yield item

    @filter.command("heartflow_help")
    async def cmd_heartflow_help(self, event: AstrMessageEvent):
        await self._ensure_ready()
        if self.heartflow is None:
            yield event.plain_result("心流引擎未加载")
            return
        async for item in self.heartflow.heartflow_help(event):
            yield item

    @filter.command("amo")
    async def cmd_amo(self, event: AstrMessageEvent):
        await self._ensure_ready()
        try:
            message = await self._handle_command(event)
        except Exception as exc:
            logger.error("[amo] 指令异常: %s" % exc)
            message = "处理失败：" + str(exc)
        if message:
            yield event.plain_result(message)

    @filter.command("c_status")
    async def cmd_status(self, event: AstrMessageEvent):
        await self._ensure_ready()
        yield event.plain_result(self._format_status(await self._status_data()))

    @filter.command("c_profile")
    async def cmd_profile(self, event: AstrMessageEvent):
        await self._ensure_ready()
        uid = self._canonical_uid(event)
        profile = self.db.get_profile(uid)
        if not profile:
            yield event.plain_result("还没有你的档案。")
            return
        yield event.plain_result(
            "🤍 关系：" + str(profile.get("relation", "普通"))
            + "\n📖 记忆条数：" + str(len(self._external_all_memories(uid, "", 200)))
        )

    @filter.command("c_setrel")
    async def cmd_setrel(self, event: AstrMessageEvent):
        await self._ensure_ready()
        if not self._is_admin(event):
            yield event.plain_result("只有管理员才能调整关系。")
            return
        parts = [item for item in (event.message_str or "").replace("/", " ").split() if item]
        relation = parts[-1] if parts else ""
        if relation not in RELATIONS:
            yield event.plain_result("用法：/c_setrel 仇恨|抵触|普通|熟识|相恋")
            return
        uid = self._canonical_uid(event)
        self.db.update_profile(uid, relation=relation)
        yield event.plain_result("✅ 关系已设置为：" + relation)

    @filter.command("learn_and_gate")
    async def cmd_learn(self, event: AstrMessageEvent):
        await self._ensure_ready()
        text = (event.message_str or "").replace("/learn_and_gate", "").strip()
        if not text:
            yield event.plain_result("请输入要学习的内容")
            return
        uid = self._canonical_uid(event)
        scope, group_id = self._memory_scope(event)
        if self._external_memory_write(uid, text, "manual", 1, scope, group_id):
            yield event.plain_result("✅ 已经记下来啦。")
        else:
            yield event.plain_result("⚠️ 没能写进记忆插件：请先在设置里选好记忆来源插件。")

    # ---------- Web 面板 ----------
    def _register_web_apis(self):
        prefixes = uniq([
            getattr(self, "name", None),
            PLUGIN_NAME,
            os.path.basename(self.plugin_dir),
            "astrbot_plugin_Astrbot_Amo_forever",
            "astrbot_plugin_amo_forever",
        ])
        # 清除上一实例/旧版本残留的 Web API 路由。
        # AstrBot 重载插件时不会自动清理 registered_web_apis，旧路由会继续
        # 指向已经 terminate 的旧实例，表现为 "Cannot operate on a closed database"。
        try:
            own_prefixes = tuple(
                "/" + str(prefix).strip("/") + "/"
                for prefix in prefixes
                if str(prefix).strip("/")
            )
            holders = (type(self.context), self.context)
            seen_holders = set()
            for holder in holders:
                if id(holder) in seen_holders:
                    continue
                seen_holders.add(id(holder))
                registry = getattr(holder, "registered_web_apis", None)
                if not isinstance(registry, list):
                    continue
                registry[:] = [
                    item
                    for item in registry
                    if not (
                        isinstance(item, tuple)
                        and item
                        and (
                            str(item[0]).startswith(own_prefixes)
                            or str(item[0]) in ("get_status", "get_profile", "refresh_status")
                        )
                    )
                ]
        except Exception as exc:
            logger.warning("[amo] 清理旧 Web API 路由失败（插件重载后如遇 closed database，请完整重启）: %s" % exc)
        routes = [
            ("/status", self.api_status, ["GET"]),
            ("/get_status", self.api_get_status, ["GET"]),
            ("/diary/tree", self.api_diary_tree, ["GET", "POST"]),
            ("/diary/read", self.api_diary_read, ["GET", "POST"]),
            ("/diary/write", self.api_diary_write, ["POST"]),
            ("/diary/open", self.api_diary_open, ["GET", "POST"]),
            ("/diary/import", self.api_diary_import, ["POST"]),
            ("/profiles", self.api_profiles, ["GET", "POST"]),
            ("/get_profile", self.api_get_profile, ["GET", "POST"]),
            ("/profiles/sync", self.api_profiles_sync, ["GET", "POST"]),
            ("/relations", self.api_relations, ["GET", "POST"]),
            ("/relation/save", self.api_relation_save, ["GET", "POST"]),
            ("/relation_save", self.api_relation_save, ["GET", "POST"]),
            ("/relation/delete", self.api_relation_delete, ["GET", "POST"]),
            ("/relation_delete", self.api_relation_delete, ["GET", "POST"]),
            ("/memory/candidates", self.api_memory_candidates, ["GET"]),
            ("/memory_candidates", self.api_memory_candidates, ["GET"]),
            ("/profiles_sync", self.api_profiles_sync, ["GET", "POST"]),
            ("/config", self.api_config, ["GET"]),
            ("/voice/save", self.api_voice_save, ["GET", "POST"]),
            ("/weather/brief", self.api_weather_brief, ["GET", "POST"]),
            ("/city/search", self.api_city_search, ["GET", "POST"]),
            ("/city/set", self.api_city_set, ["GET", "POST"]),
            ("/photo/job", self.api_photo_job, ["GET", "POST"]),
            ("/photo/self", self.api_photo_self, ["GET", "POST"]),
            ("/photo/last", self.api_photo_last, ["GET", "POST"]),
            ("/photo/clear", self.api_photo_clear, ["GET", "POST"]),
            ("/draw/status", self.api_draw_status, ["GET", "POST"]),
            ("/draw/test", self.api_draw_test, ["GET", "POST"]),
            ("/draw/decide", self.api_draw_decide, ["GET", "POST"]),
            ("/usage", self.api_usage, ["GET"]),
            ("/providers", self.api_providers, ["GET"]),
            ("/providers_list", self.api_providers, ["GET"]),
            ("/balance", self.api_balance, ["GET"]),
            ("/config/save", self.api_config_save, ["GET", "POST"]),
            ("/config_save", self.api_config_save, ["GET", "POST"]),
            ("/profile/save", self.api_profile_save, ["GET", "POST"]),
            ("/profile/links", self.api_profile_links, ["GET", "POST"]),
            ("/profile_save", self.api_profile_save, ["GET", "POST"]),
            ("/profile/delete", self.api_profile_delete, ["GET", "POST"]),
            ("/profile_delete", self.api_profile_delete, ["GET", "POST"]),
            ("/memories", self.api_memories, ["GET", "POST"]),
            ("/chat/history", self.api_chat_history, ["GET", "POST"]),
            ("/chat_history", self.api_chat_history, ["GET", "POST"]),
            ("/memory/add", self.api_memory_add, ["GET", "POST"]),
            ("/memory_add", self.api_memory_add, ["GET", "POST"]),
            ("/memory/delete", self.api_memory_delete, ["GET", "POST"]),
            ("/memory_delete", self.api_memory_delete, ["GET", "POST"]),
            ("/schedule", self.api_schedule, ["GET", "POST"]),
            ("/diary/warm", self.api_diary_warm, ["GET", "POST"]),
            ("/wardrobe", self.api_wardrobe, ["GET", "POST"]),
            ("/wardrobe/save", self.api_wardrobe_save, ["GET", "POST"]),
            ("/wardrobe/delete", self.api_wardrobe_delete, ["GET", "POST"]),
            ("/wardrobe/wear", self.api_wardrobe_wear, ["GET", "POST"]),
            ("/schedule/detail", self.api_schedule_detail, ["GET", "POST"]),
            ("/schedule_detail", self.api_schedule_detail, ["GET", "POST"]),
            ("/schedule/regen", self.api_schedule_regen, ["GET", "POST"]),
            ("/kb/regen", self.api_kb_regen, ["GET", "POST"]),
            ("/scenic_kb/regen", self.api_scenic_kb_regen, ["GET", "POST"]),
            ("/scenic_kb_regen", self.api_scenic_kb_regen, ["GET", "POST"]),
            ("/kb_regen", self.api_kb_regen, ["GET", "POST"]),
            ("/schedule_regen", self.api_schedule_regen, ["GET", "POST"]),
            ("/weather", self.api_weather, ["GET"]),
            ("/worldview", self.api_worldview, ["GET"]),
            ("/worldview/regen", self.api_worldview_regen, ["GET", "POST"]),
            ("/worldview_regen", self.api_worldview_regen, ["GET", "POST"]),
            ("/say", self.api_say, ["GET", "POST"]),
            ("/refresh_status", self.api_refresh_status, ["GET"]),
        ]
        for prefix in prefixes:
            clean = str(prefix).strip("/")
            if not clean:
                continue
            for path, handler, methods in routes:
                self._safe_register("/" + clean + path, handler, methods, path)
        # 不注册无前缀的旧路由，避免和其他插件或 AstrBot 自带路由冲突。

    def _web_guard(self, handler, is_write=False):
        """写操作的前置检查：只收 POST + 拒绝跨站来源。

        这不是完整鉴权（AstrBot 侧有它自己的登录态），而是挡住
        <img src>/聊天预览/外链/跨站表单这类最容易触发的 CSRF 面。

        - 写路由在 `_safe_register` 里已经只注册 POST，这里再兜一层（防止别的注册路径漏掉）；
        - `Sec-Fetch-Site: cross-site` 直接 403（浏览器自己标的跨站，最可靠）；
        - Origin/Referer 与 Host 不一致：带 `same-origin/same-site` 的放行（反向代理/内网穿透下
          Host 常被改写），没有 Sec-Fetch-Site 的按跨站处理。
        """
        async def wrapper(*args, **kwargs):
            try:
                method = ""
                origin = ""
                host = ""
                site = ""
                headers = None
                if web_request is not None:
                    method = str(getattr(web_request, "method", "") or "").upper()
                    headers = getattr(web_request, "headers", None)
                    if headers is not None:
                        origin = str(headers.get("origin") or headers.get("referer") or "")
                        host = str(headers.get("host") or "")
                        site = str(headers.get("sec-fetch-site") or "").strip().lower()
                if is_write and method and method != "POST":
                    logger.warning("[amo] 拒绝非 POST 的 Web 写操作（%s）" % method)
                    return {"code": 403, "msg": "写操作只接受 POST（面板请刷新到最新版）"}
                if is_write and site == "cross-site":
                    logger.warning("[amo] 拒绝跨站 Web 写操作（origin=%s）" % origin)
                    return {"code": 403, "msg": "拒绝跨站请求"}
                if is_write and origin and host:
                    from urllib.parse import urlparse
                    origin_host = (urlparse(origin).hostname or "").lower()
                    allowed_hosts = {(host.split(":")[0] or "").strip().lower()}
                    if headers is not None:
                        for key in ("x-forwarded-host", "x-real-host"):
                            value = str(headers.get(key) or "").split(",")[0].strip()
                            if value:
                                allowed_hosts.add(value.split(":")[0].strip().lower())
                    allowed_hosts.discard("")
                    if origin_host and allowed_hosts and origin_host not in allowed_hosts:
                        if site in ("same-origin", "same-site"):
                            logger.debug("[amo] Web 写操作 Host 与 Origin 不一致（同源请求，放行）: %s -> %s"
                                         % (origin, host))
                        else:
                            logger.warning("[amo] 拒绝来源不一致的 Web 写操作: %s -> %s" % (origin, host))
                            return {"code": 403, "msg": "拒绝来源不一致的请求"}
            except Exception as exc:
                logger.debug("[amo] Web 守卫检查失败（放行）: %s" % exc)
            return await handler(*args, **kwargs)
        return wrapper

    def _safe_register(self, route, handler, methods, desc):
        # 写接口只收 POST：面板的 WRITE_ACTIONS 已经强制带 body 走 POST，
        # 老版本面板桥接没有 apiPost 时会收到 405/403，然后自动退回 fetch POST（前端有兜底）。
        # 读接口不套守卫，避免给状态轮询加额外开销。
        # 注意：route 带插件名前缀（/Astrbot_Amo_forever/...），WRITE_ROUTES 里存的是不带前缀的
        # 路径，所以要拿 desc（注册时传的 path）来判定，否则所有写路由都会被漏掉。
        is_write = str(desc or "") in WRITE_ROUTES
        if is_write:
            methods = ["POST"]
        if is_write:
            handler = self._web_guard(handler, is_write=True)
        try:
            self.context.register_web_api(route, handler, methods, desc)
            return True
        except TypeError:
            pass
        except Exception as exc:
            logger.debug("[amo] Web API 注册失败 %s: %s" % (route, exc))
            return False
        try:
            self.context.register_web_api(route, methods, desc, handler)
            return True
        except Exception as exc:
            logger.debug("[amo] Web API 兼容注册失败 %s: %s" % (route, exc))
            return False

    def _q(self, key, default=None):
        try:
            if web_request is not None:
                return web_request.query.get(key, default)
        except Exception:
            pass
        return default

    def _q_int(self, key, default=0):
        return to_int(self._q(key, default), default)

    async def _body(self):
        try:
            if web_request is not None and hasattr(web_request, "json"):
                data = await web_request.json(default={})
                return data if isinstance(data, dict) else {}
        except Exception:
            pass
        try:
            if web_request is not None:
                data = await web_request.get_json(silent=True)
                return data or {}
        except Exception:
            pass
        return {}

    @staticmethod
    def _coerce_config_value(kind, value):
        if kind == "bool":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("1", "true", "yes", "on", "是")
        if kind == "int":
            return int(float(value))
        if kind == "float":
            return float(value)
        if kind in ("list", "template_list"):
            if isinstance(value, list):
                return value
            parsed = json.loads(value) if isinstance(value, str) and value.strip() else []
            return parsed if isinstance(parsed, list) else []
        if kind in ("dict", "object"):
            if isinstance(value, dict):
                return value
            parsed = json.loads(value) if isinstance(value, str) and value.strip() else {}
            return parsed if isinstance(parsed, dict) else {}
        return str(value)

    def _schema_map(self):
        path = os.path.join(self.plugin_dir, "_conf_schema.json")
        try:
            with open(path, encoding="utf-8") as stream:
                schema = json.load(stream)
            return schema if isinstance(schema, dict) else {}
        except Exception as exc:
            logger.warning("[amo] 读取配置 schema 失败: %s" % exc)
            return {}

    # 这些值绝不能随 /config 明文下发（GET 无 body、无 CSRF 校验）
    SENSITIVE_KEYS = {"hefeng_key", "deepseek_api_key"}

    def _apply_forced_on_config(self):
        for key in FORCED_ON_CONFIG_KEYS:
            try:
                if key in self.config and self.config.get(key) is not True:
                    self.config[key] = True
            except Exception:
                pass

    @staticmethod
    def _mask_secret(value):
        text = str(value or "")
        if not text:
            return ""
        if len(text) <= 8:
            return "*" * len(text)
        return text[:4] + "*" * (len(text) - 8) + text[-4:]

    def _config_schema_items(self):
        schema = self._schema_map()
        items = []
        for key, meta in schema.items():
            if not isinstance(meta, dict):
                continue
            if key in FORCED_ON_CONFIG_KEYS:
                # 默认常开、关了会整块失效的开关：不在面板显示，值固定为开。
                continue
            if key in PANEL_HIDDEN_KEYS:
                # 面板不展示（配置文件仍可改）：评分规则、判定提示词这类「改错了很难查」的项
                continue
            if key.startswith("hf_"):
                group = "心流"
            elif key.startswith("voice_"):
                group = "语音"
            elif key.startswith("image_share_") or key.startswith("draw_") or key.startswith("photo_"):
                group = "照片"
            elif key.startswith("seg_"):
                group = "分段"
            elif key.startswith("companion_") or key.startswith("memory_") or key in ("admin_uids",):
                group = "记忆"
            elif key.startswith("proactive_") or key.startswith("delay_") or key.startswith("disturb_") or key in ("quiet_hours", "auto_active_msg"):
                group = "私聊"
            elif key.startswith("period_") or key.startswith("enable_period") or key.startswith("enable_sick"):
                group = "状态"
            elif (
                key in ("timezone", "hefeng_key", "weather_city", "weather_city_name",
                        "weather_host", "weather_geo_host")
                or key.startswith("weather_alert_")
                or key.startswith("city_follow_")
                or key == "city_travel_schedule"
            ):
                group = "时间天气"
            else:
                group = "基础"
            items.append({
                "key": key,
                "type": meta.get("type", "string"),
                "description": meta.get("description") or key,
                "hint": meta.get("hint", ""),
                "default": meta.get("default"),
                "options": meta.get("options") or [],
                "special": meta.get("_special", ""),
                "group": group,
                "value": (
                    self._mask_secret(self.cfg(key, meta.get("default")))
                    if key in self.SENSITIVE_KEYS
                    else self.cfg(key, meta.get("default"))
                ),
                "configured": (
                    bool(str(self.cfg(key, "") or "").strip())
                    if key in self.SENSITIVE_KEYS
                    else True
                ),
                "sensitive": key in self.SENSITIVE_KEYS,
            })
        return items

    async def _apply_runtime_config(self):
        self._admin_cache = {}
        self.bot_name = self.cfg_str("bot_name", self.bot_name) or "陪伴"
        self._persona_name_cache.clear()
        self.bot_aliases = [
            item.strip() for item in self.cfg_str("bot_aliases", "").split(",") if item.strip()
        ]
        self.admin_uids = {
            item.strip() for item in self.cfg_str("admin_uids", "").split(",") if item.strip()
        }
        if self.state is not None:
            start = self.cfg_str("period_start", "").strip()
            if start and start != self.state.period_start:
                try:
                    date.fromisoformat(start)
                    self.state.set_period_start(start)
                except Exception:
                    pass
            try:
                await self.state.refresh_weather(force=True)
            except Exception:
                pass
        if HeartflowEngine is not None:
            old = self.heartflow
            if old is not None:
                try:
                    await old.terminate()
                except Exception:
                    pass
            try:
                hf_config = self._hf_config()
                hf_config.setdefault("enable_heartflow", True)
                hf_config.setdefault("enable_dynamic_threshold", True)
                hf_config.setdefault("judge_provider_name", "")
                self.heartflow = HeartflowEngine(self.context, hf_config)
                try:
                    self.heartflow.plugin = self
                except Exception:
                    pass
                self.heartflow.set_identity(self.bot_name, self.bot_aliases)
            except Exception as exc:
                logger.error("[amo] 应用心流配置失败: %s" % exc)
        if SegmentEngine is not None:
            old = self.segment_engine
            if old is not None:
                for task in list(getattr(old, "_tasks", set())):
                    try:
                        task.cancel()
                    except Exception:
                        pass
            try:
                seg_config = self._seg_config()
                seg_config.setdefault("protect_paired_symbols", True)
                self.segment_engine = SegmentEngine(self.context, seg_config, plugin=self)
            except Exception as exc:
                logger.error("[amo] 应用分段配置失败: %s" % exc)

    # ---- 中文城市名 → LocationID（离线表，见 amo_city_index.py） ----
    def _city_module(self):
        """离线城市表模块（懒加载；缺失时返回 None，天气按原样走）。"""
        try:
            try:
                from . import amo_city_index
            except Exception:
                import amo_city_index
            return amo_city_index
        except Exception as exc:
            logger.debug("[amo] 城市表不可用: %s" % exc)
            return None

    def _city_lookup(self, text):
        """把「东莞」「北京朝阳」解析成 LocationID；失败返回 None。"""
        module = self._city_module()
        if module is None:
            return None
        try:
            return module.resolve_city(text)
        except Exception as exc:
            logger.debug("[amo] 城市名解析失败: %s" % exc)
            return None

    async def _maybe_follow_city(self, event, uid, profile):
        """他到了某地：她问「我来陪你吧」；同意就跟去（路上约 2 小时），拒绝就闷闷不乐。"""
        if not self.cfg_bool("city_follow_enabled", True):
            return ""
        try:
            if not event.is_private_chat():
                return ""
        except Exception:
            return ""
        if str(profile.get("relation") or "") != "相恋":
            return ""
        text = str(event.message_str or "")
        now = now_ts()
        offer = self.db.kv_get("follow_offer", {}) or {}
        offer = offer if isinstance(offer, dict) else {}
        if offer and now - to_float(offer.get("ts"), 0) > 1800:
            self.db.kv_set("follow_offer", {})
            offer = {}
        travel = self.db.kv_get("travel", {}) or {}
        travel = travel if isinstance(travel, dict) else {}
        if travel.get("city") and re.search(r"(回来吧|回家吧|别玩了|该回来了|我回东莞)", text):
            await self._end_follow_trip(uid)
            return "【回家】他说回来了：自然应一句「好，我这就回」，别拖，也别说还没玩够。"
        if travel.get("city"):
            return ""
        if self.db.kv_get("wander_trip", {}):
            return ""
        if _follow_invite(text):
            city = str(self.db.kv_get("he_city", "") or "").strip()
            if not city:
                return "【邀请】他让你过去，但你不知道他在哪个城市：先问一句他在哪。"
            if city == _CITY_DEFAULT:
                return "【邀请】他让你过去，可你俩都在东莞：自然回一句“我不就在你旁边吗”之类的。"
            self.db.kv_set("follow_declined", {})
            return await self._start_follow_trip(uid, {
                "city": city, "id": "",
                "tomorrow": _now().hour >= 22,
            })
        if offer.get("city"):
            if _wander_agree(text):
                return await self._start_follow_trip(uid, offer)
            if _follow_refuse(text):
                return await self._reject_follow_trip(uid, offer)
        old_he = str(self.db.kv_get("he_city", "") or "").strip()
        old = str(self.db.kv_get("his_city", "") or "").strip()
        hit = _city_detect(text, prefer_city=old or old_he)
        if not hit:
            return ""
        name = str(hit.get("name") or "").strip()
        declined = self.db.kv_get("follow_declined", {}) or {}
        declined_city = str(declined.get("city") or "") if isinstance(declined, dict) else ""
        if not name or name == old_he:
            if declined_city and declined_city == name:
                return "【别重复提】你之前问过要不要去陪他，他没让；别再主动提这事，按他说的上班就好。"
            return ""
        if name == _CITY_DEFAULT:
            self.db.kv_set("he_city", name)
            self.db.kv_set("follow_declined", {})
            return ""
        # 到了新的城市：之前"被拒过"的标记作废，可以再问一次
        self.db.kv_set("follow_declined", {})
        tomorrow = _now().hour >= 22
        self.db.kv_set("he_city", name)
        self.db.kv_set("wander_offer", {})
        self.db.kv_set("follow_offer", {
            "ts": now, "city": name, "id": str(hit.get("id") or ""), "tomorrow": tomorrow,
        })
        return _follow_block(True, name, tomorrow)

    async def _start_follow_trip(self, uid, offer):
        """同意跟去：定出发日/出发时间，当天或次日先坐 2 小时车再玩。"""
        city = str(offer.get("city") or "").strip()
        if not city:
            self.db.kv_set("follow_offer", {})
            return ""
        tomorrow = bool(offer.get("tomorrow"))
        start = (_now().date() + timedelta(days=1)) if tomorrow else _now().date()
        start_hour = 9 if tomorrow else _now().hour
        spots = []
        try:
            spots = _city_pick_spots(self.scenic_spots(), city, start.isoformat())
        except Exception:
            spots = []
        trip = {
            "city": city,
            "id": str(offer.get("id") or ""),
            "from": str(self.db.kv_get("his_city", "") or ""),
            "start_day": start.isoformat(),
            "start_hour": start_hour,
            "spots": [dict(x) for x in spots][:4],
            "phase": "journey",
        }
        self.db.kv_set("travel", trip)
        self.db.kv_set("follow_offer", {})
        self.db.kv_set("follow_declined", {})
        try:
            content = "她 %s 坐车去 %s 陪他（路上约 2 小时）" % (start.isoformat(), city)
            if not await self._write_memory_checked(uid, content, "event", 1):
                logger.warning("[amo] 跟随记忆没写进去")
        except Exception as exc:
            logger.warning("[amo] 跟随记忆写入失败: %s" % exc)
        try:
            log = self.db.kv_get("travel_log", []) or []
            if not isinstance(log, list):
                log = []
            log.append({"day": start.isoformat(), "hour": "%02d:00" % start_hour,
                        "city": city, "journey": True})
            self.db.kv_set("travel_log", log[-10:])
        except Exception:
            pass
        if not tomorrow:
            self.db.kv_set("his_city", city)
            hit = self._city_lookup(city)
            if hit:
                try:
                    await self._switch_weather_city(hit)
                except Exception as exc:
                    logger.warning("[amo] 跟随天气切换失败: %s" % exc)
            try:
                self.state.apply_follow_start(city, start_hour, spots, keep_past=True)
            except Exception as exc:
                logger.warning("[amo] 跟随日程失败: %s" % exc)
            trip["phase"] = "touring"
            self.db.kv_set("travel", trip)
        plan = _wander_follow_agree_text(city, random)
        when = "明天一早" if tomorrow else "现在"
        return (
            "【出发】他同意了：你" + when + "出发去 " + city + " 陪他，路上约 2 小时，到了再找他。"
            "照这个意思说一句（别报公司/上班）：" + plan
        )

    async def _reject_follow_trip(self, uid, offer):
        """他让她好好上班：她闷闷不乐，日程不变，日记记一笔。"""
        city = str(offer.get("city") or "").strip()
        self.db.kv_set("follow_offer", {})
        self.db.kv_set("follow_declined", {"city": city, "day": today_str()})
        try:
            self.state.nudge(委屈=10, 郁闷=8, 开心=-6)
        except Exception:
            pass
        try:
            content = "她说想去%s陪他，他让她好好上班，她闷闷不乐" % city
            if not await self._write_memory_checked(uid, content, "event", 1):
                logger.warning("[amo] 被拒记忆没写进去")
        except Exception as exc:
            logger.warning("[amo] 被拒记忆失败: %s" % exc)
        try:
            log = self.db.kv_get("follow_reject_log", []) or []
            if not isinstance(log, list):
                log = []
            log.append({"day": today_str(), "hour": "%02d:00" % _now().hour, "city": city})
            self.db.kv_set("follow_reject_log", log[-10:])
        except Exception:
            pass
        return _follow_block(False, city)

    async def _end_follow_trip(self, uid):
        """结束跟随：回家、恢复城市/天气/日程、写回来记忆。"""
        trip = self.db.kv_get("travel", {}) or {}
        city = str(trip.get("city") or "") if isinstance(trip, dict) else ""
        self.db.kv_set("travel", {})
        home = _CITY_DEFAULT
        self.db.kv_set("his_city", home)
        self.db.kv_set("he_city", home)
        hit = self._city_lookup(home)
        if hit:
            try:
                await self._switch_weather_city(hit)
            except Exception:
                pass
        try:
            self.state.apply_travel_overlay(home)
        except Exception:
            pass
        try:
            content = "她 %s 从 %s 回来了" % (today_str(), city)
            await self._write_memory_checked(uid, content, "event", 1)
        except Exception:
            pass
        try:
            log = self.db.kv_get("travel_log", []) or []
            if isinstance(log, list):
                log.append({
                    "day": today_str(), "hour": "%02d:00" % _now().hour,
                    "city": city, "back": True,
                })
                self.db.kv_set("travel_log", log[-10:])
        except Exception:
            pass

    async def _switch_weather_city(self, hit):
        """按城市跟随的结果改 weather_city / 显示名，并立刻刷一次天气。"""
        city_id = str(hit.get("id") or "").strip()
        name = str(hit.get("name") or "").strip()
        if not city_id or not name:
            return
        changed = False
        if str(self.config.get("weather_city") or "") != city_id:
            self.config["weather_city"] = city_id
            changed = True
        if self.cfg_str("weather_city_name", "").strip() != name:
            self.config["weather_city_name"] = name
            changed = True
        if not changed:
            return
        try:
            save = getattr(self.config, "save_config", None)
            if callable(save):
                save()
        except Exception as exc:
            logger.warning("[amo] 城市跟随：保存天气城市失败: %s" % exc)
        await self.state.refresh_weather(force=True)

    async def _maybe_wander(self, event, uid, profile):
        """她自己出去玩：问意愿 → 同意 → 定行程；旅行中让他叫回来。"""
        if not self.cfg_bool("wander_enabled", True):
            return ""
        try:
            if not event.is_private_chat():
                return ""
        except Exception:
            return ""
        if str(profile.get("relation") or "") != "相恋":
            return ""
        if self.db.kv_get("travel", {}) or self.db.kv_get("follow_offer", {}):
            return ""
        text = str(event.message_str or "")
        now = now_ts()
        trip = self.db.kv_get("wander_trip", {}) or {}
        trip = trip if isinstance(trip, dict) else {}
        if trip.get("city") and re.search(r"(回来吧|回家吧|别玩了|早点回来|该回来了)", text):
            await self._end_solo_trip(uid, "他让你回来")
            return "【旅游】他让你回来：自然应一句“好，我收拾下就回”，别拖，也别说还没玩够。"
        offer = self.db.kv_get("wander_offer", {}) or {}
        offer = offer if isinstance(offer, dict) else {}
        if offer and now - to_float(offer.get("ts"), 0) > 1800:
            self.db.kv_set("wander_offer", {})
            offer = {}
        if _wander_question(text):
            if (
                self.db.kv_get("travel", {})
                or self.db.kv_get("follow_offer", {})
                or self.db.kv_get("wander_trip", {})
            ):
                return ""
            today = today_str()
            count = 0
            if str(self.db.kv_get("wander_asked_day", "") or "") == today:
                try:
                    count = int(self.db.kv_get("wander_ask_count", 0) or 0)
                except (TypeError, ValueError):
                    count = 0
            limit = _wander_ask_limit(self.cfg_bool("wander_ask_three_times", False))
            if count >= limit:
                return (
                    "【旅游提议】今天已经问过 " + str(count) + " 次了（一天最多 " + str(limit)
                    + " 次），别再重新决定、别再报新城市；按之前说的自然接一句。"
                )
            self.db.kv_set("wander_asked_day", today)
            self.db.kv_set("wander_ask_count", count + 1)
            low, tired = _wander_assess(self.state.mood, self.state.health_info())
            want = _wander_want(
                low, tired, random,
                self.cfg_float("wander_prob_low", 0.85),
                self.cfg_float("wander_prob_good", 0.15),
            )
            city, spots = "", []
            if want:
                city, spots = _wander_pick(
                    self.scenic_spots(), random, count=4,
                    exclude_city=str(self.db.kv_get("his_city", "") or ""),
                )
                want = bool(city)
            if not want:
                self.db.kv_set("wander_offer", {"ts": now, "want": False})
            else:
                self.db.kv_set("wander_offer", {
                    "ts": now, "want": True, "city": city,
                    "spots": [str(x.get("name") or "") for x in spots][:4],
                    "spot_rows": spots[:4],
                })
            return _wander_offer_block(bool(want), city, spots)
        if offer.get("want") and _wander_agree(text):
            return await self._start_solo_trip(uid, offer)
        if offer.get("want") and _wander_refuse(text):
            self.db.kv_set("wander_offer", {})
            try:
                self.state.nudge(委屈=5, 郁闷=4)
            except Exception:
                pass
            return (
                "【不出去了】他说这次不让你去：你有点失落，但别闹，用自己的口吻说一句："
                + _wander_solo_refuse_text(random)
            )
        if trip.get("city") and not trip.get("announced"):
            start = str(trip.get("day") or "")
            ret = str(trip.get("return_day") or start)
            if start and start <= today_str() <= ret:
                try:
                    day_no = (_now().date() - date.fromisoformat(start)).days + 1
                except Exception:
                    day_no = 1
                return _wander_solo_block(str(trip["city"]), trip.get("spots") or [], day_no=day_no)
        return ""

    async def _start_solo_trip(self, uid, offer):
        """确认出发：>=22 点明天走，否则现在就走。"""
        city = str(offer.get("city") or "").strip()
        spots = [x for x in (offer.get("spot_rows") or []) if isinstance(x, dict)]
        if not city:
            self.db.kv_set("wander_offer", {})
            return ""
        tomorrow = _now().hour >= 22
        start = (_now().date() + timedelta(days=1)) if tomorrow else _now().date()
        days = max(1, min(3, _wander_trip_days(random)))
        if days == 1 and not tomorrow and _now().hour >= 17:
            days = 2  # 傍晚才走，别刚出门就回家
        return_day = start + timedelta(days=days - 1)
        return_hour = 21 if days == 1 else 12
        hit = self._city_lookup(city)
        trip = {
            "city": city,
            "id": str((hit or {}).get("id") or ""),
            "day": start.isoformat(),
            "days": days,
            "return_day": return_day.isoformat(),
            "return_hour": return_hour,
            "spots": [str(x.get("name") or "") for x in spots][:4],
            "phase": "planned",
        }
        self.db.kv_set("wander_trip", trip)
        self.db.kv_set("wander_offer", {})
        try:
            content = "她 %s 一个人去 %s 旅游（他同意了，玩 %d 天）" % (start.isoformat(), city, days)
            if not await self._write_memory_checked(uid, content, "event", 1):
                logger.warning("[amo] 旅游记忆没写进去")
        except Exception as exc:
            logger.warning("[amo] 旅游记忆写入失败: %s" % exc)
        try:
            log = self.db.kv_get("travel_log", []) or []
            if not isinstance(log, list):
                log = []
            log.append({
                "day": start.isoformat(), "hour": "%02d:00" % _now().hour,
                "city": city, "solo": True,
            })
            self.db.kv_set("travel_log", log[-10:])
        except Exception:
            pass
        if not tomorrow:
            if hit:
                try:
                    await self._switch_weather_city(hit)
                except Exception as exc:
                    logger.warning("[amo] 旅游天气切换失败: %s" % exc)
            try:
                self.state.apply_travel_overlay(city)
            except Exception as exc:
                logger.warning("[amo] 旅游日程失败: %s" % exc)
            trip["phase"] = "applied"
            self.db.kv_set("wander_trip", trip)
        agree = _wander_solo_agree_text(city, random)
        plan = _wander_plan_text(city, spots, tomorrow, random)
        when = "明天" if tomorrow else "现在"
        back_text = "第 %d 天中午回来" % days if days > 1 else "当晚回来"
        return (
            "【出发】他同意了：你" + when + "去 " + city + " 旅游（一个人），玩 %d 天，%s。"
            % (days, back_text) + "先照这个说一句：" + agree + " 再说安排：" + plan
            + " 别说成跟他一起；白天自己去景点，晚上住酒店。"
        )

    async def _maybe_solo_return(self):
        """旅游最后一天到点回家：换天气、报平安、写记忆/日记。"""
        trip = self.db.kv_get("wander_trip", {}) or {}
        if not isinstance(trip, dict) or not trip.get("city") or trip.get("announced"):
            return
        ret_day = str(trip.get("return_day") or "")
        if not ret_day or today_str() != ret_day:
            return
        try:
            hour = int(trip.get("return_hour") or 12)
        except (TypeError, ValueError):
            hour = 12
        if _now().hour < hour:
            return
        city = str(trip["city"])
        his = str(self.db.kv_get("his_city", "") or "").strip() or _CITY_DEFAULT
        hit = self._city_lookup(his)
        if hit:
            try:
                await self._switch_weather_city(hit)
            except Exception as exc:
                logger.warning("[amo] 回来天气切换失败: %s" % exc)
        try:
            self.state.apply_travel_overlay(his)
        except Exception as exc:
            logger.warning("[amo] 回来日程失败: %s" % exc)
        # 报平安必须进私聊：以前用 _last_umo，他最后一句是在群里就会把「我回来啦」发进群。
        umo = self._first_private_umo()
        if not umo:
            last = str(getattr(self, "_last_umo", "") or "")
            umo = last if "FriendMessage" in last else ""
        uid = ""
        try:
            rows = self.db.list_profiles(limit=1) or []
            uid = str((rows[0] or {}).get("uid") or "") if rows else ""
        except Exception:
            uid = ""
        try:
            if umo:
                text = random.choice((
                    "我回来啦，刚到家。",
                    "到家啦，你在干嘛呢？",
                    "我回来了，你吃饭了没？",
                ))
                if await self._send_to_umo(umo, text):
                    self._mark_bot_initiated(umo)
                    if uid:
                        self._set_proactive_pending(uid, "travel_back", text, umo=umo)
        except Exception as exc:
            logger.warning("[amo] 回来报平安失败: %s" % exc)
        try:
            if uid:
                if not await self._write_memory_checked(
                    uid, "她 %s 从 %s 旅游回来了" % (today_str(), city), "event", 1,
                ):
                    logger.warning("[amo] 回来记忆没写进去")
        except Exception as exc:
            logger.warning("[amo] 回来记忆失败: %s" % exc)
        try:
            log = self.db.kv_get("travel_log", []) or []
            if isinstance(log, list):
                log.append({
                    "day": today_str(), "hour": "%02d:00" % _now().hour,
                    "city": city, "solo": True, "back": True,
                })
                self.db.kv_set("travel_log", log[-10:])
        except Exception:
            pass
        trip["announced"] = True
        self.db.kv_set("wander_trip", trip)
        logger.info("[amo] 旅游回来：%s" % city)

    async def _end_solo_trip(self, uid, reason=""):
        """结束 solo 旅游：清状态、记回来、天气换回他在的城市、日程回家。"""
        trip = self.db.kv_get("wander_trip", {}) or {}
        if not isinstance(trip, dict) or not trip.get("city"):
            return
        city = str(trip["city"])
        self.db.kv_set("wander_trip", {})
        try:
            content = "她 %s 从 %s 旅游回来了" % (today_str(), city)
            if not await self._write_memory_checked(uid, content, "event", 1):
                logger.warning("[amo] 回来记忆没写进去")
        except Exception as exc:
            logger.warning("[amo] 回来记忆写入失败: %s" % exc)
        try:
            log = self.db.kv_get("travel_log", []) or []
            if not isinstance(log, list):
                log = []
            log.append({
                "day": today_str(), "hour": "%02d:00" % _now().hour,
                "city": city, "solo": True, "back": True,
            })
            self.db.kv_set("travel_log", log[-10:])
        except Exception:
            pass
        his = str(self.db.kv_get("his_city", "") or "").strip() or _CITY_DEFAULT
        hit = self._city_lookup(his)
        if hit:
            try:
                await self._switch_weather_city(hit)
            except Exception as exc:
                logger.warning("[amo] 回来天气切换失败: %s" % exc)
        try:
            self.state.apply_travel_overlay(his)
        except Exception as exc:
            logger.warning("[amo] 回来日程失败: %s" % exc)

    def _sync_weather_city_config(self):
        """配置里填了中文城市名时，自动换算并回填 LocationID（幂等）。"""
        raw = self.cfg_str("weather_city", "").strip()
        if not raw or raw.isdigit() or "," in raw:
            return False
        hit = self._city_lookup(raw)
        if not hit:
            # 同一个错城市名每小时只提醒一次，避免后台 30 秒一轮刷日志
            cache = getattr(self, "_city_warn_cache", None)
            if not isinstance(cache, dict):
                cache = {}
                self._city_warn_cache = cache
            now = time.time()
            if now - to_float(cache.get(raw), 0) > 3600:
                cache[raw] = now
                logger.warning(
                    "[amo] 城市名「%s」不在离线城市表里，天气会退回模拟数据；"
                    "可以写「省+市」或直接填 LocationID" % raw
                )
            return False
        if hit.get("ambiguous"):
            cache = getattr(self, "_city_warn_cache", None)
            if not isinstance(cache, dict):
                cache = {}
                self._city_warn_cache = cache
            now = time.time()
            key = "amb:" + raw
            if now - to_float(cache.get(key), 0) > 3600:
                cache[key] = now
                logger.warning(
                    "[amo] 天气城市%s" % (hit.get("note") or "有多个同名城市，已默认选一个")
                )
        changed = False
        if str(hit["id"]) != raw:
            self.config["weather_city"] = str(hit["id"])
            changed = True
        if not self.cfg_str("weather_city_name", "").strip():
            self.config["weather_city_name"] = hit["name"]
            changed = True
        if changed:
            try:
                if hasattr(self.config, "save_config"):
                    self.config.save_config()
                logger.info("[amo] 城市「%s」→ LocationID %s（已回填）" % (raw, hit["id"]))
            except Exception as exc:
                logger.error("[amo] 回填城市配置失败: %s" % exc)
        return changed

    async def api_weather_brief(self):
        """面板用：当前天气一行摘要 + 配置里的城市（只读缓存）。"""
        await self._ensure_ready()
        if not self.state.weather:
            try:
                await self.state.refresh_weather()
            except Exception as exc:
                logger.debug("[amo] 面板取天气失败: %s" % exc)
        return {
            "code": 0,
            "data": {
                "weather": self.state.weather_brief(),
                "city": self.cfg_str("weather_city", ""),
                "city_name": self.cfg_str("weather_city_name", ""),
            },
        }

    async def api_city_search(self):
        """面板用：中文城市名候选。"""
        await self._ensure_ready()
        query = str(self._q("q", "") or "").strip()
        if not query:
            data = await self._body()
            if isinstance(data, dict):
                query = str(data.get("q") or "").strip()
        if not query:
            return {"code": 0, "data": {"items": [], "query": ""}}
        module = self._city_module()
        if module is None:
            return {"code": 1, "msg": "城市表缺失：amo_city_index.py 没装好"}
        try:
            items = module.search_city(query, 20)
        except Exception as exc:
            return {"code": 1, "msg": "城市表读取失败：%s" % exc}
        return {"code": 0, "data": {"items": items, "query": query}}

    async def api_city_set(self):
        """面板用：中文城市名 → 写入 weather_city(LocationID) + 城市显示名。"""
        await self._ensure_ready()
        data = await self._body()
        data = data if isinstance(data, dict) else {}
        text = str(data.get("city") or data.get("q") or "").strip()
        if not text:
            return {"code": 1, "msg": "请填写城市名"}
        hit = self._city_lookup(text)
        if not hit:
            return {
                "code": 1,
                "msg": "没找到「%s」；重名或冷门地方请写「省+市」，例如「广东东莞」「北京朝阳」" % text,
            }
        save = False
        if str(self.config.get("weather_city") or "") != str(hit["id"]):
            self.config["weather_city"] = str(hit["id"])
            save = True
        if not data.get("keep_name"):
            if self.cfg_str("weather_city_name", "").strip() != hit["name"]:
                self.config["weather_city_name"] = hit["name"]
                save = True
        if save:
            try:
                if hasattr(self.config, "save_config"):
                    self.config.save_config()
            except Exception as exc:
                return {"code": 1, "msg": "保存配置失败：%s" % exc}
        weather = None
        if not save and self.state.weather:
            # 城市没变，别为一次「设置」白打接口
            weather = self.state.weather
        else:
            try:
                weather = await self.state.refresh_weather(force=bool(save))
            except Exception as exc:
                logger.debug("[amo] 切换城市后刷新天气失败: %s" % exc)
        return {
            "code": 0,
            "data": {
                "id": hit["id"], "name": hit["name"],
                "label": hit["label"], "weather": weather or {},
                "ambiguous": hit.get("ambiguous", 0),
                "candidates": hit.get("candidates", []),
                "note": hit.get("note", ""),
            },
        }

    async def api_config(self):
        await self._ensure_ready()
        items = self._config_schema_items()
        notes = {}
        try:
            voice_items = self._voice_panel_items()
            items.extend(voice_items)
            if not voice_items:
                notes["语音"] = ("没找到「我想永远陪着你-语音」（未安装或未启用）。"
                                  "装好并启用它，语音设置才会出现在这里；key、后端、音色仍在它自己的配置页填。")
        except Exception as exc:
            logger.warning("[amo] 读取语音设置失败: %s" % exc)
            notes["语音"] = "读取语音设置失败：%s" % exc
        return {"code": 0, "data": {"items": items, "groupNotes": notes}}

    # ---- 用量 / 余额 ----
    def _usage_db_path(self):
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            return os.path.join(str(get_astrbot_data_path()), "data_v4.db")
        except Exception:
            try:
                data_dir = os.path.dirname(os.path.dirname(os.path.dirname(str(self.db.path))))
                return os.path.join(data_dir, "data_v4.db")
            except Exception:
                return ""

    def _deepseek_api_key(self):
        key = str(self.cfg_str("deepseek_api_key", "") or "").strip()
        if key:
            return key
        for name in ("DEEPSEEK_API_KEY", "COMPANION_V2_BALANCE_API_KEY"):
            value = str(os.environ.get(name, "") or "").strip()
            if value:
                return value
        return ""

    def _usage_prices(self):
        prices = {}
        for key in ("hit_peak", "hit_idle", "miss_peak", "miss_idle", "out_peak", "out_idle"):
            prices[key] = self.cfg_float("usage_price_" + key, USAGE_DEFAULT_PRICES[key])
        return prices

    def _usage_start_of_today(self):
        now = _now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp()

    # ---- 供应商识别 / 多模型用量 ----
    def _provider_inventory(self):
        """读取 AstrBot 已配置的对话供应商；只返回脱敏信息，绝不回传密钥。"""
        items = []
        try:
            providers = self.context.get_all_providers() or []
        except Exception:
            providers = []
        for provider in providers:
            config = getattr(provider, "provider_config", None) or {}
            pid = str(config.get("id") or "")
            if not pid:
                continue
            model = ""
            try:
                model = str(provider.get_model() or "")
            except Exception:
                model = str(config.get("model") or "")
            api_base = str(config.get("api_base") or config.get("url") or "").strip()
            key = config.get("key") or ""
            if isinstance(key, list):
                has_key = any(str(item or "").strip() for item in key)
            else:
                has_key = bool(str(key or "").strip())
            items.append({
                "id": pid,
                "model": model,
                "type": str(config.get("type") or ""),
                "enable": config.get("enable", True) is not False,
                "has_key": has_key,
                "api_base": api_base,
            })
        return items

    def _judge_provider_id(self):
        try:
            if self.heartflow is not None:
                return str(self.heartflow.judge_provider_info().get("id") or "")
        except Exception:
            pass
        return ""

    def _using_provider_id(self):
        try:
            provider = self.context.get_using_provider()
            return str((getattr(provider, "provider_config", None) or {}).get("id") or "")
        except Exception:
            return ""

    async def api_providers(self):
        """面板下拉用：列出已配置的模型供应商（脱敏），并标注心流判定/主对话模型。"""
        await self._ensure_ready()
        judge_id = self._judge_provider_id()
        using_id = self._using_provider_id()
        items = self._provider_inventory()
        for item in items:
            item["judge"] = bool(judge_id) and item["id"] == judge_id
            item["using"] = bool(using_id) and item["id"] == using_id
        return {"code": 0, "data": {"items": items}}

    @staticmethod
    def _balance_probe_kind(api_base):
        base = str(api_base or "").lower()
        if "deepseek" in base:
            return "deepseek"
        if "siliconflow" in base:
            return "siliconflow"
        return "openai_bill"

    async def _provider_balances_cached(self, providers):
        """逐个探测供应商余额；60 秒缓存，失败不阻塞面板。"""
        now = time.time()
        signature = "|".join(sorted(
            item["id"] + ":" + item["api_base"] + ":" + str(item["has_key"]) for item in providers
        ))
        cache = getattr(self, "_provider_balance_cache", None)
        if (
            isinstance(cache, dict)
            and now - to_float(cache.get("at"), 0) < 60
            and cache.get("signature") == signature
        ):
            return cache.get("data") or []
        enabled = [item for item in providers if item["enable"] and item["has_key"] and item["api_base"]]

        def probe(item):
            kind = self._balance_probe_kind(item["api_base"])
            key = self._provider_api_key(item)
            result = {"id": item["id"], "model": item["model"], "kind": kind}
            if not key:
                result.update({"ok": False, "error": "未配置密钥"})
                return result
            data = fetch_provider_balance(key, item["api_base"], kind)
            data["id"] = item["id"]
            data["model"] = item["model"]
            data["kind"] = kind
            return data

        results = []
        if enabled:
            def run_all():
                return [probe(item) for item in enabled]

            try:
                results = await asyncio.to_thread(run_all)
            except Exception as exc:
                logger.debug("[amo] 供应商余额探测失败: %s" % exc)
                results = []
        self._provider_balance_cache = {"at": now, "signature": signature, "data": results}
        return results

    def _provider_api_key(self, item):
        """从 AstrBot 供应商配置里取密钥；只在内存中使用，不写日志不回传。"""
        config = {}
        try:
            for provider in (self.context.get_all_providers() or []):
                candidate = getattr(provider, "provider_config", None) or {}
                if str(candidate.get("id") or "") == str(item.get("id") or ""):
                    config = candidate
                    break
        except Exception:
            config = {}
        key = config.get("key") or ""
        if isinstance(key, list):
            key = next((str(item or "").strip() for item in key if str(item or "").strip()), "")
        return str(key or "").strip()

    async def _balance_cached(self):
        """余额 60 秒内复用，避免面板每刷一次就打一次外网。"""
        now = time.time()
        cache = getattr(self, "_balance_cache", None)
        if isinstance(cache, dict) and now - float(cache.get("at") or 0) < 60:
            return cache.get("data") or {"ok": False, "error": "查询失败"}
        key = self._deepseek_api_key()
        data = await asyncio.to_thread(fetch_deepseek_balance, key)
        self._balance_cache = {"at": now, "data": data}
        return data

    async def api_usage(self):
        await self._ensure_ready()
        if not self.cfg_bool("usage_stats_enabled", True):
            return {"code": 0, "data": {"enabled": False}}
        db_path = self._usage_db_path()
        prices = self._usage_prices()
        day_start = self._usage_start_of_today()

        def build():
            result = {"enabled": True, "currency": "元", "prices": prices}
            try:
                result["clock"] = usage_clock(_now())
            except Exception as exc:
                logger.debug("[amo] 峰谷分段失败: %s" % exc)
            for label, start in (("today", day_start), ("week", day_start - 6 * 86400), ("total", None)):
                usage = summarize_token_usage(db_path, start)
                usage["cost"] = usage_cost(usage, prices)
                # 插件内部调用（判分/润色/日记）不进 provider_stats，这里补自记账
                internal = self.db.usage_since(start)
                usage["internal"] = internal
                usage["all_calls"] = int(usage.get("calls") or 0) + int(internal["calls"])
                usage["all_input"] = (int(usage.get("input_miss") or 0) + int(usage.get("input_cached") or 0)
                                      + int(internal["input_other"]) + int(internal["input_cached"]))
                usage["all_output"] = int(usage.get("output") or 0) + int(internal["output"])
                # 面板要能一眼看到「一共跑了多少」，不能只给主回复那一半
                usage["all_total"] = int(usage["all_input"]) + int(usage["all_output"])
                usage["internal_total"] = (int(internal["input_other"]) + int(internal["input_cached"])
                                            + int(internal["output"]))
                usage["all_cost"] = float(usage.get("cost") or 0) + float(internal["cost"])
                result[label] = usage
            return result

        data = await asyncio.to_thread(build)
        if self.cfg_bool("deepseek_balance_enabled", True):
            data["balance"] = await self._balance_cached()
        else:
            data["balance"] = {"ok": False, "error": "余额查询已关闭"}
        # 多模型用量：已配置供应商 + 逐个余额探测 + 按模型匹配今日 token
        providers = self._provider_inventory()
        judge_id = self._judge_provider_id()
        using_id = self._using_provider_id()
        today_by_model = {}
        for entry in (data.get("today", {}) or {}).get("by_model", []) or []:
            today_by_model[str(entry.get("model") or "")] = entry
        # 判分/润色/摘要这些内部调用也吃同一份额度，模型卡片不能只算主回复
        internal_by_model = ((data.get("today") or {}).get("internal") or {}).get("by_model") or {}
        for item in providers:
            item["judge"] = bool(judge_id) and item["id"] == judge_id
            item["using"] = bool(using_id) and item["id"] == using_id
            stats = today_by_model.get(item["model"]) or today_by_model.get(item["id"]) or {}
            tokens = int(stats.get("input_miss") or 0) + int(stats.get("input_cached") or 0) + int(stats.get("output") or 0)
            extra = internal_by_model.get(str(item.get("model") or "")) or {}
            extra_tokens = (int(extra.get("input_other") or 0) + int(extra.get("input_cached") or 0)
                            + int(extra.get("output") or 0))
            item["today_tokens"] = tokens + extra_tokens
            item["today_internal_tokens"] = extra_tokens
            item["today_calls"] = int(stats.get("calls") or 0) + int(extra.get("calls") or 0)
            item["today_cost"] = float(stats.get("cost") or 0) if isinstance(stats.get("cost"), (int, float)) else 0.0
        if self.cfg_bool("usage_balance_enabled", True) and self.cfg_bool("deepseek_balance_enabled", True):
            balances = await self._provider_balances_cached(providers)
            by_id = {str(item.get("id") or ""): item for item in balances}
            for item in providers:
                item["balance"] = by_id.get(item["id"]) or {"ok": False, "error": "未配置密钥或地址"}
        else:
            for item in providers:
                item["balance"] = {"ok": False, "error": "余额查询已关闭"}
        data["providers"] = providers
        return {"code": 0, "data": data}

    async def api_balance(self):
        await self._ensure_ready()
        data = await self._balance_cached()
        return {"code": 0, "data": data}

    VOICE_PLUGIN_NAMES = ("Astrbot_Amo_Speechsound", "astrbot_plugin_speechsound", "amo_speechsound")
    # 语音插件（我想永远陪着你-语音）的设置：key, 类型, 标题, 说明, 默认值
    # 只放行为类开关；后端 / key / 音色仍然在语音插件自己的配置页填。
    VOICE_SETTING_KEYS = (
        ("enable", "bool", "启用语音", "总开关：关掉后她发不了语音，也不会有兜底转语音。", True),
        ("group_enable", "bool", "允许群聊发语音", "默认关。群聊里还受下面的「每天条数」和「最小间隔」限制。", False),
        ("auto_fallback", "bool", "兜底转语音", "你明说要语音、她只回了文字时，补一条语音。", True),
        ("dual_output", "bool", "语音之外同时发文字", "关掉就只发语音。", False),
        ("read_relation", "bool", "参考关系度决定语气", "从陪伴这边读关系阶段，越亲近越容易开口、语气越软。", True),
        ("schedule_aware", "bool", "参考日程决定场景", "按在家里 / 在外面 / 在睡觉切到对应场景音色。", True),
        ("speak_threshold", "float", "开口阈值（0-1，越高越少开口）", "兜底规则用的及格线。她主动调工具发语音时不受这个限制。", 0.6),
        ("daily_quota", "int", "群聊每天语音条数上限", "所有群共用这一份额度，0 = 不限。私聊不占这个额度。", 10),
        ("cooldown_seconds", "int", "群聊两条语音最小间隔（秒）", "只管群聊，防刷屏。", 240),
        ("private_cooldown_seconds", "int", "私聊两条语音最小间隔（秒）", "0 = 私聊不冷却（推荐）。", 0),
        ("max_chars", "int", "每段字数上限", "整条语音总长 = 这个数 × 最多分段数，超过就退回文字。", 80),
        ("max_segments", "int", "最多分段数", "长句按标点切段，最多切几段。", 2),
        ("speed", "float", "语速（0.5-2.0）", "1.0 是正常语速。", 1.0),
        ("volume", "float", "音量（0.1-2.0）", "", 1.0),
    )

    def _voice_plugin(self):
        """找「我想永远陪着你-语音」插件实例；没装或没启用返回 None。"""
        for name in self.VOICE_PLUGIN_NAMES:
            try:
                meta = self.context.get_registered_star(name)
            except Exception:
                meta = None
            star = self._voice_instance(meta)
            if star is not None:
                return star
        try:
            for meta in self.context.get_all_stars():
                marker = ((getattr(meta, "name", "") or "") + " "
                          + (getattr(meta, "module_path", "") or "")).lower()
                if "speechsound" not in marker:
                    continue
                star = self._voice_instance(meta)
                if star is not None:
                    return star
        except Exception:
            pass
        return None

    @staticmethod
    def _voice_instance(meta):
        if meta is None:
            return None
        for attr in ("star_cls", "instance", "star", "plugin"):
            value = getattr(meta, attr, None)
            if value is None or isinstance(value, type):
                continue
            if callable(getattr(value, "_persist_config", None)) and hasattr(value, "config"):
                return value
        return None

    @staticmethod
    def _voice_value(config, key, kind, default):
        try:
            raw = config.get(key) if hasattr(config, "get") else None
        except Exception:
            raw = None
        if raw is None:
            return default
        if kind == "bool":
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in ("1", "true", "yes", "on", "开")
        if kind == "int":
            try:
                return int(float(raw))
            except Exception:
                return default
        if kind == "float":
            try:
                return float(raw)
            except Exception:
                return default
        return str(raw)

    def _voice_panel_items(self):
        """面板「语音」分组的行：值来自语音插件的配置。"""
        plugin = self._voice_plugin()
        if plugin is None:
            return []
        config = getattr(plugin, "config", {}) or {}
        items = []
        for key, kind, title, hint, default in self.VOICE_SETTING_KEYS:
            items.append({
                "key": key,
                "type": kind,
                "description": title,
                "hint": hint,
                "default": default,
                "options": [],
                "special": "",
                "group": "语音",
                "external": "voice",
                "value": self._voice_value(config, key, kind, default),
            })
        return items

    async def api_voice_save(self):
        """把「语音」分组里的设置写进语音插件（内存立即生效 + 落盘）。"""
        await self._ensure_ready()
        data = await self._body()
        changes = data.get("changes") if isinstance(data.get("changes"), dict) else data
        plugin = self._voice_plugin()
        if plugin is None:
            return {"code": 1, "msg": "没找到「我想永远陪着你-语音」（未安装或未启用）"}
        config = getattr(plugin, "config", None)
        if config is None or not hasattr(config, "update"):
            return {"code": 1, "msg": "语音插件的配置对象不可写"}
        kinds = {key: kind for key, kind, _t, _h, _d in self.VOICE_SETTING_KEYS}
        applied = {}
        for key, value in (changes or {}).items():
            kind = kinds.get(key)
            if not kind:
                continue
            try:
                applied[key] = self._coerce_config_value(kind, value)
            except Exception as exc:
                logger.warning("[amo] 语音设置 %s 值无效: %s" % (key, exc))
                continue
        if not applied:
            return {"code": 0, "data": {"saved": {}, "persisted": False}}
        try:
            config.update(applied)
        except Exception as exc:
            logger.error("[amo] 写入语音插件配置失败: %s" % exc)
            return {"code": 1, "msg": "写入失败：" + str(exc)}
        persisted = False
        saver = getattr(plugin, "_persist_config", None)
        if callable(saver):
            try:
                result = saver()
                if hasattr(result, "__await__"):
                    result = await result
                persisted = bool(result)
            except Exception as exc:
                logger.warning("[amo] 语音设置落盘失败（内存已生效）: %s" % exc)
        logger.info("[amo] 语音设置已更新: %s" % ", ".join(sorted(applied)))
        return {"code": 0, "data": {"saved": applied, "persisted": persisted}}

    async def api_config_save(self):
        await self._ensure_ready()
        data = await self._body()
        changes = data.get("changes") if isinstance(data.get("changes"), dict) else data
        schema = self._schema_map()
        saved = {}
        for key, value in (changes or {}).items():
            if key in FORCED_ON_CONFIG_KEYS:
                continue
            meta = schema.get(key)
            if not isinstance(meta, dict):
                # 操作页的「语种」下拉不在 schema 里，单独放行（普通话/各地方言）
                if key == "dialect_style":
                    meta = {"type": "string", "default": ""}
                else:
                    continue
            try:
                coerced = self._coerce_config_value(meta.get("type", "string"), value)
            except Exception as exc:
                logger.warning("[amo] 配置 %s 值无效: %s" % (key, exc))
                continue
            if key in self.SENSITIVE_KEYS:
                current = str(self.cfg(key, "") or "")
                incoming = str(coerced or "")
                # 面板回传的是打码串、或者干脆留空 → 当作"不修改"，别把真 key 覆盖掉
                if not incoming or incoming == self._mask_secret(current):
                    continue
            self.config[key] = coerced
            saved[key] = coerced
        if saved:
            try:
                if hasattr(self.config, "save_config"):
                    self.config.save_config()
            except Exception as exc:
                logger.error("[amo] 保存插件配置失败: %s" % exc)
                return {"code": 1, "msg": "保存配置失败：" + str(exc)}
            try:
                await self._apply_runtime_config()
            except Exception as exc:
                logger.error("[amo] 应用配置失败: %s" % exc)
        return {"code": 0, "data": {"saved": saved}}

    async def api_profiles_sync(self):
        # 4.3.2 起用户画像只来自本插件聊天/手动建档；
        # 不再把记忆插件的用户导入画像，记忆由 LLM hook 读取。
        return {
            "code": 0,
            "data": {"synced": 0, "profiles": self.db.list_profiles(limit=500)},
            "msg": "原版模式：画像只从聊天建立，不再从记忆插件同步用户",
        }

    async def api_memory_candidates(self):
        await self._ensure_ready()
        selected = self.cfg_str("companion_memory_plugin_name", "").strip()
        meta = self._companion_plugin_meta()
        return {
            "code": 0,
            "data": {
                "items": self._companion_candidates(),
                "selected": selected,
                "detected": str(getattr(meta, "name", "") or "") if meta is not None else "",
            },
        }

    async def api_relations(self):
        await self._ensure_ready()
        profiles = self.db.list_profiles(limit=500)
        names = {str(item.get("uid")): (item.get("alias") or item.get("name") or item.get("uid")) for item in profiles}
        names["bot"] = str(getattr(self, "bot_name", "") or "你")
        edges = []
        for edge in self.db.list_relations():
            row = dict(edge)
            row["a_name"] = names.get(str(row.get("a_uid")), row.get("a_uid"))
            row["b_name"] = names.get(str(row.get("b_uid")), row.get("b_uid"))
            edges.append(row)
        # 画像里显式设过的关系要压过自动沉淀：否则把对方设成「恋人」，
        # 关系图还停在 relation_sediment 自动算出来的「熟人」。
        by_pair = {}
        for row in edges:
            key = tuple(sorted([str(row.get("a_uid") or ""), str(row.get("b_uid") or "")]))
            by_pair[key] = row
        for profile in profiles:
            uid = str(profile.get("uid") or "").strip()
            relation = str(profile.get("relation") or "").strip()
            if not uid or not relation or uid in INTERNAL_RELATION_NODES:
                continue
            relation = {"相恋": "恋人", "熟识": "熟人", "仇恨": "仇人"}.get(relation, relation)
            if relation in ("普通", ""):
                continue
            key = tuple(sorted(["bot", uid]))
            row = by_pair.get(key)
            if row is None:
                row = {
                    "a_uid": "bot", "b_uid": uid, "relation": relation,
                    "note": "画像：关系字段", "updated_at": 0,
                    "a_name": names.get("bot", "你"), "b_name": names.get(uid, uid),
                }
                edges.append(row)
                by_pair[key] = row
            elif str(row.get("relation") or "") != relation:
                row["relation"] = relation
                row["note"] = "画像：关系字段"
        return {"code": 0, "data": {"edges": edges, "profiles": profiles, "relations": list(NETWORK_RELATIONS)}}

    async def api_profile_links(self):
        """面板用：这个 UID 关联了哪些平台身份（QQ / 飞书等）。"""
        data = await self._body()
        uid = str(data.get("uid") or "").strip()
        platform = str(data.get("platform") or "").strip() or "aiocqhttp"
        if not uid:
            return {"code": 0, "data": {"links": []}}
        mem = self._data_mem()
        if mem is None or not callable(getattr(mem, "person_context", None)):
            return {"code": 0, "data": {"links": []}}
        try:
            detail = await self._data_call("person_context", self._data_bot_id(), platform, uid, 1)
        except Exception as exc:
            logger.debug("[amo] 读取关联身份失败: %s" % exc)
            detail = {}
        links = []
        for item in (detail or {}).get("links") or []:
            links.append({
                "platform": str(item.get("platform") or ""),
                "label": str(item.get("label") or item.get("platform") or ""),
                "uid": str(item.get("uid") or ""),
                "name": str(item.get("name") or ""),
            })
        return {"code": 0, "data": {"links": links}}

    async def api_profile_delete(self):
        """面板用：删掉一个人的档案，并把本插件跟他有关的引用清干净。

        清掉：profiles / messages / proactive_log / relation_network、
              他专属的 kv（channels:、last_channel:、节流、主动消息、纪念日…）、
              礼物心愿与礼物墙、内存里的临时缓存。
        不清（属于别处）：AstrBot 核心会话库、牢记/livingmemory 等记忆插件的库。
        """
        await self._ensure_ready()
        data = await self._body()
        data = data if isinstance(data, dict) else {}
        uid = str(data.get("uid") or "").strip()
        confirm = str(data.get("confirm") or "").strip().lower()
        if not uid:
            return {"code": 1, "msg": "缺少 uid"}
        if confirm not in ("1", "true", "yes", "on"):
            return {"code": 1, "msg": "删除档案需要确认：再带一次 confirm=1"}
        profile = {}
        try:
            profile = self.db.get_profile(uid) or {}
        except Exception:
            profile = {}
        umos = set()
        for value in (profile.get("private_umo"), profile.get("last_group")):
            if value:
                umos.add(str(value))
        try:
            channels = self.db.kv_get("channels:%s" % uid, {}) or {}
            if isinstance(channels, dict):
                for entry in channels.values():
                    if isinstance(entry, dict) and entry.get("umo"):
                        umos.add(str(entry["umo"]))
        except Exception:
            pass
        counts = {}
        try:
            for table in ("profiles", "messages", "proactive_log"):
                try:
                    cur = self.db.conn.execute("DELETE FROM %s WHERE uid=?" % table, (uid,))
                    counts[table] = max(0, cur.rowcount or 0)
                except Exception as exc:
                    logger.debug("[amo] 删除档案时清理 %s 失败: %s" % (table, exc))
            try:
                cur = self.db.conn.execute(
                    "DELETE FROM relation_network WHERE a_uid=? OR b_uid=?", (uid, uid)
                )
                counts["relation_network"] = max(0, cur.rowcount or 0)
            except Exception as exc:
                logger.debug("[amo] 删除档案时清理关系网失败: %s" % exc)
            counts["kv"] = self._purge_profile_kv(uid)
            try:
                self.db.conn.commit()
            except Exception:
                pass
        except Exception as exc:
            return {"code": 1, "msg": "删除失败：%s" % exc}
        try:
            if str(getattr(self, "_last_umo", "") or "") in umos:
                self._last_umo = ""
            cache = getattr(self, "_last_reply_at", None)
            if isinstance(cache, dict):
                for umo in umos:
                    cache.pop(umo, None)
        except Exception:
            pass
        logger.info("[amo] 已删除档案 %s（清理 %s）" % (uid, counts))
        return {"code": 0, "msg": "已删除", "data": {"uid": uid, "counts": counts}}

    def _purge_profile_kv(self, uid):
        """删掉这个 uid 专属的 kv（渠道/节流/主动消息/纪念日…），返回删除条数。"""
        prefixes = (
            "channels:", "last_channel:", "lover_uid_", "auto_learn_",
            "angel_profile_sync_", "companion_profile_sync_", "memcomp_profile_sync_",
            "proactive_ignored_", "proactive_depressed_until_",
            "proactive_followup_last_", "proactive_forced_hour_", "proactive_pending_",
            "ext_mem_count_", "ext_mem_count_at_",
        )
        try:
            rows = self.db.conn.execute("SELECT key FROM kv").fetchall()
        except Exception:
            return 0
        keys = []
        for row in rows:
            try:
                key = str(row["key"] if hasattr(row, "keys") else row[0])
            except Exception:
                continue
            if any(key == prefix + uid for prefix in prefixes):
                keys.append(key)
            elif key.startswith("ritual_") and ("_" + uid + "_") in key:
                keys.append(key)
        if not keys:
            return 0
        try:
            for key in keys:
                self.db.conn.execute("DELETE FROM kv WHERE key=?", (key,))
            self.db.conn.commit()
        except Exception as exc:
            logger.debug("[amo] 清理 kv 失败: %s" % exc)
            return 0
        return len(keys)

    async def api_relation_save(self):
        await self._ensure_ready()
        data = await self._body()
        a_uid = str(data.get("a_uid") or "").strip()
        b_uid = str(data.get("b_uid") or "").strip()
        relation = str(data.get("relation") or "朋友").strip()
        note = str(data.get("note") or "").strip()
        if not a_uid or not b_uid or a_uid == b_uid:
            return {"code": 1, "msg": "请选择两个不同的用户"}
        if relation not in NETWORK_RELATIONS:
            return {"code": 1, "msg": "关系类型无效"}
        self.db.upsert_relation(a_uid, b_uid, relation, note)
        try:
            await self._push_relation_to_data(a_uid, b_uid, relation, note)
        except Exception as exc:
            logger.debug("[amo] 关系同步失败: %s" % exc)
        logger.debug("[amo] 关系网更新: %s <-> %s = %s" % (a_uid, b_uid, relation))
        return await self.api_relations()

    async def api_relation_delete(self):
        await self._ensure_ready()
        data = await self._body()
        a_uid = str(data.get("a_uid") or "").strip()
        b_uid = str(data.get("b_uid") or "").strip()
        if not a_uid or not b_uid:
            return {"code": 1, "msg": "缺少用户"}
        self.db.delete_relation(a_uid, b_uid)
        await self._data_call("delete_relation", self._data_bot_id(), a_uid, b_uid)
        return await self.api_relations()

    async def api_diary_import(self):
        await self._ensure_ready()
        payload = await self._body()
        path = str((payload or {}).get("path") or "").strip()
        if not path:
            return {"code": 1, "msg": "缺少文件夹路径"}
        if len(path.rstrip("\\/")) <= 2:
            return {"code": 1, "msg": "别整盘导入，请选具体文件夹"}
        if not callable(_diary_import_folder):
            return {"code": 1, "msg": "日记模块未加载"}
        # 递归遍历 + 复制是同步阻塞的，放线程里，别把 AstrBot 事件循环卡住
        result = await asyncio.to_thread(_diary_import_folder, path, self._diary_dir())
        if not result.get("ok"):
            return {"code": 1, "msg": result.get("error") or "导入失败"}
        return {"code": 0, "data": result}

    async def api_diary_tree(self):
        await self._ensure_ready()
        if not callable(_diary_tree):
            return {"code": 1, "msg": "日记模块未加载"}
        return {"code": 0, "data": await asyncio.to_thread(_diary_tree, self._diary_dir())}

    async def api_diary_read(self):
        await self._ensure_ready()
        payload = await self._body()
        day = _diary_parse_day((payload or {}).get("date"))
        if not day:
            return {"code": 1, "msg": "日期格式应为 YYYY-MM-DD"}
        text = _diary_read(self._diary_dir(), day) if callable(_diary_read) else ""
        return {"code": 0, "data": {"date": day.isoformat(), "text": text}}

    async def api_diary_write(self):
        await self._ensure_ready()
        payload = await self._body()
        day = _diary_parse_day((payload or {}).get("date"))
        if not day:
            day = (_now() - timedelta(days=1)).date()
        text = await self._generate_daily_diary(day)
        if not text:
            return {"code": 1, "msg": "日记生成失败（没有素材或模型没返回）"}
        try:
            path = _diary_write(self._diary_dir(), day, text)
        except Exception as exc:
            return {"code": 1, "msg": "写入失败: %s" % exc}
        try:
            self.db.kv_set("diary_written:" + day.isoformat(), path)
        except Exception:
            pass
        logger.info("[amo] 日记已写（手动）: %s" % path)
        return {"code": 0, "data": {"date": day.isoformat(), "path": path, "text": text}}

    async def api_diary_open(self):
        await self._ensure_ready()
        root = self._diary_dir()
        try:
            os.makedirs(root, exist_ok=True)
        except Exception:
            pass
        opened = False
        try:
            if os.name == "nt" and os.path.isdir(root):
                os.startfile(root)
                opened = True
        except Exception as exc:
            logger.debug("[amo] 打开日记文件夹失败: %s" % exc)
        return {"code": 0, "data": {"root": root, "opened": opened}}

    async def api_dispatch(self, action: str = ""):
        await self._ensure_ready()
        name = (action or "").replace("/", "_").strip("_").lower()
        try:
            if name in ("", "index", "status", "get_status"):
                return await self.api_get_status()
            if name in ("profiles", "profile_list"):
                return await self.api_profiles()
            if name in ("profile_delete", "delete_profile"):
                return await self.api_profile_delete()
            if name in ("profile_save", "save_profile"):
                return await self.api_profile_save()
            if name in ("memories", "memory_list"):
                return await self.api_memories()
            if name in ("memory_add", "add_memory"):
                return await self.api_memory_add()
            if name in ("memory_delete", "delete_memory"):
                return await self.api_memory_delete()
            if name == "schedule":
                return await self.api_schedule()
            if name in ("scenic_kb_regen", "regen_scenic_kb"):
                return await self.api_scenic_kb_regen()
            if name in ("kb_regen", "regen_kb", "dialect_kb_regen"):
                return await self.api_kb_regen()
            if name in ("schedule_regen", "regen_schedule"):
                return await self.api_schedule_regen()
            if name in ("weather", "weather_refresh", "refresh_weather"):
                return await self.api_weather()
            if name == "worldview":
                return await self.api_worldview()
            if name in ("worldview_regen", "regen_worldview"):
                return await self.api_worldview_regen()
            if name in ("say", "send"):
                return await self.api_say()
            if name in ("refresh_status", "refresh"):
                return await self.api_refresh_status()
            if name in ("get_profile", "profile"):
                return await self.api_get_profile()
            return {"code": 1, "msg": "未知接口：" + name}
        except Exception as exc:
            logger.error("[amo] Web API %s 异常: %s" % (name, exc))
            return {"code": 1, "msg": str(exc)}

    async def api_status(self):
        await self._ensure_ready()
        data = await self._status_data()
        return {"code": 0, "data": data}

    async def api_get_status(self):
        await self._ensure_ready()
        data = await self._status_data()
        return {
            "code": 0,
            "data": {
                "mood": data["dominant"] + "（" + data["mood"].__str__() + "）",
                "schedule": data["activity"].get("activity", ""),
                "health": data["health"]["status"],
                "period": data["period"]["phase"] + " 第" + str(data["period"]["day"]) + "天",
                "weather": data["weather_text"],
                "switch_status": data["config"],
                "threshold": data["threshold"],
                "counts": data["counts"],
            },
        }

    async def api_get_profile(self):
        await self._ensure_ready()
        data = await self._body()
        uid = str(data.get("uid") or self._q("uid", "") or "")
        if uid:
            profile = self.db.get_profile(uid)
        else:
            profiles = self.db.list_profiles(limit=1)
            profile = profiles[0] if profiles else {}
        mem_uid = str(profile.get("uid") or uid or "")
        mem_count = self._data_memory_count(mem_uid)
        if not mem_count and mem_uid:
            mem_count = len(self._external_all_memories(mem_uid, "", 200))
        return {
            "code": 0,
            "data": {
                "relation": profile.get("relation", "普通"),
                "mem_count": mem_count,
                "profile": profile,
            },
        }

    async def api_refresh_status(self):
        await self._ensure_ready()
        # 限频：这个接口会强制刷新天气（和风额度），被 <img>/外链或连点触发时不能每次都打出去
        now = now_ts()
        last = to_float(getattr(self, "_refresh_status_at", 0), 0)
        if last and now - last < 5:
            return {"code": 0, "msg": "刚刚刷新过，请稍候", "data": {"throttled": True}}
        self._refresh_status_at = now
        try:
            await self.state.refresh_weather(force=True)
        except Exception as exc:
            logger.warning("[amo] 手动刷新天气失败: %s" % exc)
            return {"code": 1, "msg": "刷新失败：%s" % exc}
        return {"code": 0, "msg": "刷新成功"}

    async def api_profiles(self):
        await self._ensure_ready()
        data = await self._body()
        keyword = str(data.get("q") or self._q("q", "") or "")
        limit = to_int(data.get("limit") or self._q("limit", 100), 100)
        return {"code": 0, "data": self.db.list_profiles(keyword, limit)}

    async def api_profile_save(self):
        await self._ensure_ready()
        data = await self._body()
        uid = str(data.get("uid") or "").strip()
        if not uid:
            return {"code": 1, "msg": "uid 不能为空"}
        fields = {}
        for key in ("name", "alias", "birthday", "relation", "notes"):
            value = data.get(key, None)
            if value is not None:
                fields[key] = str(value)[:100]
        if "relation" in fields and fields["relation"] not in RELATIONS:
            return {"code": 1, "msg": "关系只能是：" + "、".join(RELATIONS)}
        if "birthday" in fields and fields["birthday"]:
            match = re.match(r"^(\d{4}-)?(\d{1,2})-(\d{1,2})$", fields["birthday"])
            if not match:
                return {"code": 1, "msg": "生日格式应为 MM-DD 或 YYYY-MM-DD"}
            fields["birthday"] = "%02d-%02d" % (to_int(match.group(2)), to_int(match.group(3)))
        affection = data.get("affection", None)
        if affection is not None:
            fields["affection"] = int(clamp(to_int(affection, 10), 0, 100))
        if not self.db.get_profile(uid):
            self.db.touch_profile(uid, fields.get("name", ""), "web", "", "", True)
        self.db.update_profile(uid, **fields)
        if fields.get("relation") == "相恋":
            self._register_lover(uid)
        if fields.get("relation"):
            await self._sync_profile_relation_edge(uid, fields["relation"])
        try:
            await self._push_profile_to_data(uid, self.db.get_profile(uid))
        except Exception as exc:
            logger.debug("[amo] 画像同步失败: %s" % exc)
        return {"code": 0, "data": self.db.get_profile(uid)}

    async def api_chat_history(self):
        await self._ensure_ready()
        data = await self._body()
        uid = str(data.get("uid") or self._q("uid", "") or "")
        if not uid:
            return {"code": 1, "msg": "uid 不能为空"}
        limit = to_int(data.get("limit") or self._q("limit", 200), 200)
        profile = self.db.get_profile(uid) or {}
        # 面板的“读取记忆”先读记忆终端；数据插件是主终端，不能只读外挂插件，
        # 否则装的是 Astr_Amo_data 时这里永远显示 0 条。
        memories = await self._data_mem_list(uid, "", limit)
        if not memories:
            memories = self._external_profile_memories(
                uid, profile.get("name", ""), profile.get("alias", ""), limit
            )
        return {
            "code": 0,
            "data": {
                # 本地不再写聊天：面板聊天记录也要从记忆终端取，否则新消息永远为空。
                "chat": await self._recent_by_uid(uid, limit),
                "memories": memories,
            },
        }

    async def api_memories(self):
        """面板记忆页：只读外挂记忆插件的记忆（本插件不再存记忆）。"""
        await self._ensure_ready()
        data = await self._body()
        uid = str(data.get("uid") or self._q("uid", "") or "")
        if not uid:
            return {"code": 1, "msg": "uid 不能为空"}
        keyword = str(data.get("q") or self._q("q", "") or "")
        limit = self._q_int("limit", 50)
        items = await self._data_mem_list(uid, keyword, limit)
        if not items:
            items = self._external_all_memories(uid, keyword, limit)
        return {"code": 0, "data": items[:max(1, min(100, limit))]}

    async def api_memory_add(self):
        """面板“添加记忆”改为写进外挂记忆插件。"""
        await self._ensure_ready()
        data = await self._body()
        uid = str(data.get("uid") or "").strip()
        content = str(data.get("content") or "").strip()
        if not uid or not content:
            return {"code": 1, "msg": "uid 和 content 不能为空"}
        tier = to_int(data.get("tier", 1), 1)
        kind = str(data.get("kind", "manual"))
        scope = str(data.get("scope") or "private")
        group_id = str(data.get("group_id") or "")
        # 面板点“记住”要等真的写进去再返回，否则紧接着点“读取记忆”会空一次，
        # 用户只能再刷新；旧代码 fire-and-forget，写失败也报成功。
        if await self._write_memory_checked(uid, content, kind, tier, scope, group_id):
            return {"code": 0, "msg": "已写入记忆终端"}
        if self._external_memory_write(uid, content, kind, tier, scope, group_id):
            return {"code": 0, "msg": "已写入记忆终端"}
        return {"code": 1, "msg": "没有可写入的记忆终端，请先安装并启用「我想永远陪着你-记忆」"}

    async def api_memory_delete(self):
        """有记忆终端就删终端里的那条；没有就还按老规矩让对方插件自己管。"""
        await self._ensure_ready()
        data = await self._body()
        memory_id = to_int(data.get("id") or 0)
        if memory_id and self._data_mem() is not None:
            ok = await self._data_call("delete_memory", self._data_bot_id(), memory_id)
            if ok:
                return {"code": 0, "msg": "已删除"}
        return {
            "code": 1,
            "msg": "记忆由记忆终端保存，请到「我想永远陪着你-记忆」面板里删除",
        }

    async def api_schedule(self):
        await self._ensure_ready()
        data = await self._body()
        day = str(data.get("date") or self._q("date", "") or today_str())
        if day == today_str():
            items = await self.state.ensure_schedule(self._last_umo)
        else:
            items = self.state._hourly_schedule(self.db.get_schedule(day) or [])
        return {"code": 0, "data": {"day": day, "meta": day_meta(day), "items": items, "tree": self.state.schedule_tree(day), "current": self.state.current_activity(), "context": self.state.schedule_context(day)}}

    async def api_schedule_detail(self):
        await self._ensure_ready()
        data = await self._body()
        day = str(data.get("date") or "").strip() or today_str()
        start_raw = str(data.get("start") or "").strip()
        matched = re.match(r"^(\d{1,2})(?::(\d{2}))?$", start_raw)
        if not matched:
            return {"code": 1, "msg": "start 需要 HH:MM，例如 10:00"}
        hour = max(0, min(23, int(matched.group(1))))
        start = "%02d:00" % hour
        if day == today_str():
            items = await self.state.ensure_schedule(self._last_umo)
        else:
            items = self.state._hourly_schedule(self.db.get_schedule(day) or [])
        item = None
        for entry in items:
            if str(entry.get("start") or "") == start:
                item = entry
                break
        if item is None:
            return {"code": 1, "msg": "没有找到这一小时的日程：" + start}
        force_raw = data.get("force", "")
        force = str(force_raw).lower() in ("1", "true", "yes", "on")
        result = await self.state.expand_hour(day, item, items, force=force)
        payload = {"day": day, "start": item.get("start", start), "end": item.get("end", "")}
        payload.update(result)
        return {"code": 0, "data": payload}

    async def api_wardrobe(self):
        """服装库：GET 列表，POST 也能读（面板桥接只有 GET 时用）。"""
        await self._ensure_ready()
        if self.wardrobe is None:
            return {"code": 1, "msg": "服装库不可用"}
        data = self.wardrobe.panel_data()
        current = ""
        try:
            current = str((self.state.current_activity() or {}).get("outfit") or "")
        except Exception:
            current = ""
        data["current"] = current
        data["today"] = today_str()
        return {"code": 0, "data": data}

    async def api_wardrobe_save(self):
        """新增或修改一件衣服。"""
        await self._ensure_ready()
        if self.wardrobe is None:
            return {"code": 1, "msg": "服装库不可用"}
        payload = await self._body()
        payload = payload if isinstance(payload, dict) else {}
        item_id = str(payload.get("id") or "").strip()
        name = str(payload.get("name") or "").strip()
        scenes = payload.get("scenes") if isinstance(payload.get("scenes"), list) else []
        gender = str(payload.get("gender") or "通用").strip()
        note = str(payload.get("note") or "").strip()
        try:
            if item_id:
                item = self.wardrobe.update(item_id, name=name, scenes=scenes,
                                            gender=gender, note=note)
            else:
                item = self.wardrobe.add(name, scenes=scenes, gender=gender, note=note)
        except Exception as exc:
            return {"code": 1, "msg": "保存失败：%s" % exc}
        if not item:
            return {"code": 1, "msg": "名字太短或场景没选"}
        return {"code": 0, "msg": "已保存：" + item["name"], "data": item}

    async def api_wardrobe_delete(self):
        await self._ensure_ready()
        if self.wardrobe is None:
            return {"code": 1, "msg": "服装库不可用"}
        payload = await self._body()
        payload = payload if isinstance(payload, dict) else {}
        item_id = str(payload.get("id") or "").strip()
        if not item_id:
            return {"code": 1, "msg": "缺少 id"}
        ok = self.wardrobe.delete(item_id)
        return {"code": 0 if ok else 1, "msg": "已删除" if ok else "没找到这件"}

    async def api_wardrobe_wear(self):
        """让今天的她换上一件（面板/聊天共用同一份 override）。"""
        await self._ensure_ready()
        if self.outfits is None:
            return {"code": 1, "msg": "穿搭引擎不可用"}
        payload = await self._body()
        payload = payload if isinstance(payload, dict) else {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return {"code": 1, "msg": "缺少衣服名"}
        day = today_str()
        try:
            ok, place = self.outfits.can_change_to(name)
        except Exception:
            ok, place = True, ""
        if not ok:
            return {"code": 1, "msg": "她现在在%s，这类衣服不能在外面换" % place}
        data = self.outfits.change_outfit(day, name, from_hour=str(payload.get("from") or ""))
        items = self.state.schedule.get(day) or self.db.get_schedule(day) or []
        items = self.outfits.assign(self.state._hourly_schedule(items), day)
        self.state.schedule[day] = items
        try:
            self.db.kv_set("schedule", self._sanitize_schedule(self.state.schedule))
            self.db.save_schedule(day, items)
        except Exception:
            pass
        return {"code": 0, "msg": "换好了：" + data.get("name", name), "data": data}

    async def api_diary_warm(self):
        """重建今天的小日记（详细版），用于首次部署或规则升级后手动触发。"""
        await self._ensure_ready()
        data = await self._body()
        data = data if isinstance(data, dict) else {}
        day = str(data.get("date") or today_str()).strip() or today_str()
        items = (self.state.schedule.get(day)
                 or self.db.get_schedule(day)
                 or await self.state.ensure_schedule(self._last_umo))
        items = self.state._hourly_schedule(items)
        try:
            result = await self.state.warm_diaries(day, items, self._last_umo, force=True)
        except Exception as exc:
            logger.warning("[amo] 手动重建日记失败: %s" % exc)
            return {"code": 1, "msg": "重建失败：%s" % exc}
        return {"code": 0, "data": result}

    async def api_scenic_kb_regen(self):
        await self._ensure_ready()
        kb = await self._ensure_scenic_kb()
        if kb is None:
            return {
                "code": 1,
                "msg": "景区知识库创建失败：请检查 Embedding 供应商，并查看 AstrBot 日志",
            }
        return {"code": 0, "msg": "景区知识库已就绪：" + self._scenic_kb_name()}

    async def api_kb_regen(self):
        await self._ensure_ready()
        try:
            data = await self._body()
        except Exception:
            data = {}
        style = str(data.get("dialect_style") or "").strip()
        if style in DIALECT_REGIONS:
            self.config["dialect_style"] = style
            try:
                if hasattr(self.config, "save_config"):
                    self.config.save_config()
            except Exception:
                pass
        style_now = self._dialect_style().strip()
        logger.info("[amo] 重建语种: style=%s region=%s rows=%d kb=%s" % (
            style_now, self._dialect_region(), len(self._dialect_rows()), self._dialect_kb_name()
        ))
        kb = await self._ensure_dialect_kb()
        if kb is None:
            return {
                "code": 1,
                "msg": "知识库创建失败：请检查是否配置了 Embedding 供应商，并查看 AstrBot 日志",
            }
        return {"code": 0, "msg": "知识库已就绪：" + self._dialect_kb_name()}

    def _photo_job_start(self, kind, coro):
        """后台跑生图任务，接口立刻返回 job id，避免桥接请求超时。"""
        jobs = getattr(self, "_photo_jobs", None)
        if jobs is None:
            jobs = {}
            self._photo_jobs = jobs
        cutoff = now_ts() - 900
        for key in [key for key, value in jobs.items() if float(value.get("ts") or 0) < cutoff]:
            jobs.pop(key, None)
        job_id = uuid.uuid4().hex[:12]
        jobs[job_id] = {"status": "running", "kind": kind, "ts": now_ts(), "data": None, "msg": ""}

        async def runner():
            try:
                result = await coro
                jobs[job_id].update(status="done", data=result)
                logger.info("[amo] 照片任务完成(%s): %d 字节图片" % (kind, len(str((result or {}).get("image") or ""))))
            except Exception as exc:
                logger.warning("[amo] 照片任务失败(%s): %s" % (kind, exc))
                jobs[job_id].update(status="error", msg=str(exc))

        try:
            asyncio.create_task(runner())
        except RuntimeError:
            try:
                coro.close()
            except Exception:
                pass
            jobs[job_id].update(status="error", msg="事件循环不可用")
        return job_id

    # ---------- 财务中枢：所有钱只能走这里 ----------
    #
    # 设计要点：
    #   * 医疗、房租、购物都不许自己改账，一律调 charge()/income()；
    #   * 成功不写日志（正常交易不该刷屏），失败由金融插件打 warning；
    #   * 每笔都会同步到 self.state.finance，她下次开口时心里有数。

    FINANCE_PLUGIN_NAMES = (
        "Astrbot_Amo_Finance", "astrbot_plugin_amo_finance", "amo_finance",
    )

    def _finance(self):
        """找「我想永远陪着你-金融」实例；没装返回 None。"""
        for name in self.FINANCE_PLUGIN_NAMES:
            try:
                meta = self.context.get_registered_star(name)
            except Exception:
                meta = None
            star = self._finance_instance(meta)
            if star is not None:
                return star
        try:
            for meta in self.context.get_all_stars():
                marker = ((getattr(meta, "name", "") or "") + " "
                          + (getattr(meta, "module_path", "") or "")).lower()
                if "amo_finance" not in marker:
                    continue
                star = self._finance_instance(meta)
                if star is not None:
                    return star
        except Exception:
            pass
        return None

    @staticmethod
    def _finance_instance(meta):
        if meta is None:
            return None
        for attr in ("star_cls", "instance", "star", "plugin"):
            value = getattr(meta, attr, None)
            if value is not None:
                return value
        return None

    def _sync_finance(self) -> None:
        """把金融插件的最新快照拉进状态。不写日志，失败也不影响主链路。"""
        plugin = self._finance()
        if plugin is None:
            return
        try:
            try:
                snap = plugin.snapshot(refresh=False)
            except TypeError:
                snap = plugin.snapshot()
            if isinstance(snap, dict):
                self.state.finance = {
                    "balance": snap.get("balance", 0),
                    "fixed_total": snap.get("fixed_total", 0),
                    "anxiety": snap.get("anxiety", 0),
                    "owed": snap.get("owed_to_user", 0),
                    "month_spent": snap.get("month_spent", 0),
                }
                inv = snap.get("invest") or {}
                self.state.invest = {
                    "stance": inv.get("stance") or "",
                    "leek": inv.get("leek") or {},
                    "cash": inv.get("cash", 0),
                    "value": inv.get("total_value", 0),
                    "pnl": inv.get("total_pnl", 0),
                    "pnl_pct": inv.get("total_pnl_pct", 0),
                    "day_pnl": inv.get("day_pnl", 0),
                    "count": inv.get("count", 0),
                    "positions": [
                        {"name": p.get("name") or p.get("symbol"),
                         "qty": p.get("qty"), "pnl_pct": p.get("pnl_pct")}
                        for p in (inv.get("positions") or [])[:6]
                    ],
                    "bankrupt": inv.get("bankrupt") or {},
                    "aggressive": bool(inv.get("aggressive")),
                }
        except Exception as exc:
            logger.debug("[amo] 财务快照同步失败: %s" % exc)

    #: 单笔扣款上限：模型或挂载插件算错时，宁可拒绝，也不能把余额一次清空。
    CHARGE_MAX = 100000.0

    def _primary_uid(self) -> str:
        """花钱要记在「人」身上，不能记到群里随便谁。

        顺序：相恋关系的人 → 最近私聊的人 → 随便一个画像（最后兜底）。
        之前直接取 ``list_profiles(limit=1)``，结果记到了列表里第一个陌生人头上。
        """
        try:
            for uid in self._lover_aliases().values():
                if uid:
                    return str(uid)
        except Exception:
            pass
        try:
            umo = str(getattr(self, "_last_umo", "") or "") or self._first_private_umo()
        except Exception:
            umo = ""
        parts = [part for part in str(umo).split(":") if part]
        if len(parts) >= 3 and "group" not in str(umo).lower():
            return parts[-1]
        try:
            rows = self.db.list_profiles(limit=1)
        except Exception:
            rows = []
        return str(rows[0].get("uid") or "") if rows else ""

    #: 失败单只在内存里留 60 秒（挡并发重试）；成功单才持久化。
    CHARGE_FAIL_TTL = 60.0
    #: 持久化多少条成功幂等号（够覆盖「重启后重试同一笔」就行）。
    CHARGE_OK_KEEP = 200

    def _charge_conflict(self, note="终端缓存"):
        """同一个幂等号配了不同金额：调用方拿错了号，不许当同一笔账复用。"""
        return {"ok": False, "code": "idempotency_conflict", "repeated": True,
                "reason": "同一幂等号的金额不一致（%s）" % note,
                "balance": self.balance()}

    @staticmethod
    def _amount_conflicts(entry, amount):
        if not isinstance(entry, dict) or amount is None:
            return False
        stored = entry.get("_amount")
        if stored is None:
            return False
        try:
            return abs(round(float(stored), 2) - round(float(amount), 2)) > 0.005
        except (TypeError, ValueError):
            return False

    def _charge_cache_get(self, request_id, amount=None):
        """查幂等号。

        - 成功单：内存 + 磁盘（``charge_ok``），重启后同一笔不会再扣；
        - 失败单：只留 60 秒，补钱之后能重试——永久缓存失败等于把这笔锁死。
        - 金额对不上：说明调用方拿错了号，返回 ``idempotency_conflict``。
        """
        if not request_id:
            return None
        cache = getattr(self, "_charge_cache", None) or {}
        hit = cache.get(request_id)
        if isinstance(hit, dict):
            if self._amount_conflicts(hit, amount):
                return self._charge_conflict("内存")
            return dict(hit)
        try:
            stored = self.db.kv_get("charge_ok", {}) or {}
        except Exception:
            stored = {}
        entry = stored.get(request_id) if isinstance(stored, dict) else None
        if isinstance(entry, dict) and entry.get("ok"):
            if self._amount_conflicts(entry, amount):
                return self._charge_conflict("落库")
            return dict(entry)
        fail = (getattr(self, "_charge_fail", None) or {}).get(request_id)
        if isinstance(fail, tuple) and len(fail) == 2:
            ts, result = fail
            if time.time() - to_float(ts, 0) <= self.CHARGE_FAIL_TTL:
                return dict(result)
            try:
                self._charge_fail.pop(request_id, None)
            except Exception:
                pass
        return None

    def _charge_cache_put(self, request_id, result, amount=None):
        if not request_id:
            return
        if not result.get("ok"):
            fail = getattr(self, "_charge_fail", None)
            if fail is None:
                fail = {}
                self._charge_fail = fail
            fail[request_id] = (time.time(), dict(result))
            if len(fail) > 200:
                for key in list(fail)[:50]:
                    fail.pop(key, None)
            return
        payload = dict(result)
        try:
            if amount is not None:
                payload["_amount"] = round(float(amount), 2)
        except (TypeError, ValueError):
            pass
        cache = getattr(self, "_charge_cache", None)
        if cache is None:
            cache = {}
            self._charge_cache = cache
        cache[request_id] = dict(payload)
        if len(cache) > 200:
            for key in list(cache)[:50]:
                cache.pop(key, None)
        try:
            stored = self.db.kv_get("charge_ok", {}) or {}
            if not isinstance(stored, dict):
                stored = {}
            stored[request_id] = dict(payload, ts=time.time())
            if len(stored) > self.CHARGE_OK_KEEP:
                oldest = sorted(stored, key=lambda k: to_float((stored.get(k) or {}).get("ts"), 0))
                for key in oldest[: max(1, len(stored) - self.CHARGE_OK_KEEP)]:
                    stored.pop(key, None)
            self.db.kv_set("charge_ok", stored)
        except Exception as exc:
            logger.debug("[amo] 幂等号落库失败: %s" % exc)

    async def charge(self, amount, reason: str = "", payee: str = "",
                     request_id: str = "", source: str = "", detail: str = "",
                     uid: str = "") -> dict:
        """花钱的唯一入口：**审批 → 交给金融 → 把结果告诉记忆**。

        她不自己算账：余额只认金融返回的数字，这里不写余额、不算流水。
        ``request_id`` 是幂等号——同一个号重试只扣一次（医疗重试、网络重发都走这里）。
        """
        try:
            value = round(float(amount or 0), 2)
        except Exception:
            value = 0.0
        rid = str(request_id or "").strip()
        if value <= 0:
            return {"ok": False, "code": "bad_amount", "reason": "金额不对",
                    "balance": self.balance()}
        if value > self.CHARGE_MAX:
            return {"ok": False, "code": "over_limit", "reason": "超过单笔上限",
                    "balance": self.balance()}
        cached = self._charge_cache_get(rid, amount=value)
        if cached is not None:
            cached["repeated"] = True
            return cached

        plugin = self._finance()
        if plugin is None:
            result = {"ok": False, "code": "no_finance", "reason": "没有金融插件", "balance": 0}
        else:
            try:
                try:
                    # 幂等号一起交给金融：它才是账本，重启后也认得出这笔扣过没有
                    result = await asyncio.to_thread(
                        plugin.charge, value, reason, payee, request_id=rid or None)
                except TypeError as exc:
                    if "request_id" not in str(exc):
                        raise
                    # 老版本金融不认识 request_id：退回三参数
                    result = await asyncio.to_thread(plugin.charge, value, reason, payee)
            except Exception as exc:
                logger.warning("[amo] 扣款调用失败: %s" % exc)
                result = {"ok": False, "code": "call_failed", "reason": "扣款出错"}
            if not isinstance(result, dict):
                result = {"ok": False, "code": "bad_result", "reason": "返回值异常"}
        result.setdefault("code", "ok" if result.get("ok") else "failed")
        result.setdefault("transaction_id", rid or ("amo" + uuid.uuid4().hex[:10]))
        self._sync_finance()
        self._charge_cache_put(rid, result, amount=value)
        if not result.get("repeated"):
            await self._record_expense(value, reason, detail, source, result, uid)
            if result.get("ok"):
                self._record("buy", reason or "花钱", detail or payee,
                             "source=%s" % (source or "-"), value)
        return result

    async def _record_expense(self, amount, reason, detail, source, result, uid=""):
        """把这一笔告诉记忆——**成功失败都记**。

        只记成功的话，聊天里她会以为钱没花，或者不知道自己为什么没钱。
        """
        try:
            target = str(uid or "").strip() or self._primary_uid()
        except Exception:
            target = ""
        if not target:
            return
        rate = ("%s（%s）" % (reason or "一笔支出", detail)) if detail else (reason or "一笔支出")
        if result.get("ok"):
            text = "%s：支出 ¥%.2f，金融已扣款" % (rate, float(amount))
        else:
            text = "%s：¥%.2f 没扣成（%s）" % (
                rate, float(amount), result.get("reason") or "余额不足")
        try:
            balance = result.get("balance")
            if balance is not None:
                text += "，余额 ¥%.2f" % float(balance)
        except Exception:
            pass
        if source:
            text = "[" + str(source) + "] " + text
        try:
            await self._write_memory_checked(target, text, kind="expense", tier=0,
                                             scope="private", group_id="")
        except Exception as exc:
            logger.debug("[amo] 支出事件没写进记忆: %s" % exc)

    async def income(self, amount, reason: str = "") -> dict:
        plugin = self._finance()
        if plugin is None:
            return {"ok": False, "reason": "没有金融插件"}
        try:
            result = await asyncio.to_thread(plugin.income, amount, reason, "")
        except Exception as exc:
            logger.warning("[amo] 入账调用失败: %s" % exc)
            return {"ok": False, "reason": "入账出错"}
        self._sync_finance()
        return result if isinstance(result, dict) else {"ok": False}

    def balance(self) -> float:
        plugin = self._finance()
        if plugin is None:
            return 0.0
        try:
            return float(plugin.balance())
        except Exception:
            return 0.0

    def recent_money(self, limit: int = 5) -> list:
        plugin = self._finance()
        if plugin is None:
            return []
        try:
            return list(plugin.recent(limit))
        except Exception:
            return []

    # ---------- 就医：生病了，去不去治 ----------

    MEDICAL_PLUGIN_NAMES = (
        "Astrbot_Amo_Medical", "astrbot_plugin_amo_medical", "amo_medical",
    )

    def _medical(self):
        """找「我想永远陪着你-医疗」实例；没装返回 None。"""
        for name in self.MEDICAL_PLUGIN_NAMES:
            try:
                meta = self.context.get_registered_star(name)
            except Exception:
                meta = None
            star = self._finance_instance(meta)
            if star is not None:
                return star
        try:
            for meta in self.context.get_all_stars():
                marker = ((getattr(meta, "name", "") or "") + " "
                          + (getattr(meta, "module_path", "") or "")).lower()
                if "amo_medical" not in marker:
                    continue
                star = self._finance_instance(meta)
                if star is not None:
                    return star
        except Exception:
            pass
        return None

    async def _maybe_notify_repay(self) -> None:
        """她自动还了钱：在私聊里说一声，不要只在账本里静默扣。"""
        plugin = self._finance()
        reader = getattr(plugin, "money_repay", None) if plugin is not None else None
        if not callable(reader):
            return
        try:
            note = reader() or {}
            amount = float(note.get("amount") or 0)
        except Exception:
            return
        if amount <= 0:
            return
        ts = float(note.get("ts") or 0)
        last = to_float(self.db.kv_get("last_repay_notified_ts", 0), 0)
        if ts and ts <= last:
            return
        umo = self._first_private_umo() or self._last_umo
        if not umo:
            return
        remaining = float(note.get("remaining") or 0)
        if remaining > 0:
            text = ("老公，我刚还你 %.0f 啦，还欠你 %.0f，剩下的我慢慢还嘛。"
                    % (amount, remaining))
        else:
            text = "老公，我还你钱啦，转了你 %.0f，欠你的还清咯～" % amount
        try:
            await self.context.send_message(umo, text)
        except Exception as exc:
            logger.debug("[amo] 还款通知发送失败: %s" % exc)
            return
        self.db.kv_set("last_repay_notified_ts", ts or now_ts())
        logger.info("[amo] 还款通知已发：%.0f（还欠 %.0f）" % (amount, remaining))

    async def _maybe_push_salary(self) -> None:
        """把人格里的月薪同步给金融。

        人格没写薪资是常态：这时不推，金融按城市平均发。人格改过就重新读一次。
        """
        now = now_ts()
        if now - to_float(getattr(self, "_salary_checked_at", 0), 0) < 600:
            return
        self._salary_checked_at = now
        plugin = self._finance()
        setter = getattr(plugin, "set_salary", None) if plugin is not None else None
        if not callable(setter):
            return
        umo = self._last_umo or self._first_private_umo()
        text = ""
        try:
            if self.llm is not None and umo:
                text = await self.llm.persona(umo) or ""
        except Exception as exc:
            logger.debug("[amo] 读人格失败（薪资）: %s" % exc)
            return
        gross = extract_salary(text)
        if gross <= 0:
            return
        try:
            result = await asyncio.to_thread(setter, gross, "persona")
        except Exception as exc:
            logger.debug("[amo] 推送月薪失败: %s" % exc)
            return
        if isinstance(result, dict) and result.get("skipped"):
            return
        logger.info("[amo] 从人格读到月薪 %.0f，已交给金融" % gross)

    async def _maybe_push_assets(self) -> None:
        """把人格里的房/车同步给金融：她开奔驰，就不能被随机成比亚迪。"""
        now = now_ts()
        if now - to_float(getattr(self, "_assets_checked_at", 0), 0) < 600:
            return
        self._assets_checked_at = now
        plugin = self._finance()
        setter = getattr(plugin, "set_persona_assets", None) if plugin is not None else None
        if not callable(setter):
            return
        car = ""
        house = ""
        try:
            profile = getattr(self.state, "schedule_profile", {}) or {}
            car = str(profile.get("car") or "").strip()
            house = str(profile.get("home") or "").strip()
        except Exception as exc:
            logger.debug("[amo] 读人格资产失败: %s" % exc)
            return
        if not car and not house:
            return
        try:
            result = await asyncio.to_thread(setter, car, house)
        except Exception as exc:
            logger.debug("[amo] 推送房车失败: %s" % exc)
            return
        city = ""
        try:
            profile_city = (getattr(self.state, "schedule_profile", {}) or {}).get("city")
            city = str(profile_city or "").strip()
        except Exception:
            city = ""
        city_setter = getattr(plugin, "set_persona_city", None)
        if city and callable(city_setter):
            try:
                await asyncio.to_thread(city_setter, city)
            except Exception as exc:
                logger.debug("[amo] 推送城市失败: %s" % exc)
        if isinstance(result, dict) and result.get("changed"):
            logger.info("[amo] 从人格读到房车，已交给金融：%s｜%s" % (house or "-", car or "-"))

    async def _note_invest_seed(self) -> None:
        """第一次建仓后，把这件事记成记忆——她要真的"知道"自己买了股票。"""
        try:
            if self.db.kv_get("invest_seed_noted", False):
                return
        except Exception:
            return
        inv = getattr(self.state, "invest", None) or {}
        positions = inv.get("positions") or []
        if not positions:
            return
        first = positions[0]
        try:
            self.db.kv_set("invest_seed_noted", True)
        except Exception:
            pass
        await self._market_memory(
            "我用自己的钱买了 %s %d 股，先放着看看；跌了会心疼，涨了想奖励自己"
            % (first.get("name") or "一只股票", int(first.get("qty") or 0)),
            kind="asset",
        )
        logger.info("[amo] 已记住建仓：%s %s 股" % (first.get("name"), first.get("qty")))

    async def _sync_market_mood(self) -> None:
        """股市盈亏影响心情。

        赚了：开心、兴奋，奖励自己一顿好的（真的记一笔支出）。
        亏了：郁闷、焦虑，吃得简单——语气会跟着无精打采（心情会注入人格提示）。
        一天只按方向记一次，不然每条 tick 都在加焦虑。
        """
        plugin = self._finance()
        reader = getattr(plugin, "mood_signal", None) if plugin is not None else None
        if not callable(reader):
            return
        try:
            try:
                signal = reader(refresh=False)
            except TypeError:
                signal = reader()
        except Exception as exc:
            logger.debug("[amo] 读投资盈亏失败: %s" % exc)
            return
        if not isinstance(signal, dict):
            return
        pct = to_float(signal.get("day_pnl_pct"), 0)
        pnl = to_float(signal.get("day_pnl"), 0)
        # 韭菜档位（±3%）先单独处理：上头/死扛各加一次，和 ±2% 的心情不冲突
        stance = str((getattr(self.state, "invest", None) or {}).get("stance") or "")
        if stance:
            key = "%s|leek|%s" % (today_str(), stance)
            if getattr(self, "_leek_key", "") != key:
                self._leek_key = key
                if stance == "overconfident":
                    self.state.nudge(兴奋=8, 开心=5)
                    await self._market_memory("今天股票大涨，我飘了，觉得自己就是巴菲特", kind="event")
                else:
                    self.state.nudge(焦虑=7, 郁闷=4)
                    await self._market_memory("今天股票大跌，我死扛着不卖，心里其实很难受", kind="event")
        if abs(pct) < 2.0:
            return
        mood = "up" if pct > 0 else "down"
        key = "%s|%s" % (today_str(), mood)
        if getattr(self, "_market_mood_key", "") == key:
            return
        self._market_mood_key = key
        if mood == "up":
            self.state.nudge(开心=8, 兴奋=4)
            await self._market_memory(
                "今天股市赚了 %.2f%%（¥%.0f），心情不错，想吃点好的" % (pct, pnl),
                kind="event",
            )
            await self._market_reward(pnl)
        else:
            self.state.nudge(郁闷=8, 焦虑=6, 开心=-4)
            await self._market_memory(
                "今天股市亏了 %.2f%%（¥%.0f），有点没精神，吃得简单点" % (-pct, -pnl),
                kind="event",
            )

    async def _market_memory(self, text: str, kind: str = "event") -> None:
        try:
            uid = self._primary_uid()
        except Exception:
            uid = ""
        if not uid:
            return
        try:
            await self._write_memory_checked(uid, text, kind=kind, tier=0,
                                             scope="private", group_id="")
        except Exception as exc:
            logger.debug("[amo] 股市心情没写进记忆: %s" % exc)

    async def _market_reward(self, pnl: float) -> None:
        """赚了就奖励自己吃顿好的——真花钱，走同一个账本。"""
        if not self.cfg_bool("market_reward_enable", True):
            return
        amount = 68.0 if pnl < 500 else (128.0 if pnl < 3000 else 198.0)
        try:
            result = await self.charge(
                amount, reason="犒劳自己吃顿好的", payee="餐厅",
                request_id="market-reward-%s" % today_str(),
                source="market", detail="今天股票赚了",
            )
        except Exception as exc:
            logger.debug("[amo] 奖励自己失败: %s" % exc)
            return
        if result.get("ok"):
            logger.info("[amo] 股市赚了，奖励自己一顿 %.0f 元" % amount)

    def _sync_health_from_medical(self) -> None:
        """身体状态以医疗插件为准。

        医疗说「恢复中」就写恢复中，别抢着改成健康——否则人格资料里会出现
        「刚看完病」和「身体：健康」并存的自相矛盾。
        """
        medical = self._medical()
        if medical is None:
            return
        try:
            info = medical.status()
        except Exception:
            return
        status = str(info.get("status") or "").strip() or "健康"
        note = str(info.get("note") or "")
        current = self.state.health or {}
        if str(current.get("status") or "") == status and str(current.get("note") or "") == note:
            return
        hours = 0
        try:
            until = float(info.get("until") or 0)
            if until > time.time():
                hours = max(1, int((until - time.time()) / 3600.0) + 1)
        except Exception:
            hours = 0
        self.state.set_health(status, hours, note)

    #: 只有「他带她去」才触发手动就医；单纯催促（“去医院看看”“病成这样”）
    #: 不触发——留给她回一句“没钱”，等他转钱、带她去再治。
    DOCTOR_WORDS = (
        "我带你去", "走我带你去", "带你去医院", "带你去看病", "带你去看医生",
        "带你去看看", "我带你看病", "我带你去看看",
    )

    async def _maybe_user_takes_her_to_doctor(self, event, text) -> bool:
        """他说要带她去医院，这才是她去看病的入口。

        她自己不会主动去（后台每天自动判断那条路已经停掉）；只有他发现她不对劲、
        说「都病成这样了还不去医院看看，走我带你去医院」，才走医疗插件的手动就医。
        """
        if not text or not event.is_private_chat():
            return False
        medical = self._medical()
        if medical is None:
            return False
        try:
            info = medical.status()
        except Exception:
            return False
        if not info.get("sick"):
            return False
        if not any(word in text for word in self.DOCTOR_WORDS):
            return False
        try:
            result = await medical.treat(auto=False) or {}
        except Exception as exc:
            logger.warning("[amo] 带她去医院失败: %s" % exc)
            return False
        note = {
            "ts": now_ts(),
            "name": str(result.get("name") or ""),
            "self_pay": float(result.get("self_pay") or 0),
            "ok": bool(result.get("ok")),
            "reason": str(result.get("reason") or ""),
        }
        self.db.kv_set("doctor_note", note)
        if result.get("ok"):
            logger.info("[amo] 他带她去看了病：%s，自付 %.0f"
                        % (note["name"], note["self_pay"]))
            self._sync_health_from_medical()
        else:
            logger.info("[amo] 带她去医院没治成：%s"
                        % (note["reason"] or "余额不足"))
        return True

    def _doctor_line(self) -> str:
        """刚被带去看病（或没看成）：让她的反应接得上。"""
        note = self.db.kv_get("doctor_note", {}) or {}
        try:
            age = now_ts() - float(note.get("ts") or 0)
        except Exception:
            return ""
        if not note or age < 0 or age > 900:
            return ""
        if note.get("ok"):
            return (
                "【他带你去医院】%d 分钟前他带你去看了病（自付 %.0f），现在在恢复。"
                "记得谢谢他、跟他撒个娇，别装没事，也别报流水。"
                % (max(1, int(age // 60)), float(note.get("self_pay") or 0))
            )
        return (
            "【他带你去医院】%d 分钟前他要带你去医院，但没治成：%s。"
            "可以委屈地跟他说，别硬撑。"
            % (max(1, int(age // 60)), note.get("reason") or "没钱")
        )

    async def _maybe_treat(self) -> None:
        """换成医疗插件管的病情后，由它决定治不治、钱够不够。

        她自己会去看病；医疗插件会回调 self.charge()——**所以这里仍然是
        「她知情」的那条路**。成功只写状态，不刷日志；失败由医疗插件记 warning。
        """
        medical = self._medical()
        if medical is None:
            return
        try:
            info = medical.status()
        except Exception:
            return
        if not info.get("sick"):
            return
        # 同一个病一天只判断一次，避免后台循环反复去治
        key = "%s|%s" % (today_str(), info.get("illness") or info.get("status"))
        if getattr(self, "_treat_marked", None) == key:
            return
        self._treat_marked = key
        try:
            result = await medical.treat(auto=True)
        except Exception as exc:
            logger.warning("[amo] 就医失败: %s" % exc)
            return
        if result.get("skipped"):
            # 手动模式 / 她自己先扛着：都不是失败，不该记成焦虑
            logger.debug("[amo] 这次没去看病：%s" % result.get("reason"))
            return
        if result.get("ok"):
            logger.info("[amo] 去看了病：%s，自付 %.0f"
                        % (result.get("name"), float(result.get("self_pay") or 0)))
            # 状态交给医疗插件：它说「恢复中」就写恢复中
            self._sync_health_from_medical()
        else:
            self.state.nudge(焦虑=8, 郁闷=4)

    # ---------- 世界页照片：单击自拍、三击一寸证件照 ----------

    ID_PHOTO_PROMPT = (
        "一寸证件照，正面免冠，纯白背景，端正坐姿，表情自然，"
        "标准证件照构图，光线均匀，高清"
    )
    # 证件照必须和本人一致：脸、五官、身材都不动，只换衣服
    ID_PHOTO_CONSISTENCY = "保持同一个人：脸型、五官、眼睛、发型、身材比例完全不变，只更换服装"

    def _id_photo_prompt(self, clothes=""):
        clothes = str(clothes or "").strip()[:60]
        parts = [self.ID_PHOTO_PROMPT, self.ID_PHOTO_CONSISTENCY]
        if clothes:
            parts.insert(1, "穿着" + clothes)
        else:
            parts.insert(1, "白衬衫")
        return "，".join(parts)

    def _selfie_prompt(self):
        """按她此刻的穿搭/地点/在做的事拼自拍提示词。"""
        activity = {}
        try:
            activity = self.state.current_activity() or {}
        except Exception:
            activity = {}
        parts = ["自拍"]
        outfit = str(activity.get("outfit") or "").strip()
        if outfit:
            parts.append("穿着" + outfit)
        place = str(activity.get("place") or "").strip()
        if place:
            parts.append("在" + place)
        doing = str(activity.get("activity") or "").strip()
        if doing:
            parts.append(doing[:30])
        parts.extend(["自然光", "手机前置摄像头", "生活感"])
        return "，".join(parts)

    async def _image_bytes(self, prompt, umo="", uid="", selfie=None, scene=None):
        """出图兜底入口：让生图插件（Astrbot_Amo_Image）直接吐图片字节。

        画图/照片引擎原先只认万象画卷（OmniDraw），机器上没装就一张都出不来；
        有了这个兜底，装万象画卷或装生图插件都能出图。
        """
        plugin = self._image_plugin()
        if plugin is None:
            return None
        prompt = str(prompt or "").strip()
        if not prompt:
            return None
        scene = scene if isinstance(scene, dict) else self._activity_snapshot(umo)
        place = str((scene or {}).get("place") or "").strip()
        activity = str((scene or {}).get("activity") or "").strip()
        zone = str((scene or {}).get("zone") or "").strip()
        logger.info("[amo] 出图场景：%s / %s" % (place or "未定", activity or "未定"))
        try:
            try:
                return await asyncio.wait_for(
                    plugin.draw_for(str(umo or ""), str(uid or ""), prompt, selfie=selfie,
                                    place=place, activity=activity, zone=zone),
                    timeout=180,
                )
            except TypeError:
                # 老版本生图插件：先退到 selfie，再不认就退回三参数
                try:
                    return await asyncio.wait_for(
                        plugin.draw_for(str(umo or ""), str(uid or ""), prompt, selfie=selfie),
                        timeout=180,
                    )
                except TypeError:
                    return await asyncio.wait_for(
                        plugin.draw_for(str(umo or ""), str(uid or ""), prompt), timeout=180
                    )
        except Exception as exc:
            logger.warning("[amo] 生图插件出图失败: %s" % exc)
            return None

    async def _draw_for_panel(self, prompt):
        """调生图插件出一张图，返回 data URL（面板直接显示）。"""
        plugin = self._image_plugin()
        if plugin is None:
            raise RuntimeError("没装生图插件（Astrbot_Amo_Image）")
        umo = str(self._last_umo or self._first_private_umo() or "")
        uid = ""
        try:
            for profile in self.db.proactive_profiles(limit=5) or []:
                uid = str(profile.get("uid") or "")
                if uid:
                    break
        except Exception:
            uid = ""
        data = await asyncio.wait_for(plugin.draw_for(umo, uid, prompt), timeout=180)
        if not data:
            raise RuntimeError("没出图（后端报错或超时）")
        import base64 as _b64
        # 相框只有 84~220px：缩到 512px 的 JPEG，base64 从约 500KB 降到几十 KB，
        # 桥接不用扛大包，localStorage 也存得下。缩图失败就用原图。
        try:
            import io as _io
            from PIL import Image as _Image
            _img = _Image.open(_io.BytesIO(data))
            _img = _img.convert("RGB")
            if _img.width > 512:
                _img = _img.resize((512, max(1, int(_img.height * 512.0 / _img.width))), _Image.LANCZOS)
            _buf = _io.BytesIO()
            _img.save(_buf, format="JPEG", quality=88)
            _small = _buf.getvalue()
            logger.info("[amo] 面板照片缩图: %d -> %d 字节" % (len(data), len(_small)))
            return "data:image/jpeg;base64," + _b64.b64encode(_small).decode()
        except Exception as _exc:
            logger.debug("[amo] 面板照片缩图失败（用原图）: %s" % _exc)
        return "data:image/png;base64," + _b64.b64encode(data).decode()

    def _panel_photo_dir(self):
        """面板照片目录：和数据同处 plugin_data，不写插件安装目录。"""
        base = os.path.dirname(str(getattr(getattr(self, "db", None), "path", "") or ""))
        if not base:
            plugin_dir = str(getattr(self, "plugin_dir", "") or "")
            name = os.path.basename(plugin_dir) or "Astrbot_Amo_forever"
            parent = os.path.dirname(plugin_dir)
            base = os.path.join(parent, "plugin_data", name) if parent else os.getcwd()
        path = os.path.join(base, "photo_cache")
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass
        return path

    def _panel_photo_file(self):
        return os.path.join(self._panel_photo_dir(), "panel_last.jpg")

    def _save_panel_photo(self, data_url):
        """把面板那张图存下来：刷新、重开面板都还在（localStorage 在 iframe 里不可靠）。"""
        text = str(data_url or "")
        if "," in text and text.startswith("data:"):
            text = text.split(",", 1)[1]
        if not text:
            return 0
        import base64 as _b64
        raw = _b64.b64decode(text)
        path = self._panel_photo_file()
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(raw)
        os.replace(tmp, path)  # 旧图被直接替换掉，不会留多份
        logger.info("[amo] 面板照片已保存（替换旧图）: %d 字节" % len(raw))
        return len(raw)

    def _panel_photo_data_url(self):
        import base64 as _b64
        try:
            with open(self._panel_photo_file(), "rb") as fh:
                raw = fh.read()
        except Exception:
            return ""
        if not raw:
            return ""
        return "data:image/jpeg;base64," + _b64.b64encode(raw).decode()

    async def api_photo_last(self):
        """面板打开时取回上次那张图（小 JPEG，几十 KB）。"""
        await self._ensure_ready()
        image = self._panel_photo_data_url()
        return {"code": 0, "data": {"image": image, "bytes": len(image)}}

    async def api_photo_clear(self):
        """三击取消：把服务端那张也删掉，否则刷新又回来。"""
        await self._ensure_ready()
        removed = False
        try:
            os.remove(self._panel_photo_file())
            removed = True
        except Exception:
            removed = False
        logger.info("[amo] 面板照片已清除: %s" % ("是" if removed else "本来就没有"))
        return {"code": 0, "data": {"removed": removed}}

    async def _remember_panel_photo(self, kind: str, clothes: str = "", size: int = 0) -> None:
        """把「今天拍了张照片」写进记忆（照片本身不进模型，只记一条事实）。"""
        mem = self._data_mem()
        remember = getattr(mem, "remember", None) if mem is not None else None
        if not callable(remember):
            return
        try:
            umo = str(self._last_umo or self._first_private_umo() or "")
        except Exception:
            umo = ""
        uid = umo.rsplit(":", 1)[-1] if umo else ""
        if not uid:
            return
        label = "证件照" if str(kind) == "id" else "自拍"
        outfit = ("，穿的" + clothes) if clothes else ""
        now_text = ""
        try:
            snap = self.state.snapshot() if self.state is not None else {}
            now_text = str(snap.get("datetime_text") or "")[:16]
        except Exception:
            now_text = ""
        content = "【照片】%s我%s拍了一张%s%s。" % (
            (now_text + " ") if now_text else "", "", label, outfit)
        try:
            await remember(self._data_bot_id(), str(uid), content,
                           kind="photo_record", importance=0.35,
                           scope="private", group_id="")
            logger.info("[amo] 面板照片已记进记忆：%s（%d 字节）" % (label, size))
        except TypeError:
            try:
                await remember(self._data_bot_id(), str(uid), content)
            except Exception:
                pass

    async def api_photo_self(self):
        """世界页那张照片：kind=self 自拍，kind=id 一寸证件照。"""
        await self._ensure_ready()
        data = await self._body()
        data = data if isinstance(data, dict) else {}
        kind = str(data.get("kind") or "self").strip().lower()
        if kind not in ("self", "id"):
            kind = "self"
        clothes = str(data.get("clothes") or "").strip()
        prompt = self._id_photo_prompt(clothes) if kind == "id" else self._selfie_prompt()
        logger.info("[amo] 面板照片任务开始: kind=%s clothes=%s | %s"
                    % (kind, clothes or "-", prompt[:60]))

        async def build():
            image = await self._draw_for_panel(prompt)
            size = 0
            try:
                size = self._save_panel_photo(image)
            except Exception as exc:
                logger.debug("[amo] 面板照片落盘失败: %s" % exc)
            # 拍完要记住：不然她下次完全不记得这张照片
            try:
                await self._remember_panel_photo(kind, clothes, size)
            except Exception as exc:
                logger.debug("[amo] 记录面板照片失败: %s" % exc)
            return {"kind": kind, "prompt": prompt, "image": image}

        return {"code": 0, "data": {"job": self._photo_job_start("self_" + kind, build())}}

    async def api_photo_job(self):
        await self._ensure_ready()
        data = await self._body()
        data = data if isinstance(data, dict) else {}
        job_id = str(data.get("id") or "")
        job = (getattr(self, "_photo_jobs", {}) or {}).get(job_id)
        if not job:
            return {"code": 1, "msg": "任务不存在（插件可能重载过，重新生成一次）"}
        return {"code": 0, "data": {
            "id": job_id,
            "status": job.get("status"),
            "kind": job.get("kind"),
            "msg": job.get("msg") or "",
            "data": job.get("data"),
        }}

    async def api_draw_status(self):
        await self._ensure_ready()
        engine = getattr(self, "draw", None)
        if engine is None:
            return {"code": 1, "msg": "画图引擎未加载"}
        try:
            return {"code": 0, "msg": engine.diagnostics()}
        except Exception as exc:
            return {"code": 1, "msg": "画图自检失败：%s" % exc}

    async def api_draw_decide(self):
        """调试：给一段用户消息和她的回复，看会不会触发、提示词是什么。"""
        await self._ensure_ready()
        data = await self._body()
        data = data if isinstance(data, dict) else {}
        text = str(data.get("text") or "")
        reply = str(data.get("reply") or "")
        uid = str(data.get("uid") or "302578963")
        engine = getattr(self, "draw", None)
        if engine is None:
            return {"code": 1, "msg": "画图引擎未加载"}

        class _FakeEvent:
            def __init__(self, message, sender):
                self.message_str = message
                self.unified_msg_origin = "debug:private:%s" % sender
                self._sender = sender

            def is_private_chat(self):
                return True

            def get_sender_id(self):
                return self._sender

            def is_admin(self):
                return False

        try:
            plan = engine.decide(_FakeEvent(text, uid), reply)
        except Exception as exc:
            return {"code": 1, "msg": "decide 异常：%s" % exc}
        safe = None
        if isinstance(plan, dict):
            safe = {k: v for k, v in plan.items() if k != "cached"}
            safe["cached"] = bool(plan.get("cached"))
        return {"code": 0, "data": {"plan": safe}}

    async def api_draw_test(self):
        """调试：按当前场景真画一张并发到最近会话（会花钱，仅测试用）。"""
        await self._ensure_ready()
        data = await self._body()
        data = data if isinstance(data, dict) else {}
        text = str(data.get("text") or "拍照给我看看")
        reply = str(data.get("reply") or "在呀")
        umo = str(data.get("umo") or self._last_umo or "")
        if not umo:
            try:
                for profile in self.db.proactive_profiles(limit=5) or []:
                    candidate = self._pick_proactive_umo(profile)
                    if candidate:
                        umo = str(candidate)
                        break
            except Exception as exc:
                logger.debug("[amo] 画图测试取会话失败: %s" % exc)
        engine = getattr(self, "draw", None)
        if engine is None:
            return {"code": 1, "msg": "画图引擎未加载"}
        if not umo:
            return {"code": 1, "msg": "没有可发送的会话"}
        plugin = self

        class _FakeEvent:
            def __init__(self):
                self.message_str = text
                self.unified_msg_origin = umo

            def is_private_chat(self):
                return True

            def get_sender_id(self):
                return "302578963"

            def is_admin(self):
                return False

            async def send(self, chain):
                await plugin.context.send_message(umo, chain)

        plan = engine.decide(_FakeEvent(), reply)
        if not plan:
            return {"code": 0, "msg": "没有触发（看 draw_debug 日志）", "data": {"plan": None}}
        engine._schedule(_FakeEvent(), plan["prompt"], plan.get("reason", "test"),
                         plan.get("cached"), plan.get("cache_key", ""), plan.get("selfie", False))
        return {"code": 0, "msg": "已开始画：%s" % plan["prompt"], "data": {"umo": umo}}

    async def api_schedule_regen(self):
        await self._ensure_ready()
        items = await self.state.ensure_schedule(self._last_umo, force=True)
        return {"code": 0, "data": items}

    async def api_weather(self):
        await self._ensure_ready()
        weather = await self.state.refresh_weather(force=True)
        return {"code": 0, "data": weather}

    async def api_worldview(self):
        await self._ensure_ready()
        await self.state.ensure_worldview(self._last_umo)
        world = self.state.worldview
        try:
            data = dict(world or {})
        except Exception:
            return {"code": 0, "data": world}
        # 顺手把已保存的面板照片带回去：刷新/重开面板直接就能画上
        try:
            photo = self._panel_photo_data_url()
            if photo:
                data["panel_photo"] = photo
        except Exception:
            pass
        return {"code": 0, "data": data}

    async def api_worldview_regen(self):
        await self._ensure_ready()
        worldview = await self.state.ensure_worldview(self._last_umo, force=True)
        return {"code": 0, "data": worldview}

    async def api_say(self):
        """面板「代她说一句」。只允许发到已知会话，参数只认 body。"""
        await self._ensure_ready()
        data = await self._body()
        text = str(data.get("text") or "").strip()
        umo = str(data.get("umo") or "").strip() or str(self._last_umo or "")
        if not text:
            return {"code": 1, "msg": "text 不能为空"}
        if not umo:
            return {"code": 1, "msg": "没有可发送的会话"}
        known = set()
        try:
            for profile in self.db.list_profiles(limit=500):
                for key in ("private_umo", "last_group"):
                    value = str(profile.get(key) or "").strip()
                    if value:
                        known.add(value)
        except Exception as exc:
            logger.debug("[amo] 读取已知会话失败: %s" % exc)
        if umo not in known:
            logger.warning("[amo] 拒绝向未知会话发送: %s" % umo)
            return {"code": 1, "msg": "umo 不在已知会话内"}
        ok = await self._send_to_umo(umo, text)
        return {"code": 0 if ok else 1, "msg": "已发送" if ok else "发送失败"}
