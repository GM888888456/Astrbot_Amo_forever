# -*- coding: utf-8 -*-
"""私聊「要语音」的识别：他明确开口要了，就必须给语音（心流打分只是补充）。"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import astrbot_stub  # noqa: E402

astrbot_stub.install()

import main as amo_main  # noqa: E402


class VoiceAskTests(unittest.TestCase):
    def setUp(self):
        # 只用到类属性 + 正则，不必走 __init__
        self.plugin = object.__new__(amo_main.HumanCorePlugin)

    def ask(self, text):
        return self.plugin._user_asks_voice(text)

    def test_explicit_voice_phrases(self):
        for text in (
            "老婆，我想听听你的声音",
            "老婆能用语音说我爱你嘛",
            "再用语音说一遍我爱你嘿嘿",
            "给我发条语音呗",
            "唱一句给我听听",
            "你念一句给我听",
            "叫我一声名字",
            "亲口说句晚安",
            "想听你说说话",
            "说说你爱我",
        ):
            self.assertTrue(self.ask(text), text)

    def test_plain_chat_is_not_voice(self):
        for text in (
            "老婆吃的啥，能不能拍给我看看",
            "今天上班好累",
            "外面有声音，像是下雨了",
            "晚安",
        ):
            self.assertFalse(self.ask(text), text)


if __name__ == "__main__":
    unittest.main()
