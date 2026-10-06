#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""姿态求解与蒙皮（吸收自 research/t22_v3d_render.py, T4.1）。

约定: 矩阵 = 行主序 16 元组, D3D 行向量 (v' = v×M, 平移在 m[12..14], m[15]=1)。
蒙皮公式: v' = Σ w·v·bind_i⁻¹·anim_i, bind = v3d 节点记录矩阵的层级世界积
（蒙皮恒等点）; anim = van 键 (欧拉角+平移) 的层级世界积, van 块 i ↔ 节点记录 i。
"""
import math

from bugbits.assets.van import sample


def mat_mul(a, b):
    return tuple(sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4))
                 for r in range(4) for c in range(4))


def mat_apply(m, v):
    return tuple(sum(v[i] * m[i * 4 + c] for i in range(4)) for c in range(3))


def mat_apply_dir(m, v):
    """方向向量变换（w=0）：只取 3×3 线性部分，不含平移（法线/方向用）。"""
    return tuple(sum(v[i] * m[i * 4 + c] for i in range(3)) for c in range(3))


def mat_inv(m):
    """行向量仿射逆，支持旋转、平移、非均匀缩放和剪切；拒绝奇异/透视矩阵。"""
    if (len(m) != 16 or not all(math.isfinite(x) for x in m)
            or any(abs(m[i]) > 1e-9 for i in (3, 7, 11))
            or abs(m[15] - 1) > 1e-9):
        raise ValueError("需要有限的仿射矩阵")
    a, b, c, d, e, f, g, h, i = (m[j] for j in (0, 1, 2, 4, 5, 6, 8, 9, 10))
    det = a * (e*i - f*h) - b * (d*i - f*g) + c * (d*h - e*g)
    if det == 0:
        raise ValueError("奇异矩阵无逆")
    r = tuple(x / det for x in (e*i-f*h, c*h-b*i, b*f-c*e,
                                f*g-d*i, a*i-c*g, c*d-a*f,
                                d*h-e*g, b*g-a*h, a*e-b*d))
    t = tuple(-sum(m[12 + k] * r[k * 3 + j] for k in range(3)) for j in range(3))
    return (r[0], r[1], r[2], 0, r[3], r[4], r[5], 0,
            r[6], r[7], r[8], 0, *t, 1)


def euler_rot(rx, ry, rz):
    """Original 402AC0 raw row-vector Rx×Ry×Rz rotation.

    Track 44D170 passes +24/+28/+2C in this order. This fixes the former
    column-vector transpose; Python trig/arithmetic is not x87 bit parity.
    """
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    return (cz * cy, sz * cy, -sy, 0,
            cz * sy * sx - sz * cx, sz * sy * sx + cz * cx, cy * sx, 0,
            cz * sy * cx + sz * sx, sz * sy * cx - cz * sx, cy * cx, 0,
            0, 0, 0, 1)


def worlds_from_records(recs):
    """节点记录矩阵的层级世界积 = 真 bind 姿态（蒙皮恒等点）。"""
    ws = [None] * len(recs)
    for i, (_, par, _, m, _) in enumerate(recs):
        p = par if par != 0xFFFFFFFF else -1
        ws[i] = m if (p < 0 or p >= len(ws) or ws[p] is None) else mat_mul(m, ws[p])
    return ws


def worlds_at(recs, blocks, t):
    """t 时刻各节点世界矩阵（van 块 i ↔ 节点记录 i；记录 parent 0 基索引）。"""
    ws = [None] * len(recs)
    for i, (_, par, _, m, _) in enumerate(recs):
        if i < len(blocks):
            key = sample(blocks[i], t)
            local = mat_mul(euler_rot(key[1], key[2], key[3]),
                            (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0,
                             key[4], key[5], key[6], 1))
        else:
            local = m
        p = par if par != 0xFFFFFFFF else -1
        ws[i] = local if (p < 0 or p >= len(ws) or ws[p] is None) else mat_mul(local, ws[p])
    return ws


def _source_uvs(skin, source_vertices):
    """Validate the original geometry/skin bijection before copying UV by index."""
    def vector(value, count):
        try:
            result = tuple(value)
        except TypeError as exc:
            raise ValueError('source mapping requires finite numeric vectors') from exc
        if (len(result) != count or any(isinstance(v, bool)
                or not isinstance(v, (int, float)) or not math.isfinite(v)
                for v in result)):
            raise ValueError('source mapping requires finite numeric vectors')
        return result

    try:
        vertices = tuple(source_vertices)
        if len(vertices) != len(skin):
            raise ValueError('source geometry/skin vertex counts differ')
        uvs = []
        for source, skinned in zip(vertices, skin):
            if len(source) != 3 or len(skinned) != 3:
                raise ValueError('source geometry/skin vertex records must have three fields')
            if vector(source[0], 3) != vector(skinned[0], 3):
                raise ValueError('source geometry/skin bind positions differ at the same index')
            vector(source[1], 3)
            uvs.append(vector(source[2], 2))
        return uvs
    except (TypeError, IndexError, OverflowError) as exc:
        raise ValueError('invalid source geometry/skin mapping') from exc


def skin_at(skin, bind, anim, *, source_vertices=None):
    """行向量先从绑定世界回到骨局部，再变换到动画世界。

    法线随刚体变换的 3×3 旋转部分变换并重归一化（bind/anim 均为刚体，det=1；
    无缩放 → 逆转置即旋转本身）。位置按原44C5B0除以总权重；零和保源位置。
    渲染调用必须显式传 source_vertices（原几何，同序同 bind 位置）以保留 UV。
    三参旧调用保位置/法线和 UV=(0,0) 兼容；不推测缺失映射。
    已解析影响的节点 -1 表示原NULL引用，直接加权源位置/法线。
    """
    if source_vertices is not None:
        skin = tuple(skin)
        source_uvs = _source_uvs(skin, source_vertices)
    transforms = [mat_mul(mat_inv(m), anim[i]) for i, m in enumerate(bind)]
    out = []
    for index, (pos, nrm, inf) in enumerate(skin):
        acc = [0.0] * 3
        accn = [0.0] * 3
        total = 0.0
        for bi, w in inf:
            total += w
            if bi == -1:
                v, n = pos, nrm
            else:
                if not 0 <= bi < len(transforms):
                    raise ValueError('skin node index outside resolved rig')
                v = mat_apply(transforms[bi], pos + (1,))
                n = mat_apply_dir(transforms[bi], nrm)
            for c in range(3):
                acc[c] += w * v[c]
                accn[c] += w * n[c]
        nl = math.hypot(*accn)
        out_n = tuple(x / nl for x in accn) if nl > 0 else tuple(accn)
        uv = source_uvs[index] if source_vertices is not None else (0.0, 0.0)
        out_pos = tuple(x / total for x in acc) if total != 0 else tuple(pos)
        out.append((out_pos, out_n, uv))
    return out
