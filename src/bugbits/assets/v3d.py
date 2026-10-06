#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BugBits .v3d 模型与世界网格解析，详见 docs/formats/v3d.md。

正常binary模型：首DWORD声明节点数；每节点读名称、矩阵、parent、几何标志。
有几何时读36B顶点池、各组u16索引和固定128B材质缓冲，再读skin-present
DWORD及可选56B蒙皮池。所有节点后逐节点读引用表，蒙皮槽经此表映射到
节点或NULL(-1)。parse_v3d不将未消费尾部扫描结果当作动画节点。
世界网格沿既有独立parse_world_meshes路径；其扫描范围不由本模型合同升级。
"""
import math
import struct

STRIDE = 36          # 根几何块顶点步长 (字节)


def u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def i32(d, o):
    return struct.unpack_from("<i", d, o)[0]


def printable(bs):
    return all(0x21 <= b <= 0x7E for b in bs)


def parse_header(d):
    """解析文件头 → dict. 结构异常抛 ValueError."""
    if len(d) < 88:
        raise ValueError("文件过短")
    A, nl = u32(d, 0), u32(d, 4)
    if not (1 <= nl <= 64):
        raise ValueError("名称长度异常 %d" % nl)
    name = d[8:8 + nl]
    if not printable(name):
        raise ValueError("名称含非可打印字节")
    mo = 8 + nl
    m = struct.unpack_from("<16f", d, mo)
    parent, flag, vc = u32(d, mo + 64), u32(d, mo + 68), u32(d, mo + 72)
    return {
        "A": A, "nl": nl, "name": name.decode("ascii"),
        "m": m, "parent": parent, "flag": flag, "vc": vc,
        "vc_off": mo + 72,          # 几何段头(顶点数)偏移
        "vert_off": mo + 76,        # 顶点数据起始 = 84 + name_len
    }


def node_record_at(d, o, A):
    """o 处是否为合法节点记录 [u32 len][名][64B 矩阵][i32 parent][u32 ext].

    判据: 长度 1..64, 名称可打印, 矩阵有限且 m[15]≈1, parent 为 -1 或 < A.
    返回 (name, parent, ext, matrix, end) 或 None. 根记录与骨骼/网格/控制器节点同构.
    """
    if o + 76 > len(d):
        return None
    if not (1 <= d[o] <= 64) or d[o + 1] or d[o + 2] or d[o + 3]:
        return None
    ln = d[o]
    nm = d[o + 4:o + 4 + ln]
    if len(nm) != ln or not printable(nm):
        return None
    mo = o + 4 + ln
    try:
        m = struct.unpack_from("<16f", d, mo)
    except struct.error:
        return None
    if not all(x == x and abs(x) < 1e9 for x in m) or abs(m[15] - 1.0) > 1e-3:
        return None
    parent, ext = u32(d, mo + 64), u32(d, mo + 68)
    if parent != 0xFFFFFFFF and parent >= A:
        return None
    return (nm.decode("ascii"), parent, ext, m, mo + 72)


def _locate_skin(blob, verts, geo_end):
    """历史研究用位置搜索；生产解析使用原binary游标。

    名字后间隔变化来自固定128B材质缓冲中名字长度及skin-present DWORD，
    不是变长矩阵metadata。保留此诊断接口供既有调查脚本重跑。
    """
    if len(verts) < 2:
        return None
    pats = [struct.pack("<3f", *verts[i][0]) for i in range(min(3, len(verts)))]
    x = blob.find(pats[0], geo_end)
    while x >= 0:
        if all(blob[x + 56 * i:x + 56 * i + 12] == pats[i]
               for i in range(len(pats))):
            if all(blob[x + 56 * i:x + 56 * i + 12] == struct.pack("<3f", *verts[i][0])
                   for i in range(len(verts))):
                return x
        x = blob.find(pats[0], x + 1)
    return None


def _locate_submesh(blob, geo_end, vc):
    """历史k=2调查接口；生产模型逐组读取索引和128B材质缓冲。

    DATA 布局（geo_end+128 定界，survey_k2.py 全量背书）:
      [geo 根几何][tex0\\0][pad 使 geo_end→ic1 恒 128B][u32 ic1][ic1×u16 索引]
      [固定128B tex1材质缓冲][u32 skin-present][可选skin]
    校验不变量：ic1%3==0 ∧ 2<ic1<200000 ∧ 全索引<vc ∧ tex1 为索引流后首段可打印
    NUL 串；否则抛 ValueError（拒绝含糊输入，同 _read_world_group 口径——
    不允许静默回退单组）。
    """
    ic1_off = geo_end + 128
    if ic1_off + 4 > len(blob):
        raise ValueError(f"子网格定位失败: ic1 偏移越界 {ic1_off}")
    ic = u32(blob, ic1_off)
    if ic % 3 != 0 or not (2 < ic < 200000):
        raise ValueError(f"子网格定位失败: ic1={ic} 非法（非三角列表或计数越界）")
    if ic1_off + 4 + ic * 2 > len(blob):
        raise ValueError(f"子网格定位失败: ic1={ic} 索引流截断")
    idx = struct.unpack_from(f"<{ic}H", blob, ic1_off + 4)
    if max(idx, default=0) >= vc:
        raise ValueError(f"子网格定位失败: 索引≥vc（越界索引）")
    stream_end = ic1_off + 4 + ic * 2
    nul = blob.find(b"\x00", stream_end)
    if nul < 0:
        raise ValueError("子网格定位失败: tex1 无 NUL 结尾")
    if nul == stream_end or not printable(blob[stream_end:nul]):
        raise ValueError("子网格定位失败: tex1 非可打印 NUL 串")
    return tuple(idx), blob[stream_end:nul].decode("ascii")


def _read_model(path):
    """Read the declared normal-binary prefix, including node reference tables.

    Original 4B5C91..4B628D consumes each geometry's groups as index data plus
    a fixed 128-byte material buffer, then a skin-present DWORD and optional
    vertex_count*56 skin bytes. Reference tables follow all declared nodes.
    Unconsumed exporter suffixes are not additional animation nodes.
    """
    with open(path, "rb") as stream:
        blob = stream.read()
    cursor = 0

    def read(size):
        nonlocal cursor
        if size < 0 or cursor + size > len(blob):
            raise ValueError(f"V3D 数据截断: offset={cursor}, size={size}")
        result = blob[cursor:cursor + size]
        cursor += size
        return result

    def integer():
        return struct.unpack("<I", read(4))[0]

    count = integer()
    if not 0 < count <= len(blob) // 76:
        raise ValueError("V3D 节点计数异常")
    records, geometries, raw_skins = [], [], []
    for node_index in range(count):
        name_length = integer()
        name_bytes = read(name_length)
        if not name_bytes or not printable(name_bytes):
            raise ValueError("V3D 节点名称异常")
        matrix = struct.unpack("<16f", read(64))
        parent, ext = struct.unpack("<II", read(8))
        if (not all(math.isfinite(x) for x in matrix)
                or parent != 0xFFFFFFFF and parent >= node_index
                or ext not in (0, 1)):
            raise ValueError("V3D 节点矩阵、父节点或几何标志异常")
        records.append((name_bytes.decode("ascii"), parent, ext, matrix, cursor))
        geometry, skin = None, []
        if ext:
            vertex_count = integer()
            pool = read(vertex_count * STRIDE)
            vertices = [(struct.unpack_from("<3f", pool, i * STRIDE),
                         struct.unpack_from("<3f", pool, i * STRIDE + 12),
                         struct.unpack_from("<2f", pool, i * STRIDE + 28))
                        for i in range(vertex_count)]
            group_count = integer()
            if not 0 < group_count <= (len(blob) - cursor) // 132:
                raise ValueError("V3D 材质组计数异常")
            groups = []
            for _ in range(group_count):
                index_count = integer()
                indices = struct.unpack(f"<{index_count}H", read(index_count * 2))
                if index_count % 3 or any(i >= vertex_count for i in indices):
                    raise ValueError("V3D 三角索引异常")
                material = read(128)
                texture = material.split(b"\0", 1)[0]
                if b"\0" not in material or texture and not printable(texture):
                    raise ValueError("V3D 材质名称异常")
                groups.append((indices, texture.decode("ascii") if texture else None))
            skin_present = integer()
            if skin_present not in (0, 1):
                raise ValueError("V3D 蒙皮标志异常")
            if skin_present:
                pool = read(vertex_count * 56)
                for i in range(vertex_count):
                    base = i * 56
                    position = struct.unpack_from("<3f", pool, base)
                    normal = struct.unpack_from("<3f", pool, base + 12)
                    if position != vertices[i][0]:
                        raise ValueError("V3D 几何与蒙皮同序位置不符")
                    influences = [struct.unpack_from("<if", pool, base + 24 + j * 8)
                                  for j in range(4)]
                    skin.append((position, normal, influences))
            geometry = vertices, groups
        geometries.append(geometry)
        raw_skins.append(skin)

    skins = []
    for skin in raw_skins:
        reference_count = integer()
        references = struct.unpack(f"<{reference_count}i", read(reference_count * 4))
        if any(r < -1 or r >= count for r in references):
            raise ValueError("V3D 骨骼引用节点越界")
        resolved = []
        for position, normal, influences in skin:
            mapped = []
            for slot, percentage in influences:
                if not math.isfinite(percentage):
                    raise ValueError("V3D 蒙皮权重非有限")
                if percentage == 0:
                    continue
                if slot == -1:
                    node = -1
                elif 0 <= slot < reference_count:
                    node = references[slot]
                else:
                    raise ValueError("V3D 蒙皮引用槽越界")
                # -1 means an original NULL reference: weighted source point
                # and direction, never the root or the last Python list item.
                mapped.append((node, percentage / 100.0))
            resolved.append((position, normal, mapped))
        skins.append(resolved)
    if geometries[0] is None:
        raise ValueError("V3D 根节点无几何")
    return geometries[0], skins[0], records


def parse_v3d(path):
    """Return root geometry, resolved skin, declared nodes and first texture.

    Influences refer to declared node indices after the original per-geometry
    reference-table lookup. Node -1 is a NULL/identity influence. The caller
    must preserve it; out-of-range slots are invalid, not root attachments.
    """
    (vertices, groups), skin, records = _read_model(path)
    indices, texture = groups[0]
    return (vertices, indices, len(groups)), skin, records, texture


def vertex_diffuse(path):
    """Unsigned ARGB DWORD at +24 in every root 36B vertex, in source order.

    This is a bind-source pool; it makes no claim about later runtime writers.
    Keep the legacy position/normal/UV tuple API unchanged for other consumers.
    """
    with open(path,'rb') as stream:blob=stream.read()
    header=parse_header(blob)
    count,start=header['vc'],header['vert_off']
    if count<1 or start+count*STRIDE>len(blob):
        raise ValueError('incomplete root diffuse vertex pool')
    return tuple(u32(blob,start+i*STRIDE+24) for i in range(count))


def parse_v3d_groups(path):
    """Return all original root material groups with the same resolved rig."""
    (vertices, groups), skin, records = _read_model(path)
    return vertices, groups, skin, records


# ── 世界网格遍历（T4.2: worlds 是网格节点型, 地形分在多个 mesh 节点） ──────
WORLD_K_DOMAIN = (1, 2, 3, 4)  # k=材质数 (实测: grass_a k=3 ↔ .vsc World 块 Material0/1/2)
# RF-03：k>1 mesh 相邻索引流之间 gap 恒 128B（数据级证据：9 世界全部 48 组界一致 +
# 82/82 mesh 与旧贪心启发式逐索引交叉验证一致，research/r73_world_gap.py、
# r74_world_group_stride.py）。确定性步长取代 _scan_index_array 贪心扫描。
WORLD_GROUP_STRIDE = 128


class WorldMesh:
    """世界网格节点: [记录][几何 [vc][36B×vc][k][ic][u16×ic]][材质尾段: 纹理名\\0+填充]。

    多材质组（k>1）：每组 = [u32 ic][u16×ic][纹理名\\0+gap]，组间 gap 恒 128B
    （WORLD_GROUP_STRIDE）。group_indices/group_tex_names 按组保留（OF-03.B 材质消费）；
    indices=全部组合并（向后兼容，FIX-02 语义）；tex_name=第 0 组纹理名。
    """

    __slots__ = ("name", "parent", "matrix", "verts", "k", "ic", "indices",
                 "tex_name", "group_indices", "group_tex_names")

    def __init__(self, name, parent, matrix, verts, k, ic, indices, tex_name,
                 group_indices=None, group_tex_names=None):
        self.name = name
        self.parent = parent
        self.matrix = matrix
        self.verts = verts
        self.k = k
        self.ic = ic
        self.indices = indices
        self.tex_name = tex_name
        self.group_indices = group_indices
        self.group_tex_names = group_tex_names


def _scan_records(blob, a):
    """贪心扫描全部节点记录（t21 V5: worlds 记录数==A）。"""
    recs, o = [], 4
    while o + 76 <= len(blob):
        r = node_record_at(blob, o, a)
        if r:
            recs.append(r)
            o = r[4]
        else:
            o += 1
    return recs


def _scan_index_array(blob, start, limit, vc):
    """[已由 _read_world_group 确定性读取取代，仅保留作诊断/调查脚本用]

    从 start 起扫描下一组 [u32 ic][u16×ic 全<vc]（世界材质组索引流=三角形列表）。
    贪心 2 字节步进，判据 ic%3==0 + 索引全<vc。该启发式不能区分 gap 内的伪合法
    序列——生产解析已改用 128B 确定性步长（WORLD_GROUP_STRIDE）。
    """
    o = start
    while o + 4 <= limit:
        ic = u32(blob, o)
        if ic % 3 == 0 and 2 < ic < 200000 and o + 4 + ic * 2 <= limit:
            idx = struct.unpack_from(f"<{ic}H", blob, o + 4)
            if max(idx, default=0) < vc:
                return ic, idx, o + 4 + ic * 2
        o += 2
    return None


def _read_world_group(blob, ic_off, vc, name):
    """在确定性偏移 ic_off 读一组索引流并校验；异常抛 ValueError（拒绝含糊输入）。

    组布局 [u32 ic][u16×ic 全<vc]。校验：ic 为三角列表计数（%3==0 且 2<ic<200000）、
    索引不越界（截断）、全<vc（越界索引）。返回 (ic, idx, 组尾偏移)。
    """
    if ic_off + 4 > len(blob):
        raise ValueError(f"{name}: 索引组偏移越界 {ic_off}")
    ic = u32(blob, ic_off)
    if ic % 3 != 0 or not (2 < ic < 200000):
        raise ValueError(f"{name}: ic={ic} 非法（非三角列表或计数越界）")
    if ic_off + 4 + ic * 2 > len(blob):
        raise ValueError(f"{name}: ic={ic} 索引流截断")
    idx = struct.unpack_from(f"<{ic}H", blob, ic_off + 4)
    if max(idx, default=0) >= vc:
        raise ValueError(f"{name}: 索引≥vc（越界索引）")
    return ic, idx, ic_off + 4 + ic * 2


def parse_world_meshes(path):
    """世界 .v3d → [WorldMesh]。

    布局（research/t42_semantics.py S8 实测, 9/9 世界自洽; FIX-02 补全多材质组）:
      每 mesh 节点 = [记录][几何块 [vc][vc×36B][k][ic₀][ic₀×u16]][材质组₀ 尾段
      (纹理名\\0+gap)][ic₁][ic₁×u16][材质组₁ 尾段]…（共 k 组）。
    记录经贪心散布扫描定位；记录数必须 == A。FIX-02 起读全部 k 组索引流并合并。
    """
    with open(path, "rb") as f:
        blob = f.read()
    a, _ = struct.unpack("<2I", blob[:8])
    recs = _scan_records(blob, a)
    if len(recs) != a:
        raise ValueError(f"记录数 {len(recs)} != A={a}")
    out = []
    for i, (name, parent, ext, matrix, end) in enumerate(recs):
        if end + 12 > len(blob):
            raise ValueError(f"{name}: 记录尾溢出")
        vc = u32(blob, end)
        if not (0 < vc < 200000) or end + 4 + vc * 36 + 8 > len(blob):
            raise ValueError(f"{name}: vc={vc} 异常")
        gend = end + 4 + vc * 36
        k, ic0 = u32(blob, gend), u32(blob, gend + 4)
        if k not in WORLD_K_DOMAIN or ic0 == 0 or gend + 8 + ic0 * 2 > len(blob):
            raise ValueError(f"{name}: k={k} ic={ic0} 异常")
        verts = []
        for j in range(vc):
            b0 = end + 4 + j * 36
            verts.append((struct.unpack_from("<3f", blob, b0),
                          struct.unpack_from("<3f", blob, b0 + 12),
                          struct.unpack_from("<2f", blob, b0 + 28)))
        # RF-03: 全部 k 组索引流按确定性 128B 步长读取（组间 gap 恒 128B——数据级
        # 证据：9 世界全部 48 组界一致 + 82/82 mesh 与旧启发式逐索引交叉验证一致，
        # research/r73+r74）。拒绝含糊输入（非法 ic/截断/索引越界），不贪心扫描凑 k 组。
        # OF-03.B：每组保留各自索引流 + 纹理名（材质消费，ground/grass/clod 等分材质组）。
        all_indices = []
        group_indices = []
        group_tex_names = []
        ic_off = gend + 4                              # group 0 的 ic 偏移
        for _ in range(k):
            ic, idx, group_end = _read_world_group(blob, ic_off, vc, name)
            all_indices.extend(idx)
            group_indices.append(tuple(idx))
            # 每组纹理名 = 该组索引流后首个 NUL 串（组 0 与旧 tex_name 同口径）
            e = blob.find(b"\x00", group_end)
            gtex = (blob[group_end:e].decode("ascii", "replace")
                    if 0 < e - group_end and printable(blob[group_end:e]) else None)
            group_tex_names.append(gtex)
            ic_off = group_end + WORLD_GROUP_STRIDE
        # 纹理名（第一组后首个 NUL 串；字段语义与旧实现一致）
        e = blob.find(b"\x00", gend + 8 + ic0 * 2)
        tex_name = (blob[gend + 8 + ic0 * 2:e].decode("ascii", "replace")
                    if 0 < e - (gend + 8 + ic0 * 2)
                    and printable(blob[gend + 8 + ic0 * 2:e]) else None)
        out.append(WorldMesh(name, parent, matrix, verts, k,
                             len(all_indices), tuple(all_indices), tex_name,
                             tuple(group_indices), tuple(group_tex_names)))
    return out
