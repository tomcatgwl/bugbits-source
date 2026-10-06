#!/usr/bin/env python3
"""BugBits RE 验证 harness：全部格式知识以可执行断言形式存在于此。

不变量 I1: 全绿 (exit 0) 才允许 commit。
每次新增格式结论, 必须同步在此添加断言 (WORKFLOW.md 协议)。

用法: python3 harness/run.py [--quick]
"""
import os
import struct
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bugbits.assets import vfm, vln, vsc, vtx  # noqa: E402

GAME = os.environ.get(
    "BUGBITS_DATA",
    "/data/bugbits/analyze/extracted/ccdzz",
)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(f"{name} {('— ' + detail) if detail and not cond else ''}")


def walk(*sub, ext=None):
    root = os.path.join(GAME, *sub)
    out = []
    for dirpath, _, files in os.walk(root):
        for f in files:
            if ext is None or f.lower().endswith(ext):
                out.append(os.path.join(dirpath, f))
    return out


# ── 文件清单基线 (资产统计, 2026-09-12 全量实测) ──────────────────────
def a_inventory():
    check("清单.vtx总数", len(walk("data", ext=".vtx")) == 208)
    check("清单.ogg总数", len(walk("data", ext=".ogg")) == 44)
    check("清单.vfm总数", len(walk("data", ext=".vfm")) == 13)
    check("清单.v3d总数", len(walk("data", ext=".v3d")) == 41)
    check("清单.van总数", len(walk("data", ext=".van")) == 87)
    check("清单.vsc总数", len(walk("data", "scripts", ext=".vsc")) +
          len(walk("data", "worlds", ext=".vsc")) == 123)
    check("清单.exe存在", os.path.isfile(os.path.join(GAME, "虫虫大作战 鸾霄汉化版.exe")))
    # .vant: 文本格式动画 (原厂导出器遗留, Phase 2 的 .van 语义线索)
    vants = walk("data", ext=".vant")
    check("清单.vant唯一", len(vants) == 1 and
          open(vants[0], "rb").read(18) == b"**VOID_3DANIMATION")


# ── T1.1 .vtx 全量断言 ────────────────────────────────────────────────
def a_vtx():
    files = walk("data", ext=".vtx")
    bad, footer_cn, header8 = [], 0, 0
    for p in files:
        try:
            info = vtx.inspect_vtx(p)
            if info["footer"]:
                footer_cn += 1
            if info["header_len"] == 8:
                header8 += 1
            # 头字段自洽
            if info["ow"] > info["w"] or info["oh"] > info["h"]:
                bad.append(f"{os.path.basename(p)}: 原始尺寸超对齐")
            vtx.parse_vtx(p)
        except (vtx.VtxError, OSError, struct.error) as e:
            bad.append(f"{os.path.basename(p)}: {e}")
    check("VTX.全部可解析", not bad, "; ".join(bad[:3]))
    # TGA footer 属 2010-08 官方更新批次产物: 两个 _cn 主图集 + logo_01
    check("VTX.TGAfooter集合", footer_cn == 3, f"footer={footer_cn}")
    check("VTX.8B头变体数", header8 == 1, f"8B头={header8}")  # 仅 stagbeetle.vtx


# ── T1.2 .vsc 全量断言 ────────────────────────────────────────────────
def a_vsc():
    files = walk("data", "scripts", ext=".vsc") + walk("data", "worlds", ext=".vsc")
    check("VSC.文件数", len(files) == 123, str(len(files)))
    warns, prop_names, tree_files = [], set(), 0
    for p in files:
        c, w = vsc.validate(p)
        warns += w
        cmds = vsc.parse_vsc(p)
        if vsc.is_tree_dialect(cmds):
            tree_files += 1
        for _, cmd, args in cmds:
            if cmd == "sp" and args:
                prop_names.add(args[0])
    check("VSC.词表封闭", not warns, "; ".join(warns[:3]))
    check("VSC.树状方言2个", tree_files == 2, str(tree_files))  # init + initeditor
    globals()["SP_PROPERTIES"] = prop_names
    check("VSC.sp属性数", len(prop_names) == 89, str(len(prop_names)))  # T1.2 清单化锁定


