"""原引用映射与24模型绑定不变量；旧scanner/挂根预期由R380原流替代。"""
import os
import struct
import sys
import unittest
import math

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.assets import data_dir  # noqa: E402
from bugbits.assets import pose, v3d  # noqa: E402

BUGS = data_dir("models", "bugs")


class TestUniversalSkin(unittest.TestCase):
    def test_bind_pose_restores_normals(self):
        """anim=bind（恒等）→ 法线应随刚体变换还原且仍单位长（24 模型不变量）。"""
        names = sorted(f[:-4] for f in os.listdir(BUGS) if f.endswith(".v3d"))
        self.assertEqual(len(names), 24)
        for name in names:
            _, skin, recs, _ = v3d.parse_v3d(os.path.join(BUGS, name + ".v3d"))
            bind = pose.worlds_from_records(recs)
            result = pose.skin_at(skin, bind, bind)
            for (_, n, _), (_, gn, _) in zip(skin, result):
                for a, b in zip(gn, n):
                    self.assertAlmostEqual(a, b, places=5, msg=name)
                self.assertAlmostEqual(math.hypot(*gn), 1.0, places=5, msg=name)

    def test_all_24_models_skinnable(self):
        """蒙皮顶点与根几何同序同位（t22 性质, T5.2 全量验证）; 权重归一; 骨索引域封闭。"""
        names = sorted(f[:-4] for f in os.listdir(BUGS) if f.endswith(".v3d"))
        self.assertEqual(len(names), 24)
        for name in names:
            (verts, idx, k), skin, recs, tex = v3d.parse_v3d(
                os.path.join(BUGS, name + ".v3d"))
            self.assertTrue(skin, name)
            self.assertEqual(len(skin), len(verts), name)
            for v, s in zip(verts, skin):
                for a, b in zip(v[0], s[0]):
                    self.assertAlmostEqual(a, b, places=4, msg=name)
            for _, _, inf in skin:
                self.assertTrue(inf, name)
                self.assertLess(abs(sum(w for _, w in inf) - 1.0), 0.02, name)
                for bi, _ in inf:
                    self.assertLess(bi, len(recs), f"{name}: 骨索引越界 {bi}")

    def test_ant_declared_nodes_and_percent_weights(self):
        """原39节点，百分比权重不按被误判越界的引用槽重归一化。"""
        (verts, idx, k), skin, recs, tex = v3d.parse_v3d(
            os.path.join(BUGS, "ant.v3d"))
        self.assertEqual((len(verts), len(idx), k, len(recs), tex),
                         (808, 4824, 1, 39, "ant"))
        # 权重恰为百分比直除（无重归一化）: 抽 v0
        w0 = [w for _, w in skin[0][2]]
        self.assertTrue(all(abs(w * 100 - round(w * 100)) < 0.01 for w in w0))

    def test_bee_wing_references_resolve_to_wing_nodes(self):
        """原翼膜引用表映射到wing节点3/5，不是越界后挂根。"""
        verts, groups, skin, recs = v3d.parse_v3d_groups(
            os.path.join(BUGS, "bee.v3d"))
        # Original first wing triangle starts at vertex866, slot5->node5;
        # all referenced wing vertices resolve to nodes3/5.
        self.assertEqual(groups[0][0][0], 866)
        self.assertEqual(skin[866][2], [(5, 1.)])
        self.assertEqual({bi for vi in groups[0][0] for bi, _ in skin[vi][2]}, {3, 5})
        self.assertEqual(len(recs), 44)


