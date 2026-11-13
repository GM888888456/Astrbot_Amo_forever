# -*- coding: utf-8 -*-
"""心流数值核心：基础生理 + 七情 + 六欲，纯加减法。

设计约束（照做，不要往里塞业务）：

- **只做加减法和边界锁定**，0–100；任何「因为她在上班所以…」这种判断都属于
  调用方（终端/挂载事件），这里一概不收。
- **双核驱动**：
  * 内驱动 = ``decay(minutes)``：饥饿随时间涨、精力随时间掉，七情六欲慢慢回到基线；
  * 外驱动 = ``apply(event, extra=…)``：挂载（金融/医疗/社交）只发事件名，这里照表加减。
- **枚举即接口**：``Physiology`` / ``Emotion`` / ``Desire`` / ``HeartflowEvent``；
  拼错的键会当场报错，而不是静默写进一个没人读的字段。

存 kv ``heartflow``，重启不丢。
"""

from __future__ import annotations

from enum import Enum


class _StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover
        return str(self.value)


class Physiology(_StrEnum):
    HUNGER = "hunger"     # 饱食度：越高越饿
    ENERGY = "energy"     # 精力：越低越累


class Emotion(_StrEnum):
    JOY = "joy"
    ANGER = "anger"
    SADNESS = "sadness"
    FEAR = "fear"
    LOVE = "love"
    DISGUST = "disgust"
    SURPRISE = "surprise"


class Desire(_StrEnum):
    EYE = "desire_eye"        # 眼：想看好看的、想见他
    EAR = "desire_ear"        # 耳：想听好听的、想被哄
    NOSE = "desire_nose"      # 鼻：想闻熟悉的味道
    TONGUE = "desire_tongue"  # 舌：想吃想喝
    BODY = "desire_body"      # 身：想被抱、想亲近
    MIND = "desire_mind"      # 意：想被理解、想有共鸣


class HeartflowEvent(_StrEnum):
    """外部世界发生的事——只有事件名，加减表在本文件底部。"""

    TIME_TICK = "time_tick"             # 内驱动：时间流逝
    CHAT_REPLY = "chat_reply"           # 好好聊了几句
    CHAT_IGNORED = "chat_ignored"       # 被晾着
    CHAT_PRAISE = "chat_praise"         # 被夸
    CHAT_INSULT = "chat_insult"         # 被凶/被骂
    MONEY_GIFT = "money_gift"           # 收到转账/红包
    MONEY_TIP = "money_tip"             # 打赏
    MONEY_TIGHT = "money_tight"         # 余额告急
    PHOTO_SENT = "photo_sent"           # 发了照片
    VOICE_SENT = "voice_sent"           # 说了语音
    MEAL = "meal"                       # 吃饭喝水
    MEDICAL_SICK = "medical_sick"       # 生病
    MEDICAL_TREATED = "medical_treated"  # 治好
    PERIOD_START = "period_start"       # 生理期开始
    PERIOD_END = "period_end"           # 生理期结束
    TRIP_START = "trip_start"           # 出门旅游
    TRIP_END = "trip_end"               # 旅行结束
    WISH_MOVE = "wish_move"             # 她按他说的改了行程


#: 基线：没有外部刺激时，一切都慢慢回到这里
BASELINE = 30.0
LOW = 10.0
HIGH = 70.0

#: 事件 → 加减表（纯数据；正数加、负数减）
EVENT_DELTAS: dict[HeartflowEvent, dict] = {
    HeartflowEvent.CHAT_REPLY: {Emotion.JOY: 6, Desire.EAR: 5, Desire.MIND: 4},
    HeartflowEvent.CHAT_IGNORED: {Emotion.SADNESS: 5, Desire.MIND: 6, Emotion.ANGER: 3},
    HeartflowEvent.CHAT_PRAISE: {Emotion.JOY: 10, Emotion.LOVE: 5, Desire.EAR: 8},
    HeartflowEvent.CHAT_INSULT: {Emotion.ANGER: 12, Emotion.SADNESS: 6, Emotion.LOVE: -6},
    HeartflowEvent.MONEY_GIFT: {Emotion.JOY: 8, Desire.MIND: 4, Emotion.LOVE: 4},
    HeartflowEvent.MONEY_TIP: {Emotion.JOY: 6, Emotion.SURPRISE: 8},
    HeartflowEvent.MONEY_TIGHT: {Emotion.ANGER: 4, Emotion.SADNESS: 6, Desire.MIND: 3},
    HeartflowEvent.PHOTO_SENT: {Emotion.JOY: 4, Desire.EYE: 4},
    HeartflowEvent.VOICE_SENT: {Emotion.JOY: 4, Desire.EAR: 6},
    HeartflowEvent.MEAL: {Physiology.HUNGER: -25, Emotion.JOY: 3, Desire.TONGUE: -15},
    HeartflowEvent.MEDICAL_SICK: {Physiology.ENERGY: -15, Emotion.SADNESS: 6},
    HeartflowEvent.MEDICAL_TREATED: {Physiology.ENERGY: 10, Emotion.JOY: 5},
    HeartflowEvent.PERIOD_START: {Physiology.ENERGY: -20, Emotion.ANGER: 15, Desire.BODY: 20},
    HeartflowEvent.PERIOD_END: {Physiology.ENERGY: 10, Emotion.ANGER: -8},
    HeartflowEvent.TRIP_START: {Emotion.JOY: 12, Desire.EYE: 15},
    HeartflowEvent.TRIP_END: {Emotion.JOY: -4, Physiology.ENERGY: -8},
    HeartflowEvent.WISH_MOVE: {Emotion.JOY: 4, Desire.MIND: 4},
}

