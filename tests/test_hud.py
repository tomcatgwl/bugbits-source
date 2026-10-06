"""T4.6b: HUD——字图集排版（步进与 .vfm 一致）+ 三层 UI 几何。"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from PIL import Image  # noqa: E402

from bugbits.render.ui import component, font, layout, shell  # noqa: E402


class TestFontAtlas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = font.FontAtlas.load_cn()

    def test_text_width_matches_vfm(self):
        # 虫虫大作战 = 5×48; "1.07" = 22+16+22+22
        self.assertEqual(self.f.text_width("虫虫大作战"), 5 * 48)
        self.assertEqual(self.f.text_width("1.07"), 22 + 16 + 22 + 22)

    def test_fullwidth_space_48(self):
        # 全角空格 U+3000 → 字形 133 → 步进 48（vfm.md 判别锚点）
        self.assertEqual(self.f.text_width("　"), 48)

    def test_glyph_cell_has_ink(self):
        # '虫' = 字形 756 → 格 (756%32, 756//32); 该格非空
        cell = self.f.glyph_cell("虫")
        px = cell.load()
        ink = sum(1 for x in range(0, 64, 4) for y in range(0, 64, 4) if px[x, y][3] > 0)
        self.assertGreater(ink, 5)

    def test_draw_text_ink_and_extent(self):
        img = Image.new("RGBA", (600, 128), (0, 0, 0, 0))
        self.f.draw_text(img, (10, 10), "虫虫大作战")
        px = img.load()
        xs = [x for y in range(128) for x in range(600) if px[x, y][3] > 0]
        self.assertTrue(xs)
        self.assertGreaterEqual(min(xs), 10)
        self.assertLessEqual(max(xs), 10 + 5 * 64)      # 不超 5 格宽
        ink = sum(1 for y in range(128) for x in range(600) if px[x, y][3] > 0)
        self.assertGreater(ink, 200)

    def test_newline_advances(self):
        img = Image.new("RGBA", (600, 300), (0, 0, 0, 0))
        self.f.draw_text(img, (10, 10), "虫\n虫")
        px = img.load()
        rows = [y for y in range(300) for x in range(600) if px[x, y][3] > 0]
        self.assertGreater(max(rows) - min(rows), 64)   # 两行分离


class TestLayoutAndWidgets(unittest.TestCase):
    def test_panel_columns_even(self):
        p = layout.Panel(0, 400, 512, 96)
        cols = p.columns(3, margin=8)
        self.assertEqual(len(cols), 3)
        self.assertEqual(cols[0].x, 8)
        self.assertEqual(cols[1].x - cols[0].x, cols[2].x - cols[1].x)   # 等距
        for c in cols:
            self.assertEqual(c.h, 96 - 2 * 8)
            self.assertEqual(c.y, 408)

    def test_hud_overlay_widgets(self):
        f = font.FontAtlas.load_cn()
        snap = {"nectar": 13, "title": "新的战场！",
                "buy": [("工蚁", 0, True), ("小型甲虫", 3, True), ("蜜蜂", 3, False)],
                "hint": "敌方的巢穴还在建筑中。"}
        hud = shell.Hud(f)
        ov = hud.render(snap, (512, 512))
        self.assertEqual(ov.size, (512, 512))
        self.assertEqual(ov.mode, "RGBA")
        px = ov.load()
        ink = sum(1 for x in range(0, 512, 2) for y in range(0, 512, 2) if px[x, y][3] > 0)
        self.assertGreater(ink, 100, "HUD 无墨迹")

    def test_hud_frame_budget_with_scene(self):
        # 出口: 单帧预算 <2s（scene 合成 + HUD 叠层）
        from bugbits.render import bake, scene as scenemod
        f = font.FontAtlas.load_cn()
        terrain = bake.bake_terrain("world_02", size=256)
        sprites = bake.bake_unit_sprites(["ant"], frames=1, yaws=2, size=64)
        sc = scenemod.Scene(terrain, sprites, bounds=(-350, 353, -409, 396))
        hud = shell.Hud(f)
        snap = {"nectar": 13, "title": "新的战场！",
                "buy": [("工蚁", 0, True)], "hint": "提示"}
        t0 = time.time()
        frame = sc.compose_frame([("ant", 0, 0, 0.0)], flowers=[], hives=[])
        frame.paste(hud.render(snap, frame.size), (0, 0), hud.render(snap, frame.size))
        self.assertLess(time.time() - t0, 2.0)

    def test_ui_no_sim_import(self):
        # D4 纯度: render/ui/ 不得 import sim（HUD 只读快照 dict）
        import bugbits.render.ui as uipkg
        for mod in (font, layout, component, shell):
            src = open(mod.__file__, encoding="utf-8").read()
            self.assertNotIn("bugbits.sim", src, mod.__name__)


if __name__ == "__main__":
    unittest.main()
