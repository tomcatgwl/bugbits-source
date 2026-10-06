"""T4.2: unitdb——三源合并对齐 docs/units.md。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits import unitdb  # noqa: E402


class TestUnitdb(unittest.TestCase):
    def test_ant(self):
        u = unitdb.load_unit("ant")
        self.assertEqual((u.price, u.priority), (0, 0))
        self.assertEqual(u.initial_health, 15.0)
        self.assertEqual(u.melee_damage, 5.0)
        self.assertEqual(u.speed, 22.0)
        self.assertEqual(u.attack_hit_frame, 1.3)
        self.assertFalse(u.can_fly)
        self.assertTrue(u.can_gather)
        self.assertEqual(u.model, "Bugs/ant")
        self.assertEqual(u.anims["walk"], "Bugs/ant_walk")
        self.assertEqual(u.attack_hit_frames, (1.3,))
        # ant_attack.van 根节点最后一个键的时间，非根据命中帧猜测。
        self.assertAlmostEqual(u.attack_duration, 2.933333396911621)

    def test_littlebeetle_bee(self):
        lb = unitdb.load_unit("littlebeetle")
        self.assertEqual(lb.attack_hit_frames, (1.0, 1.4, 2.6))
        self.assertEqual((lb.price, lb.priority, lb.initial_health, lb.melee_damage,
                          lb.speed, lb.attack_speed), (3, 10, 30.0, 2.5, 14.0, 1.5))
        bee = unitdb.load_unit("bee")
        self.assertEqual((bee.price, bee.priority, bee.special_damage, bee.speed),
                         (3, 2, 30.0, 40.0))
        self.assertTrue(bee.can_fly)
        self.assertTrue(bee.can_gather)

    def test_load_all_24(self):
        allu = unitdb.load_all()
        self.assertEqual(len(allu), 24)
        for must in ("ant", "littlebeetle", "bee", "beetlehero", "beetlehero_tick",
                     "toxichero_tick", "wasphero_tick", "tick"):
            self.assertIn(must, allu)

    def test_engine_specials_not_units(self):
        self.assertRaises(KeyError, unitdb.load_unit, "nectarbonus")
        self.assertRaises(KeyError, unitdb.load_unit, "trapped")


if __name__ == "__main__":
    unittest.main()
