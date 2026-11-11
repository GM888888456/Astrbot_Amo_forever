# -*- coding: utf-8 -*-
"""群聊 / 私聊的记忆归属：按人归纳的总结只能吃私聊。

里程碑、每日总结、日记最终都写成 ``scope='private'`` 的长期记忆，
数据插件那头又支持按 ``umo`` 取聊天；这里锁住「群里的行不会被当成你俩的事」。
"""

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from memory_scope import is_group_row, is_group_umo, private_rows  # noqa: E402


def _row(umo, text="随便聊聊", role="user"):
    return {"umo": umo, "role": role, "content": text}


class GroupUmoTests(unittest.TestCase):
    def test_group_umos(self):
        self.assertTrue(is_group_umo("aiocqhttp:GroupMessage:123456"))
        self.assertTrue(is_group_umo("lark:GroupMessage:oc_abc"))

    def test_private_umos(self):
        self.assertFalse(is_group_umo("aiocqhttp:FriendMessage:302578963"))
        self.assertFalse(is_group_umo("lark:FriendMessage:ou_cec66"))
        self.assertFalse(is_group_umo(""))
        self.assertFalse(is_group_umo(None))

    def test_row_without_umo_is_not_group(self):
        self.assertFalse(is_group_row({"role": "user", "content": "x"}))
        self.assertFalse(is_group_row(None))
        self.assertTrue(is_group_row(_row("aiocqhttp:GroupMessage:1")))


class PrivateRowsTests(unittest.TestCase):
    def test_drops_group_rows(self):
        rows = [
            _row("aiocqhttp:FriendMessage:1", "私聊说的"),
            _row("aiocqhttp:GroupMessage:2", "群里说的"),
            _row("lark:FriendMessage:3", "飞书私聊"),
            _row("lark:GroupMessage:4", "飞书群里"),
        ]
        kept = [row["content"] for row in private_rows(rows)]
        self.assertEqual(kept, ["私聊说的", "飞书私聊"])

    def test_order_preserved(self):
        rows = [_row("aiocqhttp:FriendMessage:1", "a"), _row("aiocqhttp:FriendMessage:1", "b")]
        self.assertEqual([row["content"] for row in private_rows(rows)], ["a", "b"])

    def test_legacy_rows_without_umo_kept(self):
        # 老版数据插件不回 umo：无从判断，按私聊保留，不能凭空丢历史
        rows = [{"role": "user", "content": "老数据"}, {"role": "bot", "content": "嗯"}]
        self.assertEqual(len(private_rows(rows)), 2)

    def test_ignores_junk(self):
        self.assertEqual(private_rows(None), [])
        self.assertEqual(private_rows([]), [])
        self.assertEqual(private_rows([None, "x", 3]), [])

    def test_all_group_means_nothing_to_summarize(self):
        rows = [_row("aiocqhttp:GroupMessage:1", "群里的 A"), _row("aiocqhttp:GroupMessage:1", "群里的 B")]
        self.assertEqual(private_rows(rows), [])


class MilestoneCountTests(unittest.TestCase):
    """里程碑的「够不够一轮」必须按过滤后的私聊条数算。"""

    def test_group_chatter_does_not_trigger_archive(self):
        from milestone import should_archive

        group = [_row("aiocqhttp:GroupMessage:9", "群里 %d" % i) for i in range(30)]
        self.assertFalse(should_archive(private_rows(group), every_turns=20, min_messages=12))
        # 同一批「消息」如果是私聊，就该归档
        private = [_row("aiocqhttp:FriendMessage:1", "私聊 %d" % i) for i in range(30)]
        self.assertTrue(should_archive(private_rows(private), every_turns=20, min_messages=12))


class WiringTests(unittest.TestCase):
    """main.py 里那三处按人归纳的取数都得过一遍过滤器。"""

    def setUp(self):
        with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as fh:
            self.source = fh.read()

    def test_imported(self):
        self.assertIn("private_rows as _private_rows", self.source)

    def test_milestone_filters(self):
        block = self.source.split("async def _milestone_archive_once", 1)[1].split("async def _maybe_daily_digest", 1)[0]
        self.assertIn("rows = _private_rows(rows)", block)

    def test_daily_digest_filters(self):
        block = self.source.split("async def _maybe_daily_digest", 1)[1].split("\n    async def ", 1)[0]
        self.assertIn("messages = _private_rows(messages)", block)

    def test_diary_filters(self):
        block = self.source.split("async def _diary_chat_lines", 1)[1].split("\n    def ", 1)[0]
        self.assertIn("rows = _private_rows(rows)", block)

    def test_no_unguarded_messages_since(self):
        # 里程碑取消息不能退回「只按 uid 取」而不做过滤
        pattern = re.compile(r'_data_call\(\s*"messages_since"[^\n]*\)')
        for match in pattern.finditer(self.source):
            tail = self.source[match.end():match.end() + 400]
            self.assertIn("_private_rows", tail, match.group(0))


if __name__ == "__main__":
    unittest.main()
