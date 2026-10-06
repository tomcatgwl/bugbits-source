"""T4.1: assets/vsc——分词/解析/校验（真实数据 + 合成用例）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.assets import data_dir  # noqa: E402
from bugbits.assets import vsc  # noqa: E402


class TestTokenize(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(vsc.tokenize("BugSetup 0 ant 100"),
                         ["BugSetup", "0", "ant", "100"])

    def test_quoted_script_arg(self):
        toks = vsc.tokenize('Script "sendenemy ant 0 null 9"')
        self.assertEqual(toks, ["Script", '"sendenemy ant 0 null 9"'])


class TestParseVsc(unittest.TestCase):
    def test_bug_script(self):
        cmds = vsc.parse_vsc(data_dir("scripts", "bugs", "ant.vsc"))
        self.assertTrue(cmds)
        heads = {c for _, c, _ in cmds}
        self.assertIn("sp", heads)          # 虫属性定义
        self.assertTrue(heads <= vsc.TOP_COMMANDS)

    def test_char_table(self):
        cmds = vsc.parse_vsc(data_dir("scripts", "lang4_chars.vsc"))
        chars = [a for _, c, a in cmds if c == "char"]
        self.assertTrue(chars)
        first = chars[0]
        self.assertEqual(len(first), 2)
        int(first[0], 16)  # 码点为十六进制
        int(first[1])      # 字形号为十进制
        self.assertTrue(all(len(a) == 2 for a in chars))

    def test_level_validate_clean(self):
        counter, warns = vsc.validate(data_dir("scripts", "levels", "level_02.vsc"))
        self.assertEqual(warns, [])
        self.assertTrue(counter["BugSetup"] >= 1)

    def test_tree_dialect(self):
        cmds = vsc.parse_vsc(data_dir("scripts", "init.vsc"))
        self.assertTrue(vsc.is_tree_dialect(cmds))
        cmds2 = vsc.parse_vsc(data_dir("scripts", "bugs", "ant.vsc"))
        self.assertFalse(vsc.is_tree_dialect(cmds2))


if __name__ == "__main__":
    unittest.main()
