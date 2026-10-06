#!/usr/bin/env python3
"""BugBits .vsc 脚本校验器（薄壳；实现: src/bugbits/assets/vsc.py）。

用法:
  python3 tools/vsc_parse.py <file.vsc> [--stats]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.assets.vsc import (  # noqa: E402,F401
    SCRIPT_SUBCOMMANDS, TOP_COMMANDS, VscError, is_tree_dialect, parse_vsc,
    tokenize, validate,
)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    counter, warns = validate(sys.argv[1])
    for cmd, n in counter.most_common():
        print(f"{n:5d}  {cmd}")
    for w in warns:
        print("⚠", w)
    return 1 if warns else 0


if __name__ == "__main__":
    sys.exit(main())
