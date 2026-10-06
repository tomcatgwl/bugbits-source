"""资产结构与修复后姿态回归快照；矩阵正确性另见 test_review_foundations。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.assets import data_dir  # noqa: E402
from bugbits.assets import pose, v3d, van  # noqa: E402

ANT = data_dir("models", "bugs", "ant.v3d")
WALK = data_dir("models", "bugs", "ant_walk.van")


class TestV3d(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(ANT, "rb") as f:
            cls.blob = f.read()
        cls.hdr = v3d.parse_header(cls.blob)
        (cls.verts, cls.idx, cls.k), cls.skin, cls.recs, cls.tex = v3d.parse_v3d(ANT)

    def test_header(self):
        h = self.hdr
        self.assertEqual((h["A"], h["nl"], h["name"]), (39, 3, "ant"))
        self.assertEqual(h["parent"], 0xFFFFFFFF)
        self.assertEqual(h["flag"], 1)
        self.assertEqual(h["vc"], 808)
        self.assertEqual(h["vert_off"], 84 + h["nl"])

    def test_geometry(self):
        self.assertEqual(len(self.verts), 808)
        self.assertEqual(len(self.idx), 4824)
        self.assertEqual(self.k, 1)
        self.assertEqual(self.tex, "ant")
        self.assertEqual(len(self.recs), 39)
        self.assertEqual(self.recs[0][0], "ant")  # 原声明节点首条 = 根记录

    def test_skin_parallel_array(self):
        # V2: 蒙皮顶点与根几何同序同位 (808/808)
        same = sum(1 for v, s in zip(self.verts, self.skin)
                   if all(abs(a - b) < 1e-4 for a, b in zip(v[0], s[0])))
        self.assertEqual(same, 808)
        bad_w = sum(1 for _, _, inf in self.skin if abs(sum(w for _, w in inf) - 1.0) > 0.02)
        self.assertEqual(bad_w, 0)


class TestVan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blocks = van.parse_van(WALK)
        with open(WALK, "rb") as f:
            cls.size = len(f.read())

    def test_layout(self):
        self.assertEqual(len(self.blocks), 39)
        self.assertEqual(len(self.blocks[0]), 12)
        self.assertAlmostEqual(self.blocks[0][-1][0], 1.9333332777023315, places=6)

    def test_sample_clamps_and_interpolates(self):
        keys = self.blocks[0]
        self.assertEqual(van.sample(keys, -1.0), keys[0])       # 左钳位
        self.assertEqual(van.sample(keys, 99.0), keys[-1])      # 右钳位
        t0, t1 = keys[0][0], keys[1][0]
        mid = van.sample(keys, (t0 + t1) / 2)
        self.assertAlmostEqual(mid[0], (t0 + t1) / 2, places=6)  # 时间线性
        for i in range(1, 7):
            lo, hi = keys[0][i], keys[1][i]
            self.assertAlmostEqual(mid[i], (lo + hi) / 2, places=5)


class TestPose(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (cls.verts, cls.idx, cls.k), cls.skin, cls.recs, cls.tex = v3d.parse_v3d(ANT)
        cls.blocks = van.parse_van(WALK)
        cls.bind = pose.worlds_from_records(cls.recs)

    def test_mat_roundtrip(self):
        ident = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
        self.assertEqual(pose.mat_mul(ident, ident), ident)
        self.assertEqual(pose.euler_rot(0, 0, 0), ident)
        m = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 3, -4, 5, 1)
        prod = pose.mat_mul(m, pose.mat_inv(m))
        for a, b in zip(prod, ident):
            self.assertAlmostEqual(a, b, places=5)
        self.assertEqual(pose.mat_apply(m, (0, 0, 0, 1)), (3.0, -4.0, 5.0))

    def test_bind_bounds(self):
        # R369: the previous snapshot used a transposed Euler matrix. The
        # original 402AC0 nine stores and independent directed axes/product
        # regressions now establish its row convention (test_original_euler_pose).
        # R380 resolves skin reference slots through the original table;
        # scanner indices generated the former bounds and are invalid here.
        # These current-source bounds are regression snapshots, not an oracle
        # for original skin parity. Animation t0 is distinct from bind.
        posed = pose.skin_at(self.skin, self.bind,
                             pose.worlds_at(self.recs, self.blocks, 0.0))
        xs = [v[0][0] for v in posed]
        ys = [v[0][1] for v in posed]
        zs = [v[0][2] for v in posed]
        self.assertAlmostEqual(min(xs), -4.960028, places=3)
        self.assertAlmostEqual(max(xs), 3.858156, places=3)
        self.assertAlmostEqual(min(ys), -0.049429, places=3)
        self.assertAlmostEqual(max(ys), 5.445202, places=3)
        self.assertAlmostEqual(min(zs), -5.793983, places=3)
        self.assertAlmostEqual(max(zs), 4.791455, places=3)

    def test_walk50_bounds(self):
        t = self.blocks[0][-1][0] * 0.5
        self.assertAlmostEqual(t, 0.966667, places=5)
        posed = pose.skin_at(self.skin, self.bind,
                             pose.worlds_at(self.recs, self.blocks, t))
        xs = [v[0][0] for v in posed]
        ys = [v[0][1] for v in posed]
        zs = [v[0][2] for v in posed]
        self.assertAlmostEqual(min(xs), -3.944596, places=3)
        self.assertAlmostEqual(max(xs), 5.050845, places=3)
        self.assertAlmostEqual(min(ys), -0.108667, places=3)
        self.assertAlmostEqual(max(ys), 5.423529, places=3)
        self.assertAlmostEqual(min(zs), -5.344441, places=3)
        self.assertAlmostEqual(max(zs), 4.775564, places=3)


if __name__ == "__main__":
    unittest.main()
