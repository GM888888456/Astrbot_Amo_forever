# -*- coding: utf-8 -*-
"""面板「状态」页：七情 ↔ 六欲 切换时，标题和分数必须一起换。

以前只重画了雷达图，标题写死「七情」、分数写死七情平均，切到六欲还显示「喜 35」。
"""

import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "views", "dashboard", "index.html")


class RadarToggleTests(unittest.TestCase):
    def setUp(self):
        with open(HTML, encoding="utf-8") as handle:
            self.html = handle.read()

    def test_label_has_id(self):
        self.assertIn('id="radarLabel"', self.html)

    def test_render_hero_switches_by_mode(self):
        self.assertIn("function renderHero()", self.html)
        self.assertIn('desire ? DESIRE_CN : EMOTION_CN', self.html)
        self.assertIn('desire ? "六欲（只读）" : "七情（只读）"', self.html)

    def test_schedule_tab_is_back(self):
        """「想法」搬去记忆面板了，终端这一格必须还给「日程」。"""
        self.assertIn('data-tab="schedule"', self.html)
        self.assertIn('id="tab-schedule"', self.html)
        self.assertIn("function loadSchedule(", self.html)

    def test_thoughts_tab_is_gone(self):
        self.assertNotIn('data-tab="thoughts"', self.html)
        self.assertNotIn('id="tab-thoughts"', self.html)

    def test_both_toggles_rerender_hero(self):
        """双击和手机短按两次这两条路径都要重算标题。"""
        self.assertEqual(self.html.count("renderHero();"), 3)  # 1 次定义调用 + 2 个切换口


if __name__ == "__main__":
    unittest.main()
