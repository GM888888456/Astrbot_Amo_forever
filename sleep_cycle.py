# -*- coding: utf-8 -*-
"""睡眠状态机：他让她睡 → 她掂量；睡着后不聊天；半夜醒来有原因，写进日程和日记。

这里是**唯一**决定「她现在是不是在睡」的地方。以前判断靠零散字符串
（"在睡"/"睡觉" 之类的关键词），加一个状态就得改好几处；现在全部走枚举。

状态：

- ``AWAKE``      醒着，正常聊天；
- ``ASLEEP``     睡了，不再回群聊/私聊，直到醒来；
- ``NIGHT_WAKE`` 半夜醒了（有原因），过一会儿再睡回去。

回答（``SleepAnswer``）：答应 / 太早不睡 / 现在不想睡。
醒来的原因（``WakeReason``）是枚举，写进日程、日记和记忆时都用同一套中文。
"""

from __future__ import annotations

import random
from datetime import datetime
from enum import Enum


class SleepPhase(str, Enum):
    AWAKE = "awake"
    ASLEEP = "asleep"
    NIGHT_WAKE = "night_wake"


class SleepAnswer(str, Enum):
    ACCEPT = "accept"
    TOO_EARLY = "too_early"
    BUSY = "busy"


class WakeReason(str, Enum):
    CANNOT_SLEEP = "cannot_sleep"
    THIRSTY = "thirsty"
    DREAM = "dream"
    NIGHTMARE = "nightmare"
    NOISE = "noise"
    TOILET = "toilet"
    HOT = "hot"
    COLD = "cold"
    MISS_HIM = "miss_him"
    PHONE = "phone"
    UNKNOWN = "unknown"


#: 醒来原因 → 她日记/日程里的说法
WAKE_TEXT = {
    WakeReason.CANNOT_SLEEP: "躺着翻来覆去睡不着",
    WakeReason.THIRSTY: "渴醒了，摸黑找水喝",
    WakeReason.DREAM: "做了个梦醒了，半天没缓过来",
    WakeReason.NIGHTMARE: "做噩梦吓醒了，缩在被子里",
    WakeReason.NOISE: "被外面的动静吵醒了",
    WakeReason.TOILET: "起夜去了趟卫生间",
    WakeReason.HOT: "热醒了，把被子踢开",
    WakeReason.COLD: "冻醒了，把被子裹紧",
    WakeReason.MISS_HIM: "醒了，想他想到睡不着",
    WakeReason.PHONE: "手机亮了一下，醒过来看了一眼",
    WakeReason.UNKNOWN: "莫名其妙醒了",
}

#: 半夜醒来的权重（越想醒越靠前）
WAKE_WEIGHTS = (
    (WakeReason.THIRSTY, 3),
    (WakeReason.CANNOT_SLEEP, 3),
    (WakeReason.TOILET, 2),
    (WakeReason.DREAM, 2),
    (WakeReason.NIGHTMARE, 2),
    (WakeReason.MISS_HIM, 2),
    (WakeReason.HOT, 1),
    (WakeReason.COLD, 1),
    (WakeReason.NOISE, 1),
    (WakeReason.PHONE, 1),
)

#: 触发「去睡觉」的说法
GO_SLEEP_WORDS = (
    "去睡觉", "睡觉去", "该睡了", "快去睡", "早点睡", "睡吧", "睡觉吧",
    "去睡", "洗洗睡", "快去睡觉", "该睡觉了", "睡觉了",
)

#: 叫醒她的说法（睡着了也认）
WAKE_WORDS = ("起床", "醒醒", "别睡了", "起来吧", "起床啦", "叫你起床", "我回来了")


def _hhmm(value) -> int:
    try:
        hour, minute = str(value).split(":")[:2]
        return int(hour) * 60 + int(minute)
    except Exception:
        return -1


def reason_for(reason: WakeReason) -> str:
    return WAKE_TEXT.get(reason, WAKE_TEXT[WakeReason.UNKNOWN])


def pick_reason(rng: random.Random | None = None) -> WakeReason:
    chooser = rng or random.Random()
    total = sum(weight for _, weight in WAKE_WEIGHTS)
    point = chooser.uniform(0, total)
    upto = 0.0
    for reason, weight in WAKE_WEIGHTS:
        upto += weight
        if point <= upto:
            return reason
    return WakeReason.UNKNOWN


