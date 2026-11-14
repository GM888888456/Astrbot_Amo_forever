# -*- coding: utf-8 -*-
"""事件总线（执行文档第三节）。

插件只能**提案**，执行权在终端：

```text
插件组装提案 → 终端校验 / 去重 → 基线加权 → 心流打分 → allow | deny | defer
  → 终端下发指令 → 插件自己执行 → 回执 → 终端归档给记忆
```

这一层只做「接、判、记」：

* 不碰账本（钱由金融在收到 allow 后自己扣）；
* 不碰心流数值（分数由 ``scorer`` 回调给）；
* 不替插件执行（下发与执行都在各自插件里）。
"""

from __future__ import annotations

import time
from collections import deque

try:
    from .baseline import Baseline
except Exception:  # pragma: no cover - 终端里按文件加载
    from baseline import Baseline  # type: ignore

REQUIRED = ("event_id", "event_type", "source", "scene")
SCENES = ("private", "group")
RECEIPT_STATUS = ("success", "fail")
CONFLICT = "idempotency_conflict"


class ProposalError(ValueError):
    """提案字段不合法。"""


def normalize_proposal(raw, now=None) -> dict:
    if not isinstance(raw, dict):
        raise ProposalError("提案必须是 dict")
    missing = [key for key in REQUIRED if not str(raw.get(key) or "").strip()]
    if missing:
        raise ProposalError("缺字段：%s" % "、".join(missing))
    event_id = str(raw["event_id"]).strip()
    if len(event_id) > 128:
        raise ProposalError("event_id 太长（>128）")
    scene = str(raw["scene"]).strip().lower()
    if scene not in SCENES:
        raise ProposalError("scene 只能是 private / group")
    payload = raw.get("payload") or {}
    if not isinstance(payload, dict):
        raise ProposalError("payload 必须是 dict")
    try:
        cost = float(payload.get("cost") or 0)
    except (TypeError, ValueError):
        raise ProposalError("payload.cost 必须是数字")
    if cost < 0:
        raise ProposalError("payload.cost 不能为负")
    try:
        ts = float(raw.get("ts")) if raw.get("ts") is not None else float(now or time.time())
    except (TypeError, ValueError):
        ts = float(now or time.time())
    need = raw.get("need_approve")
    detail = payload.get("detail")
    return {
        "event_id": event_id,
        "event_type": str(raw["event_type"]).strip(),
        "source": str(raw["source"]).strip(),
        "scene": scene,
        "umo": str(raw.get("umo") or ""),
        "payload": {
            "cost": round(max(0.0, cost), 2),
            "reason": str(payload.get("reason") or "").strip(),
            "detail": detail if isinstance(detail, dict) else {},
        },
        "need_approve": None if need is None else bool(need),
        "ts": ts,
    }


def _decision(event_id, approved, kind, reason, score=0.0, fallback="") -> dict:
    return {
        "event_id": event_id,
        "approved": bool(approved),
        "decision": kind,
        "reason": reason,
        "score": round(float(score), 3),
        "fallback": fallback,
    }


