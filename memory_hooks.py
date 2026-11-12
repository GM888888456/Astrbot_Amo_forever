# -*- coding: utf-8 -*-
"""记忆能力层：陪伴只做判定，数据全部交给挂载插件。

设计原则
--------
- **能力声明**：每个 Provider 用 ``caps`` 声明自己能干什么，陪伴按能力调度，
  不再靠「猜方法名、试一串签名」。
- **不缓存插件实例**：AstrBot reload 之后旧实例会变僵尸，每次按名字重新取。
- **不裸读别人的库**：只走对方公开的接口；对方明确没有 Python 接口时如实报告，
  绝不直接连它的 sqlite。
- **数据只落地一处**：聊天、画像、记忆都写进挂载的记忆终端；陪伴本地只留一个
  进程内环形缓冲（``ChatBuffer``），不落盘，重启后从终端补。

对外只有四样东西：``ChatBuffer`` / ``MemoryProvider`` / ``MemoryHub`` / 三个渲染函数。
"""

from __future__ import annotations

import asyncio
import re
import threading
import time

CAP_REMEMBER = "remember"
CAP_RECALL = "recall"
CAP_PROFILE = "profile"
CAP_RECENT = "recent"


def _clean(text, limit=500):
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value[:limit]


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- 渲染

def render_profile_line(profile):
    """把画像压成一行，例如：小冉（相恋）· 喜欢无糖茶。"""
    if not isinstance(profile, dict):
        return ""
    name = str(profile.get("name") or "").strip()
    alias = str(profile.get("alias") or "").strip()
    relation = str(profile.get("relation") or "").strip()
    remark = str(profile.get("remark") or "").strip()
    if not any((name, alias, relation, remark)):
        return ""
    head = name or alias
    if name and alias and alias != name:
        head = name + "（" + alias + "）"
    parts = [head] if head else []
    if relation:
        parts.append(relation)
    line = " · ".join(parts)
    if remark:
        line = (line + " · " if line else "") + remark
    return line


def render_memory_block(items, limit=6):
    """把记忆条目渲染成提示词片段，带人名：``- 小冉：喜欢无糖茶（重要）``。"""
    lines = []
    for item in list(items or [])[:limit]:
        if not isinstance(item, dict):
            continue
        content = _clean(item.get("content"), 300)
        if len(content) < 2:
            continue
        who = _clean(item.get("name"), 24)
        tier = int(_number(item.get("tier"), 0))
        label = "珍贵" if tier >= 2 else ("重要" if tier == 1 else "")
        line = "- " + (who + "：" if who else "") + content
        if label:
            line += "（" + label + "）"
        lines.append(line)
    return "\n".join(lines)


def render_recent_block(rows, self_name="你", limit=8):
    """把近聊渲染成对话记录，例如：``他：今天加班``。"""
    lines = []
    for row in list(rows or [])[-limit:]:
        if not isinstance(row, dict):
            continue
        content = _clean(row.get("content"), 120)
        if not content:
            continue
        role = str(row.get("role"))
        if role == "summary":
            lines.append("【摘要】" + content)
            continue
        if role == "bot":
            who = self_name
        else:
            who = _clean(row.get("name"), 16) or "他"
        lines.append(who + "：" + content)
    return "\n".join(lines)


# ---------------------------------------------------------------- 缓冲

_WARN_AT = {}


def _warn_once(logger, key, message, gap=600.0):
    """同一条能力缺失只在 10 分钟内提示一次，避免每轮消息都刷日志。"""
    now = time.time()
    if now - _WARN_AT.get(key, 0.0) < gap:
        return
    _WARN_AT[key] = now
    try:
        logger.warning(message)
    except Exception:
        pass


