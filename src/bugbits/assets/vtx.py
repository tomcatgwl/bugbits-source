#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BugBits .vtx 纹理格式解析库（从 tools/vtx2png.py 逐字迁移, T4.1）。

格式（harness 断言背书）:
  16 字节头, 4×u32 LE: [POT对齐宽][POT对齐高][原始宽][原始高]
  + 未压缩 BGRA32 像素 (对齐宽×对齐高×4 字节)
  例外: 2010-08-09 官方中文更新产出的 *_cn.vtx 尾部多 26 字节
  TGA 2.0 footer (TRUEVISION-XFILE. 签名), 解析时忽略。
"""
import os
import struct

from PIL import Image

VTX_HEADER = 16
TGA_FOOTER = 26  # 仅 _cn 文件携带, 忽略


class VtxError(ValueError):
    pass


def parse_vtx(path):
    """解析 .vtx → (w, h, orig_w, orig_h, PIL.Image)。

    两种头布局（按文件大小判别）:
      16B: [POT宽][POT高][原宽][原高] + 像素   （绝大多数文件）
       8B: [POT宽][POT高] + 像素, 原尺寸=对齐尺寸 （仅 stagbeetle.vtx）
    2010-08-09 官方中文更新的文件尾部多 26B TGA footer, 忽略。
    """
    with open(path, "rb") as f:
        blob = f.read()
    if len(blob) < 8:
        raise VtxError(f"过短: {len(blob)}B")
    w, h = struct.unpack("<2I", blob[:8])
    if w == 0 or h == 0:
        raise VtxError(f"零尺寸: [{w},{h}]")
    if w & (w - 1) or h & (h - 1):
        raise VtxError(f"非 POT 尺寸: [{w},{h}]")
    body = len(blob) - 8
    if body == w * h * 4:
        ow = oh = None  # 8B 头变体
        pix_off = 8
    else:
        ow, oh = struct.unpack("<2I", blob[8:16])
        if ow > w or oh > h or ow == 0 or oh == 0:
            raise VtxError(f"原始尺寸非法: [{w},{h},{ow},{oh}]")
        expected = 16 + w * h * 4
        if len(blob) not in (expected, expected + TGA_FOOTER):
            raise VtxError(f"大小不符: {len(blob)} != {expected}(+26)")
        if len(blob) == expected + TGA_FOOTER and b"TRUEVISION-XFILE" not in blob[-TGA_FOOTER:]:
            raise VtxError("尾部 26B 但非 TGA footer 签名")
        pix_off = 16
    if ow is None:
        ow, oh = w, h
    img = Image.frombytes("RGBA", (w, h), blob[pix_off:pix_off + w * h * 4], "raw", "BGRA")
    if (ow, oh) != (w, h):
        img = img.crop((0, 0, ow, oh))  # 裁掉 POT 补齐区
    return w, h, ow, oh, img


def inspect_vtx(path):
    """返回布局信息 dict（harness 用）: header_len/w/h/ow/oh/footer。"""
    with open(path, "rb") as f:
        blob = f.read()
    w, h = struct.unpack("<2I", blob[:8])
    if len(blob) - 8 == w * h * 4:
        return {"header_len": 8, "w": w, "h": h, "ow": w, "oh": h, "footer": False}
    ow, oh = struct.unpack("<2I", blob[8:16])
    footer = len(blob) == 16 + w * h * 4 + TGA_FOOTER
    return {"header_len": 16, "w": w, "h": h, "ow": ow, "oh": oh, "footer": footer}


def convert_tree(src_root, dst_root):
    """递归转换 src_root 下全部 .vtx 到 dst_root, 保持目录结构。返回 (成功数, 失败表)。"""
    ok, fails = 0, []
    for dirpath, _, files in os.walk(src_root):
        for name in files:
            if not name.lower().endswith(".vtx"):
                continue
            src = os.path.join(dirpath, name)
            rel = os.path.relpath(src, src_root)
            dst = os.path.join(dst_root, os.path.splitext(rel)[0] + ".png")
            try:
                _, _, _, _, img = parse_vtx(src)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                img.save(dst)
                ok += 1
            except (VtxError, OSError) as e:
                fails.append((rel, str(e)))
    return ok, fails
