"""BugBits .vfm 字体度量表访问（dump_vfm 从 tools/vln_extract.py 迁移, T4.1）。

格式（harness 断言背书, 详见 docs/formats/vfm.md）:
  u16 LE 数组, 每槽一个步进宽度值; 槽空间 = 字体字符集槽位
  （低槽 ASCII 兼容 + 控制槽; CJK 槽默认 48 等宽; CN 为 12 位槽 4096 项）。
"""
import struct

from bugbits.assets.vln import VlnError


def dump_vfm(path, count=None):
    """导出 .vfm 原始 u16 表。返回 u16 列表。"""
    with open(path, "rb") as f:
        blob = f.read()
    if len(blob) % 2:
        raise VlnError(f"{path}: 长度 {len(blob)} 非 2 的倍数")
    vals = struct.unpack(f"<{len(blob)//2}H", blob)
    return list(vals[:count]) if count else list(vals)
