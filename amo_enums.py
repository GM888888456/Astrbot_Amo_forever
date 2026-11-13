# -*- coding: utf-8 -*-
"""全项目共用的枚举：心情、日程分类、场景区域。

为什么要有这个文件：这些值以前是散落各处的裸字符串（`"生气"`、`"sleep"`、
`"scenic"`…），拼错一个字母不会报错，只会**静默走错分支**——日程写成
`"Sleep"` 就永远不睡、生图拿到 `"景区"` 就找不到场景，表现出来就像"她失忆/"
"她幻视"。枚举把这类错误变成当场报错。

三条铁律：

1. **值必须和旧字符串完全一致**（`MoodKey.ANGRY.value == "生气"`），
   数据库和配置里的老数据不用迁移；
2. 一律用 `str` 子类，并且 `__str__` 返回中文值——拼提示词、写日志时不会出现
   `MoodKey.ANGRY` 这种鬼东西；
3. 认不出的旧值**不抛异常**：`coerce()` 会退回给定的默认值，历史脏数据仍能读。
"""

from __future__ import annotations

from enum import Enum


class _StrEnum(str, Enum):
    """值就是字符串，`str()` / f-string 也输出值本身。"""

    def __str__(self) -> str:  # pragma: no cover - 一行，行为由测试锁住
        return str(self.value)

    def __repr__(self) -> str:  # pragma: no cover
        return "<%s.%s: %r>" % (type(self).__name__, self.name, self.value)


class MoodKey(_StrEnum):
    HAPPY = "开心"
    CALM = "平静"
    GLOOMY = "郁闷"
    ANGRY = "生气"
    FURIOUS = "暴躁"
    WRONGED = "委屈"
    TIRED = "疲惫"
    ANXIOUS = "焦虑"
    EXCITED = "兴奋"
    ATTACHED = "依恋"


#: 心情维度，顺序和以前 `MOOD_KEYS` 一模一样（顺序影响面板展示，别乱动）
MOOD_KEYS = tuple(item.value for item in MoodKey)


class ActivityCategory(_StrEnum):
    SLEEP = "sleep"
    MEAL = "meal"
    LIFE = "life"
    WORK = "work"
    REST = "rest"
    PLAY = "play"
    COMMUTE = "commute"
    EXERCISE = "exercise"


class SceneZone(_StrEnum):
    HOME = "home"
    HOTEL = "hotel"
    SCENIC = "scenic"
    PARK = "park"
    STREET = "street"
    ROAD = "road"
    CAFE = "cafe"
    RESTAURANT = "restaurant"
    MALL = "mall"
    OFFICE = "office"
    WORK = "work"
    COMMUTE = "commute"


def coerce(enum_cls, value, default=None):
    """把老字符串/新枚举都变成枚举成员；认不出就返回 default。

    读历史数据时用它，别让一个脏值把整条链路打挂。
    """
    if isinstance(value, enum_cls):
        return value
    text = str(value or "").strip()
    for item in enum_cls:
        if item.value == text:
            return item
    # 大小写不一致也算认出来（历史脏数据里常有 "Sleep" / "SCENIC"）
    lowered = text.lower()
    if lowered and text == text.strip():
        for item in enum_cls:
            if item.value.lower() == lowered:
                return item
    if default is not None:
        try:
            return enum_cls(default)
        except Exception:
            return None
    return None


def value_of(enum_cls, value, default=""):
    """取字符串值（写库、拼提示词用）。认不出就用 default 原文。"""
    item = coerce(enum_cls, value)
    return item.value if item is not None else str(default or "")