class SleepCycle:
    """睡着/醒来这件事的唯一裁判。状态存在 kv ``sleep_state`` 里，重启也认。"""

    KEY = "sleep_state"

    def __init__(self, db, accept_after: int = 23, wake_hour: int = 7,
                 night_wake_chance: float = 0.25):
        self.db = db
        self.accept_after = max(0, min(23, int(accept_after)))
        self.wake_hour = max(0, min(23, int(wake_hour)))
        self.night_wake_chance = max(0.0, min(1.0, float(night_wake_chance)))

    # ---------- 状态 ----------

    def load(self) -> dict:
        try:
            row = self.db.kv_get(self.KEY, {}) or {}
        except Exception:
            return {}
        return row if isinstance(row, dict) else {}

    def save(self, state: dict) -> None:
        try:
            self.db.kv_set(self.KEY, dict(state or {}))
        except Exception:
            pass

    def phase(self) -> SleepPhase:
        raw = str(self.load().get("phase") or "")
        try:
            return SleepPhase(raw)
        except ValueError:
            return SleepPhase.AWAKE

    def state(self) -> dict:
        return self.load()

    # ---------- 判断 ----------

    def answer(self, now: datetime) -> SleepAnswer:
        """他让她睡，她答不答应：晚上十一点后、或已经是凌晨，就答应。"""
        if now.hour >= self.accept_after or now.hour < 4:
            return SleepAnswer.ACCEPT
        return SleepAnswer.TOO_EARLY

    def is_asleep(self, now: datetime) -> bool:
        state = self.load()
        raw = str(state.get("phase") or "")
        if raw not in (SleepPhase.ASLEEP.value, SleepPhase.NIGHT_WAKE.value):
            return False
        wake_day = str(state.get("wake_day") or "")
        wake_at = str(state.get("wake_at") or "")
        if not wake_day or _hhmm(wake_at) < 0:
            return True
        today = now.date().isoformat()
        if today < wake_day:
            return True
        if today > wake_day:
            return False
        return (now.hour * 60 + now.minute) < _hhmm(wake_at)

    def wake_at(self, day: str) -> str:
        return "%02d:00" % self.wake_hour

    def go_to_sleep(self, now: datetime) -> dict:
        """答应去睡：状态落盘，醒来时间定在明天 ``wake_hour``。"""
        from datetime import timedelta

        today = now.date()
        wake_day = today if now.hour < self.wake_hour else (today + timedelta(days=1))
        state = {
            "phase": SleepPhase.ASLEEP.value,
            "day": today.isoformat(),
            "since": now.strftime("%H:%M"),
            "wake_day": wake_day.isoformat(),
            "wake_at": self.wake_at(""),
            "reason": "",
            "reason_at": "",
        }
        self.save(state)
        return state

    def wake_up(self, now: datetime, woke_early: bool = False) -> dict:
        state = self.load()
        state.update({
            "phase": SleepPhase.AWAKE.value,
            "woke_at": now.strftime("%H:%M"),
            "woke_day": now.date().isoformat(),
            "woke_early": bool(woke_early),
        })
        self.save(state)
        return state

    def maybe_night_wake(self, now: datetime, rng: random.Random | None = None) -> WakeReason | None:
        """睡着时半夜可能醒一次：返回原因；今晚已经醒过就不再醒。"""
        if not self.is_asleep(now):
            return None
        if not (0 <= now.hour < 6):
            return None
        state = self.load()
        if str(state.get("reason") or ""):
            return None
        chooser = rng or random.Random()
        if chooser.random() > self.night_wake_chance:
            return None
        reason = pick_reason(chooser)
        state.update({
            "phase": SleepPhase.NIGHT_WAKE.value,
            "reason": reason.value,
            "reason_at": now.strftime("%H:%M"),
        })
        self.save(state)
        return reason

    def back_to_sleep(self, now: datetime) -> dict:
        state = self.load()
        state.update({"phase": SleepPhase.ASLEEP.value,
                      "back_at": now.strftime("%H:%M")})
        self.save(state)
        return state

    def today_woke_reason(self) -> WakeReason | None:
        state = self.load()
        try:
            return WakeReason(str(state.get("reason") or ""))
        except ValueError:
            return None
