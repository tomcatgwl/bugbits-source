"""T4.1: assets/vtx——真实数据结构断言（三种头布局变体 + 错误路径）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.assets import data_dir  # noqa: E402
from bugbits.assets import vtx  # noqa: E402


class TestParseVtx(unittest.TestCase):
    def test_ant_standard_16b_header(self):
        w, h, ow, oh, img = vtx.parse_vtx(data_dir("textures", "ant.vtx"))
        self.assertEqual((w, h, ow, oh), (128, 128, 128, 128))
        self.assertEqual(img.size, (128, 128))
        self.assertEqual(img.mode, "RGBA")
        self.assertEqual(os.path.getsize(data_dir("textures", "ant.vtx")), 16 + 128 * 128 * 4)

    def test_stagbeetle_8b_header_variant(self):
        info = vtx.inspect_vtx(data_dir("textures", "stagbeetle.vtx"))
        self.assertEqual(info["header_len"], 8)
        self.assertEqual((info["w"], info["h"]), (256, 256))
        self.assertEqual((info["ow"], info["oh"]), (256, 256))
        self.assertFalse(info["footer"])

    def test_cn_tga_footer_variant(self):
        info = vtx.inspect_vtx(data_dir("textures", "fonts", "menufont_01_cn.vtx"))
        self.assertEqual(info["header_len"], 16)
        self.assertEqual((info["w"], info["h"]), (2048, 2048))
        self.assertTrue(info["footer"])

    def test_lowres_cn_no_footer(self):
        info = vtx.inspect_vtx(data_dir("textures", "fonts", "menufont_01_lowres_cn.vtx"))
        self.assertFalse(info["footer"])
        self.assertEqual((info["w"], info["h"]), (1024, 1024))


class TestBugIcons(unittest.TestCase):
    """OF-04：兵种图标（gui/main/maingui_bug_*.vtx）覆盖 20 本体单位，_tick 无图标。"""

    def test_icons_cover_buyable_units_not_tick(self):
        import os
        gui = os.path.join(data_dir("textures"), "gui", "main")
        icons = {f[len("maingui_bug_"):-4] for f in os.listdir(gui)
                 if f.startswith("maingui_bug_") and f.endswith(".vtx")}
        # 20 本体单位，无 _tick 坐骑变体
        self.assertEqual(len(icons), 20)
        self.assertTrue(all(not u.endswith("_tick") for u in icons))
        self.assertEqual(icons & {"ant", "littlebeetle", "wasp", "bee"},
                         {"ant", "littlebeetle", "wasp", "bee"})

    def test_icon_is_120px_rgba(self):
        img = vtx.parse_vtx(data_dir("textures", "gui", "main",
                                     "maingui_bug_ant.vtx"))[4]
        self.assertEqual(img.size, (120, 120))
        self.assertEqual(img.mode, "RGBA")


class TestVtxError(unittest.TestCase):
    def test_truncated(self):
        path = "/tmp/bugbits_test_trunc.vtx"
        with open(path, "wb") as f:
            f.write(b"\x00" * 4)
        self.assertRaises(vtx.VtxError, vtx.parse_vtx, path)

    def test_non_pot(self):
        path = "/tmp/bugbits_test_nonpot.vtx"
        with open(path, "wb") as f:
            f.write((100).to_bytes(4, "little") + (100).to_bytes(4, "little"))
        self.assertRaises(vtx.VtxError, vtx.parse_vtx, path)


if __name__ == "__main__":
    unittest.main()
