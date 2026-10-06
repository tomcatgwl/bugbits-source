"""T4.2: level——level_02 锚点 + 时间轴保序。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.assets import data_dir  # noqa: E402
from bugbits import level  # noqa: E402

L2 = data_dir("scripts", "levels", "level_02.vsc")


class TestLevel02(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lv = level.parse_level(L2)

    def test_props(self):
        self.assertEqual(self.lv.world_name, "world_02")
        self.assertEqual(self.lv.type, "battle")
        self.assertEqual((self.lv.player_base_size, self.lv.enemy_base_size), (10, 3))
        self.assertEqual(self.lv.initial_nectar, 10)
        self.assertEqual(self.lv.nectar_on_paths, 4)
        self.assertFalse(self.lv.is_reversed)
        self.assertIsNone(self.lv.goal_nectar)
        self.assertIsNone(self.lv.rescue_bug)
        self.assertEqual(self.lv.music, "grass")
        self.assertEqual(self.lv.unlock, "level_01")

    def test_bug_setups(self):
        self.assertEqual(self.lv.bug_setups,
                         [(0, "ant", 100), (1, "littlebeetle", 90), (1, "bee", 10)])

    def test_set_lanes(self):
        self.assertEqual(self.lv.set_lanes,
                         [(0, 0), (0, 1), (0, 2), (0, 3),
                          (1, 0), (1, 1), (1, 2), (1, 3)])

    def test_scripts_ordered(self):
        sc = self.lv.scripts
        self.assertEqual(len(sc), 20)
        self.assertEqual(sc[0][0], "setlight")
        self.assertEqual(sc[1][0], "addhint")
        self.assertEqual(sc[2], ("sendenemy", ["littlebeetle", "2", "D_NONE", "5"]))
        setflows = [a for c, a in sc if c == "setflow"]
        self.assertEqual(setflows, [["0", "20", "40", "40"],
                                    ["1", "10", "20", "40"],
                                    ["1", "10", "30", "30"]])


if __name__ == "__main__":
    unittest.main()
