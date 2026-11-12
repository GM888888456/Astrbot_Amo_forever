# -*- coding: utf-8 -*-
"""从人格里读月薪：读得到就用，读不到就交给金融按城市平均。

人格写法很随意（「月薪 8000」「工资 1.2 万」「年薪 24 万」），但这几种都得认；
同时不能把「工作 3 年」「房租 2000」误当成工资。
"""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import astrbot_stub  # noqa: E402

astrbot_stub.install()

import main as M  # noqa: E402


class SalaryExtractTests(unittest.TestCase):
    def test_plain_monthly(self):
        self.assertEqual(M.extract_salary("月薪 8000"), 8000.0)

    def test_colon_and_yuan(self):
        self.assertEqual(M.extract_salary("工资：9500 元"), 9500.0)

    def test_wan_unit(self):
        self.assertEqual(M.extract_salary("工资 1.2 万"), 12000.0)

    def test_k_unit(self):
        self.assertEqual(M.extract_salary("薪资 12k"), 12000.0)

    def test_annual_divided_by_12(self):
        self.assertAlmostEqual(M.extract_salary("年薪 24 万"), 20000.0)

    def test_missing_returns_default(self):
        self.assertEqual(M.extract_salary(""), 0.0)
        self.assertEqual(M.extract_salary("性格温柔，喜欢下雨天"), 0.0)

    def test_unrelated_numbers_ignored(self):
        self.assertEqual(M.extract_salary("工作 3 年，房租 2000"), 0.0)

    def test_unreasonable_number_ignored(self):
        self.assertEqual(M.extract_salary("月薪 5"), 0.0, "5 块不是月薪")

    def test_picks_largest(self):
        text = "上一份工作月薪 6000，现在月薪 12000"
        self.assertEqual(M.extract_salary(text), 12000.0)


if __name__ == "__main__":
    unittest.main()
