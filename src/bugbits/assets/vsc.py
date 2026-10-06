#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BugBits .vsc 脚本解析库（从 tools/vsc_parse.py 逐字迁移, T4.1）。

格式（harness 断言背书）:
  纯文本, CRLF 行尾, 每行一条命令: `命令 参数...`
  顶层命令词表(封闭): sp char SpawnEntity Script SetLanes BugSetup UnlockLevel
                      setlight menumode
  Script 行内嵌子命令(引号包裹): addhint removehint sendenemy sendplayer setflow
                      sethintfreq setlight sp wait waituntilnectar
"""
import re
from collections import Counter

TOP_COMMANDS = {
    "sp", "char", "SpawnEntity", "Script", "SetLanes",
    "BugSetup", "UnlockLevel", "setlight", "menumode",
    ">", "<",  # 对象块标记: > "名字" 开块, < 闭块 (世界文件的 SpawnEntity 附加属性; init*.vsc 整文件为树)
    "ConnectTo",  # 对象块内: 连接 waypoint → path (727 处)
}
SCRIPT_SUBCOMMANDS = {
    "addhint", "removehint", "sendenemy", "sendplayer", "setflow",
    "sethintfreq", "setlight", "sp", "wait", "waituntilnectar",
}


class VscError(ValueError):
    pass


def tokenize(line):
    """按空白切分, 引号内为一个 token。"""
    return re.findall(r'"[^"]*"|[^\s]+', line)


def parse_vsc(path):
    """解析 .vsc → 命令元组列表 [(行号, cmd, args), ...]。

    两种方言:
      命令式 (bugs/levels/worlds/buginfos): `sp 名 值` / `BugSetup ...` 等
      树状式 (init.vsc/initeditor.vsc): 首命令 root, 节点用 `>`/`<` 缩进
    """
    cmds = []
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8", errors="strict") if _is_utf8(raw) else raw.decode("gbk", errors="strict")
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        toks = tokenize(line)
        cmds.append((lineno, toks[0], [t.strip('"') for t in toks[1:]]))
    return cmds


def is_tree_dialect(cmds):
    """首条命令为 root → 树状方言（UI 树定义, 属性行任意, 不做词表校验）。"""
    return bool(cmds) and cmds[0][1] == "root"


def _is_utf8(raw):
    try:
        raw.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def validate(path):
    """校验: 词表封闭 + Script 子命令合法。返回 (命令计数器, 警告列表)。

    树状方言跳过词表校验（语法不同: root/>/< + 任意属性行）。
    """
    cmds = parse_vsc(path)
    counter, warns = Counter(), []
    if is_tree_dialect(cmds):
        for lineno, cmd, args in cmds:
            counter[cmd] += 1
        return counter, warns
    for lineno, cmd, args in cmds:
        counter[cmd] += 1
        if cmd not in TOP_COMMANDS:
            warns.append(f"{path}:{lineno} 未知顶层命令 {cmd!r}")
        if cmd == "Script" and args:
            # Script 的参数是单个引号串: "sendenemy ant 0 null 9" → 子命令 = 首词
            sub = args[0].split()[0] if args[0].split() else ""
            if sub not in SCRIPT_SUBCOMMANDS:
                warns.append(f"{path}:{lineno} 未知 Script 子命令 {sub!r}")
    return counter, warns
