# -*- coding: utf-8 -*-
"""全局基线（执行文档第四节）。

基线只做**加权**，不做硬阻断：

* 同一笔花钱，私聊权重 1.0、群聊 0.3；
* 群聊里诉苦类表达权重 0.4（私聊 1.0）；
* 标签有时效：``label_stale_seconds`` 之后降权，``label_drop_seconds`` 之后丢弃。

硬规则（群聊不提钱、生图内容边界、金融仓位校验）仍然在各自的执行点，
基线只是把「该不该做」的分数往下压一压。
"""

from __future__ import annotations

DEFAULTS = {
    "baseline_private_money": 1.0,
    "baseline_group_money": 0.3,
    "baseline_group_complain": 0.4,
    "baseline_private_complain": 1.0,
    "label_stale_seconds": 900,
    "label_drop_seconds": 1800,
    "auto_approve_types": ("speech_synth", "image_view"),
    "high_risk_types": ("medical_treat", "stock_trade", "market_buy", "food_buy"),
    "approve_threshold": 0.5,
    "defer_group_money": True,
}

COMPLAIN_CATEGORIES = ("complain", "诉苦")


def _float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _int(value, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on", "开启", "开"):
        return True
    if text in ("0", "false", "no", "off", "关闭", "关", ""):
        return False
    return default


def as_list(value) -> list:
    """配置里可能是 list，也可能是一行逗号分隔的字符串。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).replace("，", ",").replace("\n", ",")
    return [part.strip() for part in text.split(",") if part.strip()]


class Baseline:
    """一份基线配置，外加几个纯函数判定。"""

    def __init__(self, config=None):
        values = dict(DEFAULTS)
        if config is not None:
            for key in DEFAULTS:
                try:
                    value = config.get(key)
                except Exception:
                    value = None
                if value is not None:
                    values[key] = value
        self.private_money = max(0.0, _float(values["baseline_private_money"], 1.0))
        self.group_money = max(0.0, _float(values["baseline_group_money"], 0.3))
        self.private_complain = max(0.0, _float(values["baseline_private_complain"], 1.0))
        self.group_complain = max(0.0, _float(values["baseline_group_complain"], 0.4))
        self.stale_seconds = max(0, _int(values["label_stale_seconds"], 900))
        self.drop_seconds = max(self.stale_seconds, _int(values["label_drop_seconds"], 1800))
        self.auto_approve = tuple(as_list(values["auto_approve_types"]))
        self.high_risk = tuple(as_list(values["high_risk_types"]))
        self.threshold = min(1.0, max(0.0, _float(values["approve_threshold"], 0.5)))
        self.defer_group_money = _bool(values["defer_group_money"], True)

    # ------------------------------------------------------------ 加权

    def multiplier(self, scene: str = "private", cost=0.0, category: str = "") -> float:
        """这件事在这个场景里的权重。只压分，不判生死。"""
        group = str(scene or "").strip().lower() == "group"
        value = 1.0
        try:
            money = float(cost or 0) > 0
        except (TypeError, ValueError):
            money = False
        if money:
            value *= self.group_money if group else self.private_money
        if str(category or "").strip() in COMPLAIN_CATEGORIES:
            value *= self.group_complain if group else self.private_complain
        return min(2.0, max(0.0, value))

    def needs_approve(self, event_type: str) -> bool:
        """默认要不要审批：轻动作免审批，高风险必审，其余按审。"""
        name = str(event_type or "").strip()
        if name in self.auto_approve:
            return False
        if name in self.high_risk:
            return True
        return True

    # ------------------------------------------------------------ 标签时效

    def label_state(self, age_seconds) -> str:
        """fresh / stale / drop。"""
        try:
            age = float(age_seconds)
        except (TypeError, ValueError):
            return "stale"
        if age < 0:
            return "fresh"
        if age >= self.drop_seconds:
            return "drop"
        if self.stale_seconds and age >= self.stale_seconds:
            return "stale"
        return "fresh"

    def label_weight(self, age_seconds) -> float:
        return {"fresh": 1.0, "stale": 0.5, "drop": 0.0}[self.label_state(age_seconds)]

    def to_dict(self) -> dict:
        return {
            "baseline_private_money": self.private_money,
            "baseline_group_money": self.group_money,
            "baseline_private_complain": self.private_complain,
            "baseline_group_complain": self.group_complain,
            "label_stale_seconds": self.stale_seconds,
            "label_drop_seconds": self.drop_seconds,
            "auto_approve_types": list(self.auto_approve),
            "high_risk_types": list(self.high_risk),
            "approve_threshold": self.threshold,
            "defer_group_money": self.defer_group_money,
        }
