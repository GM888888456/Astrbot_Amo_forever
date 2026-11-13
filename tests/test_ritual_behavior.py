# -*- coding: utf-8 -*-
"""行为测试：把 main.py 里的每日问候方法抠出来，喂假 self 跑。

不依赖 astrbot、不连真库；平台选择、失败回退、跨平台去重、主动消息让路
这些行为都是从这里验证的（纯单测覆盖不到 `_maybe_rituals` 的发送流程）。

    python -m unittest tests.test_ritual_behavior
"""

from __future__ import annotations

import ast
import asyncio
import datetime
import os
import random
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from greet_route import greeting_targets, within_minutes  # noqa: E402

QQ = "大肥鱼:FriendMessage:302578963"
LARK = "lark:FriendMessage:ou_cec66ea605ad17f62632fb044bc5f6ac"
UID = "302578963"
NOW = 1_800_000_000.0  # 固定时间戳
TODAY = "2026-11-10"

WANTED = {
    "_ritual_umos",
    "_recent_greeting",
    "_mark_greeting",
    "_ritual_pending",
    "_ritual_should_send",
    "_ritual_should_send_async",
    "_ritual_lookback_start",
    "_ritual_judge_rows",
    "_ritual_in_window",
    "_maybe_rituals",
}


def load_methods(main_path):
    """把 HumanCorePlugin 里这几个方法抠出来，放同一个全局命名空间里编译。"""
    with open(main_path, encoding="utf-8") as fp:
        source = fp.read()
    tree = ast.parse(source)
    nodes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "HumanCorePlugin":
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in WANTED:
                    nodes.append(item)
    missing = WANTED - {node.name for node in nodes}
    if missing:
        raise AssertionError("main.py 里找不到方法：%s" % sorted(missing))
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {}
    exec(compile(module, main_path, "exec"), namespace)
    return {name: namespace[name] for name in WANTED}


class FakeDB:
    def __init__(self, profiles, channels):
        self.profiles = profiles
        self.store = {"channels:%s" % UID: channels}
        self.logs = []

    def proactive_profiles(self, limit=100):
        return self.profiles

    def kv_get(self, key, default=None):
        return self.store.get(key, default)

    def kv_set(self, key, value):
        self.store[key] = value

    def log_proactive(self, uid, kind, text):
        self.logs.append((uid, kind, text))


class FakeLLM:
    async def gen_proactive(self, umo, profile, snap, kind):
        return {"goodnight": "晚安啦", "morning": "早呀", "lunch": "中午吃啥"}[kind]


class FakeState:
    def snapshot(self):
        return {"activity": {"category": "life"}}


