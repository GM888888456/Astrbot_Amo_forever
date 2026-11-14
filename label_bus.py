# -*- coding: utf-8 -*-
"""结构化标签（执行文档 5.2 / 5.3）。

本能模式下，事实只以标签出现：

    [Body: Hunger=93, Thirst=80, Satiety=7, Hydration=20, Last_Meal=None, ts=1763041233]
    [World: My_City=东莞, Activity=休息, Place=家, Partner_Location=温州, Partner_Away=true]
    [Wallet: Cash=50, Savings=0, Total=50, Debt=200]
    [Market: NVDA=Up, Pnl=+120, Equity=10000, Cash=3000, Positions=2, Risk_Tolerance=100]

规则（和 5.2 / 9.1 的契约测试对齐）：

* 空标签**不发布**：宁可不写，也不给模型一个空壳去瞎编；
* 数值按表裁剪（身体 0-100）；字符串去掉 ``[``/``]``/换行并截断；
* 每条标签自带 ``ts``；过期由 :meth:`LabelBus.render` 丢弃或降权；
* 标签只写事实，不写台词。
"""

from __future__ import annotations

import re
import time

try:
    from .baseline import Baseline
except Exception:  # pragma: no cover - 终端里按文件加载
    from baseline import Baseline  # type: ignore

NUMERIC_RANGES = {
    "Hunger": (0, 100),
    "Thirst": (0, 100),
    "Satiety": (0, 100),
    "Hydration": (0, 100),
    "Energy": (0, 100),
    "Risk_Tolerance": (0, 100),
    "Positions": (0, 999),
    "Max_Positions": (0, 999),
}

MAX_VALUE_LEN = 80

TAG_RE = re.compile(r"\[([A-Za-z_][A-Za-z0-9_]*):\s*([^\[\]\n]*)\]")


def _clamp(key: str, value) -> float:
    low, high = NUMERIC_RANGES[key]
    return max(low, min(high, value))


def format_value(key: str, value) -> str:
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        number = _clamp(key, value) if key in NUMERIC_RANGES else value
        if key == "Pnl" and number > 0:
            return "+%g" % number
        if isinstance(number, float):
            text = ("%.2f" % number).rstrip("0").rstrip(".")
            return text or "0"
        return str(number)
    text = str(value)
    for char in ("\r", "\n", "[", "]", "\x00"):
        text = text.replace(char, " ")
    text = " ".join(text.split())
    if len(text) > MAX_VALUE_LEN:
        text = text[:MAX_VALUE_LEN]
    return text or "None"


def format_tag(name: str, fields: dict, ts=None) -> str:
    parts = []
    for key, value in (fields or {}).items():
        if key == "ts":
            continue
        parts.append("%s=%s" % (key, format_value(key, value)))
    if ts:
        parts.append("ts=%d" % int(ts))
    return "[%s: %s]" % (name, ", ".join(parts))


def parse_tags(text: str) -> list:
    """把文本里的标签拆出来，给联调/测试看。"""
    found = []
    for match in TAG_RE.finditer(str(text or "")):
        fields = {}
        for part in match.group(2).split(","):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            key = key.strip()
            if key:
                fields[key] = value.strip()
        found.append((match.group(1), fields))
    return found


def strip_tags(text: str) -> str:
    """切模式时用：把结构化标签从文本里清掉，避免长句和标签混排。"""
    return TAG_RE.sub("", str(text or "")).strip()


class LabelBus:
    """按插件上报的事实攒标签；读的时候按基线判时效。"""

    def __init__(self, baseline=None, clock=time.time):
        self.baseline = baseline or Baseline()
        self.clock = clock
        self._labels = {}

    def publish(self, name: str, fields: dict, ts=None, now=None) -> bool:
        if not name:
            return False
        existing = (self._labels.get(name) or {}).get("fields") or {}
        clean = {}
        for key, value in (fields or {}).items():
            if key == "ts" or value == "":
                continue
            # None = 这次没拿到（插件断连/没上报）。已有有效值就沿用，别拿空值覆盖；
            # 首次出现时照实记 None（例如 Last_Meal=None 表示今天还没吃）。
            if value is None and existing.get(key) is not None:
                continue
            clean[key] = value
        if not clean:
            if existing:
                return True          # 这次什么都没拿到，保留之前的事实
            self._labels.pop(name, None)
            return False
        stamp = ts if ts is not None else (now if now is not None else self.clock())
        self._labels[name] = {"fields": clean, "ts": float(stamp)}
        return True

    def get(self, name: str, now=None):
        record = self._labels.get(name)
        if not record:
            return None
        moment = now if now is not None else self.clock()
        age = float(moment) - float(record["ts"])
        if self.baseline.label_state(age) == "drop":
            return None
        return {"name": name, "fields": dict(record["fields"]), "ts": record["ts"], "age": age}

    def render(self, names=None, now=None) -> str:
        lines = []
        for name in (names if names is not None else list(self._labels)):
            record = self.get(name, now)
            if record is None:
                continue
            lines.append(format_tag(record["name"], record["fields"], record["ts"]))
        return "\n".join(lines)

    def states(self, now=None) -> list:
        rows = []
        for name, record in self._labels.items():
            moment = now if now is not None else self.clock()
            age = float(moment) - float(record["ts"])
            rows.append({"name": name, "ts": record["ts"], "age": age,
                         "state": self.baseline.label_state(age)})
        return rows

    def clear(self, name: str = "") -> None:
        if name:
            self._labels.pop(name, None)
        else:
            self._labels.clear()
