"""ant 渲染回归快照（REVIEW 修正逆矩阵和行向量蒙皮顺序后重建并查看）。

不与已知错误的 t22 管线求 parity；不把像素 hash 作为原作正确性证明。
独立几何依据见 test_review_foundations；图像只防后续意外变化。
T7.5（2026-09-16）：skin_at 开始变换法线（刚体旋转+重归一化）→ 光照变化，
本文件 MD5 快照随之更新（几何不变，tris=1608 断言不变）。
R369（2026-10-06）：原402AC0/44D170证实Euler为raw row Rx×Ry×Rz，
纠正旧转置后重新查看两幅离线图并更新精确hash。原先失败日志保留，
独立正确性回归在test_original_euler_pose；图片不是原作同帧或网页验收。
R380：原声明节点/引用表取代scanner下标，原错误映射生成的hash失效；
新hash来自真实管线快照，独立原表与NULL反例见test_skin_reference_contract。
"""
import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from PIL import Image  # noqa: E402

from bugbits.assets import data_dir  # noqa: E402
from bugbits.assets import pose, v3d, van, vtx  # noqa: E402
from bugbits.render import software  # noqa: E402


def _pipeline(t):
    (verts, idx, k), skin, recs, tex_name = v3d.parse_v3d(
        data_dir("models", "bugs", "ant.v3d"))
    blocks = van.parse_van(data_dir("models", "bugs", "ant_walk.van"))
    bind = pose.worlds_from_records(recs)
    return pose.skin_at(skin, bind, pose.worlds_at(recs, blocks, t)), idx


class TestSmokeAnt(unittest.TestCase):
    def test_bind_frame(self):
        posed, idx = _pipeline(0.0)
        dummy = Image.new("RGBA", (1, 1))
        img, tris = software.render(posed, idx, dummy, use_tex=False, size=160)
        self.assertEqual(tris, 1608)
        # NC-04：render 输出 RGBA；不透明 no-tex 路径 RGB 逐位一致（回归锚），
        # 故 MD5 取 convert("RGB")——与原 RGB 输出逐字节相同。
        self.assertEqual(hashlib.md5(img.convert("RGB").tobytes()).hexdigest(),
                         "f137ae218f0809c6c292adcec894b152")

    def test_walk50_frame(self):
        blocks = van.parse_van(data_dir("models", "bugs", "ant_walk.van"))
        posed, idx = _pipeline(blocks[0][-1][0] * 0.5)
        dummy = Image.new("RGBA", (1, 1))
        img, tris = software.render(posed, idx, dummy, use_tex=False, size=160)
        self.assertEqual(tris, 1608)
        self.assertEqual(hashlib.md5(img.convert("RGB").tobytes()).hexdigest(),
                         "7124ab914025cda0b9510aba2f75f1ce")

    def test_ascii_preview(self):
        posed, idx = _pipeline(0.0)
        dummy = Image.new("RGBA", (1, 1))
        img, _ = software.render(posed, idx, dummy, use_tex=False, size=160)
        text = software.ascii_preview(img)
        self.assertIn("\n", text)
        self.assertTrue(all(c in " .:-=+*#%@" or c == "\n" for c in text))


class TestCli(unittest.TestCase):
    def test_info_returns_zero(self):
        from bugbits import cli
        self.assertEqual(cli.main(["info"]), 0)

    def test_unknown_command(self):
        from bugbits import cli
        self.assertNotEqual(cli.main(["no-such-cmd"]), 0)


if __name__ == "__main__":
    unittest.main()
