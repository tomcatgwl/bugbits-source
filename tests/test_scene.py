"""T4.6: scene——2D 合成器（地形层 + 实体精灵层 + 蜂巢占位）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from PIL import Image  # noqa: E402

from bugbits.render import bake, scene  # noqa: E402


class TestScene(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 小尺寸烘焙（测试提速; 合成逻辑与尺寸无关）
        cls.terrain = bake.bake_terrain("world_02", size=256)
        cls.sprites = bake.bake_unit_sprites(["ant"], frames=2, yaws=8, size=64)
        cls.flower = bake.bake_flower_sprite(size=64)
        cls.sc = scene.Scene(cls.terrain, cls.sprites, flower=cls.flower,
                             bounds=(-350, 353, -409, 396))

    def test_world_to_pixel(self):
        # OF-03.B/C：scene.world_to_pixel = 透视相机取整+钳位；与地形相机逐像素对齐。
        w2p = self.sc.world_to_pixel
        cam = self.sc.cam
        xmin, xmax, zmin, zmax = self.sc.bounds
        for (x, z) in [(xmin, zmin), (xmax, zmax), (xmin, zmax), (xmax, zmin),
                       (0, 0), (100, 100), (-100, -200)]:
            px, py = w2p(x, z)
            self.assertTrue(0 <= px < 256 and 0 <= py < 256, (x, z))
            # 逐像素对齐：scene = clamp(int(cam.world_to_pixel))
            fpx, fpy = cam.world_to_pixel(x, 0.0, z)
            self.assertEqual(px, max(0, min(255, int(fpx))), (x, z))
            self.assertEqual(py, max(0, min(255, int(fpy))), (x, z))
            # 相机浮点往返（无 int 量化）误差 <1 世界单位
            x2, z2 = cam.pixel_to_ground(fpx, fpy)
            self.assertLess(abs(x2 - x), 1.0, (x, z))
            self.assertLess(abs(z2 - z), 1.0, (x, z))

    def test_world_to_pixel_center_at_canvas_center(self):
        # 相机目标 = 地面矩形中心 (cx,0,cz) → 投影像素为画布中心
        xmin, xmax, zmin, zmax = self.sc.bounds
        cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
        px, py = self.sc.world_to_pixel(cx, cz)
        self.assertAlmostEqual(px, 128, delta=1)
        self.assertAlmostEqual(py, 128, delta=1)

    def test_compose_frame_fast(self):
        import time
        ents = [("ant", 0, 0, 0.0), ("ant", 50, 60, 90.0), ("ant", -100, -200, 45.0)]
        t0 = time.time()
        img = self.sc.compose_frame(ents, flowers=[(10, 20)],
                                    hives=[(0, 93, 3, -344), (1, 350, 4, -150)])
        self.assertLess(time.time() - t0, 2.0)          # 出口: 单帧 <2s
        self.assertEqual(img.size, (256, 256))

    def test_hive_placeholder_labeled(self):
        img = self.sc.compose_frame([], flowers=[], hives=[(0, 93, 3, -344)])
        # 数值代理: 巢锚点近旁存在占位框描边色 (80,200,90)
        px = img.load()
        outline = {(80, 200, 90), (79, 199, 89), (81, 201, 91)}
        hits = sum(1 for x in range(0, 256, 2) for y in range(0, 256, 2)
                   if px[x, y] in outline)
        self.assertGreater(hits, 4, "无蜂巢占位描边像素")

    def test_sprites_within_canvas(self):
        # 出界坐标不炸（边界钳位）
        img = self.sc.compose_frame([("ant", 9999, 9999, 0.0)], flowers=[(9999, -9999)],
                                    hives=[])
        self.assertEqual(img.size, (256, 256))

    def test_sprite_actually_drawn(self):
        # 精灵落点像素与地形底色不同（合成生效的数值代理）
        bare = self.sc.compose_frame([], flowers=[], hives=[])
        withants = self.sc.compose_frame(
            [("ant", 0, 0, 0.0)], flowers=[], hives=[])
        self.assertNotEqual(bare.tobytes(), withants.tobytes())

    def test_flower_world_size_contract(self):
        # NC-03B：flower_a.v3d 世界尺寸合同——worldSize=AABB、atlasScale=normSpan/(0.8·size)
        ws = bake.flower_world_size()
        self.assertAlmostEqual(ws[0], 21.44, delta=0.05)
        self.assertAlmostEqual(ws[1], 15.53, delta=0.05)
        self.assertAlmostEqual(ws[2], 17.98, delta=0.05)
        asc64 = bake.flower_atlas_scale(size=64)
        asc128 = bake.flower_atlas_scale(size=128)
        self.assertAlmostEqual(asc64, asc128 * 2.0, delta=1e-6)  # atlasScale ∝ 1/size


if __name__ == "__main__":
    unittest.main()
