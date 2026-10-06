"""T4.6: bake——地形正交俯视 + 单位/花精灵（数值代理断言）。"""
import math
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.assets import data_dir  # noqa: E402
from bugbits.render import bake  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out", "bake_test")


class TestTerrainBake(unittest.TestCase):
    def test_world_02_terrain(self):
        t0 = time.time()
        img = bake.bake_terrain("world_02", size=256)
        dt = time.time() - t0
        self.assertEqual(img.size, (256, 256))
        self.assertEqual(img.mode, "RGB")
        colors = img.getcolors(maxcolors=256 * 256)
        self.assertIsNotNone(colors)                  # 非单色
        self.assertGreater(len(colors), 100)          # 明暗/材质变化丰富
        os.makedirs(OUT, exist_ok=True)
        img.save(os.path.join(OUT, "terrain_w02_256.png"))
        self.assertLess(dt, 120, f"烘焙 {dt:.1f}s 超时")  # <10min 的测试代理

    def test_world_03_has_water_pixels(self):
        # world_03 有 water mesh → 俯视图含蓝色系像素
        img = bake.bake_terrain("world_03", size=256)
        px = img.load()
        blues = sum(1 for x in range(0, 256, 4) for y in range(0, 256, 4)
                    if px[x, y][2] > px[x, y][0] + 20 and px[x, y][2] > 80)
        self.assertGreater(blues, 10, "无水域蓝色像素")

    def test_terrain_consumes_material_textures(self):
        # OF-03.B：地形按材质组消费纹理（UV 采样）——flat 调色板仅 ~640 色，
        # 纹理采样后 color 多样性呈纹理级（世界 ground/grass/clod decal）。
        img = bake.bake_terrain("world_02", size=512)
        colors = img.getcolors(maxcolors=512 * 512)
        self.assertGreater(len(colors), 5000,
                           f"distinct={len(colors)} 仍接近调色板量级（未消费纹理）")


class TestUnitSprites(unittest.TestCase):
    def test_sprite_set_complete(self):
        sprites = bake.bake_unit_sprites(["ant", "littlebeetle", "bee"],
                                         frames=5, yaws=8, size=128)
        keys = {(u, f, y) for u in ("ant", "littlebeetle", "bee")
                for f in range(5) for y in range(8)}
        self.assertEqual(set(sprites), keys)
        img = sprites[("ant", 0, 0)]
        self.assertEqual(img.size, (128, 128))
        self.assertEqual(img.mode, "RGBA")
        # 透明底: 四角 alpha=0
        for corner in ((0, 0), (127, 0), (0, 127), (127, 127)):
            self.assertEqual(img.getpixel(corner)[3], 0, corner)
        # 单位可见: 不透明像素 >300 且质心近图心
        px = img.load()
        opaque = [(x, y) for y in range(128) for x in range(128) if px[x, y][3] > 0]
        self.assertGreater(len(opaque), 300)
        cx = sum(p[0] for p in opaque) / len(opaque)
        cy = sum(p[1] for p in opaque) / len(opaque)
        self.assertLess(abs(cx - 64), 28, f"质心 x={cx:.0f}")
        self.assertLess(abs(cy - 64), 28, f"质心 y={cy:.0f}")

    def test_flower_sprite(self):
        img = bake.bake_flower_sprite(size=128)
        self.assertEqual(img.size, (128, 128))
        px = img.load()
        opaque = sum(1 for y in range(128) for x in range(128) if px[x, y][3] > 0)
        self.assertGreater(opaque, 300)

    def test_bake_sprites_timing(self):
        t0 = time.time()
        bake.bake_unit_sprites(["ant"], frames=2, yaws=4, size=64)
        self.assertLess(time.time() - t0, 120)


