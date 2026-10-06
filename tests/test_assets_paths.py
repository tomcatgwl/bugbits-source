"""T4.1: assets 路径层——game_root/data_dir 解析与关键资产存在性。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.assets import data_dir, game_root  # noqa: E402


class TestGameRoot(unittest.TestCase):
    def test_default_root_has_data(self):
        # 缺省根必须含 data/（本机布局 = 仓库根/analyze/extracted/ccdzz）
        self.assertTrue(os.path.isdir(os.path.join(game_root(), "data")))

    def test_env_override(self):
        # BUGBITS_DATA 覆盖后指向同一根，语义不变（只读环境探测）
        old = os.environ.get("BUGBITS_DATA")
        try:
            os.environ["BUGBITS_DATA"] = game_root()
            self.assertTrue(os.path.isdir(os.path.join(game_root(), "data")))
        finally:
            if old is None:
                os.environ.pop("BUGBITS_DATA", None)
            else:
                os.environ["BUGBITS_DATA"] = old


class TestDataDir(unittest.TestCase):
    def test_key_assets_exist(self):
        for rel in [("models", "bugs", "ant.v3d"),
                    ("models", "bugs", "ant_walk.van"),
                    ("textures", "ant.vtx"),
                    ("scripts", "lang4.vln"),
                    ("scripts", "lang4_chars.vsc"),
                    ("scripts", "levels", "level_02.vsc"),
                    ("scripts", "bugs", "ant.vsc"),
                    ("fontmetrics", "menufont_01_cn.vfm")]:
            self.assertTrue(os.path.isfile(data_dir(*rel)), str(rel))

    def test_inventory_counts(self):
        def count(sub, ext):
            n = 0
            for _, _, fs in os.walk(data_dir(sub)):
                n += sum(1 for f in fs if f.endswith(ext))
            return n
        self.assertEqual(count("models", ".v3d"), 41)
        self.assertEqual(count("models", ".van"), 87)
        self.assertEqual(count("fontmetrics", ".vfm"), 13)


if __name__ == "__main__":
    unittest.main()
