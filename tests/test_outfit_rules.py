# -*- coding: utf-8 -*-
import unittest

from wardrobe import pair_ok


class OutfitRuleTests(unittest.TestCase):
    def test_jk_shirt_only_with_jk_skirt(self):
        self.assertTrue(pair_ok(["jk_shirt", "jk_skirt", "socks", "shoes"]))
        self.assertFalse(pair_ok(["jk_shirt", "bottom"]))
        self.assertFalse(pair_ok(["jk_shirt", "dress"]))

    def test_jk_skirt_only_with_jk_shirt(self):
        self.assertFalse(pair_ok(["jk_skirt", "top"]))
        self.assertFalse(pair_ok(["jk_skirt", "bottom"]))

    def test_dress_is_alone(self):
        self.assertTrue(pair_ok(["dress", "shoes", "socks"]))
        self.assertFalse(pair_ok(["dress", "bottom"]))
        self.assertFalse(pair_ok(["dress", "top"]))

    def test_normal_top_bottom_ok(self):
        self.assertTrue(pair_ok(["top", "bottom", "socks", "shoes", "accessory"]))


if __name__ == "__main__":
    unittest.main()
