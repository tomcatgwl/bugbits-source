"""BugBits 重实现包（Phase 4 垂直切片）。

分层（rules/dev.md D4 纯度）:
  assets/  资源访问层——游戏原始数据只读访问与格式解析的唯一 IO 入口
  sim/     纯模拟核心（T4.4+, 禁 import render/）
  render/  离线渲染（T4.6+）
  cli.py   命令行入口
规则源: CLAUDE.md / rules/ree.md / rules/dev.md。
"""
__version__ = "0.1.0"
