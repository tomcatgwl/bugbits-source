"""资源访问层：游戏原始数据（只读基线）访问的唯一入口（D4: sim/render 只经此处碰 IO）。"""
import os


def game_root():
    """游戏安装根目录（含 data/ 与 exe）。env BUGBITS_DATA 优先。

    缺省从包位置推导: src/bugbits/assets/__init__.py 上溯 3 级 = 仓库根,
    拼 analyze/extracted/ccdzz（与 research/harness 的既有缺省一致）。
    """
    env = os.environ.get("BUGBITS_DATA")
    if env:
        return env
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(os.path.dirname(os.path.dirname(pkg_dir)))
    return os.path.join(repo, "analyze", "extracted", "ccdzz")


def data_dir(*parts):
    """游戏 data/ 下子路径 → 绝对路径。"""
    return os.path.join(game_root(), "data", *parts)
