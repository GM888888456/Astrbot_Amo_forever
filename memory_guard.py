# -*- coding: utf-8 -*-
"""记忆写入前的守门人：去重、把相对时间换成绝对日期、冲突只记日志不拦。

为什么要有它：模型编的、重复的、时间含糊的记忆一旦入库，后面召回时会被当成
"她真的经历过"，表现出来就是幻视。这里只做三件**不改变语义、不额外调模型**的事：

1. **去重**：同一个人 10 分钟内写同样的内容，只留一条；
2. **绝对时间**：「今天/昨天/明天」换成具体日期，避免以后读起来串台
   （记忆是给未来的她看的，相对时间放久了就是错的）；
3. **冲突留痕**：同一天里出现互相矛盾的地点时写 warning 日志，
   方便我们知道"她在编"，但**不阻断写入**（阻断会丢真事）。
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timedelta

#: 相对时间 → 偏移天数
_RELATIVE_DAYS = {
    "大前天": -3,
    "前天": -2,
    "昨天夜里": -1,
    "昨晚": -1,
    "昨天": -1,
    "今天": 0,
    "今早": 0,
    "今晚": 0,
    "明天": 1,
    "明早": 1,
    "明晚": 1,
    "后天": 2,
}

#: 去重窗口（秒）
DEDUPE_WINDOW = 600


def absolutize(text: str, now: datetime) -> str:
    """把相对时间换成绝对日期：『昨天』→『11-12』。"""
    body = str(text or "")
    if not body:
        return body
    for word in sorted(_RELATIVE_DAYS, key=len, reverse=True):
        if word not in body:
            continue
        day = (now + timedelta(days=_RELATIVE_DAYS[word])).strftime("%m-%d")
        body = body.replace(word, day)
    return body


def fingerprint(text: str) -> str:
    return hashlib.sha1(str(text or "").strip().encode("utf-8")).hexdigest()[:16]


def is_duplicate(db, uid: str, text: str, now_ts: float, window: int = DEDUPE_WINDOW) -> bool:
    """同一个 uid 在窗口内写过同样的内容吗？（kv 里记指纹和时间）"""
    key = "mem_write:%s:%s" % (str(uid or ""), fingerprint(str(uid or "") + text))
    try:
        row = db.kv_get(key, {}) or {}
    except Exception:
        return False
    if not isinstance(row, dict):
        return False
    try:
        last = float(row.get("ts") or 0)
    except (TypeError, ValueError):
        last = 0.0
    if last and now_ts - last <= max(60, int(window)):
        return True
    return False


def remember_write(db, uid: str, text: str, now_ts: float) -> None:
    key = "mem_write:%s:%s" % (str(uid or ""), fingerprint(str(uid or "") + text))
    try:
        db.kv_set(key, {"ts": now_ts})
    except Exception:
        pass


def prepare(db, uid: str, text: str, now: datetime, now_ts: float | None = None):
    """返回 (是否允许写入, 处理后的文本, 原因)。"""
    body = str(text or "").strip()
    if not body:
        return False, "", "empty"
    stamp = float(now_ts if now_ts is not None else time.time())
    if is_duplicate(db, uid, body, stamp):
        return False, body, "duplicate"
    fixed = absolutize(body, now)
    # 这里**不**记账：真正写进记忆库以后才调 commit()，
    # 否则写失败后 10 分钟内的重试会被自己的去重挡死。
    return True, fixed, "ok"


def commit(db, uid: str, text: str, now, now_ts: float | None = None) -> str:
    """写入成功后登记（用于去重 + 冲突提示）。返回冲突提示，没有就空串。"""
    stamp = float(now_ts if now_ts is not None else time.time())
    remember_write(db, uid, text, stamp)
    return conflict_hint(db, uid, text, now)


#: 只用来做冲突提示的地点词（宁可少报，不要误报）
_PLACE_WORDS = ("酒店", "景区", "公司", "咖啡店", "家里", "家", "商场", "超市", "机场", "车站")


def conflict_hint(db, uid: str, text: str, now: datetime) -> str:
    """同一天里地点互相矛盾时给一句提示（只用于日志，不拦截）。"""
    try:
        day = now.strftime("%Y-%m-%d")
        seen = db.kv_get("mem_places:%s:%s" % (uid, day), []) or []
    except Exception:
        return ""
    if not isinstance(seen, list):
        seen = []
    match = None
    for word in _PLACE_WORDS:
        if word in str(text or ""):
            match = word
            break
    if match is None:
        return ""
    others = [word for word in seen if word != match]
    try:
        db.kv_set("mem_places:%s:%s" % (uid, day), (seen + [match])[-6:])
    except Exception:
        pass
    if others:
        return "地点与今天记过的「%s」不一致" % "、".join(sorted(set(others))[:3])
    return ""
