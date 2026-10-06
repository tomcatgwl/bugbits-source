"""Historical legacy world_02 contract; loaded defaults have separate tests."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.assets import data_dir  # noqa: E402
from bugbits import worlddb  # noqa: E402

W2 = data_dir("worlds", "world_02.vsc")


class TestLegacyWorld02(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = worlddb.parse_world(W2, basis='legacy-grid-v1')

    def test_counts(self):
        self.assertEqual(len(self.w.waypoints), 122)
        self.assertEqual(len(self.w.starts), 8)
        self.assertEqual(len(self.w.flowers), 4)
        self.assertEqual(len(self.w.lights), 1)
        self.assertEqual(self.w.static_model, "worlds/world_02")
        self.assertEqual(self.w.edges, 124)

    def test_axis_mapping(self):
        # 轴映射 (x,y,z)=(p1,p2,p0): start(SideID0,Index0) vsc(-344.543,93.529,3.739)
        s = self.w.start(0, 0)
        self.assertAlmostEqual(s.grid_pos[0], 93.529, places=2)    # x = p1
        self.assertAlmostEqual(s.grid_pos[1], 3.739, places=2)     # y = p2 (up)
        self.assertAlmostEqual(s.grid_pos[2], -344.543, places=2)  # z = p0

    def test_start_matrix(self):
        for side in (0, 1):
            for idx in range(4):
                self.assertIsNotNone(self.w.start(side, idx))

    def test_terrain_bounds(self):
        t = self.w.terrain
        self.assertAlmostEqual(t[0], -350, delta=1.0)
        self.assertAlmostEqual(t[1], 353, delta=1.0)
        self.assertAlmostEqual(t[4], -409, delta=1.0)
        self.assertAlmostEqual(t[5], 396, delta=1.0)

    def test_entities_within_terrain(self):
        t = self.w.terrain
        ents = list(self.w.waypoints) + list(self.w.starts) + list(self.w.flowers)
        for e in ents:
            self.assertTrue(t[0] - 5 <= e.grid_pos[0] <= t[1] + 5, e.name)
            self.assertTrue(t[4] - 5 <= e.grid_pos[2] <= t[5] + 5, e.name)

    def test_components_and_water(self):
        comps = self.w.components()
        self.assertEqual(len(comps), 4)
        self.assertEqual(sorted((len(c) for c in comps), reverse=True)[:4], [39, 38, 27, 24])
        # 数据事实: wp32/wp51 为无边设计残留 (度 0, 不入分量)
        self.assertEqual(sorted(n for n in self.w.adjacency if not self.w.adjacency[n]),
                         ["wp32", "wp51"])
        self.assertTrue(all(not wp.water for wp in self.w.waypoints))  # world_02 无水


if __name__ == "__main__":
    unittest.main()
