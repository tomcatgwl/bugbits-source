#!/usr/bin/env python3
"""BugBits .vfm 字体度量导出器（薄壳；实现: src/bugbits/assets/vfm.py）。

.vfm 格式（harness 断言背书, 详见 docs/formats/vfm.md）:
  u16 LE 数组, 每槽一个步进宽度值; 槽空间 = 字体字符集槽位
  （低槽 ASCII 兼容 + 控制槽; CJK 槽默认 48 等宽; CN 为 12 位槽 4096 项）。

用法:
  python3 tools/vfm_dump.py <file.vfm> [--special]   # 全表 / 仅非默认槽
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.assets.vfm import dump_vfm  # noqa: E402


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    vals = dump_vfm(args[0])
    default = max(set(vals), key=vals.count)  # 众数 = 默认步进 (CJK=48)
    if "--special" in args:
        sp = [(i, v) for i, v in enumerate(vals) if v != default]
        print(f"# 默认步进={default}, 非默认槽 {len(sp)} 个")
        for i, v in sp:
            note = chr(i) if 32 <= i < 127 else ""
            print(f"  槽 {i:4d} = {v:3d} {note}")
        return 0
    for i, v in enumerate(vals):
        mark = "" if v == default else " *"
        print(f"{i:5d}  {v:5d}{mark}")
    print(f"# {len(vals)} 槽, 默认步进={default}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
