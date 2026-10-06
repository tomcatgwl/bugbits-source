#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BugBits .vln 语言文件编解码库（从 tools/vln_extract.py 逐字迁移, T4.1）。

.vln 格式（harness 断言背书, 详见 docs/formats/vln.md）:
  KEY\\0VALUE\\0 交替的二进制字符串表; 键为 ASCII。
  值为「字形序号」编码流, 字形→码点映射来自同目录 lang4_chars.vsc:
    - 字节 0x01-0xFE: 字形序号 = 字节值 (ASCII 段恒等, 0x80-0xFE 为单字节 CJK)
    - 0x0A 为换行结构符直通 (字形表不含控制字符)
    - 0xFF + u16be: 字形序号 ≥ 255 的转义
      u16 = 0x8000 + g + 128*((g//128)+1), 即 0x8000|(g>>7)<<8|(0x80|(g&0x7F))
"""
import os
import re

CHARS_FILENAME = "lang4_chars.vsc"


class VlnError(ValueError):
    """vln 解析/编码失败。"""


def load_charset(path):
    """lang4_chars.vsc → (cp2glyph, glyph2cp) 双向映射。char 行格式: char <码点hex> <字形dec>。"""
    cp2g, g2cp = {}, {}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.match(r"^char\s+([0-9A-Fa-f]+)\s+(\d+)\s*$", line)
            if not m:
                continue
            cp, g = int(m.group(1), 16), int(m.group(2))
            if cp in cp2g or g in g2cp:
                raise VlnError(f"{path}: 字形表非单射 (码点 {cp:x} / 字形 {g} 重复)")
            cp2g[cp] = g
            g2cp[g] = cp
    return cp2g, g2cp


def h3_decode(u16):
    """转义载荷 u16 → 字形序号。"""
    v = u16 - 0x8000
    return v - 128 * ((v >> 8) + 1)


def h3_encode(g):
    """字形序号 ≥255 → 转义载荷 u16。"""
    return 0x8000 + g + 128 * ((g // 128) + 1)


def decode_value(val, g2cp):
    """值字节流 → Unicode 串。控制字节(<0x20)直通; 未收录字形抛 VlnError。"""
    out, i = [], 0
    while i < len(val):
        b = val[i]
        if b == 0xFF:
            if i + 2 >= len(val):
                raise VlnError(f"转义组越界: 值尾 {val[-4:].hex()}")
            g = h3_decode((val[i + 1] << 8) | val[i + 2])
            i += 3
        else:
            g = b
            i += 1
        if g < 0x20:
            out.append(chr(g))
            continue
        cp = g2cp.get(g)
        if cp is None:
            raise VlnError(f"字形 {g} (0x{g:02x}) 不在字形表")
        out.append(chr(cp))
    return "".join(out)


def encode_value(s, cp2g):
    """Unicode 串 → 值字节流。控制字符直通; 未收录码点抛 VlnError。"""
    out = bytearray()
    for ch in s:
        cp = ord(ch)
        if cp < 0x20:
            out.append(cp)
            continue
        g = cp2g.get(cp)
        if g is None:
            raise VlnError(f"码点 U+{cp:04X} {ch!r} 不在字形表, 游戏字体无法渲染")
        if g <= 0xFE:
            out.append(g)
        else:
            out += b"\xff" + h3_encode(g).to_bytes(2, "big")
    return bytes(out)


def parse_vln(path, chars_path=None):
    """解析 .vln → dict[key]=value (Unicode)。字形表缺省取同目录 lang4_chars.vsc。"""
    chars_path = chars_path or os.path.join(os.path.dirname(path) or ".", CHARS_FILENAME)
    _, g2cp = load_charset(chars_path)
    with open(path, "rb") as f:
        blob = f.read()
    if blob and not blob.endswith(b"\x00"):
        raise VlnError(f"{path}: 文件不以 NUL 结尾")
    parts = blob.split(b"\x00")
    parts = parts[:-1] if parts and parts[-1] == b"" else parts
    if len(parts) % 2:
        raise VlnError(f"{path}: 键值数量为奇数 ({len(parts)})")
    table = {}
    for i in range(0, len(parts), 2):
        key = parts[i].decode("ascii")
        val = decode_value(parts[i + 1], g2cp)
        if key in table:
            raise VlnError(f"{path}: 重复键 {key!r}")
        table[key] = val
    return table


def encode_vln(table, chars_path):
    """dict[key]=value → .vln 字节流 (与游戏原文件 round-trip 字节一致)。"""
    cp2g, _ = load_charset(chars_path)
    out = bytearray()
    for key, val in table.items():
        if not key.isascii() or not key:
            raise VlnError(f"键必须为非空 ASCII: {key!r}")
        out += key.encode("ascii") + b"\x00" + encode_value(val, cp2g) + b"\x00"
    return bytes(out)