# ── T1.3 .vln 结构+编码断言（H3 公式全量验证, research/t13_vln_charset.py）──
def a_vln():
    path = os.path.join(GAME, "data", "scripts", "lang4.vln")
    with open(path, "rb") as f:
        blob = f.read()
    parts = blob.split(b"\x00")[:-1]
    check("VLN.键值成对", len(parts) % 2 == 0, str(len(parts)))
    keys = parts[::2]
    check("VLN.键全ASCII", all(k.isascii() and k for k in keys))
    check("VLN.键无重复", len(set(keys)) == len(keys))
    # 0xFF 转义基线（状态机式计数: ff 后 2 字节为载荷, 载荷内的 ff 不计）
    vals = b"".join(parts[1::2])
    n_ff, i = 0, 0
    while i < len(vals):
        if vals[i] == 0xFF:
            n_ff += 1
            i += 3
        else:
            i += 1
    check("VLN.转义组基数", n_ff == 6405, str(n_ff))
    # 全量解码 + round-trip 字节级一致 + 已知明文
    table = vln.parse_vln(path)
    check("VLN.全量解码", len(table) == 541, str(len(table)))
    chars = os.path.join(GAME, "data", "scripts", "lang4_chars.vsc")
    check("VLN.roundtrip字节一致", vln.encode_vln(table, chars) == blob)
    check("VLN.已知明文GAME_TITLE",
          table.get("GAME_TITLE", "").startswith("虫虫大作战　1.07"),
          repr(table.get("GAME_TITLE", ""))[:40])
    # T3.3: Script 对话/提示键背书 (D_* 敌方嘲讽 18, HINT_* 教学 23)
    check("VLN.对话提示键", sum(k.startswith("D_") for k in table) == 18
          and sum(k.startswith("HINT_") for k in table) == 23)


# ── T1.4 .vfm 断言 ────────────────────────────────────────────────────
def a_vfm():
    files = walk("data", "fontmetrics", ext=".vfm")
    sizes = {os.path.getsize(p) for p in files}
    check("VFM.尺寸三档", sizes == {512, 2048, 8192}, str(sorted(sizes)))
    for p in files:
        vals = vfm.dump_vfm(p)
        check(f"VFM.{os.path.basename(p)}全为u16", all(0 <= v < 65536 for v in vals))
    # T1.4 语义: 步进宽度表, 槽空间=字符集槽位 (research/t14_vfm_index.py)
    fm = os.path.join(GAME, "data", "fontmetrics")
    cn = vfm.dump_vfm(os.path.join(fm, "menufont_01_cn.vfm"))
    special = [i for i, v in enumerate(cn) if v != 48]
    check("VFM.CN特殊槽0-125", special == list(range(126)),
          f"[{special[0] if special else '-'},{special[-1] if special else '-'}]")
    check("VFM.CN句点槽46最窄", cn[46] == 16 and min(cn) == 16)
    check("VFM.CN全角空格48", cn[133] == 48)  # 字形133=U+3000; 若按码点索引会错取 22
    en = vfm.dump_vfm(os.path.join(fm, "menufont_01.vfm"))
    jp = vfm.dump_vfm(os.path.join(fm, "menufont_01_jp.vfm"))
    check("VFM.控制槽", en[10] == 0 and en[13] == 0 and jp[9] == 344,
          f"LF={en[10]} CR={en[13]} JPtab={jp[9]}")
    md5s = {open(os.path.join(fm, f), "rb").read() for f in os.listdir(fm)
            if f.endswith("_cn.vfm")}
    check("VFM.CN四文件一致", len(md5s) == 1)


