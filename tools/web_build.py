#!/usr/bin/env python3
"""Web 构建入口（W1；实现: src/bugbits/web_build.py）。

用法:
  python3 tools/web_build.py --profile slice --out out/web
  python3 tools/web_build.py --profile full --out out/web
  python3 tools/web_build.py --profile slice --out DIR --data-root ROOT  # 覆盖数据根
  python3 tools/web_build.py --validate out/web                          # 只读校验
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits import web_build  # noqa: E402


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 1
    if argv[0] == "--validate":
        if len(argv) != 2:
            print("用法: --validate <dir>", file=sys.stderr)
            return 2
        errors = web_build.validate(argv[1])
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        print("校验: " + ("通过" if not errors else f"{len(errors)} 项错误"))
        return 0 if not errors else 1
    profile = out = data_root = None
    it = iter(argv)
    for a in it:
        if a == "--profile":
            profile = next(it, None)
        elif a == "--out":
            out = next(it, None)
        elif a == "--data-root":
            data_root = next(it, None)
        else:
            print(f"未知参数: {a}\n{__doc__}", file=sys.stderr)
            return 2
    if profile not in ("slice", "full") or not out:
        print(__doc__, file=sys.stderr)
        return 2
    mf = web_build.export(out, profile, data_root=data_root)
    errs = web_build.validate(out)
    print(f"构建: profile={profile} buildId={mf['buildId'][:16]}… "
          f"files={len(mf['files'])} levels={len(mf['levels'])} → {out}")
    print(f"校验: {'通过' if not errs else str(len(errs)) + ' 项错误'}")
    for e in errs:
        print(f"  ✗ {e}", file=sys.stderr)
    return 0 if not errs else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
