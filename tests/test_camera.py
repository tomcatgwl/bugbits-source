"""OF-03.A：透视相机原语——矩阵数值与投影不变量（与引擎 0x4060f0 逐字节一致）。"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.render import camera  # noqa: E402


class TestPerspectiveMatrix(unittest.TestCase):
    FOV = math.pi / 3          # 60°（引擎 0x4e2e30）
    ASPECT = 1.6               # 默认 16:10（引擎 0x4e2fd0）
    NEAR, FAR = 1.0, 1000.0

    def test_matches_engine_d3dx_matrix(self):
        m = camera.perspective_fov_lh(self.FOV, self.ASPECT, self.NEAR, self.FAR)
        cot = 1.0 / math.tan(self.FOV / 2)          # cot(30°) = √3
        self.assertAlmostEqual(m[0], cot / self.ASPECT, places=6)   # M[0][0]
        self.assertAlmostEqual(m[5], cot, places=6)                 # M[1][1]
        self.assertAlmostEqual(m[10], self.FAR / (self.FAR - self.NEAR), places=6)  # M[2][2]
        self.assertEqual(m[11], 1.0)                                # M[3][2]
        self.assertAlmostEqual(m[14], -self.FAR * self.NEAR / (self.FAR - self.NEAR),
                               places=6)                           # M[2][3]
        # 其余为 0
        for i in (1, 2, 3, 4, 6, 7, 8, 9, 12, 13, 15):
            self.assertEqual(m[i], 0.0, f"m[{i}] 应 0")

    def test_near_far_map_to_depth(self):
        m = camera.perspective_fov_lh(self.FOV, self.ASPECT, self.NEAR, self.FAR)
        # LH 看 +Z：z=near→ndc_z=0，z=far→ndc_z=1
        _, _, zn = camera.projection(m, (0.0, 0.0, self.NEAR))
        _, _, zf = camera.projection(m, (0.0, 0.0, self.FAR))
        self.assertAlmostEqual(zn, 0.0, places=6)
        self.assertAlmostEqual(zf, 1.0, places=6)

    def test_point_projects_to_expected_ndc(self):
        m = camera.perspective_fov_lh(self.FOV, self.ASPECT, self.NEAR, self.FAR)
        # 视锥右缘：x = aspect·tan(fov/2)·z → ndc_x=1（z=near）
        x_edge = self.ASPECT * math.tan(self.FOV / 2) * self.NEAR
        nx, ny, _ = camera.projection(m, (x_edge, 0.0, self.NEAR))
        self.assertAlmostEqual(nx, 1.0, places=6)
        self.assertAlmostEqual(ny, 0.0, places=6)

    def test_mat_mul_identity(self):
        m = camera.perspective_fov_lh(self.FOV, self.ASPECT, self.NEAR, self.FAR)
        self.assertEqual(camera.mat_mul(camera.identity(), m), m)
        self.assertEqual(camera.mat_mul(m, camera.identity()), m)


class TestStaticObliqueCamera(unittest.TestCase):
    """OF-03.B/C：静态斜俯视相机——往返/透视缩短/相机位置/矩阵一致性（数值代理）。"""
    BOUNDS = (-350, 353, -409, 396)
    SIZE = 256

    def _cam(self):
        return camera.static_oblique_camera(self.BOUNDS, self.SIZE)

    def _view_proj(self, cam):
        """由 cam 参数重建列主序视矩阵 V 与投影 P（与模块 docstring 公式交叉验证）。"""
        cx, cy, cz = cam.camera_pos
        c, s = cam.cos_p, cam.sin_p
        r = (1.0, 0.0, 0.0)
        u = (0.0, c, s)
        f = (0.0, -s, c)
        dpr = r[0] * cx + r[1] * cy + r[2] * cz
        dpu = u[0] * cx + u[1] * cy + u[2] * cz
        dpf = f[0] * cx + f[1] * cy + f[2] * cz
        V = (r[0], u[0], f[0], 0.0,
             r[1], u[1], f[1], 0.0,
             r[2], u[2], f[2], 0.0,
             -dpr, -dpu, -dpf, 1.0)
        P = camera.perspective_fov_lh(cam.fov_y, 1.0, cam.near, cam.far)
        return V, P

    def test_roundtrip_world_pixel_within_1px(self):
        cam = self._cam()
        for (x, z) in [(-350, -409), (353, 396), (-350, 396), (353, -409),
                       (0, 0), (1.5, -6.5), (-200, 200), (300, -300)]:
            px, py = cam.world_to_pixel(x, 0.0, z)
            x2, z2 = cam.pixel_to_ground(px, py)
            px2, py2 = cam.world_to_pixel(x2, 0.0, z2)
            self.assertLess(abs(px2 - px), 1e-3, f"px roundtrip @({x},{z})")
            self.assertLess(abs(py2 - py), 1e-3, f"py roundtrip @({x},{z})")
            # 世界空间往返（更强口径：世界误差 <1 世界单位）
            self.assertLess(abs(x2 - x), 1.0, f"x roundtrip @({x},{z})")
            self.assertLess(abs(z2 - z), 1.0, f"z roundtrip @({x},{z})")

    def test_world_to_pixel_matches_matrix_pipeline(self):
        cam = self._cam()
        V, P = self._view_proj(cam)
        for (x, y, z) in [(-350, 0, -409), (353, 30, 396), (0, 100, 0),
                          (-100, 50, 200), (0, 0, 0)]:
            cam_pt = camera.mat_vec_mul(V, (x, y, z, 1.0))
            ndc = camera.projection(P, (cam_pt[0], cam_pt[1], cam_pt[2]))
            mx, my = camera.viewport_ndc((ndc[0], ndc[1]),
                                         cam.size_px, cam.size_px)
            px, py = cam.world_to_pixel(x, y, z)
            self.assertAlmostEqual(px, mx, places=5,
                                   msg=f"px matrix @({x},{y},{z})")
            self.assertAlmostEqual(py, my, places=5,
                                   msg=f"py matrix @({x},{y},{z})")

    def test_foreshortening_near_wider_than_far(self):
        cam = self._cam()
        xmin, xmax, zmin, zmax = cam.bounds
        near_w = abs(cam.world_to_pixel(xmax, 0, zmin)[0]
                     - cam.world_to_pixel(xmin, 0, zmin)[0])
        far_w = abs(cam.world_to_pixel(xmax, 0, zmax)[0]
                    - cam.world_to_pixel(xmin, 0, zmax)[0])
        self.assertGreater(near_w, far_w)          # 透视缩短：远缘更窄
        # 近缘（zmin，南）在屏幕下方（py 大），远缘（zmax，北）在上方（py 小）
        self.assertGreater(cam.world_to_pixel(0, 0, zmin)[1],
                           cam.world_to_pixel(0, 0, zmax)[1])

    def test_camera_position_reasonable(self):
        cam = self._cam()
        self.assertGreater(cam.distance, 0.0)
        self.assertLess(cam.distance, 5000.0)
        self.assertGreater(cam.camera_pos[1], 0.0)          # 地面之上
        self.assertLess(cam.camera_pos[2], cam.bounds[2])   # 在 zmin 北侧（-Z）

    def test_bounds_fit_in_canvas(self):
        cam = self._cam()
        xmin, xmax, zmin, zmax = cam.bounds
        for (x, z) in [(xmin, zmin), (xmin, zmax), (xmax, zmin), (xmax, zmax)]:
            px, py = cam.world_to_pixel(x, 0.0, z)
            self.assertGreaterEqual(px, 0.0)
            self.assertLessEqual(px, self.SIZE)
            self.assertGreaterEqual(py, 0.0)
            self.assertLessEqual(py, self.SIZE)

    def test_far_auto_extended_for_full_map(self):
        cam = self._cam()
        # 全图地面远缘深度 ≤ far（不裁切北缘）
        self.assertGreaterEqual(cam.far, cam.distance + cam.hz * cam.cos_p)
        self.assertLess(cam.near, cam.distance - cam.hz * cam.cos_p)


if __name__ == "__main__":
    unittest.main()


class TestCameraPresetGeneralization(unittest.TestCase):
    """NC 相机交付：yaw/aspect/target/distance 泛化——默认位级不变 + 一般式不变量。"""
    BOUNDS = (-350.0, 353.0, -409.0, 396.0)
    SIZE = 1024.0

    # 改动前（HEAD 400cb4d）默认相机输出的金样本——锁定旧表达式分支逐位不变
    # （世界_02 bounds；terrain 烘焙回归锚依赖此路径）。
    GOLDEN = [
        ((-350.0, 0.0, -409.0),
         (15.271333603094604, 877.6177537262015, 627.5331802322123),
         (-350.0, -409.0)),
        ((353.0, 0.0, -409.0),
         (1008.7286663969054, 877.6177537262015, 627.5331802322123),
         (353.0, -409.0)),
        ((353.0, 0.0, 396.0),
         (762.5336610331515, 327.59438668161977, 1244.1989569429898),
         (352.9999999999999, 395.99999999999994)),
        ((-350.0, 0.0, 396.0),
         (261.46633896684847, 327.59438668161977, 1244.1989569429898),
         (-350.0, 395.99999999999994)),
        ((1.5, 0.0, -6.5), (512.0, 512.0, 935.866068587601), (1.5, -6.5)),
        ((1.5, 50.0, -6.5),
         (512.0, 474.4147492893691, 903.7266881032741),
         (1.5, 58.48938962464395)),
        ((0.0, 0.0, 0.0),
         (510.5861491374173, 508.0618414622112, 940.8453574678744),
         (1.0658141036401503e-14, 4.618527782440651e-14)),
    ]

    def test_default_path_bit_identical(self):
        """默认参数（yaw0/aspect1/中心目标/拟合距离）输出与改动前逐位一致。"""
        cam = camera.static_oblique_camera(self.BOUNDS, self.SIZE)
        self.assertEqual(cam.distance, 935.866068587601)
        self.assertEqual(cam.far, 1245.1989569429898)
        for (x, y, z), (px, py, cz), (gx, gz) in self.GOLDEN:
            self.assertEqual(cam.world_to_pixel_depth(x, y, z), (px, py, cz),
                             f"world_to_pixel_depth @({x},{y},{z})")
            self.assertEqual(cam.pixel_to_ground(px, py), (gx, gz),
                             f"pixel_to_ground @({px},{py})")

    def test_general_roundtrip_ground_points(self):
        """一般式：地面点（y=0）正↔逆往返 <1e-6 世界单位（yaw/aspect/target 组合）。"""
        specs = [
            dict(pitchDeg=22.9, yawDeg=28.6, aspect=1.6, distance=216.5),
            dict(pitchDeg=40.107, yawDeg=22.9, aspect=1.6, distance=277.1,
                 target=(0.0, 0.0, 0.0)),
            dict(pitchDeg=30.0, yawDeg=0.0, aspect=1.6, distance=400.0),
            dict(pitchDeg=40.0, yawDeg=45.0, aspect=1.0, distance=300.0),
            dict(pitchDeg=40.0, yawDeg=0.0, aspect=1.0, distance=277.1,
                 target=(1.0, 0.0, 2.0)),
        ]
        for spec in specs:
            cam = camera.camera_from_spec(self.BOUNDS, self.SIZE, spec)
            worst = 0.0
            for x, z in ((0, 0), (100, 50), (-200, 150), (50, -300),
                         (300, 380), (-340, -400)):
                px, py = cam.world_to_pixel(float(x), 0.0, float(z))
                cx_, cy_, cz_ = cam.world_to_camera(float(x), 0.0, float(z))
                if cz_ <= 0:            # 相机背后的地面点不在双射域内
                    continue
                gx, gz = cam.pixel_to_ground(px, py)
                worst = max(worst, math.hypot(gx - x, gz - z))
            self.assertLess(worst, 1e-6, f"roundtrip {spec}")

    def test_elevated_point_ray_consistency(self):
        """一般式：高度点投影 → 逆映射地面点 → 再投影 = 同像素（射线自洽）。"""
        cam = camera.camera_from_spec(
            self.BOUNDS, self.SIZE,
            dict(pitchDeg=22.9, yawDeg=28.6, aspect=1.6, distance=216.5))
        for x, y, z in ((0.0, 80.0, 0.0), (50.0, 30.0, -100.0)):
            px, py = cam.world_to_pixel(x, y, z)
            gx, gz = cam.pixel_to_ground(px, py)
            px2, py2 = cam.world_to_pixel(gx, 0.0, gz)
            self.assertAlmostEqual(px, px2, places=4)
            self.assertAlmostEqual(py, py2, places=4)

    def test_target_maps_to_content_center(self):
        """目标点映射到投影空间中心（letterbox 语义：水平满幅/垂直居中）。"""
        cam = camera.camera_from_spec(
            self.BOUNDS, self.SIZE,
            dict(pitchDeg=40.107, yawDeg=22.9, aspect=1.6, distance=277.1,
                 target=(0.0, 0.0, 0.0)))
        px, py = cam.world_to_pixel(0.0, 0.0, 0.0)
        self.assertAlmostEqual(px / (self.SIZE * 1.6), 0.5, places=9)
        self.assertAlmostEqual(py / self.SIZE, 0.5, places=9)

    def test_aspect_widens_horizontal_fov(self):
        """aspect=1.6：同一世界点水平 NDC 更靠边缘（水平视场更宽）。"""
        near = camera.camera_from_spec(
            self.BOUNDS, self.SIZE, dict(pitchDeg=40.0, yawDeg=0.0, aspect=1.0,
                                         distance=277.1))
        wide = camera.camera_from_spec(
            self.BOUNDS, self.SIZE, dict(pitchDeg=40.0, yawDeg=0.0, aspect=1.6,
                                         distance=277.1))
        x_off = 100.0
        nx1, _, _ = near.world_to_pixel_depth(self.BOUNDS[0] / 2 + x_off, 0.0, 0.0)
        nx2, _, _ = wide.world_to_pixel_depth(self.BOUNDS[0] / 2 + x_off, 0.0, 0.0)
        # aspect 放大水平 NDC：宽幅下同一偏移更接近中心（相对内容宽度）
        r1 = abs(nx1 / (self.SIZE) - 0.5)
        r2 = abs(nx2 / (self.SIZE * 1.6) - 0.5)
        self.assertLess(r2, r1)

    def test_yaw_rotates_screen_position(self):
        """yaw 使地面点绕目标旋转（同距离同 pitch，屏幕位置随 yaw 变化）。"""
        base = camera.camera_from_spec(
            self.BOUNDS, self.SIZE, dict(pitchDeg=40.0, yawDeg=0.0,
                                         aspect=1.6, distance=277.1))
        rot = camera.camera_from_spec(
            self.BOUNDS, self.SIZE, dict(pitchDeg=40.0, yawDeg=30.0,
                                         aspect=1.6, distance=277.1))
        p0 = base.world_to_pixel(0.0, 0.0, 200.0)
        p1 = rot.world_to_pixel(0.0, 0.0, 200.0)
        self.assertGreater(math.hypot(p0[0] - p1[0], p0[1] - p1[1]), 1.0)

    def test_camera_from_spec_defaults(self):
        """camera_from_spec 空 spec == static_oblique_camera（缺省恒等）。"""
        a = camera.camera_from_spec(self.BOUNDS, self.SIZE, {})
        b = camera.static_oblique_camera(self.BOUNDS, self.SIZE)
        for attr in ("distance", "far", "cot", "sin_p", "cos_p", "tan_p"):
            self.assertEqual(getattr(a, attr), getattr(b, attr), attr)
        self.assertEqual(a.world_to_pixel_depth(1.0, 2.0, 3.0),
                         b.world_to_pixel_depth(1.0, 2.0, 3.0))