class ChatBuffer:
    """每个会话一个环形缓冲：只在内存里，不落盘。"""

    def __init__(self, size=48):
        self.size = max(8, int(size or 48))
        self._lock = threading.RLock()
        self._sessions = {}

    def add(self, umo, uid, name, role, content, created_at=None):
        umo = str(umo or "")
        text = _clean(content, 4000)
        if not umo or not text:
            return
        row = {
            "umo": umo,
            "uid": str(uid or ""),
            "name": str(name or ""),
            "role": str(role) if str(role) in ("bot", "summary") else "user",
            "content": text,
            "created_at": _number(created_at, time.time()),
        }
        with self._lock:
            rows = self._sessions.get(umo)
            if rows is None:
                rows = []
                self._sessions[umo] = rows
            rows.append(row)
            if len(rows) > self.size:
                del rows[:len(rows) - self.size]

    def recent(self, umo, limit=10):
        size = max(1, int(limit or 10))
        with self._lock:
            rows = list(self._sessions.get(str(umo or ""), []))
        return rows[-size:]

    def by_uid(self, uid, limit=20):
        uid = str(uid or "")
        size = max(1, int(limit or 20))
        merged = []
        with self._lock:
            for rows in self._sessions.values():
                merged.extend([row for row in rows if row["uid"] == uid])
        merged.sort(key=lambda item: _number(item.get("created_at"), 0))
        return merged[-size:]

    def hydrate(self, umo, rows):
        """用终端里的历史填缓冲；已有内容时只补更早的，不覆盖。"""
        umo = str(umo or "")
        if not umo:
            return 0
        incoming = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            text = _clean(row.get("content"), 4000)
            if not text:
                continue
            incoming.append({
                "umo": umo,
                "uid": str(row.get("uid") or ""),
                "name": str(row.get("name") or ""),
                "role": str(row.get("role")) if str(row.get("role")) in ("bot", "summary") else "user",
                "content": text,
                "created_at": _number(row.get("created_at"), 0),
            })
        if not incoming:
            return 0
        incoming.sort(key=lambda item: item["created_at"])
        with self._lock:
            current = self._sessions.get(umo, [])
            seen = {(row["role"], row["content"], int(row["created_at"])) for row in current}
            merged = [row for row in incoming if (row["role"], row["content"], int(row["created_at"])) not in seen]
            merged.extend(current)
            merged.sort(key=lambda item: item["created_at"])
            if len(merged) > self.size:
                merged = merged[-self.size:]
            self._sessions[umo] = merged
        return len(merged)

    def clear(self, umo=None):
        with self._lock:
            if umo is None:
                self._sessions.clear()
            else:
                self._sessions.pop(str(umo), None)

# ---------------------------------------------------------------- Provider

class MemoryProvider:
    """能力声明式提供者。子类只实现自己声明的能力，其余保持默认。"""

    name = "provider"
    priority = 50
    caps = frozenset()

    def __init__(self, runtime):
        self.rt = runtime

    # -- 探测 --
    def available(self):
        return False

    def describe(self):
        return {
            "name": self.name,
            "available": bool(self.available()),
            "caps": sorted(self.caps),
            "priority": self.priority,
        }

    # -- 能力 --
    async def remember(self, uid, content, kind="fact", importance=0.5, scope="private", group_id=""):
        return {"ok": False, "reason": "unsupported"}

    async def recall(self, uid, query="", limit=6, scope="", group_id="", event=None):
        return []

    async def profile(self, uid):
        return {}

    async def save_profile(self, uid, **fields):
        return {}

    async def recent(self, umo="", uid="", limit=30):
        return []

    def note(self, message):
        try:
            self.rt.logger.info("[记忆] " + str(message))
        except Exception:
            pass


