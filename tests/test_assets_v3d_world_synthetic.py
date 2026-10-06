"""RF-03：世界多材质组索引流的确定性解析（128B 步长）合成 fixture 与负例。

独立预期：合成字节流的空间位置/索引由测试自造，不反抄解析器输出。覆盖：
  - 多组几何（各组空间位置明确）完整解析
  - gap 内伪合法索引序列不取错组（确定性步长免疫伪序列）
  - 截断 / 缺组 / 越界索引 / 错误计数 → 拒绝并抛 ValueError（诊断）
"""
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.assets import v3d  # noqa: E402


def _u32(v):
    return struct.pack("<I", v)


def _vert(i):
    return (struct.pack("<3f", float(i), 0.0, float(i))
            + struct.pack("<3f", 0.0, 1.0, 0.0)
            + struct.pack("<I", 0xFFFFFFFF)
            + struct.pack("<2f", 0.0, 0.0))


def _group(indices):
    return _u32(len(indices)) + struct.pack(f"<{len(indices)}H", *indices)


def _build_world(meshes, gap_extra=b"", truncate=None):
    """最小世界 .v3d。meshes=[(name, n_verts, [idx0, idx1, ...])]（k=len(groups)）。

    gap_extra：注入到 128B 组间 gap（纹理名之后）的额外字节（如伪合法序列）。
    truncate：截断到该字节数（模拟缺组/截断）。
    """
    out = bytearray()
    out += _u32(len(meshes))
    for (name, nv, groups) in meshes:
        out += _u32(len(name))
        out += name.encode()
        m = [0.0] * 16
        m[0] = m[5] = m[10] = m[15] = 1.0
        out += struct.pack("<16f", *m)
        out += struct.pack("<iI", -1, 0)           # parent=-1, ext=0
        out += _u32(nv)
        for i in range(nv):
            out += _vert(i)
        out += _u32(len(groups))                    # k
        out += _group(groups[0])
        gap = bytearray(b"mat_a\x00" + gap_extra)
        while len(gap) < v3d.WORLD_GROUP_STRIDE:
            gap += b"\x00"
        out += bytes(gap)                           # 128B 组间 gap
        for g in groups[1:]:
            out += _group(g)
    blob = bytes(out)
    return blob[:truncate] if truncate is not None else blob


def _parse(blob):
    with tempfile.NamedTemporaryFile(suffix=".v3d", delete=False) as f:
        f.write(blob)
        path = f.name
    try:
        return v3d.parse_world_meshes(path)
    finally:
        os.unlink(path)


class TestReadWorldGroup(unittest.TestCase):
    """_read_world_group 孤立负例。"""

    def _call(self, ic, indices, vc):
        blob = _u32(ic) + struct.pack(f"<{len(indices)}H", *indices)
        return v3d._read_world_group(blob, 0, vc, "m")

    def test_valid(self):
        ic, idx, end = self._call(3, [0, 1, 2], 5)
        self.assertEqual(ic, 3)
        self.assertEqual(tuple(idx), (0, 1, 2))
        self.assertEqual(end, 4 + 3 * 2)

    def test_rejects_wrong_count(self):
        with self.assertRaises(ValueError):
            self._call(4, [0, 1, 2, 3], 5)          # 4 % 3 != 0

    def test_rejects_out_of_range_index(self):
        with self.assertRaises(ValueError):
            self._call(3, [0, 1, 9], 5)             # 9 >= vc=5

    def test_rejects_truncated(self):
        blob = _u32(6) + struct.pack("<2H", 0, 1)   # 声称 6 索引只给 2
        with self.assertRaises(ValueError):
            v3d._read_world_group(blob, 0, 5, "m")

    def test_rejects_offset_oob(self):
        with self.assertRaises(ValueError):
            v3d._read_world_group(b"\x00", 10, 5, "m")


class TestParseWorldMeshesSynthetic(unittest.TestCase):
    """parse_world_meshes 级合成 fixture（多组 + 负例）。"""

    def test_multi_group_complete_geometry(self):
        # nv=12，group0 覆盖低 z 顶点 0..3，group1 覆盖高 z 顶点 6..9
        blob = _build_world([("ground", 12, [
            [0, 1, 2, 0, 2, 3],        # ic0=6 → 顶点 {0,1,2,3}
            [6, 7, 8, 6, 8, 9],        # ic1=6 → 顶点 {6,7,8,9}
        ])])
        meshes = _parse(blob)
        self.assertEqual(len(meshes), 1)
        m = meshes[0]
        self.assertEqual(m.name, "ground")
        self.assertEqual(m.k, 2)
        self.assertEqual(m.ic, 12)                              # ic0 + ic1
        self.assertEqual(set(m.indices), {0, 1, 2, 3, 6, 7, 8, 9})  # 两组都读到
        # 空间位置：两组分别覆盖低/高 z 顶点
        lo = [m.verts[i][0][2] for i in (0, 1, 2, 3)]
        hi = [m.verts[i][0][2] for i in (6, 7, 8, 9)]
        self.assertLess(max(lo), min(hi))

    def test_pseudo_gap_sequence_ignored(self):
        # 128B gap 内注入伪合法 [ic=3][4,5,3]——4/5 不在真实组，确定性步长须跳过
        # 伪序列、读真实 group1（若误读伪序列，4/5 会混入 indices）
        pseudo = _u32(3) + struct.pack("<3H", 4, 5, 3)
        blob = _build_world([("ground", 12, [
            [0, 1, 2, 0, 2, 3],
            [6, 7, 8, 6, 8, 9],
        ])], gap_extra=pseudo)
        m = _parse(blob)[0]
        self.assertEqual(m.ic, 12)                              # 不吞伪序列 3 索引
        self.assertEqual(set(m.indices), {0, 1, 2, 3, 6, 7, 8, 9})  # 无 4/5

    def test_rejects_missing_group_truncation(self):
        # k=2 但 group1 被截断（在 128B gap 之后截断）→ 缺组/截断
        full = _build_world([("ground", 12, [
            [0, 1, 2, 0, 2, 3],
            [6, 7, 8, 6, 8, 9],
        ])])
        # 截断到 group1 的 ic 之前（idx0 结束 + 128B gap 处）
        # idx0 结束 = 8+5+64+8 + 4 + 36*12 + 8 + 6*2；此处直接按结构计算：
        # 头 8 + record(4+5+64+8=81) + vc(4) + verts(12*36) + k(4) + ic0(4) + idx0(12)
        idx0_end = 8 + 81 + 4 + 12 * 36 + 8 + 6 * 2
        with self.assertRaises(ValueError):
            _parse(full[:idx0_end + v3d.WORLD_GROUP_STRIDE + 2])  # 只给 group1 半个 ic

    def test_rejects_out_of_range_index(self):
        blob = _build_world([("ground", 12, [
            [0, 1, 2, 0, 2, 3],
            [6, 7, 99, 6, 99, 8],        # 99 >= vc=12
        ])])
        with self.assertRaises(ValueError):
            _parse(blob)

    def test_rejects_wrong_group_count(self):
        blob = _build_world([("ground", 12, [
            [0, 1, 2, 0, 2, 3],
            [6, 7, 8, 6],                # ic1=4, 4%3 != 0
        ])])
        with self.assertRaises(ValueError):
            _parse(blob)


if __name__ == "__main__":
    unittest.main()
