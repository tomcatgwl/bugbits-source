#!/usr/bin/env python3
"""BugBits .vtx 批量 PNG 转换器（薄壳；实现: src/bugbits/assets/vtx.py）。

用法:
  python3 tools/vtx2png.py <game_dir>/data/textures <out_dir>
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.assets.vtx import (  # noqa: E402,F401  (re-export: research/ 与 harness 兼容)
    TGA_FOOTER, VTX_HEADER, VtxError, convert_tree, inspect_vtx, parse_vtx,
)


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    ok, fails = convert_tree(sys.argv[1], sys.argv[2])
    print(f"转换完成: {ok} 成功, {len(fails)} 失败")
    for rel, err in fails:
        print(f"  ✗ {rel}: {err}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
