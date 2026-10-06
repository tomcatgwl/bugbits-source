#!/usr/bin/env python3
"""BugBits 包 CLI 启动器（薄壳；实现: src/bugbits/cli.py）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bugbits.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
