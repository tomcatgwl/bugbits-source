#!/usr/bin/env python3
"""BugBits .vln 语言文件编解码器 CLI（薄壳；实现: src/bugbits/assets/vln.py + vfm.py）。

用法:
  python3 tools/vln_extract.py <lang4.vln>              # TSV 查看 (\\n 转义显示)
  python3 tools/vln_extract.py <lang4.vln> --json out.json   # 无损 JSON 导出
  python3 tools/vln_extract.py --recode in.json out.vln [--chars lang4_chars.vsc]
                                                        # JSON → .vln (round-trip 字节一致)
  python3 tools/vln_extract.py --vfm <file.vfm> [N]     # u16 度量表导出
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.assets import vfm as _vfm  # noqa: E402
from bugbits.assets import vln  # noqa: E402

# re-export（research/ 与 harness 兼容原公共名; dump_vfm 移居 assets/vfm）
CHARS_FILENAME = vln.CHARS_FILENAME  # noqa: F401
VlnError = vln.VlnError  # noqa: F401
load_charset = vln.load_charset  # noqa: F401
h3_decode = vln.h3_decode  # noqa: F401
h3_encode = vln.h3_encode  # noqa: F401
decode_value = vln.decode_value  # noqa: F401
encode_value = vln.encode_value  # noqa: F401
parse_vln = vln.parse_vln  # noqa: F401
encode_vln = vln.encode_vln  # noqa: F401
dump_vfm = _vfm.dump_vfm  # noqa: F401


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    if args[0] == "--vfm":
        vals = dump_vfm(args[1], int(args[2]) if len(args) > 2 else None)
        for i, v in enumerate(vals):
            print(f"{i:4d}  {v:5d} (0x{v:04x})")
        return 0
    if args[0] == "--recode":
        # --recode in.json out.vln [--chars path]
        in_json, out_vln = args[1], args[2]
        chars = args[args.index("--chars") + 1] if "--chars" in args else None
        with open(in_json, "r", encoding="utf-8") as f:
            doc = json.load(f)
        chars = chars or doc.get("meta", {}).get("charset")
        table = doc["entries"] if "entries" in doc else doc
        blob = encode_vln(dict(table), chars)
        with open(out_vln, "wb") as f:
            f.write(blob)
        print(f"# {len(table)} 条 → {out_vln} ({len(blob)} 字节)", file=sys.stderr)
        return 0
    path = args[0]
    table = parse_vln(path)
    if "--json" in args:
        out = args[args.index("--json") + 1]
        doc = {
            "meta": {"source": os.path.basename(path), "charset": os.path.join(
                os.path.dirname(path) or ".", CHARS_FILENAME)},
            "entries": [[k, v] for k, v in table.items()],
        }
        with open(out, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        print(f"# {len(table)} 条 → {out}", file=sys.stderr)
        return 0
    nl = "\\n"
    for k, v in table.items():
        print(f"{k}\t{v.replace(chr(10), nl)}")
    print(f"# 共 {len(table)} 条", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