# ── T2.x .v3d 模型/.van 动画头部断言 ───────────────────────────────────
# 语义 [UNVERIFIED]: 首 u32 疑为骨骼数 (模型与其全部动画共享该值)
def a_v3d_van():
    v3ds = {os.path.basename(p).rsplit(".", 1)[0]: struct.unpack("<I", open(p, "rb").read(4))[0]
            for p in walk("data", ext=".v3d")}
    mism = []
    for p in walk("data", ext=".van"):
        stem = os.path.basename(p).rsplit(".", 1)[0]
        main = stem.split("_")[0]
        van_v = struct.unpack("<I", open(p, "rb").read(4))[0]
        if main in v3ds and van_v != v3ds[main]:
            mism.append(f"{stem}: van首u32={van_v} != v3d首u32={v3ds[main]}")
    check("V3D/VAN.模型动画首u32一致", not mism, "; ".join(mism[:3]))
    check("V3D/VAN.首u32值域", all(
        1 <= v <= 64 for v in v3ds.values()), str(sorted(set(v3ds.values()))[:10]))


# ── T2.1/T2.3 .v3d 根记录 + .van 全量布局断言（research/t21, t23） ──────
def a_v3d_layout():
    # .van: 节点分块关键帧表 [n][n×(k + k×28B)], 键=7×f32(时间,欧拉角xyz,位置xyz)
    tails, n_keys = [], 0
    for p in walk("data", ext=".van"):
        blob = open(p, "rb").read()
        n = struct.unpack("<I", blob[:4])[0]
        off, ks = 4, set()
        for i in range(n):
            k = struct.unpack("<I", blob[off:off + 4])[0]
            ks.add(k)
            n_keys += k
            t0 = struct.unpack("<f", blob[off + 4:off + 8])[0]
            if abs(t0) > 1e-6:
                check(f"VAN.首键t0.{os.path.basename(p)}", False, f"块{i} t={t0}")
            off += 4 + k * 28
        check(f"VAN.块键数一致.{os.path.basename(p)}", len(ks) == 1)
        if off != len(blob):
            tails.append(os.path.basename(p))
    check("VAN.尾段恰2", sorted(tails) == ["bee_flight.van", "toxichero_walk.van"],
          str(tails))
    check("VAN.键总数", n_keys == 78053, str(n_keys))
    # tick 锚点: 节点数 38 == .vant 段数(MESH1+MODEL1+ROOT11+BONE25)
    tick = open(os.path.join(GAME, "data", "models", "bugs", "tick_idle2.van"), "rb").read()
    check("VAN.tick节点38", struct.unpack("<I", tick[:4])[0] == 38)
    # .v3d 根记录: [A][len][名][mat64 行主序 m15=1][parent i32][flag u32][vc][顶点×36B]
    bad_name, bad_mat, bad_geo = [], [], []
    for p in walk("data", ext=".v3d"):
        blob = open(p, "rb").read()
        a, ln = struct.unpack("<2I", blob[:8])
        name = blob[8:8 + ln]
        if not (1 <= a <= 64 and 0 < ln < 64
                and all(0x20 <= b < 0x7F for b in name)):
            bad_name.append(os.path.basename(p))
        m = struct.unpack("<16f", blob[8 + ln:8 + ln + 64])
        if m[3] != 0 or m[7] != 0 or m[11] != 0 or m[15] != 1:
            bad_mat.append(os.path.basename(p))
        off = 8 + ln + 64 + 8  # + parent + flag
        vc = struct.unpack("<I", blob[off:off + 4])[0]
        off += 4 + vc * 36
        k = struct.unpack("<I", blob[off:off + 4])[0]
        ic = struct.unpack("<I", blob[off + 4:off + 8])[0]
        idx = struct.unpack(f"<{ic}H", blob[off + 8:off + 8 + ic * 2])
        if k not in (1, 2) or (ic and max(idx) >= vc) or off + 8 + ic * 2 > len(blob):
            bad_geo.append(f"{os.path.basename(p)}: vc={vc} k={k} ic={ic}")
    check("V3D.根记录名合法", not bad_name, "; ".join(bad_name[:3]))
    check("V3D.根矩阵行主序", not bad_mat, "; ".join(bad_mat[:3]))
    check("V3D.根几何块自洽", not bad_geo, "; ".join(bad_geo[:3]))
    # T2.2: 顶点 diffuse 槽恒 0xFFFFFFFF (D3DFVF DIFFUSE); 蒙皮段纹理名可解 (T2.4 贴图腿)
    bad_diff, bad_tex = [], []
    for p in walk("data", ext=".v3d"):
        blob = open(p, "rb").read()
        a, ln = struct.unpack("<2I", blob[:8])
        off = 8 + ln + 64 + 8
        vc = struct.unpack("<I", blob[off:off + 4])[0]
        for i in range(vc):
            if blob[off + 4 + i * 36 + 24:off + 4 + i * 36 + 28] != b"\xff\xff\xff\xff":
                bad_diff.append(os.path.basename(p))
                break
        k, ic = struct.unpack("<2I", blob[off + 4 + vc * 36:off + 12 + vc * 36])
        geo_end = off + 12 + vc * 36 + ic * 2
        e = blob.find(b"\x00", geo_end)
        tname = blob[geo_end:e].decode("ascii", "replace")
        if not os.path.isfile(os.path.join(GAME, "data", "textures", tname + ".vtx")):
            bad_tex.append(f"{os.path.basename(p)}:{tname}")
    check("V3D.顶点diffuse恒白", not bad_diff, "; ".join(bad_diff[:3]))
    check("XREF.模型纹理可解", not bad_tex, "; ".join(bad_tex[:3]))


