"""T4.1: assets/vln + vfm——真实数据全量断言（harness 已钉的值在此单测化）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.assets import data_dir  # noqa: E402
from bugbits.assets import vfm, vln  # noqa: E402

LANG4 = data_dir("scripts", "lang4.vln")
CHARS = data_dir("scripts", "lang4_chars.vsc")


class TestVln(unittest.TestCase):
    def test_parse_full_table(self):
        table = vln.parse_vln(LANG4)
        self.assertEqual(len(table), 541)
        self.assertTrue(table["GAME_TITLE"].startswith("虫虫大作战　1.07"))

    def test_roundtrip_bytes(self):
        with open(LANG4, "rb") as f:
            blob = f.read()
        self.assertEqual(vln.encode_vln(vln.parse_vln(LANG4), CHARS), blob)

    def test_h3_roundtrip(self):
        for g in (255, 256, 1000, 4095):
            self.assertEqual(vln.h3_decode(vln.h3_encode(g)), g)


class TestVfm(unittest.TestCase):
    def test_menufont_en_256_slots(self):
        en = vfm.dump_vfm(data_dir("fontmetrics", "menufont_01.vfm"))
        self.assertEqual(len(en), 256)
        self.assertEqual(en[10], 0)   # LF 槽
        self.assertEqual(en[13], 0)   # CR 槽

    def test_menufont_cn_4096_slots(self):
        cn = vfm.dump_vfm(data_dir("fontmetrics", "menufont_01_cn.vfm"))
        self.assertEqual(len(cn), 4096)
        self.assertEqual(cn[46], 16)          # 句点最窄
        self.assertEqual(cn[133], 48)         # 全角空格 (字形 133 = U+3000)
        self.assertTrue(all(v == 48 for i, v in enumerate(cn) if i >= 126))


if __name__ == "__main__":
    unittest.main()