class FakeSelf:
    RITUAL_SPECS = (
        ("goodnight", "ritual_goodnight", "ritual_goodnight_window", "22:00-02:00"),
        ("morning", "ritual_morning", "ritual_morning_window", "06:30-10:00"),
        ("lunch", "ritual_lunch", "ritual_lunch_window", "11:00-13:30"),
    )

    def __init__(self, methods, cfg, profiles=None, channels=None, recents=None):
        for name, func in methods.items():
            setattr(self, name, func.__get__(self, FakeSelf))
        self.cfg_values = dict(cfg)
        if profiles is None:
            profiles = [self.profile()]
        if channels is None:
            channels = {
                "aiocqhttp": {"umo": QQ, "ts": NOW - 10},
                "lark": {"umo": LARK, "ts": NOW - 20},
            }
        self.db = FakeDB(profiles, channels)
        self.recents = recents or {}
        self.state = FakeState()
        self.llm = FakeLLM()
        self.sent = []
        self.marked = []

    @staticmethod
    def profile(relation="相恋", private_umo=QQ):
        return {"uid": UID, "name": "family", "relation": relation, "private_umo": private_umo}

    def cfg(self, key, default=None):
        return self.cfg_values.get(key, default)

    def cfg_bool(self, key, default=False):
        value = self.cfg(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def cfg_int(self, key, default=0):
        try:
            return int(float(self.cfg(key, default)))
        except Exception:
            return default

    def cfg_str(self, key, default=""):
        return str(self.cfg(key, default))

    def _recent(self, umo, limit=10):
        return list(self.recents.get(umo, []))[-limit:]

    def _mark_bot_initiated(self, umo):
        self.marked.append(umo)

    async def _send_to_umo(self, umo, text):
        self.sent.append((umo, text))
        return True


def make_self(methods, **kwargs):
    cfg = {
        "ritual_enabled": True,
        "ritual_goodnight": True,
        "ritual_morning": True,
        "ritual_lunch": True,
        "ritual_goodnight_window": "22:00-02:00",
        "ritual_morning_window": "06:30-10:00",
        "ritual_lunch_window": "11:00-13:30",
        "ritual_skip_recent_minutes": 45,
        "ritual_skip_if_greeted": True,
        "ritual_random_platform": True,
        "ritual_min_gap_minutes": 30,
        "proactive_after_greeting_minutes": 60,
    }
    cfg.update(kwargs.pop("cfg", {}))
    return FakeSelf(methods, cfg, **kwargs)


def in_minute_range(now, start, end):
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end


def minutes_now():
    return 7 * 60  # 07:00 -> 早安时段


def parse_hhmm(value):
    hour, minute = str(value).split(":")
    return int(hour) * 60 + int(minute)


class RitualBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.methods = load_methods(os.path.join(ROOT, "main.py"))

    @staticmethod
    def patch_globals(func):
        func.__globals__.update({
            "to_float": lambda value, default=0.0: float(value or default),
            "now_ts": lambda: NOW,
            "today_str": lambda: TODAY,
            "in_minute_range": in_minute_range,
            "minutes_now": minutes_now,
            "parse_hhmm": parse_hhmm,
            "logger": type("L", (), {"debug": staticmethod(lambda *a, **k: None),
                                     "info": staticmethod(lambda *a, **k: None)})(),
            "_greeting_targets": greeting_targets,
            "_within_minutes": within_minutes,
            "random": random,
            "re": re,
            "datetime": datetime.datetime,
        })

    def run_rituals(self, fake):
        self.patch_globals(fake._maybe_rituals.__func__)
        asyncio.run(fake._maybe_rituals())

    def test_morning_greeting_goes_to_exactly_one_platform(self):
        picked = set()
        for seed in range(40):
            random.seed(seed)
            fake = make_self(self.methods)
            self.run_rituals(fake)
            self.assertEqual(len(fake.sent), 1, "一次问候只能发一处")
            picked.add(fake.sent[0][0])
            self.assertEqual(fake.sent[0][1], "早呀")
            self.assertTrue(fake.db.kv_get("ritual_morning_%s_%s" % (UID, TODAY)))
            record = fake.db.kv_get("greeting_last:%s" % UID)
            self.assertEqual(record["umo"], fake.sent[0][0])
            self.assertEqual(record["kind"], "morning")
            # 只标记真正收到的那一处
            self.assertEqual(fake.marked, [fake.sent[0][0]])
        self.assertEqual(picked, {QQ, LARK}, "随机应该两个平台都挑得到")

    def test_randomize_off_only_sends_qq(self):
        fake = make_self(self.methods, cfg={"ritual_random_platform": False})
        self.run_rituals(fake)
        self.assertEqual([umo for umo, _ in fake.sent], [QQ])

    def test_randomize_off_does_not_fall_back_to_other_platform(self):
        fake = make_self(self.methods, cfg={"ritual_random_platform": False})

        async def only_lark(umo, text):
            fake.sent.append((umo, text))
            return umo == LARK

        fake._send_to_umo = only_lark
        self.run_rituals(fake)
        self.assertEqual([umo for umo, _ in fake.sent], [QQ])
        self.assertIsNone(fake.db.kv_get("greeting_last:%s" % UID))

    def test_same_day_does_not_repeat(self):
        fake = make_self(self.methods)
        self.run_rituals(fake)
        self.assertEqual(len(fake.sent), 1)
        self.run_rituals(fake)
        self.assertEqual(len(fake.sent), 1)

    def test_recent_greeting_blocks_second_window(self):
        fake = make_self(self.methods)
        fake.db.kv_set("greeting_last:%s" % UID, {"kind": "lunch", "umo": LARK, "ts": NOW - 10 * 60})
        self.run_rituals(fake)
        self.assertEqual(fake.sent, [])

    def test_already_greeted_on_other_platform_skips(self):
        fake = make_self(self.methods, recents={
            QQ: [],
            LARK: [{"role": "user", "content": "早安老婆", "created_at": NOW - 5 * 60}],
        })
        self.run_rituals(fake)
        self.assertEqual(fake.sent, [])

    def test_send_failure_falls_back_to_other_platform(self):
        # 固定随机数，让 QQ 先发、失败后退到飞书
        seed = next(
            value for value in range(100)
            if greeting_targets([QQ, LARK], QQ, rng=random.Random(value))[0] == QQ
        )
        random.seed(seed)
        fake = make_self(self.methods)
        calls = []

        async def flaky(umo, text):
            calls.append(umo)
            return umo == LARK

        fake._send_to_umo = flaky
        self.run_rituals(fake)
        self.assertEqual(calls, [QQ, LARK])
        record = fake.db.kv_get("greeting_last:%s" % UID)
        self.assertEqual(record["umo"], LARK)

    def test_ritual_pending_true_before_greeting(self):
        fake = make_self(self.methods)
        self.patch_globals(fake._ritual_pending.__func__)
        self.assertTrue(asyncio.run(fake._ritual_pending(fake.profile())))

    def test_ritual_pending_false_for_non_lover(self):
        fake = make_self(self.methods, profiles=[FakeSelf.profile(relation="熟识")])
        self.patch_globals(fake._ritual_pending.__func__)
        self.assertFalse(asyncio.run(fake._ritual_pending(fake.profile(relation="熟识"))))

    def test_ritual_pending_false_without_any_channel(self):
        profile = FakeSelf.profile(private_umo="")
        fake = make_self(self.methods, profiles=[profile], channels={})
        self.patch_globals(fake._ritual_pending.__func__)
        self.assertFalse(asyncio.run(fake._ritual_pending(profile)))

    def test_ritual_pending_false_after_greeting(self):
        fake = make_self(self.methods)
        self.patch_globals(fake._ritual_pending.__func__)
        fake.db.kv_set("ritual_morning_%s_%s" % (UID, TODAY), True)
        self.assertFalse(asyncio.run(fake._ritual_pending(fake.profile())))

    def test_ritual_pending_false_within_gap(self):
        fake = make_self(self.methods)
        self.patch_globals(fake._ritual_pending.__func__)
        fake.db.kv_set("greeting_last:%s" % UID, {"kind": "lunch", "umo": QQ, "ts": NOW - 5 * 60})
        self.assertFalse(asyncio.run(fake._ritual_pending(fake.profile())))

    def test_ritual_should_send_sees_both_platforms(self):
        fake = make_self(self.methods, recents={
            QQ: [{"role": "user", "content": "正常聊天", "created_at": NOW - 3600}],
            LARK: [{"role": "user", "content": "晚安", "created_at": NOW - 3600}],
        })
        self.patch_globals(fake._ritual_should_send.__func__)
        self.assertFalse(fake._ritual_should_send([QQ, LARK], "goodnight"))


if __name__ == "__main__":
    unittest.main()