class AmoDataProvider(MemoryProvider):
    """「我想永远陪着你-记忆」：默认终端，能力最全。"""

    name = "amo_data"
    priority = 10
    PLUGIN_NAMES = ("Astr_Amo_data", "astrbot_plugin_amo_data", "AstrAmoData")

    @property
    def caps(self):
        """运行时探测：旧版数据插件缺哪个方法，就不声明哪个能力。"""
        owners = [self._mem(), self._store()]
        found = set()
        for owner in owners:
            if owner is None:
                continue
            if any(callable(getattr(owner, n, None)) for n in ("remember", "add_memory", "save_memory")):
                found.add(CAP_REMEMBER)
            if any(callable(getattr(owner, n, None)) for n in ("recall", "search_memory", "query_memory", "search")):
                found.add(CAP_RECALL)
            if any(callable(getattr(owner, n, None)) for n in ("get_profile", "profile", "save_profile", "set_profile")):
                found.add(CAP_PROFILE)
            if any(callable(getattr(owner, n, None)) for n in ("list_messages", "recent_messages", "messages")):
                found.add(CAP_RECENT)
        return frozenset(found)

    def _plugin(self):
        return self.rt.get_plugin(self.PLUGIN_NAMES)

    def _mem(self):
        plugin = self._plugin()
        return getattr(plugin, "mem", None) if plugin is not None else None

    def _store(self):
        plugin = self._plugin()
        return getattr(plugin, "store", None) if plugin is not None else None

    def available(self):
        return self._mem() is not None or self._store() is not None

    async def _call(self, names):
        """按 (对象, 方法) 顺序找可调用的接口。"""
        for owner in (self._mem(), self._store()):
            if owner is None:
                continue
            for name in names:
                method = getattr(owner, name, None)
                if callable(method):
                    return method
        return None

    async def remember(self, uid, content, kind="fact", importance=0.5, scope="private", group_id=""):
        method = await self._call(("remember", "add_memory", "save_memory"))
        if method is None:
            return {"ok": False, "reason": "no_interface"}
        try:
            result = await method(
                self.rt.bot_id(), str(uid), content,
                kind=kind, importance=importance, scope=scope, group_id=group_id,
            )
        except TypeError:
            try:
                result = await method(self.rt.bot_id(), str(uid), content)
            except Exception as exc:
                return {"ok": False, "reason": str(exc)}
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}
        if isinstance(result, dict):
            return result
        return {"ok": bool(result)}

    async def _call_all(self, names):
        """按 (对象, 方法) 顺序返回所有可调用的候选接口（去重）。"""
        found = []
        seen = set()
        for owner in (self._mem(), self._store()):
            if owner is None:
                continue
            for name in names:
                method = getattr(owner, name, None)
                if not callable(method):
                    continue
                key = (id(owner), name)
                if key in seen:
                    continue
                seen.add(key)
                found.append(method)
        return found

    async def recall(self, uid, query="", limit=6, scope="", group_id="", event=None):
        """先按完整签名调，TypeError 逐级缩短参数；换方法名重试的是「非 TypeError」。

        以前只选中第一个存在的方法名：接口改名/签名变化时第一次 TypeError 后
        就只剩缩短参数重试，其它候选方法（search_memory / query_memory …）永远不会被尝试，
        表现是「她失忆」但日志干净。
        """
        methods = await self._call_all(("recall", "search_memory", "query_memory", "search"))
        if not methods:
            # 以前这里直接返回空：版本不匹配时表现和「本来就没记忆」一模一样
            _warn_once(self.rt.logger, "hub_recall_no_method",
                       "[amo] 记忆终端没有可用的召回接口（recall/search_memory 都没有），这一轮召回为空")
            return []
        last_exc = None
        for method in methods:
            attempts = (
                (self.rt.bot_id(), str(uid), query, limit, scope, group_id),
                (self.rt.bot_id(), str(uid), query, limit),
                (self.rt.bot_id(), str(uid), query),
            )
            for args in attempts:
                try:
                    rows = await method(*args)
                except TypeError as exc:
                    last_exc = exc
                    continue
                except Exception as exc:
                    last_exc = exc
                    break  # 这个方法本身坏了，换下一个候选方法名
                return self.rt.normalize_memories(rows)
        if last_exc is not None:
            self.note("召回失败（已试 %d 个接口）: %s: %s"
                      % (len(methods), type(last_exc).__name__, last_exc))
        return []

    async def profile(self, uid):
        method = await self._call(("get_profile", "profile"))
        if method is None:
            return {}
        try:
            return await method(self.rt.bot_id(), str(uid)) or {}
        except Exception:
            return {}

    async def save_profile(self, uid, **fields):
        method = await self._call(("save_profile", "set_profile", "update_profile"))
        if method is None:
            return {}
        try:
            return await method(self.rt.bot_id(), str(uid), **fields) or {}
        except TypeError:
            try:
                return await method(self.rt.bot_id(), str(uid),
                                    name=fields.get("name"),
                                    relation=fields.get("relation")) or {}
            except Exception:
                return {}
        except Exception:
            return {}

    async def recent(self, umo="", uid="", limit=30):
        method = await self._call(("list_messages", "recent_messages", "messages"))
        if method is None:
            return []
        try:
            if uid and not umo:
                rows = await method(self.rt.bot_id(), "", limit, uid=str(uid))
            else:
                rows = await method(self.rt.bot_id(), str(umo or ""), limit)
        except TypeError:
            try:
                rows = await method(self.rt.bot_id(), str(umo or ""), limit)
            except Exception:
                return []
        except Exception:
            return []
        return [row for row in (rows or []) if isinstance(row, dict)]