class TestK2SubmeshGroups(unittest.TestCase):
    """k=2 双材质组（geo_end+128 定界）：parse_v3d_groups 返回两组（翼膜+身体/翼）。"""

    def test_bee_two_groups(self):
        verts, groups, skin, recs = v3d.parse_v3d_groups(
            os.path.join(BUGS, "bee.v3d"))
        self.assertEqual(len(groups), 2)
        (idx0, tex0), (idx1, tex1) = groups
        self.assertEqual(tex0, "wing_a")
        self.assertEqual(tex1, "bee")
        # DATA（survey §1.3）：ic0=90、ic1=5034（1678 三角）、%3==0、全索引<vc
        self.assertEqual(len(idx0), 90)
        self.assertEqual(len(idx1), 5034)
        self.assertEqual(len(idx1) % 3, 0)
        self.assertLess(max(idx1), len(verts))
        # 第二组 905 唯一顶点；两组顶点不相交（survey §1.3 交集=0）
        self.assertEqual(len(set(idx1)), 905)
        self.assertEqual(len(set(idx0) & set(idx1)), 0)

    def test_k1_single_group(self):
        verts, groups, skin, recs = v3d.parse_v3d_groups(
            os.path.join(BUGS, "ant.v3d"))
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][1], "ant")

    def test_all_k2_models_two_groups(self):
        # NC-03 泛化：全部 6 个 k=2 模型按 geo_end+128 定界拆第二组
        # （ic0/tex0 → ic1/tex1，survey_k2.py DATA 全量背书）。
        expected = {
            "bee": (90, "wing_a", 5034, "bee"),
            "wildbee": (84, "wing_a", 5610, "wildbee"),
            "bomberbee": (7368, "bomberbee", 90, "wing_a"),
            "wasp": (5838, "wasp", 84, "wing_a"),
            "wasphero": (6972, "wasp_hero", 84, "wing_a"),
            "wasphero_tick": (6972, "wasp_hero_tick", 84, "wing_a"),
        }
        for name, (ic0, tex0, ic1, tex1) in expected.items():
            verts, groups, skin, recs = v3d.parse_v3d_groups(
                os.path.join(BUGS, name + ".v3d"))
            self.assertEqual(len(groups), 2, name)
            (idx0, g0tex), (idx1, g1tex) = groups
            self.assertEqual(g0tex, tex0, name)
            self.assertEqual(len(idx0), ic0, name)
            self.assertEqual(g1tex, tex1, name)
            self.assertEqual(len(idx1), ic1, name)
            self.assertEqual(len(idx1) % 3, 0, name)
            self.assertLess(max(idx1), len(verts), name)

    def test_other_k2_models_unaffected(self):
        # 原「其余 k=2 模型单组」断言反转：5 模型第二组按 geo_end+128 定界拆分，
        # 各 tex1 见上表（wildbee→wildbee；其余→wing_a）。
        expected_tex1 = {
            "wildbee": "wildbee",
            "bomberbee": "wing_a",
            "wasp": "wing_a",
            "wasphero": "wing_a",
            "wasphero_tick": "wing_a",
        }
        for name, tex1 in expected_tex1.items():
            verts, groups, skin, recs = v3d.parse_v3d_groups(
                os.path.join(BUGS, name + ".v3d"))
            self.assertEqual(len(groups), 2, name)
            self.assertEqual(groups[1][1], tex1, name)

    def test_locate_submesh_rejects_malformed(self):
        # 硬约束（survey §2.3）：ic1%3!=0 或索引≥vc → ValueError（不静默回退单组）
        def _blob(ic, indices, tex1=b"bee", vc=100):
            body = struct.pack(f"<{ic}H", *indices)
            return b"\xab" * 128 + struct.pack("<I", ic) + body + tex1 + b"\x00", 0, vc

        blob, geo_end, vc = _blob(3, (0, 1, 2))
        idx, tex = v3d._locate_submesh(blob, geo_end, vc)
        self.assertEqual(idx, (0, 1, 2))
        self.assertEqual(tex, "bee")
        # ic1 % 3 != 0 → 抛 ValueError
        blob, geo_end, vc = _blob(4, (0, 1, 2, 3))
        with self.assertRaises(ValueError):
            v3d._locate_submesh(blob, geo_end, vc)
        # 索引 ≥ vc → 抛 ValueError
        blob, geo_end, vc = _blob(3, (0, 1, 200), vc=100)
        with self.assertRaises(ValueError):
            v3d._locate_submesh(blob, geo_end, vc)

    def test_locate_submesh_truncated_index_stream(self):
        # ic1 声明 6（合法 %3）但索引流截断（只写 3 个 u16）→ ValueError
        blob = b"\xab" * 128 + struct.pack("<I", 6) + struct.pack("<3H", 0, 1, 2)
        with self.assertRaises(ValueError):
            v3d._locate_submesh(blob, 0, 100)

    def test_locate_submesh_tex1_no_nul(self):
        # tex1 无 NUL 结尾 → ValueError
        blob = (b"\xab" * 128 + struct.pack("<I", 3)
                + struct.pack("<3H", 0, 1, 2) + b"bee")
        with self.assertRaises(ValueError):
            v3d._locate_submesh(blob, 0, 100)


if __name__ == "__main__":
    unittest.main()
