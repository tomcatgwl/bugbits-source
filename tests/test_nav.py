"""T4.3: nav——寻路 + 三层移动语义（合成图精确数值 + 真实数据锚点）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.assets import data_dir  # noqa: E402
from bugbits import nav, worlddb  # noqa: E402
from bugbits.worlddb import Start, Waypoint, WorldData  # noqa: E402


def synth_world():
    """合成图: A(0,0) --50-- B(50,0,water) --50-- C(100,0) 直线 (xz 平面);
    A --56.57-- D(40,z=40) --72.11-- C 弯路 (总长 128.7, 明显更长)。y 恒 0。"""
    wps = [Waypoint("B", (50, 0, 0), (0, 0, 1), True, []),
           Waypoint("D", (40, 0, 40), (0, 0, 1), False, [])]
    starts = [Start("A", (0, 0, 0), (0, 0, 1), 0, 0, []),
              Start("C", (100, 0, 0), (0, 0, 1), 1, 0, [])]
    adj = {"A": {"B", "D"}, "B": {"A", "C"}, "D": {"A", "C"}, "C": {"B", "D"}}
    return WorldData({}, [], [], None, starts, wps, 6, adj, None)


class TestSynthetic(unittest.TestCase):
    def setUp(self):
        self.w = synth_world()

    def test_shortest_path_picks_direct(self):
        r = nav.route_between(self.w, "A", "C")
        self.assertIsNotNone(r)
        self.assertEqual(r.nodes, ["A", "B", "C"])

    def test_length_and_time_exact(self):
        r = nav.route_between(self.w, "A", "C")
        self.assertAlmostEqual(r.length, 100.0, places=6)
        # H10 证伪(T5.6): 引擎无通用水域减速 → ground 水段亦 ×1.0
        # (水段实际效果=游泳动画+水花特效, 非减速)
        t = r.travel_time(10.0, "ground")
        self.assertAlmostEqual(t, 50 / (10 * 1.0) + 50 / 10.0, places=9)
        self.assertAlmostEqual(r.travel_time(10.0, "air"), 100.0 / 10.0, places=9)

    def test_position_at(self):
        r = nav.route_between(self.w, "A", "C")
        self.assertEqual(r.position_at(0), (0.0, 0.0, 0.0))
        self.assertEqual(r.position_at(25), (25.0, 0.0, 0.0))
        self.assertEqual(r.position_at(100), (100.0, 0.0, 0.0))
        self.assertEqual(r.position_at(999), (100.0, 0.0, 0.0))      # 右钳位
        self.assertEqual(r.position_at(50, fly_height=80)[1], 80.0)  # 飞行层 y
        self.assertEqual(r.position_at(30, fly_height=80), (30.0, 80.0, 0.0))

    def test_unreachable_returns_none(self):
        w = synth_world()
        w.adjacency = {n: set() for n in w.adjacency}
        self.assertIsNone(nav.route_between(w, "A", "C"))
        self.assertIsNone(nav.route_between(w, "A", "不存在的节点"))

    def test_giantwaterbeetle_water_boost(self):
        # H10: 引擎无通用水域减速(证伪); giantwaterbeetle 水段 ×1.5 (玩法语义)
        from bugbits.sim import consts
        self.assertEqual(consts.WATER_AFFINE.get("giantwaterbeetle"), 1.5)


class TestRealWorlds(unittest.TestCase):
    def test_world_02_anchor(self):
        w = worlddb.parse_world(data_dir("worlds", "world_02.vsc"))
        r = nav.route_between(w, "start", "start4")
        self.assertIsNotNone(r)
        self.assertEqual(r.nodes[:5], ["start", "wp36", "wp35", "wp34", "wp33"])
        self.assertEqual(len(r.nodes), 38)
        self.assertAlmostEqual(r.length, 872.6835, places=3)
        self.assertAlmostEqual(r.travel_time(22.0, "ground"), 39.667430, places=3)

    def test_world_03_water_layers(self):
        w = worlddb.parse_world(data_dir("worlds", "world_03.vsc"))
        r = nav.route_between(w, "Start", "Start2")
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r.length, 723.9972, places=3)
        # H10 证伪(T5.6): 无通用水域减速 → ground 与 air 同耗时 (水段恒 ×1.0)
        self.assertAlmostEqual(r.travel_time(22.0, "ground"), 32.908964, places=3)
        self.assertAlmostEqual(r.travel_time(22.0, "air"), 32.908964, places=3)

    def test_lane_reachability_all_worlds(self):
        for i in range(1, 10):
            w = worlddb.parse_world(data_dir("worlds", f"world_{i:02d}.vsc"))
            n = len({s.index for s in w.starts if s.side_id == 0})
            for lane in range(n):
                r = nav.lane_route(w, lane)
                self.assertIsNotNone(r, f"world_{i:02d} lane {lane} 不可达")

    def test_world_02_fly_height(self):
        w = worlddb.parse_world(data_dir("worlds", "world_02.vsc"))
        self.assertAlmostEqual(float(w.props["FlyHeight"][0]), 80.0, places=3)


if __name__ == "__main__":
    unittest.main()
