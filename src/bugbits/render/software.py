#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""软件光栅器（逐字吸收自 research/t22_v3d_render.py, T4.1）。

T4.6 bake.py 将以此光栅化为唯一 3D 栅格化处（地形背景 + 单位精灵烘焙）。
吸收怪癖（保留以保数值 parity）: render() 即使 use_tex=False 也读取 tex.size,
故 tex 参数必须提供有效 PIL.Image（测试中可用 1×1 哑图）。
"""
import math

from PIL import Image


def verts_span(verts):
    """顶点 AABB 最大跨度（软件渲染的归一化 span；NC-03 稳定归一化合同）。"""
    xs = [v[0][0] for v in verts]
    ys = [v[0][1] for v in verts]
    zs = [v[0][2] for v in verts]
    return max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)) or 1.0


def pose_screen_span(verts, yaws=8, pitch=-40.0, center=None):
    """姿态在 yaws 个朝向 × pitch 下的最大屏幕跨度（2·max(|x'|,|y'|)）。

    NC-03 稳定归一化：AABB 跨度归一化（verts_span）在对角朝向会超 0.8 容器
    被裁剪（|w·cosθ|+|d·sinθ| 可达 √2·span）——「体量随朝向裁剪变化」违反
    合同。本函数按 render 的同一旋转（中心化→yaw→pitch）逐朝向算实际屏幕
    包络，取最大值；用它归一化则全部朝向无裁剪，且世界尺寸映射不受影响
    （精确映射由 cb + atlasScale 承载，见 render/billboard.py）。

    center（NC-03A 锚点修复）：旋转/居中参考点；缺省 None = 本顶点集 AABB 中心
    （逐帧泵动源）。烘焙单位精灵时传入 bind 姿态 AABB 中心（稳定参考点），
    使全部帧共用同一居中点——消除「帧 AABB 中心漂移 → 脚底抖动」（DR20-03）。
    """
    if center is None:
        xs = [v[0][0] for v in verts]
        ys = [v[0][1] for v in verts]
        zs = [v[0][2] for v in verts]
        cx, cy, cz = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, \
            (max(zs) + min(zs)) / 2
    else:
        cx, cy, cz = center
    b = math.radians(pitch)
    best = 0.0
    for k in range(yaws):
        a = math.radians(k * 360.0 / yaws)
        ca, sa, cb_, sb = math.cos(a), math.sin(a), math.cos(b), math.sin(b)
        hx = hy = 0.0
        for v in verts:
            x, y, z = v[0][0] - cx, v[0][1] - cy, v[0][2] - cz
            x, z = x * ca - z * sa, x * sa + z * ca      # yaw
            y, z = y * cb_ - z * sb, y * sb + z * cb_    # pitch
            hx = max(hx, abs(x))
            hy = max(hy, abs(y))
        best = max(best, hx, hy)
    return 2.0 * best or 1.0


def _texture_has_transparency(tex):
    """纹理是否含非不透明 alpha（0 或 0<a<255）→ 该组三角需透明排序/blend。"""
    if tex is None or "A" not in tex.getbands():
        return False
    return tex.getchannel("A").getextrema()[0] < 255


def render(verts, idx, tex, size=640, yaw=90.0, pitch=-15.0, use_tex=True,
           norm_span=None, center=None):
    """norm_span（NC-03）：稳定归一化跨度——给定后取代逐顶点集自身 span，
    使同单位全部 clip/帧/yaw 共用一个 sc（消除动作切换的体量泵动）；
    缺省 None 保持旧行为（当前顶点集 span，既有调用者兼容）。

    center（NC-03A 锚点修复）：旋转/居中参考点；缺省 None = 本顶点集 AABB 中心
    （逐帧漂移）。烘焙单位精灵时传入 bind 姿态 AABB 中心（稳定），与
    pose_screen_span 同一 center 保证归一化与渲染居中一致。

    idx/tex 多材质组（NC-03 bee）：idx/tex 可为成对列表（多组）——各组共享同一
    z-buffer 与 norm_span/center（身体/翼膜深度排序正确）；单组（旧）向后兼容。

    NC-04 输出 RGBA（背景 alpha=0）+ alpha 语义（工程选择，见 docs/nc04-material.md）：
      a == 0      → 跳过（不写色、不写深）。
      a == 255    → 不透明：z-test + z-write，颜色 `int(c·lam+40)`（与旧一致）。
      0 < a < 255 → 直通（非预乘）alpha 的 source-over：out_a = sa+da·(1−sa)，
                    out_rgb = (sr·sa + dr·da·(1−sa))/out_a（SRCALPHA/INVSRCALPHA，
                    非预乘——wing_a a=0 处 RGB 白；dst 透明时 RGB 保持 src，不烤入
                    背景填充色），z-test 开、z-write 关。
    深度时序：z-write 移到「确定着色」之后（a==0 不写深）。
    透明排序：不透明组先画（保持原组序+z-buffer），透明组按三角平均深度
    back-to-front（z 小=远先画）后混合——最小实现（材质组粒度，见 change_plan）。"""
    if center is None:
        xs = [v[0][0] for v in verts]
        ys = [v[0][1] for v in verts]
        zs = [v[0][2] for v in verts]
        cx, cy, cz = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, (max(zs) + min(zs)) / 2
    else:
        cx, cy, cz = center
    span = norm_span if norm_span is not None else verts_span(verts)
    sc = size * 0.8 / span

    def rot(p):
        x, y, z = p[0] - cx, p[1] - cy, p[2] - cz
        a, b = math.radians(yaw), math.radians(pitch)
        x, z = x * math.cos(a) - z * math.sin(a), x * math.sin(a) + z * math.cos(a)
        y, z = y * math.cos(b) - z * math.sin(b), y * math.sin(b) + z * math.cos(b)
        return x, y, z

    # NC-03 bee 双材质：idx/tex 成对列表（多组）或单组（旧，向后兼容）。
    # 多组共享同一 zbuf / sc / rot / norm_span / center（身体+翼膜深度排序正确）。
    if idx and isinstance(idx[0], (tuple, list)):
        groups = list(zip(idx, tex))
    else:
        groups = [(idx, tex)]

    light = (0.4, 0.35, -0.85)

    img = Image.new("RGBA", (size, size), (24, 28, 24, 0))
    px = img.load()
    zbuf = [[-1e9] * size for _ in range(size)]
    tris = 0

    def shade(nrm, uv, tpx, tw, th):
        if not use_tex or tpx is None:
            return tuple(min(255, max(0, int(128 + 100 * n))) for n in nrm), 255
        lam = max(0.25, sum(x * y for x, y in zip(nrm, light)))
        tx = tpx[min(tw - 1, max(0, int(uv[0] * tw))),
                 min(th - 1, max(0, int((1 - uv[1]) * th)))]
        a = tx[3] if len(tx) > 3 else 255
        return tuple(min(255, int(c * lam + 40)) for c in tx[:3]), a

    # 收集三角形：opaque 组（纹理全 255 或 no-tex）→ 第一遍；透明组（含 a<255）
    # → 第二遍（back-to-front）。tri = (tpx, tw, th, i0, i1, i2, x0..z2, d)。
    opaque_tris = []
    transparent_tris = []
    for idx_g, tex_g in groups:
        tw, th = tex_g.size
        tpx = tex_g.load()
        transparent_group = use_tex and (tpx is not None) and \
            _texture_has_transparency(tex_g)
        for t in range(0, len(idx_g) - 2, 3):
            i0, i1, i2 = idx_g[t:t + 3]
            if max(i0, i1, i2) >= len(verts):
                continue
            ps = [rot(verts[i][0]) for i in (i0, i1, i2)]
            scr = [(p[0] * sc + size / 2, -p[1] * sc + size / 2, p[2]) for p in ps]
            (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = scr
            d = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if abs(d) < 1e-9:
                continue
            tris += 1
            tri = (tpx, tw, th, i0, i1, i2, x0, y0, z0, x1, y1, z1, x2, y2, z2, d)
            if transparent_group:
                transparent_tris.append(tri)
            else:
                opaque_tris.append(tri)

    def draw_tri(tri):
        tpx, tw, th, i0, i1, i2, x0, y0, z0, x1, y1, z1, x2, y2, z2, d = tri
        for py in range(max(0, int(min(y0, y1, y2))), min(size, int(max(y0, y1, y2)) + 1)):
            for pxx in range(max(0, int(min(x0, x1, x2))), min(size, int(max(x0, x1, x2)) + 1)):
                w0 = ((y1 - y2) * (pxx - x2) + (x2 - x1) * (py - y2)) / d
                w1 = ((y2 - y0) * (pxx - x2) + (x0 - x2) * (py - y2)) / d
                w2 = 1 - w0 - w1
                if w0 < 0 or w1 < 0 or w2 < 0:
                    continue
                z = w0 * z0 + w1 * z1 + w2 * z2
                uv = tuple(w0 * verts[i0][2][j] + w1 * verts[i1][2][j] + w2 * verts[i2][2][j]
                           for j in range(2))
                nrm = tuple(-(w0 * verts[i0][1][j] + w1 * verts[i1][1][j]
                              + w2 * verts[i2][1][j]) for j in range(3))
                col, a = shade(nrm, uv, tpx, tw, th)
                if a == 0:
                    continue                      # 完全透明：不写色、不写深
                if z <= zbuf[py][pxx]:
                    continue
                if a == 255:
                    zbuf[py][pxx] = z            # 不透明：z-write
                    px[pxx, py] = col + (255,)
                else:
                    # 直通（非预乘）alpha 的 source-over，z-write 关：
                    #   out_a = sa + da·(1−sa)
                    #   out_rgb = (sr·sa + dr·da·(1−sa)) / out_a   （out_a>0）
                    # 注意：不能朴素 lerp src·fa+dst·(1−fa)——dst 是透明背景
                    # (24,28,24,0) 时会把背景填充色烤进半透明像素（翼缘暗绿 halo）。
                    fa = a / 255.0
                    dst = px[pxx, py]
                    da = dst[3] / 255.0
                    out_a = fa + da * (1.0 - fa)
                    if out_a > 0.0:
                        out = tuple(int((col[i] * fa + dst[i] * da * (1.0 - fa)) / out_a)
                                    for i in range(3))
                    else:
                        out = (0, 0, 0)
                    px[pxx, py] = out + (int(out_a * 255),)

    # 第一遍：不透明（原组序，z-buffer 逐位一致）
    for tri in opaque_tris:
        draw_tri(tri)
    # 第二遍：透明 back-to-front（z 小=远先画，z 大=近后画）
    transparent_tris.sort(key=lambda t: (t[8] + t[11] + t[14]) / 3.0)
    for tri in transparent_tris:
        draw_tri(tri)
    return img, tris


def ascii_preview(img, cols=84):
    g = img.convert("L")
    w, h = g.size
    g = g.resize((cols, max(4, int(h / w * cols * 0.45))))
    p = g.load()
    ramp = " .:-=+*#%@"
    return "\n".join("".join(ramp[min(9, p[x, y] * 10 // 256)] for x in range(cols))
                     for y in range(g.size[1]))