class TestScaleAndPitch(unittest.TestCase):
    """OF-03.C：ScaleFactor per-unit 世界比例契约 + 单位精灵斜俯视 pitch。"""

    def test_unit_world_scale_values(self):
        # DATA：bugs/*.vsc ScaleFactor（ant=1.5、bee=1、wasp=1.25、caterpillar=1.25）
        self.assertAlmostEqual(bake.unit_world_scale("ant"), 1.5)
        self.assertAlmostEqual(bake.unit_world_scale("bee"), 1.0)
        self.assertAlmostEqual(bake.unit_world_scale("wasp"), 1.25)
        self.assertAlmostEqual(bake.unit_world_scale("caterpillar"), 1.25)
        # 缺省 1.0：引擎特例（无 buginfos，KeyError）与未知单位
        self.assertAlmostEqual(bake.unit_world_scale("nectarbonus"), 1.0)
        self.assertAlmostEqual(bake.unit_world_scale("no_such_unit"), 1.0)

    def test_unit_world_size(self):
        # NC-03：模型 AABB → 世界单位（不含 ScaleFactor）。ant/littlebeetle 体量比
        # 已知、绝对值与 terrain 同尺度（世界单位）。
        w, h, d = bake.unit_world_size("ant")
        self.assertAlmostEqual(w, 10.74, delta=0.2)
        self.assertAlmostEqual(h, 5.78, delta=0.2)
        self.assertAlmostEqual(d, 9.87, delta=0.2)
        w2, h2, d2 = bake.unit_world_size("littlebeetle")
        self.assertAlmostEqual(w2, 12.57, delta=0.2)
        # 体量比：littlebeetle 宽 > ant 宽（模型 AABB 真实差异，非 fit-to-box 抹平）
        self.assertGreater(w2, w)
        # 缺模型回退：返回正数体量（登记）
        w3, h3, d3 = bake.unit_world_size("no_such_unit")
        self.assertGreater(w3, 0) and self.assertGreater(d3, 0)

    def test_norm_span_semantics(self):
        # NC-03：norm_span 语义——同一姿态按 2× norm_span 渲染 → 内容 bbox 减半
        # （稳定归一化 = 尺度常数，不随姿态自身跨度变化）
        from bugbits import unitdb
        from bugbits.assets import v3d
        spec = unitdb.load_unit("ant")
        rp = bake._resolve_model(spec.model, ".v3d")
        (verts, idx, _k), _skin, _recs, tex_name = v3d.parse_v3d(rp)
        tex = bake._load_texture(tex_name)
        a = bake._render_rgba(verts, idx, tex, 64, yaw=0.0,
                              pitch=bake.UNIT_SPRITE_PITCH_DEG, norm_span=10.0)
        b = bake._render_rgba(verts, idx, tex, 64, yaw=0.0,
                              pitch=bake.UNIT_SPRITE_PITCH_DEG, norm_span=20.0)
        ba, bb = a.split()[3].getbbox(), b.split()[3].getbbox()
        self.assertTrue(ba and bb)
        wa, wb = ba[2] - ba[0], bb[2] - bb[0]
        self.assertAlmostEqual(wa / 2.0, wb, delta=1.5,
                               msg=f"2× norm_span 应减半内容宽: {wa} vs {wb}")

    def test_stable_span_no_yaw_clipping(self):
        # NC-03：pose_screen_span 归一化——全部朝向内容都留在瓦片内
        # （对角朝向 |w·cos|+|d·sin| 可达 √2·AABB 跨度，AABB 归一化会裁剪）
        from bugbits import unitdb
        from bugbits.render import software
        sprites = bake.bake_unit_sprites(["ant"], frames=2, yaws=8, size=64)
        self.assertGreater(len(sprites), 8)
        for (unit, f, y), img in sprites.items():
            bbox = img.split()[3].getbbox()
            self.assertTrue(bbox, f"{unit}.f{f}.y{y} 空白精灵")
            # 0.8 容器 → 10% 边距；光栅化取整留 5%
            self.assertGreaterEqual(bbox[0], 3,
                                    f"{unit}.f{f}.y{y} 左缘裁剪 {bbox}")
            self.assertGreaterEqual(bbox[1], 3,
                                    f"{unit}.f{f}.y{y} 上缘裁剪 {bbox}")
            self.assertLessEqual(bbox[2], 61,
                                 f"{unit}.f{f}.y{y} 右缘裁剪 {bbox}")
            self.assertLessEqual(bbox[3], 61,
                                 f"{unit}.f{f}.y{y} 下缘裁剪 {bbox}")
        # pose_screen_span ≥ AABB 跨度（对角朝向严格大于）
        from bugbits.assets import v3d
        spec = unitdb.load_unit("ant")
        rp = bake._resolve_model(spec.model, ".v3d")
        (verts, _idx, _k), _s, _r, _t = v3d.parse_v3d(rp)
        self.assertGreaterEqual(
            software.pose_screen_span(verts, 8, bake.UNIT_SPRITE_PITCH_DEG),
            software.verts_span(verts))

    def test_bake_atlas_scales(self):
        # NC-03：atlas_scales 回填 = norm_span/(0.8·size)——1 图集像素的世界单位数；
        # 内容世界宽 = cb宽 × asc ≤ 屏幕跨度（同一常数贯穿烘焙与 draw 层）
        asc = {}
        sprites = bake.bake_unit_sprites(["ant"], frames=2, yaws=8, size=64,
                                         atlas_scales=asc)
        self.assertIn("ant", asc)
        self.assertGreater(asc["ant"], 0)
        for (unit, f, y), img in sprites.items():
            bbox = img.split()[3].getbbox()
            content_w_world = (bbox[2] - bbox[0]) * asc["ant"]
            # 64px 瓦片的内容世界宽 ≤ pose_screen_span（0.8 容器内）
            self.assertLess(content_w_world, asc["ant"] * 64.0)
            self.assertGreater(content_w_world, 0.5)

    def test_sprite_pitch_matches_terrain_camera(self):
        from bugbits import unitdb
        from bugbits.assets import v3d
        # 精灵 pitch = -相机 pitch（software.render 绕 X 轴符号相反）
        self.assertEqual(bake.UNIT_SPRITE_PITCH_DEG, -40.0)
        path = bake._resolve_model(unitdb.load_unit("ant").model, ".v3d")
        (verts, idx, _k), _skin, _recs, tex_name = v3d.parse_v3d(path)
        tex = bake._load_texture(tex_name)
        oblique = bake._render_rgba(verts, idx, tex, 64, yaw=0.0, pitch=-40.0)
        topdown = bake._render_rgba(verts, idx, tex, 64, yaw=0.0, pitch=-90.0)
        # 斜俯视 ≠ 俯视（bytes 不同），且两者均非空白（透明底角 + 非零不透明）
        self.assertNotEqual(oblique.tobytes(), topdown.tobytes())
        for img in (oblique, topdown):
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            op = sum(1 for y in range(64) for x in range(64)
                     if img.getpixel((x, y))[3] > 0)
            self.assertGreater(op, 100)

    def test_bind_center_stabilizes_root(self):
        # NC-03A（DR20-03 修复不变量）：烘焙以 bind 姿态 AABB 中心为居中参考点
        # （非逐帧 AABB 中心）→ 根节点(模型原点)屏幕投影跨帧恒定；旧行为（逐帧
        # AABB 中心）随帧漂移。复刻 software.render 的 rot(·) 验证该不变量。
        from bugbits import unitdb
        spec = unitdb.load_unit("ant")
        frame_verts, _, bind_center = bake._unit_frames(spec, 3)

        def root_screen(verts, center):
            if center is None:
                xs = [v[0][0] for v in verts]
                ys = [v[0][1] for v in verts]
                zs = [v[0][2] for v in verts]
                center = ((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2,
                          (max(zs) + min(zs)) / 2)
            cx, cy, cz = center
            a, b = 0.0, math.radians(bake.UNIT_SPRITE_PITCH_DEG)
            x, y, z = -cx, -cy, -cz
            x, z = x * math.cos(a) - z * math.sin(a), x * math.sin(a) + z * math.cos(a)
            y, z = y * math.cos(b) - z * math.sin(b), y * math.sin(b) + z * math.cos(b)
            return (round(x, 6), round(y, 6), round(z, 6))

        new = {root_screen(v, bind_center) for v, _i, _t in frame_verts}
        old = {root_screen(v, None) for v, _i, _t in frame_verts}
        self.assertEqual(len(new), 1, "bind center 应使根节点屏幕位置跨帧恒定")
        self.assertGreater(len(old), 1, "逐帧 AABB center 应使根节点随帧漂移（反例）")

    def test_content_dest_anchor_stable_across_frames(self):
        # NC-03A 端到端回归（round2 缺口 A）：经真实 bake_unit_sprites → 真实 alpha
        # bbox → 真实 content_dest 消费，最终根节点屏幕位置跨帧恒定。独立预期：
        # 根节点（模型原点）在 bind 中心烘焙下落在瓦片内固定位置 r；消费锚点 =
        # 瓦片中心（content_dest 不再接收逐帧 cb）→ 最终位置 p+(r−瓦片中心)·λ
        # 跨帧恒定。旧消费以逐帧 alpha bbox 中心为锚点 → 轮廓不对称帧间漂移。
        from bugbits import unitdb
        from bugbits.render import billboard
        asc = {}
        sprites = bake.bake_unit_sprites(["ant"], frames=6, yaws=1, size=128,
                                         atlas_scales=asc)
        norm_span = asc["ant"] * 0.8 * 128.0
        _, _, bind_center = bake._unit_frames(unitdb.load_unit("ant"), 6)
        size = 128
        sc = size * 0.8 / norm_span
        # 根节点（模型原点）在瓦片内的固定位置（yaw=0：绕 Y 无旋转）
        cx, cy, cz = bind_center
        x, y, z = -cx, -cy, -cz
        b = math.radians(bake.UNIT_SPRITE_PITCH_DEG)
        y, z = y * math.cos(b) - z * math.sin(b), y * math.sin(b) + z * math.cos(b)
        root_sx = x * sc + size / 2.0
        root_sy = -y * sc + size / 2.0
        px, py, lam = 640.0, 360.0, 0.5
        finals, old_anchors = set(), set()
        for f in range(6):
            img = sprites[("ant", f, 0)]
            bbox = img.split()[3].getbbox()
            self.assertTrue(bbox, f"ant.f{f}.y0 空白精灵")
            # 新消费：瓦片中心锚点（content_dest 不含 cb）
            dx, dy, _dw, _dh = billboard.content_dest(
                {"x": 0, "y": 0, "w": size, "h": size}, px, py, lam)
            finals.add((round(dx + root_sx * lam, 6),
                        round(dy + root_sy * lam, 6)))
            # 旧消费（反例）：逐帧 alpha bbox 中心为锚点
            cccx = bbox[0] + (bbox[2] - bbox[0]) / 2.0
            cccy = bbox[1] + (bbox[3] - bbox[1]) / 2.0
            old_anchors.add((round(px + (root_sx - cccx) * lam, 6),
                             round(py + (root_sy - cccy) * lam, 6)))
        self.assertEqual(len(finals), 1, "瓦片中心锚点应使根屏幕位置跨帧恒定")
        self.assertGreater(len(old_anchors), 1,
                           "旧逐帧 alpha bbox 锚点应使根屏幕位置随帧漂移（反例）")


class TestBeeTwoGroupContract(unittest.TestCase):
    """NC-03 bee 双材质样板（TA-ASSET-SURVEY）：世界尺寸/atlasScale 合同逐位回归 +
    身体并入光栅化的 alpha bbox 验收。"""

    def test_world_size_and_atlas_scale_bit_identical(self):
        # worldSize uses the raw 931-vertex bind pool, independent of group
        # indices. The sampled atlas span additionally depends on animation:
        # R369 original row Euler correction invalidates the old transposed
        # span 27.515443011729978. R378's original weight-total division also
        # replaces the prior17.6237555563902 span. These exact values are
        # regression snapshots; independent rotation/weight oracles live in
        # test_original_euler_pose and test_skin_weight_contract.
        # R380 original reference-table mapping replaces the former direct
        # slot/root fallback, including actual animated bee wing nodes3/5.
        from bugbits import web_build
        w, h, d = bake.unit_world_size("bee")
        self.assertEqual((w, h, d),
                         (11.04334831237793, 6.324338108301163, 13.243006229400635))
        clips, norm_span = web_build.render_unit_clips("bee", {}, {}, set())
        self.assertEqual(norm_span, 17.84928612233547)
        atlas_scale = norm_span / (0.8 * 128.0)
        self.assertEqual(atlas_scale, 0.17430943478843233)

    def test_bee_body_rasterized(self):
        # survey §2.2.5：修复后 alpha bbox 覆盖身体（非翼膜窄条），身体三角光栅化。
        from bugbits import web_build
        images = {}
        web_build.render_unit_clips("bee", images, {}, set())
        img = images["bee.bee_flight.f0.y0"]
        bbox = img.split()[3].getbbox()
        self.assertIsNotNone(bbox, "bee 精灵空白")
        bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        # 修复前翼膜窄条 bbox=(41,52,80,68)：高 16；修复后身体并入 → 高显著增大
        self.assertGreater(bh, 40, f"bee 身体未并入（bbox 高={bh}）")
        self.assertGreater(bw, 30, f"bee 身体未并入（bbox 宽={bw}）")
        opaque = sum(1 for y in range(128) for x in range(128)
                     if img.getpixel((x, y))[3] > 0)
        self.assertGreater(opaque, 300, f"bee 身体三角未光栅化（不透明={opaque}）")

    def test_bee_two_group_in_bake_unit_sprites(self):
        # bake_unit_sprites（CLI 烘焙路径）也应走双组：精灵含身体（不透明显著 > 翼膜 144）
        sprites = bake.bake_unit_sprites(["bee"], frames=1, yaws=1, size=128)
        img = sprites[("bee", 0, 0)]
        opaque = sum(1 for y in range(128) for x in range(128)
                     if img.getpixel((x, y))[3] > 0)
        self.assertGreater(opaque, 300, f"bake_unit_sprites bee 身体未光栅化（不透明={opaque}）")

    def test_missing_second_texture_raises(self):
        # 硬约束（survey §2.3）：第二纹理名解不到 data/textures/<名>.vtx → 失败
        # （不允许静默回退单组渲染翼膜窄条）。
        from unittest import mock
        from bugbits import unitdb
        spec = unitdb.load_unit("bee")
        real = bake._load_texture

        def fake(name):
            return None if name == "bee" else real(name)

        with mock.patch.object(bake, "_load_texture", side_effect=fake):
            with self.assertRaises(ValueError):
                bake._unit_frames(spec, 1)

    def test_k2_tex1_textures_enter_consumed_fingerprint(self):
        # NC-03 泛化：6 个 k=2 模型的第二材质纹理（wildbee.vtx / 各模型 wing_a.vtx）
        # 均进入 web_build consumed 指纹（render_unit_clips 泛型 for _, name in groups
        # 循环自动消费 tex1）。光栅化用 stub 跳过（本测试只验 consumed 消费链，
        # 不重复全量渲染——bee=2 组逐位回归锚仍由 test_world_size_and_atlas_scale
        # _bit_identical 全量渲染背书）。
        from unittest import mock
        from PIL import Image
        from bugbits import web_build
        from bugbits.assets import data_dir
        expected_tex1 = {
            "bee": "bee",
            "wildbee": "wildbee",
            "bomberbee": "wing_a",
            "wasp": "wing_a",
            "wasphero": "wing_a",
            "wasphero_tick": "wing_a",
        }
        for unit, tex1 in expected_tex1.items():
            consumed = set()
            with mock.patch.object(bake, "_render_rgba",
                                   return_value=Image.new("RGBA", (128, 128))):
                web_build.render_unit_clips(unit, {}, {}, consumed)
            tex_path = data_dir("textures", tex1 + ".vtx")
            self.assertIn(tex_path, consumed, unit)


if __name__ == "__main__":
    unittest.main()
