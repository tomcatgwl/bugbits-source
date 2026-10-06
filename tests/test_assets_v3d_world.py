"""T4.2: assets/v3d 世界网格遍历——k=材质数 + 子网格几何布局（harness 同步背书）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.assets import data_dir  # noqa: E402
from bugbits.assets import v3d  # noqa: E402


class TestWorldMeshes(unittest.TestCase):
    def test_world_02(self):
        meshes = v3d.parse_world_meshes(data_dir("models", "worlds", "world_02.v3d"))
        self.assertEqual(len(meshes), 10)                       # == A
        names = {m.name for m in meshes}
        self.assertIn("ground", names)
        self.assertIn("grass_a", names)
        self.assertEqual(sum(len(m.verts) for m in meshes), 23240)
        xs = [v[0][0] for m in meshes for v in m.verts]
        zs = [v[0][2] for m in meshes for v in m.verts]
        self.assertAlmostEqual(min(xs), -350, delta=1.0)
        self.assertAlmostEqual(max(xs), 353, delta=1.0)
        self.assertAlmostEqual(min(zs), -409, delta=1.0)
        self.assertAlmostEqual(max(zs), 396, delta=1.0)

    def test_k_is_material_count(self):
        meshes = v3d.parse_world_meshes(data_dir("models", "worlds", "world_02.v3d"))
        by_name = {m.name: m for m in meshes}
        self.assertEqual(by_name["grass_a"].k, 3)   # ↔ .vsc World 块 grass_a Material0/1/2
        self.assertEqual(by_name["grass_c"].k, 3)
        self.assertTrue(all(m.k in (1, 2, 3, 4) for m in meshes))

    def test_all_nine_worlds_self_consistent(self):
        for i in range(1, 10):
            path = data_dir("models", "worlds", f"world_{i:02d}.v3d")
            blob = open(path, "rb").read()
            a = v3d.u32(blob, 0)
            meshes = v3d.parse_world_meshes(path)
            self.assertEqual(len(meshes), a, f"world_{i:02d}")
            for m in meshes:
                self.assertTrue(m.verts, m.name)
                self.assertTrue(m.ic > 0, m.name)
                self.assertTrue(max(m.indices) < len(m.verts), m.name)

    def test_k_gt_1_meshes_have_complete_geometry(self):
        """FIX-02（A1）：k>1 世界 mesh 有 k 组索引流；只读第一组会丢一半地面。

        旧实现 ground 顶点 48% 未引用、grass_a 74% 未引用（丢顶部/底部半区）。
        回归：每个 k>1 mesh 的未引用顶点占比须 < 40%。
        """
        for i in range(1, 10):
            path = data_dir("models", "worlds", f"world_{i:02d}.v3d")
            meshes = v3d.parse_world_meshes(path)
            for m in meshes:
                if m.k <= 1:
                    continue
                ref = set(m.indices)
                unref = len(m.verts) - len(ref)
                self.assertLess(unref / len(m.verts), 0.4,
                                f"world_{i:02d}.{m.name}: {unref}/{len(m.verts)} "
                                f"顶点未引用（疑似丢失材质组索引流）")

    def test_ground_mesh_covers_full_z_range(self):
        """FIX-02：ground 第二组索引流覆盖顶部 z 半区（旧实现只读底部 z>-17）。"""
        meshes = v3d.parse_world_meshes(data_dir("models", "worlds", "world_02.v3d"))
        ground = next(m for m in meshes if m.name == "ground")
        zs = [ground.verts[i][0][2] for i in set(ground.indices)]
        self.assertLess(min(zs), -300, "ground 未覆盖顶部 z（第二组索引流丢失）")
        self.assertGreater(max(zs), 300, "ground 未覆盖底部 z")

    def test_per_group_material_textures(self):
        """OF-03.B：每组材质组保留各自索引流 + 纹理名（ground/grass 分材质组）。"""
        meshes = v3d.parse_world_meshes(data_dir("models", "worlds", "world_02.v3d"))
        by_name = {m.name: m for m in meshes}
        ground = by_name["ground"]
        self.assertEqual(ground.k, 2)
        self.assertEqual(len(ground.group_indices), 2)
        self.assertEqual(len(ground.group_tex_names), 2)
        self.assertEqual(ground.group_tex_names[0], "world_02_ground_b")
        self.assertEqual(ground.group_tex_names[1], "world_02_ground_a")
        self.assertEqual(ground.tex_name, ground.group_tex_names[0])
        # 组索引合并 == 总 indices
        self.assertEqual(
            tuple(ground.indices),
            ground.group_indices[0] + ground.group_indices[1])
        grass_a = by_name["grass_a"]
        self.assertEqual(grass_a.k, 3)
        self.assertEqual(list(grass_a.group_tex_names),
                         ["clod_a", "grass_a", "grass_b"])


if __name__ == "__main__":
    unittest.main()