# ── T4.2 世界网格遍历 + Water 二值断言 ────────────────────────────────
def a_v3d_world():
    # 每 mesh 节点 = [记录][几何[vc][36B×vc][k=材质数][ic][u16]][材质尾段(纹理名\0+填充)];
    # k∈{1..4} 与 .vsc World 块 Material0-N 计数 82/82 相等 (research/t42_semantics.py)
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
    from bugbits.assets import v3d as _v3d
    bad_mesh, bad_tex = [], []
    for p in walk("data", "models", "worlds", ext=".v3d"):
        a = _v3d.u32(open(p, "rb").read(), 0)
        try:
            meshes = _v3d.parse_world_meshes(p)
        except ValueError as e:
            bad_mesh.append(f"{os.path.basename(p)}: {e}")
            continue
        if len(meshes) != a:
            bad_mesh.append(f"{os.path.basename(p)}: mesh 数 {len(meshes)} != A={a}")
        for m in meshes:
            if not (m.k in (1, 2, 3, 4) and m.ic > 0 and max(m.indices) < len(m.verts)):
                bad_mesh.append(f"{os.path.basename(p)}/{m.name}: k={m.k} ic={m.ic}")
            if m.tex_name and not os.path.isfile(
                    os.path.join(GAME, "data", "textures", m.tex_name + ".vtx")):
                bad_tex.append(f"{os.path.basename(p)}/{m.name}: {m.tex_name}")
    check("V3D.世界网格自洽", not bad_mesh, "; ".join(bad_mesh[:3]))
    check("V3D.世界网格纹理可解", not bad_tex, "; ".join(bad_tex[:3]))
    # Water = 二值 flag (0/1), 仅 START/WAYPOINT 携带; =1 共 39 处全为 WAYPOINT
    vals, nonzero_types = set(), set()
    for p in walk("data", "worlds", ext=".vsc"):
        from bugbits.assets import vsc as _vsc
        cmds = _vsc.parse_vsc(p)
        blocks, cur = {}, None
        for _, cmd, args in cmds:
            if cmd == ">":
                cur = args[0]
                blocks[cur] = {}
            elif cmd == "<":
                cur = None
            elif cmd == "sp" and cur and args:
                blocks[cur].setdefault(args[0], args[1:])
        types = {c[2][0]: c[2][1] for c in cmds if c[1] == "SpawnEntity" and len(c[2]) == 2}
        for n, sp in blocks.items():
            if "Water" in sp:
                v = float(sp["Water"][0])
                vals.add(v)
                if v != 0.0:
                    nonzero_types.add(types.get(n, "?"))
    check("V3D.Water二值", vals <= {0.0, 1.0}, str(sorted(vals)))
    check("V3D.Water=1仅WAYPOINT", nonzero_types <= {"WAYPOINT"}, str(nonzero_types))


