"""H1 assets 用例实现（W1；loop-web.md §H1，清单见 design/plans/W0-web-contract.md §7.1）。

独立预期来源：原解析器对象（DATA 级，经 src/bugbits 直接读原始数据）、
采样公式（W1 计划固定常数）、投影定义（合同 §6.5）——不从被测输出反抄。

HARNESS-01：本文件的可再生工作副本（det/sens/tamper/rf-b02/b03）一律经
ctx.work_dir() 写 scratch（PASS 回收/FAIL 有界保留），不再落 out/web-harness
run_dir（那里只留报告级证据）。大构建前经 ctx.check_budget() 过水位。
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "harness" / "web"))

from cases import BlockedError, CaseResult  # noqa: E402

import scratch as scratch_mod  # noqa: E402  (harness/web/scratch.py)

from bugbits import level as levelmod  # noqa: E402
from bugbits import unitdb, web_build, web_data, worlddb  # noqa: E402
from bugbits.assets import data_dir  # noqa: E402
from bugbits.render import camera  # noqa: E402

# 子构建水位预估裕量：构建中间产物 + 同 run 多副本并存的余量（有依据的
# 保守值——实测 slice 包 ~26M / full ~77M，裕量取 256MB 覆盖峰值）。
_BUILD_MARGIN_BYTES = 256 * 1024 * 1024


def _build_need(ctx):
    """单次子构建的峰值预估：受测包实测大小 + 裕量。"""
    return scratch_mod.du(ctx.web_out) + _BUILD_MARGIN_BYTES


def _seed_vendor_cache(ctx):
    """子构建的 pyodide 缓存软链到仓库缓存（out/.vendor-cache）。

    web_build._vendor_pyodide 的缓存目录 = out_dir 父目录/.vendor-cache——
    子构建 out 在本 run scratch 内 → 不 seeding 则每 run 重新下载（网络依赖
    +重复流量）。软链在 scratch 回收时被 unlink 不触目标（sens-root 同款
    安全口径）；仓库无缓存（新环境）时跳过，走原下载路径。"""
    src_dir = ROOT / "out" / ".vendor-cache"
    if not src_dir.is_dir() or not ctx.scratch_dir:
        return
    dst = Path(ctx.scratch_dir) / ".vendor-cache"
    if dst.exists() or dst.is_symlink():
        return
    os.symlink(src_dir, dst)


def _load_manifest(ctx):
    p = ctx.web_out / "manifest.json"
    if not p.is_file():
        raise BlockedError(
            f"无构建产物 {p}——先运行 python3 tools/web_build.py "
            f"--profile {ctx.profile} --out out/web")
    mf = json.loads(p.read_text(encoding="utf-8"))
    if mf.get("profile") != ctx.profile:
        raise BlockedError(f"构建 profile={mf.get('profile')!r} 与测试 "
                           f"profile={ctx.profile!r} 不符，需重建")
    return mf


def _sub_build(out_dir, data_root=None, profile="slice"):
    cmd = [sys.executable, "tools/web_build.py", "--profile", profile,
           "--out", str(out_dir)]
    if data_root:
        cmd += ["--data-root", str(data_root)]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(f"构建失败({r.returncode}): {r.stdout}\n{r.stderr}")
    return json.loads((Path(out_dir) / "manifest.json").read_text(encoding="utf-8"))


# ── A01 manifest schema + 文件哈希 ───────────────────────────────────
def a01(ctx):
    mf = _load_manifest(ctx)
    for field in ("schemaVersion", "buildId", "profile", "runtime", "config",
                  "files", "levels", "capabilities", "fallbacks", "projection",
                  "spriteStats", "missingTextKeys", "atlasPages",
                  "terrainFiles", "audioFiles", "inputs"):
        assert field in mf, f"manifest 缺字段 {field}"
    listed = set()
    for e in mf["files"]:
        p = ctx.web_out / e["path"]
        assert p.is_file(), f"files 条目缺失 {e['path']}"
        assert p.stat().st_size == e["size"], f"size 不符 {e['path']}"
        assert web_build.sha256_file(p) == e["sha256"], f"sha256 不符 {e['path']}"
        listed.add(e["path"])
    on_disk = {str(p.relative_to(ctx.web_out))
               for p in ctx.web_out.rglob("*") if p.is_file()}
    assert on_disk - {"manifest.json"} == listed, "盘上文件与 manifest 清单不一致"
    return CaseResult("PASS", f"{len(listed)} 文件哈希全符")


# ── A02 引用闭包 ─────────────────────────────────────────────────────
def a02(ctx):
    mf = _load_manifest(ctx)
    units = json.loads((ctx.web_out / "units.json").read_text(encoding="utf-8"))
    texts = json.loads((ctx.web_out / "texts.json").read_text(encoding="utf-8"))
    for lv in mf["levels"]:
        for u in lv["deps"]["units"]:
            assert u in units, f"{lv['id']} 依赖单位 {u} 不在 units.json"
        assert (ctx.web_out / "worlds" / (lv["world"] + ".json")).is_file(), \
            f"{lv['id']} 世界未导出"
        assert (ctx.web_out / "levels" / (lv["id"] + ".json")).is_file()
        lvo = web_data.restore_level(json.loads(
            (ctx.web_out / "levels" / (lv["id"] + ".json")).read_text(encoding="utf-8")))
        for sub, args in lvo.scripts:
            if sub in ("sendenemy", "sendplayer"):
                assert args[0] in units, f"脚本单位 {args[0]} 缺"
                if args[2] != "null":
                    assert args[2] in texts, f"对话键 {args[2]} 缺"
            if sub == "addhint":
                assert args[0] in texts, f"HINT 键 {args[0]} 缺"
        for u in lv["buyable"]:
            assert u in units and f"BUGNAME_{u.upper()}" in texts, \
                f"可买单位 {u} 缺单位定义或 BUGNAME 文本"
        if lv["deps"].get("music"):
            assert any(e["path"] == lv["deps"]["music"] for e in mf["files"]), \
                f"音乐 {lv['deps']['music']} 未打包"
    if mf["profile"] == "slice":
        assert [l["id"] for l in mf["levels"]] == ["level_02"], \
            "slice 必须只含 level_02"
    # 数据引用键（关卡/脚本/hint/对话）必须全部存在
    assert mf["missingTextKeys"] == [], f"文本键缺失未解释: {mf['missingTextKeys']}"
    # UI 键（单位名/统计/描述）缺失=数据面缺失，须显式登记（HUD 回退显示）
    ui_missing = set(mf.get("uiTextMissing") or [])
    units = json.loads((ctx.web_out / "units.json").read_text(encoding="utf-8"))
    for lv in mf["levels"]:
        for u in lv["buyable"]:
            name_key = (units[u].get("infoProps", {}).get("NameText") or [None])[0]
            if name_key and name_key not in texts:
                assert name_key in ui_missing, \
                    f"可买单位 {u} 名字键 {name_key} 缺失且未登记 uiTextMissing"
    return CaseResult("PASS", f"{len(mf['levels'])} 关闭包完整")


# ── A03 采样帧数独立重算 + 精灵存在 ──────────────────────────────────
def a03(ctx):
    mf = _load_manifest(ctx)
    atlas = json.loads((ctx.web_out / "atlas.json").read_text(encoding="utf-8"))
    n_checked = 0
    for lv in mf["levels"]:
        for u in lv["deps"]["units"]:
            spec = unitdb.load_unit(u)
            for clip, c in atlas["clips"][u].items():
                if c["kind"] == "sampled":
                    dur = web_build._van_duration(c["ref"])
                    assert dur is not None and abs(dur - c["duration"]) < 1e-9, \
                        f"{u}.{clip} duration {c['duration']} != 独立重算 {dur}"
                    n = web_build.frame_count(dur)
                    assert c["frames"] == n, \
                        f"{u}.{clip} frames {c['frames']} != 公式值 {n}"
                    for i in sorted({0, n // 2, n - 1}):
                        for y in range(mf["config"]["yaws"]):
                            k = f"{c['prefix']}.f{i}.y{y}"
                            assert k in atlas["sprites"], f"缺精灵 {k}"
                    n_checked += 1
                elif c["kind"] == "static":
                    for y in range(mf["config"]["yaws"]):
                        k = f"{c['prefix']}.y{y}"
                        assert k in atlas["sprites"], f"缺静态精灵 {k}"
                    n_checked += 1
                else:
                    assert c["kind"] == "missing" and c.get("fallbackClip"), \
                        f"{u}.{clip} 非法 kind"
    return CaseResult("PASS", f"{n_checked} clip 采样/精灵核验")


# ── A04 alpha 统计与 fallback 登记 ───────────────────────────────────
def a04(ctx):
    from PIL import Image
    mf = _load_manifest(ctx)
    atlas = json.loads((ctx.web_out / "atlas.json").read_text(encoding="utf-8"))
    fb_static = {e["unit"] for e in mf["fallbacks"] if e.get("kind") == "static"}
    for u, st in mf["spriteStats"].items():
        assert st["blankSprites"] == [], f"{u} 空白精灵: {st['blankSprites']}"
        assert st["minBBoxRatio"] and st["minBBoxRatio"] > 0, f"{u} bbox 全空"
        if any(c["kind"] == "static" for c in atlas["clips"][u].values()):
            assert u in fb_static, f"{u} 静态降级未登记 fallbacks"
    # 独立抽验一个 static 单位精灵非空 alpha
    for e in mf["fallbacks"]:
        if e.get("kind") != "static":
            continue
        u = e["unit"]
        prefix = next(c["prefix"] for c in atlas["clips"][u].values()
                      if c["kind"] == "static")
        s = atlas["sprites"][f"{prefix}.y0"]
        page = Image.open(ctx.web_out / atlas["pages"][s["page"]]["file"])
        img = page.crop((s["x"], s["y"], s["x"] + s["w"], s["y"] + s["h"]))
        assert img.split()[3].getbbox() is not None, f"{u} 静态精灵空 alpha"
        break
    return CaseResult("PASS", f"{len(mf['spriteStats'])} 单位 alpha/fallback 核验")


# ── A05 对象往返逐字段 ───────────────────────────────────────────────
def a05(ctx):
    mf = _load_manifest(ctx)
    lv_o = levelmod.parse_level(data_dir("scripts", "levels", "level_02.vsc"))
    lv_r = web_data.restore_level(json.loads(
        (ctx.web_out / "levels" / "level_02.json").read_text(encoding="utf-8")))
    assert lv_r == lv_o, "LevelData 往返不等"
    assert type(lv_r.scripts[0][1]) is list and lv_r.scripts[0][1] == \
        lv_o.scripts[0][1], "脚本序/参数类型丢失"
    w_o = worlddb.parse_world(data_dir("worlds", "world_02.vsc"))
    w_r = web_data.restore_world(json.loads(
        (ctx.web_out / "worlds" / "world_02.json").read_text(encoding="utf-8")))
    assert w_r == w_o, "WorldData 往返不等"
    assert isinstance(w_r.adjacency[w_r.waypoints[0].name], set), "邻接 set 丢失"
    assert isinstance(w_r.starts[0].grid_pos, tuple), "位置 tuple 丢失"
    assert isinstance(w_r.terrain, tuple), "terrain tuple 丢失"
    units = json.loads((ctx.web_out / "units.json").read_text(encoding="utf-8"))
    for u in {x for lv in mf["levels"] for x in lv["deps"]["units"]}:
        s_o = unitdb.load_unit(u)
        s_r = web_data.restore_unit(units[u])
        assert s_r == s_o, f"UnitSpec {u} 往返不等"
        assert isinstance(s_r.attack_hit_frames, tuple), "attack_hit_frames tuple 丢失"
        assert (s_r.attack_duration is None) == (s_o.attack_duration is None), \
            f"{u} attack_duration None 语义丢失"
        # dataclass __eq__ 只比声明字段——实例 __dict__ 全量比对
        # （W2 B01 抓出 speed 等动态属性假绿的回归锚点）
        assert vars(s_r) == vars(s_o), \
            f"{u} 实例属性不等: " + str({k for k in set(vars(s_o))
                                        | set(vars(s_r))
                                        if vars(s_o).get(k) != vars(s_r).get(k)})
    # None ≠ 0 专项（合同 §7.1）
    assert web_data.restore_unit(
        {"name": "x", "attackDuration": None}).attack_duration is None
    assert web_data.restore_unit(
        {"name": "x", "attackDuration": 0}).attack_duration == 0
    return CaseResult("PASS", "level_02/world_02/units 往返逐字段相等")


# ── A06 两次构建一致 ─────────────────────────────────────────────────
def a06(ctx):
    need = _build_need(ctx)
    _seed_vendor_cache(ctx)
    ctx.check_budget(need, "A06 det-a")            # HARNESS-01：大构建前水位
    a = _sub_build(ctx.work_dir("det-a"), profile=ctx.profile)
    ctx.check_budget(need, "A06 det-b")
    b = _sub_build(ctx.work_dir("det-b"), profile=ctx.profile)
    assert a == b, "两次构建 manifest 不一致"
    ha = {e["path"]: e["sha256"] for e in a["files"]}
    hb = {e["path"]: e["sha256"] for e in b["files"]}
    assert ha == hb, "两次构建内容散列不一致"
    for rel in ha:
        assert (ctx.scratch_dir / "det-a" / rel).is_file()
    return CaseResult("PASS", f"buildId={a['buildId'][:16]}… 两次构建逐字节一致")


# ── A07 buildId 输入敏感性 ───────────────────────────────────────────
def a07(ctx):
    # 符号链接数据根：仅 level_02.vsc 为真实修改副本，其余指向原始数据
    _seed_vendor_cache(ctx)
    fx = ctx.work_dir("sens-root")
    orig = Path(data_dir()).parent                  # .../ccdzz（含 data/）
    (fx / "data").mkdir(parents=True, exist_ok=True)
    for sub in os.listdir(orig / "data"):
        src = orig / "data" / sub
        if sub != "scripts":
            if not (fx / "data" / sub).exists():
                os.symlink(src, fx / "data" / sub)
    # scripts 目录逐文件链接（levels 里的 level_02.vsc 用修改副本）
    for dp, dns, fns in os.walk(orig / "data" / "scripts"):
        rel = Path(dp).relative_to(orig / "data")
        (fx / "data" / rel).mkdir(parents=True, exist_ok=True)
        for fn in fns:
            dst = fx / "data" / rel / fn
            if dst.exists():
                continue
            if rel.as_posix() == "scripts/levels" and fn == "level_02.vsc":
                txt = Path(dp, fn).read_text(encoding="utf-8")
                dst.write_text(txt.replace("sp InitialNectar 10",
                                           "sp InitialNectar 11"),
                               encoding="utf-8")
            else:
                os.symlink(Path(dp) / fn, dst)
    need = _build_need(ctx)
    ctx.check_budget(need, "A07 sens-a")           # HARNESS-01：大构建前水位
    a = _sub_build(ctx.work_dir("sens-a"), profile=ctx.profile)
    ctx.check_budget(need, "A07 sens-b")
    b = _sub_build(ctx.work_dir("sens-b"), data_root=fx,
                   profile=ctx.profile)
    assert a["buildId"] != b["buildId"], "输入变化未改变 buildId"
    la = json.loads((ctx.scratch_dir / "sens-a" / "levels" / "level_02.json")
                    .read_text(encoding="utf-8"))
    lb = json.loads((ctx.scratch_dir / "sens-b" / "levels" / "level_02.json")
                    .read_text(encoding="utf-8"))
    assert la["props"]["InitialNectar"] == ["10"], "基准构建内容异常"
    assert lb["props"]["InitialNectar"] == ["11"], "修改未生效（数据根覆盖失效）"
    # 输入指纹覆盖面：vsc/lang4 之外，模型/动画/纹理/地形/音频必须入指纹
    need = [
        "scripts/levels/level_02.vsc", "scripts/lang4.vln", "worlds/world_02.vsc",
        "scripts/bugs/ant.vsc", "scripts/buginfos/ant.vsc",
        "models/bugs/ant.v3d", "models/bugs/ant_walk.van",
        "models/worlds/world_02.v3d", "audio/music/grass.ogg",
    ]
    inputs = set(a["inputs"])
    for rel in need:
        assert rel in inputs, f"buildId 输入指纹漏 {rel}"
    tex = [i for i in inputs if i.startswith("textures/")
           and i.endswith(".vtx")]
    assert tex, "纹理未入指纹"
    return CaseResult("PASS", "改 1 源字节 → buildId 变化; "
                      f"指纹覆盖 {len(inputs)} 源文件含模型/动画/纹理/音频")


# ── A08 透视投影（OF-03.B/C：静态斜俯视） ───────────────────────────
def a08(ctx):
    mf = _load_manifest(ctx)
    w = worlddb.parse_world(data_dir("worlds", "world_02.vsc"))
    pr = mf["projection"]["world_02"]
    xmin, xmax, _, _, zmin, zmax = w.terrain
    span_x, span_z = xmax - xmin, zmax - zmin
    assert span_x != span_z, "校验前提：world_02 须为非方形"
    # 投影参数 = camera.static_oblique_camera 几何常数序列化（用原 bounds 独立重建）
    cam = camera.static_oblique_camera((xmin, xmax, zmin, zmax), pr["size"])
    pairs = (("cx", "cx"), ("cz", "cz"), ("cot", "cot"),
             ("sinP", "sin_p"), ("cosP", "cos_p"), ("tanP", "tan_p"),
             ("distance", "distance"), ("near", "near"), ("far", "far"))
    for k, attr in pairs:
        assert abs(pr[k] - getattr(cam, attr)) < 1e-9, f"projection[{k}] 与相机常数不符"
    # 透视常数自洽：cot=√3（fov=60°）、sin/cos/tan 互洽
    assert abs(pr["cot"] - 3 ** 0.5) < 1e-9, "fov≠60°（cot 应=√3）"
    assert abs(pr["sinP"] / pr["cosP"] - pr["tanP"]) < 1e-9, "sin/cos/tan 不自洽"
    # bounds 中心 → 画布中心
    cx, cy = cam.world_to_pixel((xmin + xmax) / 2, 0.0, (zmin + zmax) / 2)
    assert abs(cx - pr["size"] / 2) < 1e-6 and abs(cy - pr["size"] / 2) < 1e-6, \
        "bounds 中心未映射到画布中心"
    # 全部 start/waypoint 在界内 + 逆映射往返
    for s in w.starts + w.waypoints:
        x, z = s.grid_pos[0], s.grid_pos[2]
        px, py = cam.world_to_pixel(x, 0.0, z)
        assert 0 <= px <= pr["size"] and 0 <= py <= pr["size"], f"{s.name} 投影出界"
        rx, rz = cam.pixel_to_ground(px, py)
        assert abs(rx - x) < 1e-6 and abs(rz - z) < 1e-6, f"{s.name} 逆映射漂移"
    # 透视缩短：远缘（zmax，画面上方）横向像素跨度 < 近缘（zmin，画面下方）
    near_span = abs(cam.world_to_pixel(xmax, 0.0, zmin)[0]
                    - cam.world_to_pixel(xmin, 0.0, zmin)[0])
    far_span = abs(cam.world_to_pixel(xmax, 0.0, zmax)[0]
                   - cam.world_to_pixel(xmin, 0.0, zmax)[0])
    assert 0 < far_span < near_span, f"无透视缩短 near={near_span:.1f} far={far_span:.1f}"
    return CaseResult("PASS",
                      f"span=({span_x:.0f},{span_z:.0f}) 透视斜俯视；往返一致；"
                      f"近缘{near_span:.0f}px>远缘{far_span:.0f}px")


# ── 负例辅助 ─────────────────────────────────────────────────────────
def _tamper_copy(ctx, tag):
    dst = ctx.work_dir(f"tamper-{tag}")    # HARNESS-01：可再生副本 → scratch
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(ctx.web_out, dst)
    return dst


def _rehash(manifest_path, rel):
    mf = json.loads(manifest_path.read_text(encoding="utf-8"))
    for e in mf["files"]:
        if e["path"] == rel:
            p = manifest_path.parent / rel
            e["size"] = p.stat().st_size
            e["sha256"] = web_build.sha256_file(p)
    # files 变更后 artifactDigest 必须同步重算（否则 validate 早退报 digest 不符，
    # 掩盖真正的解码/引用检查——负例的哈希自洽语义）
    mf["artifactDigest"] = _artifact_digest(mf["files"])
    manifest_path.write_text(json.dumps(mf, ensure_ascii=False, indent=1,
                                        sort_keys=True), encoding="utf-8")


def _expect_error(ctx, dst, needle, case_id):
    errs = web_build.validate(dst)
    hits = [e for e in errs if needle in e]
    assert hits, f"validate 未报 {needle!r}（报了: {errs[:5]}）"
    return CaseResult("PASS", f"负例命中: {hits[0]}")


def a09(ctx):
    _load_manifest(ctx)
    dst = _tamper_copy(ctx, "a09")
    (dst / "levels" / "level_02.json").unlink()
    r1 = _expect_error(ctx, dst, "levels/level_02.json", "a09")
    (dst / "stray.txt").write_text("x")
    errs = web_build.validate(dst)
    assert any("未登记" in e for e in errs), f"stray 文件未检出: {errs[:5]}"
    return r1


def a10(ctx):
    _load_manifest(ctx)
    dst = _tamper_copy(ctx, "a10")
    with open(dst / "texts.json", "ab") as f:
        f.write(b" ")
    r = _expect_error(ctx, dst, "sha256 不符: texts.json", "a10")
    dst2 = _tamper_copy(ctx, "a10b")
    mf = json.loads((dst2 / "manifest.json").read_text(encoding="utf-8"))
    del mf["schemaVersion"]
    (dst2 / "manifest.json").write_text(json.dumps(mf), encoding="utf-8")
    errs = web_build.validate(dst2)
    assert any("schemaVersion" in e for e in errs), f"schema 篡改未检出: {errs[:5]}"
    return r


def a11(ctx):
    _load_manifest(ctx)
    dst = _tamper_copy(ctx, "a11")
    png = dst / "atlas_0.png"
    data = png.read_bytes()
    png.write_bytes(data[: len(data) // 2])          # 截断
    _rehash(dst / "manifest.json", "atlas_0.png")    # 哈希自洽以单测解码路径
    return _expect_error(ctx, dst, "解码失败", "a11")


def a12(ctx):
    _load_manifest(ctx)
    dst = _tamper_copy(ctx, "a12")
    ap = dst / "atlas.json"
    atlas = json.loads(ap.read_text(encoding="utf-8"))
    victim = next(k for k in atlas["sprites"] if ".f0.y0" in k)
    del atlas["sprites"][victim]
    ap.write_text(json.dumps(atlas, ensure_ascii=False, sort_keys=True),
                  encoding="utf-8")
    _rehash(dst / "manifest.json", "atlas.json")
    return _expect_error(ctx, dst, victim, "a12")


# ── RF-01 构建归属与结果追溯 ─────────────────────────────────────────
def _artifact_digest(files):
    return hashlib.sha256(
        json.dumps(files, sort_keys=True).encode()).hexdigest()


def rf_b01(ctx):
    """profile 关联：报告头/ctx.manifest 读本 profile 产物，不借用另一 profile。"""
    mf = _load_manifest(ctx)
    assert mf["profile"] == ctx.profile, "manifest.profile 与测试 profile 不符"
    assert mf.get("artifactDigest"), "manifest 缺 artifactDigest"
    # runner 报告的 manifest（ctx.manifest）必须来自本 profile，且记录实际服务目录
    assert ctx.manifest.get("present"), "runner manifest 报告 present=False"
    assert ctx.manifest.get("buildId") == mf["buildId"], \
        "报告 buildId 与受测 manifest 不一致"
    assert ctx.manifest.get("artifactDigest") == mf["artifactDigest"], \
        "报告 artifactDigest 与受测 manifest 不一致"
    assert ctx.manifest.get("webOut") == str(ctx.web_out), \
        "报告 webOut 与实际服务目录不一致"
    # slice/full 是不同构建 → buildId 与 artifactDigest 均应不同（在另一 profile
    # 已构建时交叉核对；未构建则跳过，非阻塞）
    other = "full" if ctx.profile == "slice" else "slice"
    other_mf = Path(ctx.web_out).parent.parent / (
        "web-full" if other == "full" else "web") / "manifest.json"
    if other_mf.is_file():
        om = json.loads(other_mf.read_text(encoding="utf-8"))
        assert om["buildId"] != mf["buildId"], "slice/full buildId 相同（异常）"
        assert om["artifactDigest"] != mf["artifactDigest"], \
            "slice/full artifactDigest 相同（异常）"
    return CaseResult("PASS",
                      f"profile={ctx.profile} 关联正确; "
                      f"webOut={ctx.manifest['webOut']}")


def rf_b02(ctx):
    """artifactDigest 覆盖交付文件（含页面源码/交付核心包）且对内容敏感。"""
    mf = _load_manifest(ctx)
    # 1) manifest 自带 artifactDigest 与 files 独立重算一致
    assert mf["artifactDigest"] == _artifact_digest(mf["files"]), \
        "artifactDigest 与 files 清单不一致"
    # 2) 交付覆盖清单：HTML/host/worker + 交付核心包必须入摘要
    paths = {e["path"] for e in mf["files"]}
    for need in ("index.html", "host.js", "worker.js", "py-bundle.json"):
        assert need in paths, f"artifactDigest 未覆盖交付文件 {need}"
    # 3) 临时副本修改 host.js → 摘要变化（不污染真实产物）；同输入两次一致
    #    由 A06（两次构建 manifest 含 artifactDigest 逐字节相等）覆盖
    dst = ctx.work_dir("rf-b02")           # HARNESS-01：可再生副本 → scratch
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(ctx.web_out, dst)
    host = dst / "host.js"
    host.write_text(host.read_text(encoding="utf-8") + "\n// rf-b02 tamper\n",
                    encoding="utf-8")
    files2 = []
    for dp, _, fs in os.walk(dst):
        for fn in sorted(fs):
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, dst).replace(os.sep, "/")
            if rel == "manifest.json":
                continue
            files2.append({"path": rel, "size": os.path.getsize(p),
                           "sha256": web_build.sha256_file(p)})
    files2.sort(key=lambda e: e["path"])
    assert _artifact_digest(files2) != mf["artifactDigest"], \
        "修改 host.js 未改变 artifactDigest"
    return CaseResult("PASS",
                      "artifactDigest 覆盖页面源码+交付核心包; 修改 host.js → 摘要变化")


def rf_b03(ctx):
    """缺失 manifest / 陈旧页面产物 / 篡改 artifactDigest 的失败回归。"""
    _load_manifest(ctx)
    # 1) 缺失 manifest → validate 报缺失
    empty = ctx.work_dir("rf-b03-empty")   # HARNESS-01：可再生副本 → scratch
    errs = web_build.validate(empty)
    assert any("manifest.json 缺失" in e for e in errs), \
        f"缺失 manifest 未检出: {errs}"
    # 2) 陈旧页面产物（host.js 改动但 manifest 未重算）→ validate 报 sha256 不符
    dst = _tamper_copy(ctx, "rf-b03")
    with open(dst / "host.js", "ab") as f:
        f.write(b" ")
    errs = web_build.validate(dst)
    assert any("sha256 不符: host.js" in e for e in errs), \
        f"陈旧 host.js 未检出: {errs[:5]}"
    # 3) 篡改 manifest.artifactDigest → validate 报不符（防手改 manifest 假绿）
    dst2 = _tamper_copy(ctx, "rf-b03b")
    mf = json.loads((dst2 / "manifest.json").read_text(encoding="utf-8"))
    mf["artifactDigest"] = "0" * 64
    (dst2 / "manifest.json").write_text(
        json.dumps(mf, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8")
    errs = web_build.validate(dst2)
    assert any("artifactDigest 不符" in e for e in errs), \
        f"篡改 artifactDigest 未检出: {errs[:5]}"
    return CaseResult("PASS",
                      "缺失 manifest / 陈旧 host.js / 篡改 artifactDigest 均被检出")
