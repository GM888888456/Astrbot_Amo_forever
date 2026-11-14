# -*- coding: utf-8 -*-
"""P2 回归测试：分段死循环 / 断句取最靠后 / 心流「0 当默认值」/ 礼物载入静默 / 关系 0 跳。"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import astrbot_stub  # noqa: E402

astrbot_stub.install()

from heartflow_engine import (  # noqa: E402
    _extract_weights_from_rules,
    _validate_config,
    clamp_score,
)
from relation_graph import spread_scores  # noqa: E402


class HeartflowRegressionTests(unittest.TestCase):
    def test_zero_weight_is_kept(self):
        """面板 slider min=0：权重/阈值填 0 要真的生效，不能回退默认值。"""
        self.assertEqual(clamp_score(0, 0.0, 1.0, 0.6, allow_zero=True), 0.0)
        self.assertEqual(clamp_score(0, 0.0, 1.0, 0.6), 0.6)
        config = _validate_config({"reply_threshold": 0})
        self.assertEqual(config["reply_threshold"], 0.0)
        rules = [{"dimension_name": "relevance", "weight": 0}]
        cleaned = _validate_config({"judge_rules": rules})
        self.assertEqual(cleaned["judge_rules"][0]["weight"], 0.0)

    def test_unknown_dimension_does_not_shrink_weights(self):
        """judge_rules 混入未知维度时，已知维度归一化后和仍为 1。"""
        weights = _extract_weights_from_rules([
            {"dimension_name": "relevance", "weight": 1},
            {"dimension_name": "mood", "weight": 3},
        ])
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertEqual(weights.get("mood"), None)
        self.assertAlmostEqual(weights["relevance"], 1.0)

    def test_all_zero_weights_fall_back(self):
        weights = _extract_weights_from_rules([
            {"dimension_name": "relevance", "weight": 0},
        ])
        self.assertAlmostEqual(sum(weights.values()), 1.0)


class RelationHopTests(unittest.TestCase):
    EDGES = [
        {"a_uid": "a", "b_uid": "b", "relation": "朋友"},
        {"a_uid": "b", "b_uid": "c", "relation": "朋友"},
    ]

    def test_zero_means_direct_only(self):
        scores = spread_scores(self.EDGES, "a", max_hops=0)
        self.assertIn(("a", "b"), scores)
        self.assertNotIn(("b", "c"), scores)

    def test_none_keeps_default_two_hops(self):
        scores = spread_scores(self.EDGES, "a", max_hops=None)
        self.assertIn(("b", "c"), scores)


if __name__ == "__main__":
    unittest.main()