#: 事件 → 给模型看的「为什么」（写进最近的经历里）
EVENT_NOTES = {
    HeartflowEvent.CHAT_REPLY: "他刚好好跟我聊了几句",
    HeartflowEvent.CHAT_IGNORED: "他把我晾着没回",
    HeartflowEvent.CHAT_PRAISE: "他夸我了",
    HeartflowEvent.CHAT_INSULT: "他凶我了",
    HeartflowEvent.MONEY_GIFT: "他给我转账了",
    HeartflowEvent.MONEY_TIP: "他打赏我",
    HeartflowEvent.MONEY_TIGHT: "手头有点紧",
    HeartflowEvent.PHOTO_SENT: "我刚给他发了照片",
    HeartflowEvent.VOICE_SENT: "我刚给他发了语音",
    HeartflowEvent.MEAL: "我吃了点东西",
    HeartflowEvent.MEDICAL_SICK: "我生病了",
    HeartflowEvent.MEDICAL_TREATED: "看过病了，好一点",
    HeartflowEvent.PERIOD_START: "生理期来了，肚子疼",
    HeartflowEvent.PERIOD_END: "生理期过去了",
    HeartflowEvent.TRIP_START: "出门玩了",
    HeartflowEvent.TRIP_END: "旅行结束回来了",
    HeartflowEvent.WISH_MOVE: "他说了句话，我改了行程",
}

#: 极端值的内心戏（第一人称）；键是 (维度, 方向)
INNER_VOICE = {
    (Emotion.JOY, "high"): "我现在开心得想原地转圈。",
    (Emotion.ANGER, "high"): "我现在火气压不住，谁惹我谁倒霉。",
    (Emotion.SADNESS, "high"): "我现在心里堵得慌，很想哭。",
    (Emotion.FEAR, "high"): "我现在有点怕，想找个人靠着。",
    (Emotion.LOVE, "high"): "我现在整颗心都黏在他身上。",
    (Emotion.DISGUST, "high"): "我现在烦到不想看见任何人。",
    (Emotion.SURPRISE, "high"): "我现在整个人都懵着，还没缓过来。",
    (Desire.EYE, "high"): "我现在特别想见他，想得眼睛都发酸。",
    (Desire.EAR, "high"): "我现在就想听他的声音，哄我两句也好。",
    (Desire.NOSE, "high"): "我现在很想闻到他身上的味道。",
    (Desire.TONGUE, "high"): "我现在馋得不行，想吃点好的。",
    (Desire.BODY, "high"): "我现在特别想被他抱着，贴一会儿就好。",
    (Desire.MIND, "high"): "我现在很想有人懂我，说说话也好。",
    (Physiology.HUNGER, "high"): "我现在饿得胃里发空。",
    (Physiology.ENERGY, "low"): "我现在累得眼睛都睁不开。",
    (Emotion.JOY, "low"): "我现在提不起劲，什么都不想干。",
    (Emotion.LOVE, "low"): "我现在对他有点冷淡，不想理人。",
}

DIMENSIONS = (tuple(Physiology) + tuple(Emotion) + tuple(Desire))


def clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