class MemoryCompanionProvider(MemoryProvider):
    """memory_companion：只走它自己的 bridge/服务接口；撞到门禁就永久放弃写入。"""

    name = "memory_companion"
    priority = 30
    PLUGIN_NAMES = ("astrbot_plugin_private_companion", "memory_companion")
    RECALL_METHODS = ("search_for_event", "recall_for_event", "search_memory", "recall_memory")
    WRITE_METHODS = ("add_memory", "remember", "save_memory")
    PROFILE_METHODS = ("get_profile", "profile", "save_profile", "set_profile")
    BLOCK_WORDS = ("permission", "forbidden", "denied", "p5", "attest", "unauthorized", "gate")

    def __init__(self, runtime):
        super().__init__(runtime)
        self.write_blocked = False
        self._block_logged = False

    def _target(self):
        plugin = self.rt.get_plugin(self.PLUGIN_NAMES)
        if plugin is None:
            return None
        service = getattr(plugin, "service", None)
        return service if service is not None else plugin

    @property
    def caps(self):
        """按目标插件实际暴露的接口声明能力，老版本缺方法时别误判可写。"""
        target = self._target()
        if target is None:
            return frozenset()
        found = set()
        if any(callable(getattr(target, n, None)) for n in self.WRITE_METHODS):
            found.add(CAP_REMEMBER)
        if any(callable(getattr(target, n, None)) for n in self.RECALL_METHODS):
            found.add(CAP_RECALL)
        if any(callable(getattr(target, n, None)) for n in self.PROFILE_METHODS):
            found.add(CAP_PROFILE)
        return frozenset(found)

    def available(self):
        target = self._target()
        if target is None:
            return False
        for name in self.RECALL_METHODS + self.WRITE_METHODS:
            if callable(getattr(target, name, None)):
                return True
        return False

    def _blocked(self, exc):
        text = (type(exc).__name__ + " " + str(exc)).lower()
        return any(word in text for word in self.BLOCK_WORDS)

    def _mark_blocked(self, exc):
        if self.write_blocked:
            return
        self.write_blocked = True
        if not self._block_logged:
            self._block_logged = True
            self.note("memory_companion 写入被门禁拦截，已停止再试（%s）" % type(exc).__name__)

    @staticmethod
    def _row_uid(row):
        if isinstance(row, dict):
            for key in ("uid", "user_id", "subject_id", "entity_id"):
                value = row.get(key)
                if value:
                    return str(value)
            memory = row.get("memory")
            if isinstance(memory, dict):
                for key in ("uid", "user_id", "subject_id", "entity_id"):
                    if memory.get(key):
                        return str(memory[key])
        else:
            for key in ("uid", "user_id", "subject_id", "entity_id"):
                value = getattr(row, key, None)
                if value:
                    return str(value)
            memory = getattr(row, "memory", None)
            if memory is not None:
                for key in ("uid", "user_id", "subject_id", "entity_id"):
                    value = getattr(memory, key, None)
                    if value:
                        return str(value)
        return ""

    async def _call_recall(self, method, event, uid, query, limit):
        """只接受能带 uid/event 的召回；全都 TypeError 时宁可不召回，也不全库搜。"""
        attempts = []
        if event is not None:
            attempts.extend([
                ((event, query), {"top_k": limit}),
                ((event,), {"query": query, "top_k": limit}),
                ((event,), {"top_k": limit}),
            ])
        attempts.extend([
            ((query,), {"top_k": limit, "user_id": str(uid)}),
            ((query,), {"top_k": limit, "uid": str(uid)}),
            ((query, str(uid), limit), {}),
            ((str(uid), query), {"top_k": limit}),
            ((str(uid), query, limit), {}),
        ])
        for args, kwargs in attempts:
            try:
                result = method(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
                return result
            except TypeError:
                continue
            except Exception:
                return []
        return None

    async def remember(self, uid, content, kind="fact", importance=0.5, scope="private", group_id=""):
        if self.write_blocked:
            return {"ok": False, "reason": "blocked"}
        target = self._target()
        if target is None:
            return {"ok": False, "reason": "no_provider"}
        for name in self.WRITE_METHODS:
            method = getattr(target, name, None)
            if not callable(method):
                continue
            try:
                try:
                    result = method(
                        str(uid), content,
                        scope=str(scope or "private"), group_id=str(group_id or ""),
                    )
                except TypeError:
                    result = method(str(uid), content)
                if asyncio.iscoroutine(result):
                    result = await result
                return {"ok": True, "via": name}
            except TypeError:
                continue
            except Exception as exc:
                if self._blocked(exc):
                    self._mark_blocked(exc)
                return {"ok": False, "reason": str(exc)}
        return {"ok": False, "reason": "no_interface"}

    async def recall(self, uid, query="", limit=6, scope="", group_id="", event=None):
        target = self._target()
        if target is None:
            return []
        for name in self.RECALL_METHODS:
            method = getattr(target, name, None)
            if not callable(method):
                continue
            # 只有 *_for_event 才吃 event；search_memory(query, top_k) 这类
            # 把 event 当 query 传进去不会报 TypeError，会静默返回错结果。
            use_event = event if name in ("search_for_event", "recall_for_event") else None
            rows = await self._call_recall(method, use_event, uid, query, limit)
            if rows is None:
                continue
            filtered = []
            dropped = 0
            saw_uid = False
            for row in rows or []:
                row_uid = self._row_uid(row)
                if row_uid:
                    saw_uid = True
                if row_uid and row_uid != str(uid):
                    dropped += 1
                    continue
                filtered.append(row)
            if dropped:
                self.note("memory_companion 召回丢弃了 %d 条非当前用户记忆" % dropped)
            if rows and not saw_uid and event is None:
                # 没有 uid 字段、又没有 event 上下文，无法证明这批记忆属于谁；
                # 宁可本轮不召回，也不把别人的记忆塞进当前用户 prompt。
                self.note("memory_companion 召回结果没有 uid，已跳过（避免跨用户串记忆）")
                return []
            return self.rt.normalize_memories(filtered)
        _warn_once(
            self.rt.logger, "memcomp_recall_no_uid",
            "[amo] memory_companion 没有可用的按用户召回接口，本轮不召回（避免跨用户串记忆）",
        )
        return []

    async def profile(self, uid):
        target = self._target()
        getter = getattr(target, "get_profile", None) if target is not None else None
        if not callable(getter):
            return {}
        try:
            return await getter(str(uid)) or {}
        except Exception:
            return {}


class LivingMemoryProvider(MemoryProvider):
    """livingmemory：如实报告——没有稳定的 Python 写入接口，所以不提供能力。

    以前那种直接连它的 sqlite 读表的做法已经删掉了：表结构一变就崩，
    而且绕过对方接口本身就是隐患。
    """

    name = "livingmemory"
    priority = 60
    caps = frozenset()
    PLUGIN_NAMES = ("astrbot_plugin_livingmemory", "livingmemory")

    def _plugin(self):
        return self.rt.get_plugin(self.PLUGIN_NAMES)

    def available(self):
        return False

    def describe(self):
        info = super().describe()
        info["note"] = "无稳定 Python 接口，仅由它自己注入记忆"
        return info


# ---------------------------------------------------------------- Hub

class MemoryHub:
    """统一调度：probe 带 TTL、不缓存实例、按能力选 Provider。"""

    PROBE_TTL = 60.0
    EXPLICIT_WORDS = (
        "你还记得", "你还记不记得", "记不记得", "还记得", "上次说", "之前说",
        "我说过", "我跟你说过", "你忘了", "忘了没",
    )
    KEYWORD_WORDS = ("昨天", "那天", "那次", "上回", "以前", "刚才说", "上次")

    def __init__(self, runtime, buffer_size=48):
        self.rt = runtime
        self.buffer = ChatBuffer(buffer_size)
        self.turn = 0
        self._probed_at = 0.0
        self._active = None
        self._wanted = ""
        self._providers = [
            AmoDataProvider(runtime),
            MemoryCompanionProvider(runtime),
            LivingMemoryProvider(runtime),
        ]

    # -- 探测 --
    def refresh(self, force=False):
        now = time.time()
        wanted = str(self.rt.cfg("memory_provider", "auto") or "auto").strip().lower()
        # 缓存只省“重复探测”，不能把旧 provider 焊死：
        # 配置改了（wanted 变化）或插件被停用/重载（available 变 False）时立刻重选，
        # 否则用户必须重载插件或等满 60 秒，表现就是“每次都得刷新”。
        if (
            not force
            and self._active is not None
            and wanted == self._wanted
            and now - self._probed_at < self.PROBE_TTL
            and self._active.available()
        ):
            return self._active
        self._probed_at = now
        self._wanted = wanted
        chosen = None
        if wanted not in ("auto", ""):
            for provider in self._providers:
                if provider.name == wanted and provider.available():
                    chosen = provider
                    break
        if chosen is None:
            for provider in sorted(self._providers, key=lambda item: item.priority):
                if provider.available():
                    chosen = provider
                    break
        self._active = chosen
        return chosen

    @property
    def provider(self):
        return self.refresh()

    @property
    def active_name(self):
        """当前选中 provider 的名字；没选中返回空串。"""
        provider = self.refresh()
        return str(getattr(provider, "name", "") or "")

    def writable(self):
        provider = self.refresh()
        return bool(provider is not None and CAP_REMEMBER in provider.caps)

    def describe(self):
        active = self.refresh()
        return {
            "active": active.name if active is not None else "",
            "providers": [provider.describe() for provider in self._providers],
        }

    def next_turn(self):
        self.turn += 1
        return self.turn

    def should_recall(self, text, private=True):
        """显式 > 关键词 > 私聊每轮 > 群聊抽样。"""
        body = str(text or "")
        if any(word in body for word in self.EXPLICIT_WORDS):
            return True
        if any(word in body for word in self.KEYWORD_WORDS):
            return True
        if private:
            return True
        if 0 < len(body.strip()) <= 3:
            # 短消息（“猫”“茶”“上班”）也要检索一次：
            # 群聊原来只靠关键词/抽样，两三个字永远不会触发，用户会以为“短词查不到记忆”。
            return True
        every = int(_number(self.rt.cfg("recall_sample_every", 8), 8) or 8)
        if every <= 1:
            return True
        return self.turn % every == 0

    # -- 能力转发 --
    async def remember(self, uid, content, kind="fact", importance=0.5, scope="private", group_id=""):
        provider = self.refresh()
        text = _clean(content, 500)
        if provider is None or CAP_REMEMBER not in provider.caps or not text:
            return {"ok": False, "reason": "no_provider"}
        try:
            return await provider.remember(uid, text, kind, importance, scope, group_id) or {"ok": False}
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}

    async def recall(self, uid, query="", limit=6, scope="", group_id="", event=None):
        provider = self.refresh()
        if provider is None or CAP_RECALL not in provider.caps:
            _warn_once(
                self.rt.logger, "hub_provider_no_recall",
                "[amo] 记忆来源 %s 不支持召回（caps=%s），这一轮没有记忆"
                % (getattr(provider, "name", "none"),
                   sorted(getattr(provider, "caps", set())) if provider is not None else "无来源"),
            )
            return []
        try:
            return await provider.recall(uid, query, limit, scope, group_id, event=event) or []
        except Exception as exc:
            self.rt.logger.warning("[amo] 记忆召回失败（%s）: %s" % (type(exc).__name__, exc))
            return []

    async def profile(self, uid):
        provider = self.refresh()
        if provider is None or CAP_PROFILE not in provider.caps:
            return {}
        try:
            return await provider.profile(uid) or {}
        except Exception as exc:
            self.rt.logger.warning("[amo] 记忆画像读取失败（%s）: %s" % (type(exc).__name__, exc))
            return {}

    async def save_profile(self, uid, **fields):
        provider = self.refresh()
        if provider is None or CAP_PROFILE not in provider.caps:
            return {}
        try:
            return await provider.save_profile(uid, **fields) or {}
        except Exception:
            return {}

    async def recent(self, umo="", uid="", limit=30):
        provider = self.refresh()
        rows = []
        if provider is not None and CAP_RECENT in provider.caps:
            try:
                rows = await provider.recent(umo, uid, limit) or []
            except Exception:
                rows = []
        if rows and umo:
            self.buffer.hydrate(umo, rows)
        return rows
