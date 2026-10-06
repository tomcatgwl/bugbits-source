#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BugBits .van 动画解析（吸收自 research/t22_v3d_render.py, T4.1）。

格式（harness 断言背书）:
  [u32 节点数 n][n × (u32 键数 k + k×28B 键)]; 键 = 7×f32 (时间秒, 欧拉角 xyz, 位置 xyz)
  节点序 = 模型节点记录序（parse_v3d 的 recs, 0 基含根记录）。
"""
import struct


def parse_van(path):
    with open(path, "rb") as stream:
        blob = stream.read()
    n = struct.unpack("<I", blob[:4])[0]
    blocks, off = [], 4
    for _ in range(n):
        k = struct.unpack("<I", blob[off:off + 4])[0]
        blocks.append([struct.unpack("<7f", blob[off + 4 + j * 28:off + 4 + (j + 1) * 28])
                       for j in range(k)])
        off += 4 + k * 28
    return blocks


def sample(keys, t):
    """t 时刻键值（端点钳位 + 线性插值）。"""
    if t <= keys[0][0]:
        return keys[0]
    if t >= keys[-1][0]:
        return keys[-1]
    for j in range(len(keys) - 1):
        if keys[j][0] <= t <= keys[j + 1][0]:
            a, b = keys[j], keys[j + 1]
            f = (t - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0
            return tuple(a[i] + (b[i] - a[i]) * f for i in range(7))
    return keys[-1]