class Heartflow:
    """数值仓库 + 纯加减法。调用方负责决定「发生了什么」。"""

    KEY = "heartflow"

    def __init__(self, db):
        self.db = db

    # ---------- 存取 ----------

    def load(self) -> dict:
        try:
            raw = self.db.kv_get(self.KEY, {}) or {}
        except Exception:
            raw = {}
        values = {}
        for dim in DIMENSIONS:
            try:
                value = float((raw or {}).get(dim.value, BASELINE))
            except (TypeError, ValueError):
                value = BASELINE
            values[dim.value] = clamp(value)
        return values

    def save(self, values: dict) -> dict:
        clean = {dim.value: clamp(values.get(dim.value, BASELINE)) for dim in DIMENSIONS}
        try:
            self.db.kv_set(self.KEY, clean)
        except Exception:
            pass
        return clean

    def values(self) -> dict:
        return self.load()

    # ---------- 外驱动 ----------

    LOG_KEY = "heartflow_log"

    def recent(self, limit: int = 6) -> list:
        try:
            rows = self.db.kv_get(self.LOG_KEY, []) or []
        except Exception:
            return []
        return rows[-max(1, int(limit)):] if isinstance(rows, list) else []

    def _remember(self, event, note: str) -> None:
        import time
        rows = self.recent(8)
        rows.append({"ts": time.time(), "event": str(getattr(event, "value", event)),
                     "note": str(note or "")})
        try:
            self.db.kv_set(self.LOG_KEY, rows[-8:])
        except Exception:
            pass

    def apply(self, event, extra: dict | None = None, severity: float | None = None) -> dict:
        """按事件名加减；``severity``（0–10）按比例放大这一次的影响。"""
        values = self.load()
        try:
            key = HeartflowEvent(str(event))
        except ValueError:
            key = None
        if severity is not None:
            try:
                factor = max(0.3, min(1.5, 0.3 + float(severity) / 10.0 * 1.2))
            except (TypeError, ValueError):
                factor = 1.0
        else:
            factor = 1.0
        table = {}
        if key is not None:
            table = {dim: delta * factor for dim, delta in EVENT_DELTAS.get(key, {}).items()}
            note = EVENT_NOTES.get(key, "")
            if key is HeartflowEvent.PERIOD_START and severity is not None:
                note = "生理期来了，痛经 %d 级" % int(severity)
            self._remember(key, note)
        for dim, delta in list(table.items()) + list((extra or {}).items()):
            name = dim.value if isinstance(dim, Enum) else str(dim)
            if name not in values:
                continue
            try:
                values[name] = clamp(values[name] + float(delta))
            except (TypeError, ValueError):
                continue
        return self.save(values)

    # ---------- 内驱动 ----------

    def decay(self, minutes: float) -> dict:
        """时间流逝：饿一点、累一点，其余慢慢回基线（每小时 8%）。"""
        try:
            span = max(0.0, float(minutes))
        except (TypeError, ValueError):
            return self.load()
        if span <= 0:
            return self.load()
        hours = span / 60.0
        values = self.load()
        values[Physiology.HUNGER.value] = clamp(values[Physiology.HUNGER.value] + 0.6 * span)
        values[Physiology.ENERGY.value] = clamp(values[Physiology.ENERGY.value] - 0.35 * span)
        drift = min(0.5, 0.08 * hours)
        for dim in tuple(Emotion) + tuple(Desire):
            name = dim.value
            values[name] = clamp(values[name] + (BASELINE - values[name]) * drift)
        return self.save(values)

    # ---------- Prompt ----------

    def get_prompt_summary(self) -> str:
        """给模型看的一段：常数值 + 极端值的内心戏。"""
        values = self.load()
        parts = []
        parts.append("七情：%s" % "、".join(
            "%s%.0f" % (name_cn(item), values[item.value]) for item in Emotion))
        lines = []
        for dim in DIMENSIONS:
            value = values[dim.value]
            if value > HIGH:
                lines.append(INNER_VOICE.get((dim, "high")) or ("我现在%s很强。" % name_cn(dim)))
            elif value < LOW:
                lines.append(INNER_VOICE.get((dim, "low")) or ("我现在%s几乎没有了。" % name_cn(dim)))
        if lines:
            parts.append("（内心：%s）" % " ".join(lines[:4]))
        reasons = [row.get("note") for row in self.recent(3) if str(row.get("note") or "").strip()]
        if reasons:
            parts.append("（最近发生：%s。情绪就是这么来的，别装作没这回事。）"
                         % "；".join(reasons[-3:]))
        return "\n".join(parts)


_NAMES = {
    Physiology.HUNGER: "饿", Physiology.ENERGY: "精力",
    Emotion.JOY: "喜", Emotion.ANGER: "怒", Emotion.SADNESS: "哀", Emotion.FEAR: "惧",
    Emotion.LOVE: "爱", Emotion.DISGUST: "恶", Emotion.SURPRISE: "惊",
    Desire.EYE: "眼", Desire.EAR: "耳", Desire.NOSE: "鼻", Desire.TONGUE: "舌",
    Desire.BODY: "身", Desire.MIND: "意",
}


def name_cn(dim) -> str:
    return _NAMES.get(dim, str(getattr(dim, "value", dim)))