class EventBus:
    """提案 → 审批 → 回执。一个事件 id 只算一次账。"""

    def __init__(self, baseline=None, *, scorer=None, clock=time.time, retry_after=60.0):
        self.baseline = baseline or Baseline()
        self.scorer = scorer
        self.clock = clock
        self.retry_after = max(0.0, float(retry_after))
        self._events = {}
        self._decisions = deque(maxlen=200)
        self._receipts = deque(maxlen=200)
        self._stats = {
            "proposals": 0, "allow": 0, "deny": 0, "defer": 0,
            "duplicates": 0, "conflicts": 0, "receipts": 0, "orphan_receipts": 0,
        }

    # ------------------------------------------------------------ 提案

    def submit(self, raw) -> dict:
        self._stats["proposals"] += 1
        try:
            proposal = normalize_proposal(raw, now=self.clock())
        except ProposalError as exc:
            result = _decision(
                str((raw or {}).get("event_id") or "") if isinstance(raw, dict) else "",
                False, "deny", "提案字段不合法：%s" % exc, 0.0)
            self._remember(result)
            return result

        record = self._events.get(proposal["event_id"])
        if record is not None:
            if self._retry_ready(record):
                self._events.pop(proposal["event_id"], None)  # 失败不长期占用幂等
            else:
                return self._replay(proposal, record)
        return self._evaluate(proposal)

    def _evaluate(self, proposal: dict) -> dict:
        event_id = proposal["event_id"]
        cost = proposal["payload"]["cost"]
        need = proposal["need_approve"]
        if need is None:
            need = self.baseline.needs_approve(proposal["event_type"])

        if not need:
            result = _decision(event_id, True, "allow", "轻动作免审批", 1.0)
        elif proposal["scene"] == "group" and cost > 0 and self.baseline.defer_group_money:
            result = _decision(event_id, False, "defer", "群聊资金类行为暂缓", 0.0, "晚点再说")
        else:
            score = self._score(proposal)
            weighted = score * self.baseline.multiplier(
                proposal["scene"], cost, proposal["event_type"])
            if weighted >= self.baseline.threshold:
                result = _decision(event_id, True, "allow", "心流判定通过", weighted)
            else:
                result = _decision(event_id, False, "deny", "心流判定不通过", weighted)

        self._events[event_id] = {
            "proposal": proposal,
            "status": "pending" if result["approved"] else result["decision"],
            "decision": result["decision"],
            "ts": self.clock(),
            "amount": cost,
            "reason": proposal["payload"]["reason"],
        }
        self._stats[result["decision"]] = self._stats.get(result["decision"], 0) + 1
        self._remember(result)
        return result

    def _score(self, proposal: dict) -> float:
        if self.scorer is None:
            return 1.0
        try:
            value = float(self.scorer(proposal))
        except Exception:
            return 0.0
        return min(1.0, max(0.0, value))

    def _retry_ready(self, record: dict) -> bool:
        if record.get("status") != "failed":
            return False
        return (self.clock() - float(record.get("ts") or 0)) >= self.retry_after

    def _replay(self, proposal: dict, record: dict) -> dict:
        event_id = proposal["event_id"]
        amount = proposal["payload"]["cost"]
        reason = proposal["payload"]["reason"]
        changed = (abs(float(record.get("amount") or 0) - amount) > 0.005
                   or str(record.get("reason") or "") != reason)
        if changed:
            self._stats["conflicts"] += 1
            result = _decision(event_id, False, "deny", CONFLICT, 0.0)
        elif record.get("status") == "failed":
            result = _decision(event_id, False, "defer", "上次失败，稍后可重试", 0.0)
        else:
            self._stats["duplicates"] += 1
            result = _decision(event_id, False, "deny", "duplicate", 0.0)
        self._remember(result)
        return result

    # ------------------------------------------------------------ 回执

    def receipt(self, raw) -> dict:
        self._stats["receipts"] += 1
        raw = dict(raw or {}) if isinstance(raw, dict) else {}
        event_id = str(raw.get("event_id") or "").strip()
        if not event_id:
            return {"accepted": False, "ack": False, "reason": "回执缺 event_id"}
        status = str(raw.get("status") or "").strip().lower()
        if status not in RECEIPT_STATUS:
            return {"accepted": False, "ack": False, "reason": "status 只能是 success / fail"}

        record = self._events.get(event_id)
        result = {"accepted": True, "ack": True, "event_id": event_id, "status": status}
        if record is None:
            self._stats["orphan_receipts"] += 1
            self._receipts.append({"event_id": event_id, "status": status,
                                   "ts": self.clock(), "orphan": True})
            result["orphan"] = True
            return result

        amount = raw.get("amount")
        try:
            amount_value = None if amount is None else float(amount)
        except (TypeError, ValueError):
            amount_value = None
        if status == "success" and amount_value is not None:
            if abs(amount_value - float(record.get("amount") or 0)) > 0.005:
                self._stats["conflicts"] += 1
                result.update({"accepted": False, "ack": False,
                               "reason": CONFLICT, "conflict": True})
                self._receipts.append({"event_id": event_id, "status": status,
                                       "ts": self.clock(), "conflict": True})
                return result

        record["status"] = "done" if status == "success" else "failed"
        record["ts"] = self.clock()
        record["receipt"] = {"status": status, "code": str(raw.get("code") or ""),
                             "reason": str(raw.get("reason") or ""),
                             "amount": amount_value,
                             "balance": raw.get("balance")}
        self._receipts.append({"event_id": event_id, "status": status,
                               "ts": record["ts"], "code": record["receipt"]["code"]})
        return result

    # ------------------------------------------------------------ 观测

    def _remember(self, result: dict) -> None:
        self._decisions.append(dict(result, ts=self.clock()))

    def stats(self) -> dict:
        return dict(self._stats)

    def events(self) -> dict:
        return {key: dict(value) for key, value in self._events.items()}

    def recent(self, limit: int = 20) -> dict:
        return {"decisions": list(self._decisions)[-limit:],
                "receipts": list(self._receipts)[-limit:]}

    def forget(self, event_id: str) -> bool:
        return self._events.pop(str(event_id or ""), None) is not None
