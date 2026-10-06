"""NC-03 单位公告板合同：render/billboard.py 独立几何验收。

独立预期来源（不复制实现输出）：
- 与 render/camera.py StaticObliqueCamera 已验证公式逐点对照（y=0 地面一致；
  y>0 高度项按 camera.world_to_camera 推导）。
- 近中远透视比：λ·camZ = 常数（同单位不同深度）。
- 正逆映射：project(y=0) → camera.pixel_to_ground 往返。
- 内容框锚点：dest 矩形的瓦片中心 == (px, py)（NC-03A 稳定 pivot，与 cb 分离）。
- manifest dict ↔ StaticObliqueCamera 两种输入等价（host.js 消费前者）。
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.render import billboard, camera  # noqa: E402


def _cam():
    return camera.static_oblique_camera((-350.0, 353.0, -409.0, 396.0), 1024.0)


def _proj_dict():
    """manifest projection 形态（host.js render.projection 同键）。"""
    c = _cam()
    return {"size": c.size_px, "cx": c.cx, "cz": c.cz, "cot": c.cot,
            "sinP": c.sin_p, "cosP": c.cos_p, "tanP": c.tan_p,
            "distance": c.distance, "near": c.near, "far": c.far}


class TestProject(unittest.TestCase):
    def test_ground_matches_camera(self):
        """y=0 地面投影与 camera.world_to_pixel 逐点一致（同一公式移植）。"""
        c = _cam()
        for (x, z) in [(0, 0), (-350, -409), (353, 396), (100, -200),
                       (-300, 350)]:
            px, py, camz = billboard.project(
                billboard.cam_consts(c), x, 0.0, z, 1024.0)
            epx, epy = c.world_to_pixel(x, 0.0, z)
            self.assertAlmostEqual(px, epx, places=9, msg=(x, z))
            self.assertAlmostEqual(py, epy, places=9, msg=(x, z))

    def test_height_terms(self):
        """高度项独立推导：cam_y = y·cosθ + dz·sinθ；cam_z = d + dz·cosθ − y·sinθ
        （与 camera.world_to_camera 同式——直接对照而非复制 billboard 输出）。"""
        c = _cam()
        cc = billboard.cam_consts(c)
        for (x, y, z) in [(0, 80.0, 0), (100, 12.5, -200), (-50, 80.0, 350)]:
            cx_, cy_, cz_ = c.world_to_camera(x, y, z)
            px, py, camz = billboard.project(cc, x, y, z, 1024.0)
            # NDC 由 cam_z 除法得出（aspect=1）→ 像素
            epx = (c.cot * cx_ / cz_ + 1.0) * 0.5 * 1024.0
            epy = (1.0 - c.cot * cy_ / cz_) * 0.5 * 1024.0
            self.assertAlmostEqual(px, epx, places=9, msg=(x, y, z))
            self.assertAlmostEqual(py, epy, places=9, msg=(x, y, z))
            self.assertAlmostEqual(camz, cz_, places=9, msg=(x, y, z))

    def test_altitude_lifts_and_enlarges(self):
        """飞行高度可见：同 (x,z) 上 y=80 比 y=0 屏幕位置更高（py 更小）且
        cam_z 更小（离相机更近 → λ 更大）。"""
        cc = billboard.cam_consts(_cam())
        px0, py0, cz0 = billboard.project(cc, 0.0, 0.0, 0.0, 1024.0)
        px8, py8, cz8 = billboard.project(cc, 0.0, 80.0, 0.0, 1024.0)
        self.assertLess(py8, py0 - 5.0)
        self.assertLess(cz8, cz0)

    def test_roundtrip_ground(self):
        """正逆映射：project(y=0) → camera.pixel_to_ground 往返 <1e-6 世界单位。"""
        c = _cam()
        cc = billboard.cam_consts(c)
        for (x, z) in [(0, 0), (120.5, -300.25), (-330, 380)]:
            px, py, _ = billboard.project(cc, x, 0.0, z, 1024.0)
            x2, z2 = c.pixel_to_ground(px, py)
            self.assertLess(abs(x2 - x), 1e-6, (x, z))
            self.assertLess(abs(z2 - z), 1e-6, (x, z))


class TestUnitBillboard(unittest.TestCase):
    WS = (10.0, 6.0, 12.0)      # 独立合成体量（非实现输出）
    ASC = 12.5 / (0.8 * 128.0)  # 与 norm_span=屏幕跨度 12.5 一致的 atlasScale
    SF = 1.5

    def test_perspective_constant_near_mid_far(self):
        """近中远：λ·camZ/(asc·sf) == cot·canvas/2（跨深度一致）。"""
        for world_id, z in (("near", -380.0), ("mid", 0.0), ("far", 390.0)):
            bb = billboard.unit_billboard(_proj_dict(), (50.0, 0.0, z),
                                          self.WS, self.SF, self.ASC, 640.0)
            k = bb["lam"] * bb["cam_z"] / (self.ASC * self.SF)
            expect = math.sqrt(3.0) * 640.0 / 2.0
            self.assertAlmostEqual(k, expect, places=9, msg=world_id)
        # 且近 > 中 > 远（透视单调）
        lams = [billboard.unit_billboard(_proj_dict(), (50.0, 0.0, z),
                                        self.WS, self.SF, self.ASC, 640.0)["lam"]
                for z in (-380.0, 0.0, 390.0)]
        self.assertGreater(lams[0], lams[1])
        self.assertGreater(lams[1], lams[2])

    def test_lam_formula_independent(self):
        """λ 独立推导：内容半径（世界）= asc·sf·64 图集px → 屏幕像素经
        cot·canvas/(2·camZ)。"""
        bb = billboard.unit_billboard(_proj_dict(), (0.0, 0.0, 0.0),
                                      self.WS, self.SF, self.ASC, 640.0)
        content_r_world = self.ASC * self.SF * 64.0        # 64 = 半瓦片图集px
        c = _cam()
        expect = content_r_world * c.cot * 640.0 / (2.0 * bb["cam_z"])
        self.assertAlmostEqual(bb["lam"] * 64.0, expect, places=9)

    def test_anchor_center(self):
        """锚点：模型中心世界 y = pos.y + h·sf/2（脚底在地面、头顶在其上）。"""
        pos = (10.0, 80.0, -50.0)
        bb = billboard.unit_billboard(_proj_dict(), pos, self.WS, self.SF,
                                      self.ASC, 640.0)
        self.assertAlmostEqual(bb["center_y"], 80.0 + 6.0 * 1.5 / 2.0)
        # 与显式投影该中心点一致（锚点 = 模型中心投影）
        px, py, _ = billboard.project(billboard.cam_consts(_cam()),
                                      pos[0], bb["center_y"], pos[2], 640.0)
        self.assertAlmostEqual(bb["px"], px, places=9)
        self.assertAlmostEqual(bb["py"], py, places=9)

    def test_dict_and_camera_equivalent(self):
        """manifest dict 与 StaticObliqueCamera 两种输入逐字段等价。"""
        pos = (-120.0, 30.0, 210.0)
        a = billboard.unit_billboard(_proj_dict(), pos, self.WS, self.SF,
                                     self.ASC, 640.0)
        b = billboard.unit_billboard(_cam(), pos, self.WS, self.SF,
                                     self.ASC, 640.0)
        for k in ("px", "py", "cam_z", "lam", "center_y"):
            self.assertAlmostEqual(a[k], b[k], places=12, msg=k)

    def test_canvas_scaling(self):
        """同一投影 size=1024、画布 512/1024 → 像素坐标与画布成正比。"""
        pos = (60.0, 0.0, -100.0)
        a = billboard.unit_billboard(_proj_dict(), pos, self.WS, self.SF,
                                     self.ASC, 512.0)
        b = billboard.unit_billboard(_proj_dict(), pos, self.WS, self.SF,
                                     self.ASC, 1024.0)
        self.assertAlmostEqual(a["px"] * 2.0, b["px"], places=9)
        self.assertAlmostEqual(a["py"] * 2.0, b["py"], places=9)
        self.assertAlmostEqual(a["lam"] * 2.0, b["lam"], places=9)


class TestContentDest(unittest.TestCase):
    def test_tile_center_at_anchor(self):
        """dest 矩形的瓦片中心 == (px, py)（NC-03A 稳定 pivot 锚点定义）。

        锚点与 alpha bbox（cb）无关：非对称内容框不应改变瓦片中心锚定。
        """
        sprite = {"x": 100, "y": 200, "w": 128, "h": 128}
        px, py, lam = 333.0, 444.0, 0.09
        dx, dy, dw, dh = billboard.content_dest(sprite, px, py, lam)
        self.assertAlmostEqual(dx + (sprite["w"] / 2.0) * lam, px, places=9)
        self.assertAlmostEqual(dy + (sprite["h"] / 2.0) * lam, py, places=9)
        self.assertAlmostEqual(dw, 128 * lam, places=12)
        self.assertAlmostEqual(dh, 128 * lam, places=12)

    def test_anchor_independent_of_sprite_origin(self):
        """同一瓦片尺寸，图集页原点不同 → dest 相对 (px,py) 的偏移不变（锚点=
        瓦片中心，仅依赖 w/h，不依赖 x/y）。"""
        a = billboard.content_dest({"x": 0, "y": 0, "w": 64, "h": 64},
                                   100.0, 200.0, 1.0)
        b = billboard.content_dest({"x": 512, "y": 256, "w": 64, "h": 64},
                                   100.0, 200.0, 1.0)
        self.assertAlmostEqual(a[0], b[0], places=9)
        self.assertAlmostEqual(a[1], b[1], places=9)
        self.assertAlmostEqual(a[2], b[2], places=9)
        self.assertAlmostEqual(a[3], b[3], places=9)


if __name__ == "__main__":
    unittest.main()
