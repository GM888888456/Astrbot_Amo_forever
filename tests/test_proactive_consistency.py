# -*- coding: utf-8 -*-
"""主动消息的平台一致性：追问回原平台、不重复问同一件事、问候不被自己吃掉。"""

import asyncio
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import astrbot_stub  # noqa: E402

astrbot_stub.install()

import main  # noqa: E402
from main import HumanCorePlugin  # noqa: E402

LARK_UMO = "lark:FriendMessage:ou_cec66ea605ad17f62632fb044bc5f6ac"
QQ_UMO = "大肥鱼:FriendMessage:302578963"


class FakeDB:
    def __init__(self, kv=None, profiles=None):
        self.kv = dict(kv or {})
        self.profiles = list(profiles or [])

    def kv_get(self, key, default=None):
        return self.kv.get(key, default)

    def kv_set(self, key, value):
        self.kv[key] = value

    def proactive_profiles(self, limit=100):
        return list(self.profiles)

    def bump_proactive(self, uid):
        return None

    def log_proactive(self, uid, kind, text):
        return None


class FakePlugin:
    FOLLOWUP_TEMPLATES = HumanCorePlugin.FOLLOWUP_TEMPLATES
    _followup_topics = staticmethod(HumanCorePlugin._followup_topics)

    def __init__(self, profiles=None, rows=None):
        self.db = FakeDB(profiles=profiles)
        self.rows = rows or {}
        self.sent = []
        self.marked = []
        self.remembered = []

    # ---- 被调到的插件方法 ----
    def cfg_int(self, key, default=0):
        table = {
            "proactive_followup_minutes": 30,
            "proactive_no_reply_minutes": 0,   # 关掉「没回复就心情变差」，只看追问
            "ritual_skip_recent_minutes": 45,
        }
        return table.get(key, default)

    def cfg_str(self, key, default=""):
        return "23:30-07:30" if key == "quiet_hours" else default

    def cfg_bool(self, key, default=False):
        return True if key == "ritual_skip_if_greeted" else default

    def _pending_key(self, uid):
        return "proactive_pending_" + str(uid)

    def _followup_text(self, uid, kind, previous_text=""):
        return HumanCorePlugin._followup_text(self, uid, kind, previous_text)

    def _recent(self, umo, limit=10):
        return list(self.rows.get(umo, []))

    def _ritual_lookback_start(self, kind):
        # 测试里的行都是 1 小时前，判定起点给 2 小时前，别让时间窗把行滤掉
        return main.now_ts() - 7200

    def _ritual_judge_rows(self, rows, kind, since):
        return HumanCorePlugin._ritual_judge_rows(self, rows, kind, since)

    async def _send_to_umo(self, umo, text, quote_id=None, group=False):
        self.sent.append((umo, text))
        return True

    def _remember_bot_message(self, umo, text):
        self.remembered.append((umo, text))

    def _mark_bot_initiated(self, umo):
        self.marked.append(umo)

    def state_nudge(self, **kwargs):
        return None


class FollowupTextTests(unittest.TestCase):
    def test_does_not_ask_the_same_topic_again(self):
        fake = FakePlugin()
        for _ in range(20):
            text = HumanCorePlugin._followup_text(fake, "302578963", "meal", "你中午吃啥子嘛，搞点巴适的咯。")
            for word in ("吃", "饭", "饿", "外卖"):
                self.assertNotIn(word, text, "追问又把刚问过的吃饭问了一遍: %r" % text)

    def test_comfort_followup_does_not_ask_pain_again(self):
        fake = FakePlugin()
        for _ in range(20):
            text = HumanCorePlugin._followup_text(fake, "302578963", "comfort", "还疼不疼，别硬撑着。")
            self.assertNotIn("疼", text)
            self.assertNotIn("难受", text)

    def test_unrelated_kind_keeps_its_templates(self):
        fake = FakePlugin()
        text = HumanCorePlugin._followup_text(fake, "302578963", "meal", "在忙吗？")
        self.assertIn(text, HumanCorePlugin.FOLLOWUP_TEMPLATES["meal"])


class PendingPlatformTests(unittest.TestCase):
    def test_pending_records_the_platform(self):
        fake = FakePlugin()
        HumanCorePlugin._set_proactive_pending(fake, "302578963", "meal", "吃饭没", umo=LARK_UMO)
        pending = fake.db.kv_get("proactive_pending_302578963")
        self.assertEqual(pending["umo"], LARK_UMO)

    def test_followup_goes_back_to_the_same_platform(self):
        fake = FakePlugin(profiles=[{"uid": "302578963", "private_umo": QQ_UMO}])
        fake.db.kv[HumanCorePlugin._pending_key(fake, "302578963")] = {
            "sent_at": main.now_ts() - 3600,
            "kind": "meal",
            "text": "吃饭没",
            "umo": LARK_UMO,
            "followup": False,
            "mood": False,
        }
        original = main.quiet_now
        main.quiet_now = lambda spec: False
        try:
            asyncio.run(HumanCorePlugin._check_proactive_pending(fake))
        finally:
            main.quiet_now = original
        self.assertTrue(fake.sent, "应该发出一条追问")
        self.assertEqual(fake.sent[0][0], LARK_UMO)
        self.assertEqual(fake.marked, [LARK_UMO])
        self.assertEqual(fake.remembered[0][0], LARK_UMO)

    def test_old_pending_without_umo_falls_back_to_home(self):
        fake = FakePlugin(profiles=[{"uid": "302578963", "private_umo": QQ_UMO}])
        fake.db.kv[HumanCorePlugin._pending_key(fake, "302578963")] = {
            "sent_at": main.now_ts() - 3600,
            "kind": "greet",
            "text": "在吗",
            "followup": False,
            "mood": False,
        }
        original = main.quiet_now
        main.quiet_now = lambda spec: False
        try:
            asyncio.run(HumanCorePlugin._check_proactive_pending(fake))
        finally:
            main.quiet_now = original
        self.assertEqual(fake.sent[0][0], QQ_UMO)


class RitualSkipTests(unittest.TestCase):
    def test_her_own_line_does_not_eat_the_lunch_greeting(self):
        fake = FakePlugin(rows={QQ_UMO: [
            {"role": "bot", "content": "饭吃了没？", "created_at": main.now_ts() - 3600},
        ]})
        self.assertTrue(HumanCorePlugin._ritual_should_send(fake, [QQ_UMO], "lunch"))

    def test_his_greeting_still_skips(self):
        fake = FakePlugin(rows={QQ_UMO: [
            {"role": "user", "content": "我中午吃过啦", "created_at": main.now_ts() - 3600},
        ]})
        self.assertFalse(HumanCorePlugin._ritual_should_send(fake, [QQ_UMO], "lunch"))


class SickStatusTests(unittest.TestCase):
    def test_tired_is_not_a_sickness(self):
        self.assertNotIn("疲惫", main.SICK_STATUSES)
        self.assertIn("感冒", main.SICK_STATUSES)
        self.assertIn("低烧", main.SICK_STATUSES)


if __name__ == "__main__":
    unittest.main()