# ── T2.4 脚本↔模型/动画交叉引用断言（research/t24_crossref.py） ─────────
def a_xref():
    files = walk("data", "scripts", ext=".vsc") + walk("data", "worlds", ext=".vsc")
    model_refs, anim_refs, units = set(), set(), set()
    for p in files:
        for _, cmd, args in vsc.parse_vsc(p):
            if cmd == "sp" and args:
                if args[0] == "Model":
                    model_refs.add(args[1])
                elif args[0] in {"AnimWalk", "AnimIdle", "AnimNormalAttack", "AnimHurt",
                                 "AnimSpecialAttack", "AnimSpecialMove"}:
                    anim_refs.add(args[1])
            elif cmd == "BugSetup" and len(args) == 3:
                units.add(args[1])
    models = os.path.join(GAME, "data", "models")

    def resolve(ref, ext):
        cur = models
        segs = ref.split("/")
        for i, seg in enumerate(segs):
            want = seg + ext if i == len(segs) - 1 else seg
            hit = next((n for n in os.listdir(cur) if n.lower() == want.lower()), None)
            if hit is None:
                return False
            cur = os.path.join(cur, hit)
        return True

    check("XREF.Model引用可解", len(model_refs) == 33
          and all(resolve(r, ".v3d") for r in model_refs), str(len(model_refs)))
    check("XREF.Anim引用可解", len(anim_refs) == 84
          and all(resolve(r, ".van") for r in anim_refs), str(len(anim_refs)))
    bugs = os.path.join(models, "bugs")
    b_v3d = {f[:-4] for f in os.listdir(bugs) if f.endswith(".v3d")}
    b_van = {f[:-4] for f in os.listdir(bugs) if f.endswith(".van")}
    check("XREF.bugs双向覆盖",
          b_v3d == {r.split("/")[-1] for r in model_refs if r.lower().startswith("bugs/")}
          and b_van == {r.split("/")[-1] for r in anim_refs if r.lower().startswith("bugs/")})
    buginfos = {f[:-4] for f in os.listdir(
        os.path.join(GAME, "data", "scripts", "buginfos"))}
    # BugSetup 22 = 20 已定义 + 2 引擎特例; buginfos 24 = 20 + 4 坐骑变体(_tick+tick)
    check("XREF.BugSetup单位集", units - {"nectarbonus", "trapped"} == buginfos
          - {"beetlehero_tick", "tick", "toxichero_tick", "wasphero_tick"})


# ── 杂项: ogg 魔数 ────────────────────────────────────────────────────
def a_ogg():
    bad = [os.path.basename(p) for p in walk("data", ext=".ogg")
           if open(p, "rb").read(4) != b"OggS"]
    check("OGG.魔数", not bad, "; ".join(bad[:3]))


def a_font():
    """NC-harness C：字体覆盖 = required 资产验收（离线，只验 cmap，不重生成/下载）。

    复用 research/nc04_font_coverage.py `check` 作为唯一覆盖判定来源（字体重建/下载
    不在本 gate；日常校验离线）。「串」等开发者异常串保留安全超集——只增覆盖不分类
    收窄。缺字或字体验证脚本不可运行时 exit 非零，传播到 harness 全绿门槛。
    """
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run(
        [sys.executable, "research/nc04_font_coverage.py", "check",
         "web/NotoSansSC-subset.woff2"],
        cwd=repo, capture_output=True, text=True)
    detail = (r.stdout + r.stderr).strip().replace("\n", " ")[-200:]
    check("字体.cmap覆盖全静态字符集", r.returncode == 0, detail)


def main():
    quick = "--quick" in sys.argv
    suites = [a_inventory, a_vtx, a_vsc, a_vln, a_vfm, a_v3d_van, a_v3d_layout,
              a_v3d_world, a_xref, a_ogg, a_font]
    for s in suites:
        try:
            s()
        except Exception as e:  # noqa: BLE001 — harness 自身缺陷也要显式失败
            check(f"SUITE.{s.__name__}", False, repr(e))
        if quick:
            break
    for name in PASS:
        print(f"  ✓ {name}")
    for name in FAIL:
        print(f"  ✗ {name}")
    print(f"\n{len(PASS)} 通过, {len(FAIL)} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
