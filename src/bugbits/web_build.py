"""Web 构建（W1）：slice/full 资源导出 + 产物校验。CLI 薄壳 tools/web_build.py。

流程（export）：survey 闭包 → 渲染精灵/地形 → 图集装箱 → JSON 导出（web_data
schema）→ 音频复制 → manifest（buildId 无时间戳；无增量缓存，全量重建）。
validate(out_dir) 只读产物自身（不碰原始数据）：schema/哈希/闭包/atlas 边界/
首中末帧解码/投影一致性——负例（篡改副本）必须报错。

采样规则（manifest.config 固定）：frames = clamp(ceil(duration×sampleHz),
minFrames, maxFrames)；帧 i 时刻 = duration×i/frames；loop={walk,idle}。
VAN 关键帧 ≠ 渲染帧。静态降级（H24）单位：bind 姿态 ×8 yaw 一次渲染，
全部 clip kind=static 共享；缺失 clip kind=missing 显式 fallback。

坐标/投影（合同 §6.5，OF-03.B/C 修订）：静态斜俯视透视（render/camera.py
StaticObliqueCamera），非旧版正交仿射。projection_for() 序列化相机几何常数
（cx/cz/cot/sinP/cosP/tanP/distance/near/far/size）；host.js worldToCanvas/
canvasToWorld/unitBillboard 消费同一公式（见 camera.py 模块 docstring 逐项公式）。
"""
import hashlib
import json
import math
import os
import shutil

from PIL import Image

from bugbits import level as levelmod
from bugbits import unitdb, web_data, worlddb, web_geometry, nav
from bugbits.assets import data_dir, pose, van, vln, v3d, vtx
from bugbits.render import bake, camera, software

CONFIG = {
    "schemaVersion": web_data.SCHEMA_VERSION,
    "terrainSize": 1024,
    "spriteSize": 128,
    "yaws": 8,
    "sampleHz": 8,
    "minFrames": 4,
    "maxFrames": 16,
    "atlasPageSize": 2048,
    "meshContractVersion": web_geometry.SCHEMA,
    "meshPosePolicy": web_geometry.POSE_POLICY,
}
# Pyodide 运行时锁定（合同 §8；离线交付——vendor 进 out/web，禁外网 CDN）
PYODIDE_VERSION = "0.26.4"
PYODIDE_URL = ("https://github.com/pyodide/pyodide/releases/download/"
               f"{PYODIDE_VERSION}/pyodide-core-{PYODIDE_VERSION}.tar.bz2")
PYODIDE_SHA256 = "70dba93432f3653155998cc9001f9c200182343c2f95165a2f9e9e4673fa35e8"
# py-bundle 排除（PIL/构建期模块——浏览器运行时零 PIL 依赖）
BUNDLE_EXCLUDE = ("render", "cli.py", "web_build.py", "web_geometry.py")
# 事件音效（W5；[HYPOTHESIS] 表现层选择：按文件名语义映射事件，非引擎证据）
EVENT_SFX = {"buy_ok": "sfx/bugstart_01",
             "victory_win": "sfx/medal_04",
             "victory_lose": "sfx/lose_03"}
CLIP_KEYS = ("walk", "idle", "normal_attack", "hurt",
             "special_attack", "special_move")
CLIP_LOOPS = {"walk": True, "idle": True}       # 其余 False
LEVEL_TEXT_PROPS = ("NameText", "Objective", "Description", "WinText", "LoseText")
MENU_LEVEL = "mainmenu_01"
SLICE_LEVELS = ("level_02",)
# 引擎特例名（BugSetup 出现但非真实单位，无 buginfos/模型——unitdb 白名单同款）：
# trapped→rescue 关被困虫（RescueBug 兵种），nectarbonus→NectarItem 铺场
ENGINE_SPECIAL_UNITS = {"trapped", "nectarbonus"}
# multi/multir 无 BugSetup/脚本（原虫栏选择机制未建模 H28）——版本化显式演示配置：
# 双方=ant(采集)+wasp(进攻,飞,快,能拆巢)+bee(飞行采集)；敌方=固定参数 Bot。
# 进攻兵种选 wasp（非 littlebeetle）：对称镜像下 littlebeetle 慢+攻巢低，
# 600s 内全军在半途互耗、零攻巢、终局退化为超时——不满足「实际对抗」；
# wasp（HiveDamage1+Melee8+飞 65u/s）能拆巢取胜，与 tests/test_e2e 双 bot 同构
# 对局同款参数。不伪称已还原 multibattle 8 槽 Priority / multirandom LCG 对称
# 随机虫栏（docs/exe-econ.md §6；H28）。
MULTI_DEMO_BUYABLE = ["ant", "wasp", "bee"]
MULTI_DEMO_ENEMY = {"gather_ants": 10, "attack_unit": "wasp",
                    "attack_lanes": [0], "garrison": 12, "attack_every": 10}
MULTI_DEMO_EVIDENCE = ("multi/multir 版本化显式演示配置（无 BugSetup；原虫栏=8 槽 "
                       "Priority 排序 multibattle / LCG 对称 multirandom, "
                       "exe-econ §6, H28 未建模——不伪称已还原随机虫栏）")
# OF-04：原作 GUI 纹理导出（ciBugButton/HUD/光标/选关）→ assets/gui/*.png。
# 依据 research/of04_layout.py（57 原子字节断言）与 docs/of04-layout-evidence.md。
# medal_*（30 张完成奖章）与 map_bg_hires 不导出：存档进度系统暂缓（loop §0）。
GUI_ASSETS = {
    "main": ["maingui_circle", "maingui_bar", "maingui_top", "maingui_top_right",
             "maingui_base_small", "maingui_base_small_right",
             "maingui_basebar_small", "maingui_black"],
    "gizmos": ["cursor_v1_a", "cursor_v1_b", "glow_star_01", "startarrow_01",
               "warning_01", "circlebutton_01"],
    "map": ["map_bg_lowres", "map_button_battle", "map_button_challenge",
            "map_button_defense", "map_button_empty", "map_button_gather",
            "map_button_random", "map_button_rescue", "map_completed"],
}


def frame_count(duration_sec):
    return min(CONFIG["maxFrames"],
               max(CONFIG["minFrames"], math.ceil(duration_sec * CONFIG["sampleHz"])))


def _unit_atlas_pages(unit, clip_manifest, sprites, prefix=""):
    """单位全部 clip 精灵所跨的图集页号（按 prefix/frames/yaw 展开）。"""
    pages = set()
    for clip, c in clip_manifest[unit].items():
        if c["kind"] == "sampled":
            for f in range(c["frames"]):
                for y in range(CONFIG["yaws"]):
                    k = f"{prefix}{c['prefix']}.f{f}.y{y}"
                    if k in sprites:
                        pages.add(sprites[k]["page"])
        elif c["kind"] == "static":
            for y in range(CONFIG["yaws"]):
                k = f"{prefix}{c['prefix']}.y{y}"
                if k in sprites:
                    pages.add(sprites[k]["page"])
    return pages


def _level_atlas_pages(c, clip_manifest, sprites, flower_page, prefix=""):
    """本关运行时所需图集页号 = 闭包单位全部 clip 精灵页 ∪ 花蜜页。

    `prefix`（NC 相机交付）：预设精灵键前缀（如 "origcam:"）——按同结构查
    前缀化键的页号（预设键缺失时报 KeyError，由调用方保证已烘焙）。
    """
    pages = {sprites[f"{prefix}flower.bind.y0"]["page"]
             if prefix else flower_page}
    for u in c.units:
        if u in clip_manifest:
            pages |= _unit_atlas_pages(u, clip_manifest, sprites, prefix)
    return sorted(pages)


# ── 基础工具 ─────────────────────────────────────────────────────────
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def input_fingerprint(paths, profile):
    """Original input hashes and resource buildId; shared by export and light checks.

    Hash the complete source closure, not rendered output or successful pixels.
    The payload and relative-path convention are the existing manifest contract.
    """
    data_root_dir = data_dir()
    input_paths = sorted(set(paths))
    for path in input_paths:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"闭包源文件缺失: {path}")
    input_hashes = sorted((os.path.relpath(path, data_root_dir), sha256_file(path))
                          for path in input_paths)
    build_id = hashlib.sha256(json.dumps(
        {"schemaVersion": CONFIG["schemaVersion"], "profile": profile,
         "config": CONFIG, "inputs": input_hashes,
         "pyodide": [PYODIDE_VERSION, PYODIDE_SHA256],
         "code": _code_fingerprint()}, sort_keys=True).encode()).hexdigest()
    return input_hashes, build_id


def finalize_world_inputs(paths, profile, worlds):
    """Reject source drift between survey's captured rigs and final input bytes.

    Fingerprinting retains its missing-file rejection before checking the
    captured world objects; later geometry reads cannot replace these objects.
    """
    input_hashes,build_id=input_fingerprint(paths,profile)
    for world in worlds.values():
        web_data.validate_world_rig_sources(world,dict(input_hashes))
    return input_hashes,build_id


def validate_package_worlds(out_dir, manifest):
    """Validate serialized world identity and rig sources without original IO.

    This is the world closure stage of validate(), also usable on a small
    worlds-only package while developing resource contracts.
    """
    errors=[]
    for name in sorted({lv['deps']['world'] for lv in manifest['levels']}):
        path=os.path.join(out_dir,'worlds',name+'.json')
        if not os.path.isfile(path):continue  # Dependency validation reports it.
        try:
            with open(path,encoding='utf-8') as stream:
                packet=json.load(stream)
                world=web_data.restore_world(packet)
            if world.world_id!=name:
                raise ValueError('world ID differs from level dependency')
            if world.flower_rigs and 'flowerRigJsons' not in packet:
                raise ValueError('flower rig source text required for worker transport')
            web_data.validate_world_rig_sources(world,manifest.get('inputHashes',{}))
        except (ValueError,KeyError,TypeError) as exc:
            errors.append(name+': '+str(exc))
    return errors


def _van_duration(ref):
    """clip .van 首个非空节点末键时刻（秒）；不可解析 → None。"""
    path = bake._resolve_model(ref, ".van")
    if path is None:
        return None
    try:
        blocks = van.parse_van(path)
    except (OSError, ValueError, IndexError):
        return None
    keys = next((b for b in blocks if b), None)
    return keys[-1][0] if keys else None


# ── survey：闭包计算 ─────────────────────────────────────────────────
class LevelClosure:
    def __init__(self, lid, lv):
        self.id = lid
        self.lv = lv
        units = {u for (_, u, _) in lv.bug_setups
                 if u not in ENGINE_SPECIAL_UNITS}
        for sub, args in lv.scripts:
            if sub in ("sendenemy", "sendplayer") and args:
                units.add(args[0])
        units.add("ant")            # 可买栏回退口径（合同 §3/§9.1）
        # rescue 关被困虫兵种（RescueBug）也须入闭包（有模型无 buginfos）
        rescue = lv.rescue_bug if lv.type == "rescue" else None
        if rescue and rescue not in units:
            units.add(rescue)
        # multi/multir 无 BugSetup（原虫栏未建模）→ 版本化显式演示配置；
        # 资产闭包并入演示兵种，敌方 Bot 单位/泳道纳入本关策略（非运行时启发式）。
        self.enemy_bot = None
        self.buyable_kind = "fallback"       # 默认 BugSetup∪{ant} 回退口径
        if lv.type in ("multibattle", "multirandom"):
            for u in MULTI_DEMO_BUYABLE + [MULTI_DEMO_ENEMY["attack_unit"]]:
                units.add(u)
            self.enemy_bot = dict(MULTI_DEMO_ENEMY)
            self.buyable_kind = "explicit-demo"
        self.units = sorted(units)
        self.world = lv.world_name
        keys = set()                 # 数据引用键（关卡/脚本/hint/对话——必须存在）
        for prop in LEVEL_TEXT_PROPS:
            v = lv.props.get(prop)
            if v:
                keys.add(v[0])
        for sub, args in lv.scripts:
            if sub == "addhint" and args:
                keys.add(args[0])
            if sub in ("sendenemy", "sendplayer") and len(args) > 2 \
                    and args[2] != "null":
                keys.add(args[2])
        # UI 文本键：取单位 buginfos 自身 NameText/StatText/DescText 真实键
        # （_tick 变体键为无下划线拼接 BUGNAME_TOXICHEROTICK——合成键曾错）
        ui = set()
        for u in self.units:
            if u in ENGINE_SPECIAL_UNITS:
                continue
            spec = unitdb.load_unit(u)
            if not spec.can_gather and not spec.can_fly:
                base_text = spec.props.get("BaseText")
                if base_text:
                    keys.add(base_text[0])
            for prop in ("NameText", "StatText", "DescText"):
                v = spec.info_props.get(prop)
                if v:
                    ui.add(v[0])
        self.ui_text_keys = sorted(ui)
        self.text_keys = sorted(keys)
        self.music = lv.music                      # 如 "grass"
        if self.buyable_kind == "explicit-demo":
            self.buyable = list(MULTI_DEMO_BUYABLE)
        else:
            # 可买栏 = BugSetup 兵种 ∪ {ant}（回退口径，合同 §9.1）。必须从 bug_setups
            # 推导，不能从资产闭包 units 推导：units 含脚本增援(sendenemy/sendplayer)
            # 与 rescue 被困虫，会把脚本-only 兵种漏进可买栏、并把「既是 RescueBug 又
            # 正常在 BugSetup」的兵种误删（2026-09-19 挖掘 BUG-01）。
            buyable_src = {u for (_, u, _) in lv.bug_setups
                           if u not in ENGINE_SPECIAL_UNITS}
            buyable_src.add("ant")
            self.buyable = sorted(u for u in buyable_src
                                  if unitdb.load_unit(u).price is not None)


def discover_levels(profile):
    if profile == "slice":
        return list(SLICE_LEVELS)
    names = sorted(f[:-4] for f in os.listdir(data_dir("scripts", "levels"))
                   if f.endswith(".vsc"))
    return [n for n in names if n != MENU_LEVEL]


def survey(level_ids):
    closures = [LevelClosure(lid, levelmod.parse_level(
        data_dir("scripts", "levels", lid + ".vsc"))) for lid in level_ids]
    worlds = {}                                   # name → WorldData
    for c in closures:
        if c.world and c.world not in worlds:
            worlds[c.world] = worlddb.parse_world(
                data_dir("worlds", c.world + ".vsc"))
    units = sorted({u for c in closures for u in c.units})
    return closures, worlds, units


# ── 渲染 ─────────────────────────────────────────────────────────────
def _alpha_bbox(img):
    return img.split()[3].getbbox()


def render_unit_clips(unit, images, stats, consumed, pitch_deg=None,
                      key_prefix=""):
    """单位全部 clip 槽位 → 精灵（去重）+ (clip 清单, normSpan) + alpha 统计。

    consumed：实际读取的源文件集合（入 buildId 指纹——模型/动画/纹理变化
    必须改变 buildId，合同 §6.6）。
    NC-03 稳定归一化：先收集本单元全部将渲染姿态（bind + 各 clip 采样帧），
    取最大**屏幕**跨度（pose_screen_span：8 yaw × 同 pitch，对角朝向不裁剪）
    为 norm_span，全部帧/yaw 用同一 sc 渲染——体量不随动作/朝向泵动；返回
    norm_span 供 units.json 导出（世界尺寸精确映射由 cb+atlasScale 承载，
    合同见 render/billboard.py）。

    NC 相机交付：`pitch_deg` 预设精灵烘焙 pitch（缺省 = UNIT_SPRITE_PITCH_DEG）；
    `key_prefix` 预设键前缀（如 "origcam:"）——同图集隔离缓存键，norm_span/
    atlasScale 按预设 pitch 重算（默认键与产物不受影响）。
    """
    pitch = bake.UNIT_SPRITE_PITCH_DEG if pitch_deg is None else pitch_deg
    spec = unitdb.load_unit(unit)
    size = CONFIG["spriteSize"]
    yaws = CONFIG["yaws"]
    model_path = bake._resolve_model(spec.model, ".v3d")
    # NC-03 bee：parse_v3d_groups 返回双材质组（翼膜+身体）；bee.vtx 载入 consumed
    # （进 buildId 指纹）。两组索引/纹理一并透传 _render_rgba（共享 z-buffer）。
    verts, groups, skin, recs = v3d.parse_v3d_groups(model_path)
    texs = [bake._load_texture(name) for _, name in groups]
    if len(groups) > 1 and any(t is None for t in texs):
        missing = [name for (_, name), t in zip(groups, texs) if t is None]
        raise ValueError(f"{unit}: 第二材质纹理缺失 {missing}")
    idx, tex = bake._groups_render_args(groups, texs)
    consumed.add(model_path)
    for _, name in groups:
        if name:
            tex_path = data_dir("textures", name + ".vtx")
            if os.path.isfile(tex_path):
                consumed.add(tex_path)
    skinnable = bool(skin) and sum(
        1 for _, _, inf in skin
        if inf and all(bi < len(recs) for bi, _ in inf)) > 0.9 * len(skin)
    clips, ustats = {}, {"blank": [], "bboxes": [], "edgeTouch": 0}
    # bind 姿态屏幕跨度（静态分支即此值；pitch 与精灵烘焙同视角）
    # NC-03A 稳定居中：bind 姿态 AABB 中心为居中参考点（非逐帧 AABB 中心）
    bind_center = bake._aabb_center(verts)
    norm_span = software.pose_screen_span(verts, yaws, pitch,
                                          center=bind_center)
    if not skinnable:
        # H24 静态降级：bind 姿态 ×8 yaw 一次渲染，全部 clip 共享
        for y in range(yaws):
            key = f"{key_prefix}{unit}.bind.y{y}"
            images[key] = bake._render_rgba(verts, idx, tex, size, yaw=y * 45.0,
                                            pitch=pitch,
                                            norm_span=norm_span,
                                            center=bind_center)
        for clip in CLIP_KEYS:
            ref = spec.anims.get(clip)
            van_path = bake._resolve_model(ref, ".van") if ref else None
            if van_path:
                consumed.add(van_path)
            dur = _van_duration(ref) if ref else None
            if ref is None or dur is None:
                clips[clip] = _missing_clip(clips, clip, ref)
                continue
            clips[clip] = {"prefix": f"{unit}.bind", "ref": ref,
                           "frames": 1, "duration": dur,
                           "loop": CLIP_LOOPS.get(clip, False), "kind": "static"}
    else:
        bind = pose.worlds_from_records(recs)
        posed_frames = {}                        # (prefix, f) -> 姿态顶点
        sampled_prefixes = set()
        for clip in CLIP_KEYS:
            ref = spec.anims.get(clip)
            van_path = bake._resolve_model(ref, ".van") if ref else None
            if van_path:
                consumed.add(van_path)
            dur = _van_duration(ref) if ref else None
            if ref is None or dur is None:
                clips[clip] = _missing_clip(clips, clip, ref)
                continue
            prefix = f"{key_prefix}{unit}.{os.path.basename(ref)}"
            if prefix not in sampled_prefixes:
                blocks = van.parse_van(van_path)
                n = frame_count(dur)
                for f in range(n):
                    posed = pose.skin_at(skin, bind, pose.worlds_at(
                        recs, blocks, dur * f / n), source_vertices=verts)
                    posed_frames[(prefix, f)] = posed
                    norm_span = max(norm_span, software.pose_screen_span(
                        posed, yaws, pitch, center=bind_center))
                sampled_prefixes.add(prefix)
            clips[clip] = {"prefix": prefix, "ref": ref,
                           "frames": frame_count(dur), "duration": dur,
                           "loop": CLIP_LOOPS.get(clip, False), "kind": "sampled"}
        for (prefix, f), posed in posed_frames.items():
            for y in range(yaws):
                images[f"{prefix}.f{f}.y{y}"] = bake._render_rgba(
                    posed, idx, tex, size, yaw=y * 45.0,
                    pitch=pitch, norm_span=norm_span,
                    center=bind_center)
    # alpha 统计（发现空白/裁切/静默降级）。仅默认键 pass 写统计——预设前缀键
    # 不匹配 unit. 前缀过滤，覆盖会把默认统计清成 None（NC 相机交付）。
    if not key_prefix:
        px_area = size * size
        for key, img in images.items():
            if not key.startswith(unit + "."):
                continue
            bbox = _alpha_bbox(img)
            if bbox is None:
                ustats["blank"].append(key)
                continue
            ustats["bboxes"].append(
                (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) / px_area)
            if bbox[0] == 0 or bbox[1] == 0 or bbox[2] == size or bbox[3] == size:
                ustats["edgeTouch"] += 1
        stats[unit] = {
            "blankSprites": ustats["blank"],
            "minBBoxRatio": round(min(ustats["bboxes"]), 4)
                            if ustats["bboxes"] else None,
            "maxBBoxRatio": round(max(ustats["bboxes"]), 4)
                            if ustats["bboxes"] else None,
            "edgeTouchSprites": ustats["edgeTouch"],
        }
    return clips, norm_span


def _missing_clip(clips, clip, ref):
    """缺失 clip 显式 fallback（不静默假装）。"""
    fb = next((c for c in ("walk", "idle") if clips.get(c, {}).get("kind")
               in ("sampled", "static")), None)
    return {"kind": "missing", "frames": 0, "ref": ref,
            "fallbackClip": fb, "loop": CLIP_LOOPS.get(clip, False)}


# ── 图集装箱（shelf） ────────────────────────────────────────────────
def pack_atlas(images, out_dir, page_offset=0):
    maxp = CONFIG["atlasPageSize"]
    pages, sprites = [], {}
    page = Image.new("RGBA", (maxp, maxp), (0, 0, 0, 0))
    x = y = row_h = 0
    page_no = page_offset
    for key in sorted(images):
        img = images[key]
        w, h = img.size
        if x + w > maxp:
            x, y, row_h = 0, y + row_h, 0
        if y + h > maxp:
            pages.append(page)
            page_no += 1
            page = Image.new("RGBA", (maxp, maxp), (0, 0, 0, 0))
            x = y = row_h = 0
        page.paste(img, (x, y))
        # NC-03 内容框（图集有效内容元数据）：alpha bbox 页坐标 [x0,y0,w,h]；
        # 空白精灵回退整瓦片（spriteStats.blankSprites 另行报告）。cb 仅作
        # 裁剪/内容宽测量（N05 内容宽、validation）；draw 层锚点用瓦片中心
        # pivot（NC-03A，与逐帧 cb 分离——host.js drawUnitSprite 锚定瓦片中心）。
        bbox = _alpha_bbox(img)
        cb = ([x + bbox[0], y + bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]]
              if bbox else [x, y, w, h])
        sprites[key] = {"page": page_no, "x": x, "y": y, "w": w, "h": h,
                        "pivot": [w // 2, h // 2], "cb": cb}
        x += w
        row_h = max(row_h, h)
    pages.append(page)
    files = []
    for i, p in enumerate(pages):
        name = f"atlas_{page_offset + i}.png"
        p.save(os.path.join(out_dir, name))
        files.append(name)
    return {"pages": [{"file": f, "width": maxp, "height": maxp}
                      for f in files],
            "sprites": sprites}, files


# ── 投影 ─────────────────────────────────────────────────────────────
def projection_for(world):
    """静态斜俯视透视投影参数（OF-03.B/C，render.camera.StaticObliqueCamera）。

    host.js 的 worldToCanvas/canvasToWorld 消费同一公式（world_to_pixel y=0 地面 /
    pixel_to_ground），见 camera.py 模块 docstring 逐项公式。参数为相机的几何常数
    序列化，非仿射 scale/offset。
    """
    if not world.terrain:
        raise ValueError(f"世界 {world.static_model!r} 无地形 bounds")
    size = CONFIG["terrainSize"]
    xmin, xmax, _, _, zmin, zmax = world.terrain
    cam = camera.static_oblique_camera((xmin, xmax, zmin, zmax), size)
    return {
        "size": size, "xmin": xmin, "xmax": xmax, "zmin": zmin, "zmax": zmax,
        "cx": cam.cx, "cz": cam.cz,
        "cot": cam.cot, "sinP": cam.sin_p, "cosP": cam.cos_p,
        "tanP": cam.tan_p, "distance": cam.distance,
        "near": cam.near, "far": cam.far,
        # NC 相机交付：预设消费键（默认值 = 旧口径恒等；host 通用路径读取）
        "sinY": 0.0, "cosY": 1.0, "aspect": 1.0, "tx": cam.cx, "tz": cam.cz,
    }


# ── NC 相机交付：有界相机预设（loop-harness-camera-delivery.md） ─────
# 候选预算 2：overview（生产默认，不重烤）+ original_cam（DATA/STATIC 锚定）。
# 只对下列世界烘焙预设（full 构建时间/包体有界）；其余世界保持默认。
CAMERA_PRESET_WORLDS = ("world_02", "world_03")


def _preset_projection_dict(cam):
    """StaticObliqueCamera → 投影常数 dict（billboard.cam_consts 同键）。"""
    if isinstance(cam, camera.MatrixWorldCamera):
        return cam.projection_dict()
    return {
        "size": cam.size_px, "cx": cam.cx, "cz": cam.cz,
        "cot": cam.cot, "sinP": cam.sin_p, "cosP": cam.cos_p,
        "tanP": cam.tan_p, "distance": cam.distance,
        "near": cam.near, "far": cam.far,
        "sinY": cam.sin_y, "cosY": cam.cos_y, "aspect": cam.aspect,
        "tx": cam.tx, "tz": cam.tz,
    }


def matrix_projection_camera(projection):
    """Validate a complete R59 matrix dictionary without reducing it to Euler."""
    keys = {'kind', 'basis9', 'cameraPosition', 'size', 'cot', 'aspect', 'near', 'far'}
    if not isinstance(projection, dict) or set(projection) != keys or projection['kind'] != 'matrix-yup-v1':
        raise ValueError('complete matrix-yup-v1 projection required')
    flat = camera.MatrixWorldCamera._numbers(projection['basis9'], 9)
    position = camera.MatrixWorldCamera._numbers(projection['cameraPosition'], 3)
    cot, = camera.MatrixWorldCamera._numbers((projection['cot'],), 1)
    if cot <= 0:
        raise ValueError('positive cot required')
    # Invert only the explicit Q adapter for the public R59 constructor.
    rows = tuple((flat[i+2], -flat[i], -flat[i+1]) for i in (0,3,6))
    return camera.MatrixWorldCamera.from_original(rows,
            (position[2], -position[0], -position[1]), size_px=projection['size'],
            aspect=projection['aspect'], fov_y=2*math.atan(1/cot),
            near=projection['near'], far=projection['far'])


def _matrix_terrain_digest(projection, basis, terrain_file, terrain_sha256):
    payload = {'projection': projection, 'worldBasisVersion': basis,
               'terrainFile': terrain_file, 'terrainSHA256': terrain_sha256}
    return hashlib.sha256(json.dumps(payload, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def matrix_projection_record(cam, *, world_basis_version, terrain_file, terrain_sha256):
    """Explicit geometry-only variant; never claims compatible sprite atlases."""
    if not isinstance(cam, camera.MatrixWorldCamera):
        raise ValueError('matrix terrain requires its actual MatrixWorldCamera')
    projection = cam.projection_dict()
    record = {'camera': projection, 'projection': dict(projection),
              'worldBasisVersion': world_basis_version, 'terrainFile': terrain_file,
              'terrainProjectionDigest': _matrix_terrain_digest(projection,
                  world_basis_version, terrain_file, terrain_sha256),
              'presentationScope': 'geometry-research'}
    validate_matrix_projection_record(record, world_basis_version=world_basis_version,
                                      terrain_sha256=terrain_sha256)
    return record


def validate_matrix_projection_record(record, *, world_basis_version, terrain_sha256):
    """Check the matrix, exported world basis and actual terrain-byte binding."""
    if not isinstance(record, dict):
        raise ValueError('matrix terrain record must be a dictionary')
    if world_basis_version != 'loaded-yup-v1' or record.get('worldBasisVersion') != world_basis_version:
        raise ValueError('matrix geometry requires the same loaded-yup-v1 world')
    if record.get('presentationScope') != 'geometry-research':
        raise ValueError('matrix sprites/native presentation is not supported')
    tf = record.get('terrainFile')
    if not isinstance(tf, str) or not tf or os.path.isabs(tf) or '..' in tf.split('/') or '\\' in tf:
        raise ValueError('invalid matrix terrain path')
    if (not isinstance(terrain_sha256, str) or len(terrain_sha256) != 64
            or any(c not in '0123456789abcdef' for c in terrain_sha256)):
        raise ValueError('invalid actual terrain SHA')
    projection = record.get('projection')
    cam = matrix_projection_camera(projection)
    if cam.aspect < 1:
        raise ValueError('matrix stage aspect<1 is not supported')
    if record.get('camera') != projection:
        raise ValueError('terrain camera and consumer projection differ')
    expected = _matrix_terrain_digest(projection, world_basis_version, tf, terrain_sha256)
    if record.get('terrainProjectionDigest') != expected:
        raise ValueError('matrix terrain/projection binding mismatch')
    return cam


def _mesh_projection_digest(projection, world, basis, geometry_file, geometry_sha256):
    payload = {'projection':projection, 'world':world, 'worldBasisVersion':basis,
               'geometryFile':geometry_file, 'geometrySHA256':geometry_sha256}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),
                                    allow_nan=False).encode()).hexdigest()


def mesh_projection_record(cam, *, world, world_basis_version, geometry_file, geometry_sha256):
    """Same engineering camera pose, explicit matrix + actual depth scene binding."""
    if not isinstance(cam,camera.StaticObliqueCamera):
        raise ValueError('mesh preset requires its engineering camera')
    projection = {'kind':'matrix-yup-v1',
        'basis9':[cam.cos_y,0,-cam.sin_y,
                  cam.sin_p*cam.sin_y,cam.cos_p,cam.sin_p*cam.cos_y,
                  cam.cos_p*cam.sin_y,-cam.sin_p,cam.cos_p*cam.cos_y],
        'cameraPosition':list(cam.camera_pos),'size':cam.size_px,'cot':cam.cot,
        'aspect':cam.aspect,'near':cam.near,'far':cam.far}
    result = {'label':'工程网格视角','presentationScope':web_geometry.SCHEMA,
        'meshContractVersion':web_geometry.SCHEMA,'posePolicy':web_geometry.POSE_POLICY,
        'worldBasisVersion':world_basis_version,'world':world,
        'camera':dict(projection),'projection':projection,
        'meshView':{'targetYup':list(cam.target),'distance':cam.distance},
        'geometryFile':geometry_file,'geometrySHA256':geometry_sha256,
        'geometryProjectionDigest':_mesh_projection_digest(projection,world,
            world_basis_version,geometry_file,geometry_sha256)}
    validate_mesh_projection_record(result,world=world,
        world_basis_version=world_basis_version,geometry_sha256=geometry_sha256)
    return result


def mesh_birth_camera(world, unit_envelope):
    """Engineering view of friendly spawns and their first 200u route segments.

    The supplied all-heading posed volume does not change the mesh or simulation.
    This fitting policy is separate from original dynamic camera behaviour.
    """
    if (len(unit_envelope)!=3 or any(type(x) not in (int,float) or not math.isfinite(x) for x in unit_envelope)
            or unit_envelope[0]<0 or unit_envelope[1]>unit_envelope[2]):
        raise ValueError('finite ordered unit view envelope required')
    radius,low,high=unit_envelope;fly=float(world.props['FlyHeight'][0])
    anchors=[]
    for start in world.starts:
        if start.side_id!=0:continue
        end=world.start(1,start.index)
        route=nav.route_between(world,start.name,end.name) if end else None
        if route is None:raise ValueError('mesh spawn camera requires a legal lane route')
        distances=[0,min(200,route.length)];at=0
        for length in route.seg_len:
            at+=length
            if at<200:distances.append(at)
        for distance in distances:
            anchors.extend((route.position_at(distance),route.position_at(distance,fly_height=fly)))
    if not anchors:raise ValueError('mesh spawn camera requires friendly starts')
    points=[(p[0]+x,p[1]+y,p[2]+z) for p in anchors for x in (-radius,radius)
            for y in (low,high) for z in (-radius,radius)]
    target=tuple((min(p[i] for p in points)+max(p[i] for p in points))/2 for i in range(3))
    xmin,xmax,_,_,zmin,zmax=world.terrain
    for distance in range(180,1001,5):
        cam=camera.StaticObliqueCamera((xmin,xmax,zmin,zmax),CONFIG['terrainSize'],
            pitch_deg=math.degrees(.7),yaw_deg=0,fov_deg=60,aspect=1.6,
            near=1,far=1000,target=target,distance=distance)
        projected=[cam.world_to_pixel_depth(*p) for p in points]
        if all(1<=z<=1000 and .09*cam.size_px*cam.aspect<px<.91*cam.size_px*cam.aspect
               and .13*cam.size_px<py<.87*cam.size_px for px,py,z in projected):return cam
    raise ValueError('no bounded spawn camera fits supplied posed volume')


def mesh_presets_for(worlds, world_units, geometry_assets, out_dir):
    """Build mesh views from loaded geometry independently of sprite presets."""
    geometry_file = geometry_assets['file']
    if geometry_file != 'assets/geometry/scene.json':
        raise ValueError('mesh presets require the declared geometry scene path')
    with open(os.path.join(out_dir, geometry_file), 'rb') as stream:
        raw = stream.read()
    geometry_sha = hashlib.sha256(raw).hexdigest()
    if geometry_sha != geometry_assets['sha256']:
        raise ValueError('mesh scene changed before camera construction')
    scene = json.loads(raw)
    web_geometry.validate_geometry(scene)
    result = {}
    for name, wd in sorted(worlds.items()):
        if wd.basis_version != 'loaded-yup-v1':
            raise ValueError('mesh presets require a loaded world')
        if scene.get('worlds', {}).get(name, {}).get('basisVersion') != wd.basis_version:
            raise ValueError('mesh scene world and loaded basis differ')
        envelope = _mesh_unit_envelope(scene, world_units[name], out_dir)
        cam = mesh_birth_camera(wd, envelope)
        result[name] = mesh_projection_record(cam, world=name,
            world_basis_version=wd.basis_version, geometry_file=geometry_file,
            geometry_sha256=geometry_sha)
    return result


def native_camera_record(world, *, geometry_sha256):
    """Controller view with captured 4:3 frustum and actual geometry binding."""
    from bugbits.sim.camera import NativeCamera, SCOPE
    from bugbits.captured_camera import captured_packet
    if world.basis_version!='loaded-yup-v1' or {'Position','Direction'}.intersection(world.props):
        raise ValueError('native default world input not qualified')
    pose=NativeCamera(world.props).snapshot()['view']
    projection={**captured_packet()['projection'], 'basis9':pose['basis9'],
                'cameraPosition':pose['cameraPosition']}
    record={'label':'动态视角','presentationScope':web_geometry.SCHEMA,
            'meshContractVersion':web_geometry.SCHEMA,'posePolicy':web_geometry.POSE_POLICY,
            'worldBasisVersion':world.basis_version,'world':world.world_id,
            'geometryFile':'assets/geometry/scene.json','geometrySHA256':geometry_sha256,
            'projection':projection,'camera':dict(projection),'nativeCameraContract':SCOPE,
            'nativeCameraQualification':'static-normal-no-shake-no-overlap-4:3-outer20hz-v1'}
    record['geometryProjectionDigest']=_mesh_projection_digest(projection,world.world_id,
        world.basis_version,record['geometryFile'],geometry_sha256)
    validate_mesh_projection_record(record,world=world.world_id,
        world_basis_version=world.basis_version,geometry_sha256=geometry_sha256)
    validate_native_camera_record(record,world)
    return record


def validate_native_camera_record(record,world_data=None):
    """Native metadata has a fixed frustum; package validation also binds pose."""
    from bugbits.captured_camera import captured_packet
    from bugbits.sim.camera import NativeCamera, SCOPE
    if (record.get('nativeCameraContract')!=SCOPE
            or record.get('nativeCameraQualification')!='static-normal-no-shake-no-overlap-4:3-outer20hz-v1'
            or 'meshView' in record):
        raise ValueError('native camera contract/qualification mismatch')
    projection=record.get('projection',{})
    reference=captured_packet()['projection']
    if any(projection.get(k)!=reference[k] for k in ('kind','size','cot','aspect','near','far')):
        raise ValueError('native camera requires captured 4:3 frustum')
    if record.get('camera')!=projection:
        raise ValueError('native camera aliases differ')
    if world_data is not None:
        if (world_data.basis_version!='loaded-yup-v1' or record.get('world')!=world_data.world_id
                or {'Position','Direction'}.intersection(world_data.props)):
            raise ValueError('native world input not qualified')
        expected=NativeCamera(world_data.props).snapshot()['view']
        if any(projection.get(k)!=expected[k] for k in ('basis9','cameraPosition')):
            raise ValueError('native initial pose differs from world configuration')


def _mesh_unit_envelope(scene, unit_ids, out_dir):
    """All bind/walk poses, all headings, explicit exported S/Q/scale once."""
    import struct
    radius=0;low=float('inf');high=-float('inf')
    for uid in unit_ids:
        unit=scene['units'][uid];streams=[unit['positions']]
        with open(os.path.join(out_dir,unit['frameBuffer']['file']),'rb') as stream:raw=stream.read()
        web_geometry.validate_frame_buffer(unit,raw)
        clip=unit['clips']['walk']
        while clip['kind']=='missing':clip=unit['clips'][clip['fallbackClip']]
        for frame in clip['frames']:
            ref=frame['positions'];streams.append(struct.unpack_from('<'+str(ref['count'])+'f',raw,ref['offset']))
        root=unit['rootMatrix'];scale=unit['scaleFactor'];anchor=unit['anchor']
        for values in streams:
            for i in range(0,len(values),3):
                p=[(values[i+j]-anchor[j])*scale for j in range(3)]
                r=[sum(p[k]*root[k*4+j] for k in range(3))+root[12+j] for j in range(3)]
                q=(-r[1],-r[2],r[0]);radius=max(radius,math.hypot(q[0],q[2]));low=min(low,q[1]);high=max(high,q[1])
    return radius,low,high


def validate_mesh_projection_record(record, *, world, world_basis_version, geometry_sha256):
    if 'nativeCameraContract' in record or 'nativeCameraQualification' in record:
        validate_native_camera_record(record)
    if (record.get('presentationScope')!=web_geometry.SCHEMA or
            record.get('meshContractVersion')!=web_geometry.SCHEMA or
            record.get('posePolicy')!=web_geometry.POSE_POLICY or
            world_basis_version!='loaded-yup-v1' or
            record.get('worldBasisVersion')!=world_basis_version or record.get('world')!=world):
        raise ValueError('mixed mesh scene/world policy')
    gf=record.get('geometryFile')
    if gf!='assets/geometry/scene.json' or record.get('geometrySHA256')!=geometry_sha256:
        raise ValueError('actual geometry binding differs')
    if not isinstance(geometry_sha256,str) or len(geometry_sha256)!=64 or any(c not in '0123456789abcdef' for c in geometry_sha256):
        raise ValueError('invalid geometry SHA')
    projection=record['projection'];cam=matrix_projection_camera(projection)
    if record.get('camera')!=projection or cam.aspect<1 or 'terrainFile' in record:
        raise ValueError('mixed PNG or projection camera')
    view=record.get('meshView')
    if view is not None:
        if (not isinstance(view,dict) or set(view)!= {'targetYup','distance'}
                or not isinstance(view['targetYup'],list) or len(view['targetYup'])!=3
                or any(type(v) not in (int,float) or not math.isfinite(v) for v in view['targetYup'])
                or type(view['distance']) not in (int,float) or not math.isfinite(view['distance']) or view['distance']<=0):
            raise ValueError('finite mesh view target/distance required')
        expected=[view['targetYup'][i]-projection['basis9'][6+i]*view['distance'] for i in range(3)]
        if any(abs(a-b)>1e-8 for a,b in zip(expected,projection['cameraPosition'])):
            raise ValueError('mesh view target does not match projection')
    if record.get('geometryProjectionDigest')!=_mesh_projection_digest(projection,
            world,world_basis_version,gf,geometry_sha256):
        raise ValueError('mesh projection/scene digest differs')
    if 'cameraSource' in record or 'applicability' in record:
        validate_captured_camera_scope(record, level_id='level_01', level_type='gather', world=world)
    return cam


def validate_captured_camera_scope(record, *, level_id, level_type, world, input_hashes=None):
    """Captured source is a static normal first-level sample, never dynamic follow."""
    from bugbits.captured_camera import captured_packet
    packet = captured_packet()
    if ((level_id, level_type, world) != ('level_01', 'gather', 'world_01')
            or record.get('worldBasisVersion') != 'loaded-yup-v1'
            or record.get('applicability') != {'levelId':'level_01','variant':'normal','worldId':'world_01'}
            or record.get('cameraSource') != packet['cameraSource']
            or record.get('projection') != packet['projection']
            or record.get('camera') != packet['projection'] or 'meshView' in record):
        raise ValueError('captured camera source/scope/projection mismatch')
    if input_hashes is not None:
        for path, expected in packet['cameraSource']['inputs'].items():
            if '/data/' in path and input_hashes.get(path.split('/data/')[1]) != expected:
                raise ValueError('captured camera original level/world identity mismatch')


def captured_first_level_camera_record(*, level_id, level_type, world,
                                     world_basis_version, geometry_sha256, input_hashes):
    from bugbits.captured_camera import captured_packet
    packet = captured_packet()
    projection = packet['projection']
    result = {**packet, 'label':'原作首关视角', 'presentationScope':web_geometry.SCHEMA,
        'meshContractVersion':web_geometry.SCHEMA, 'posePolicy':web_geometry.POSE_POLICY,
        'worldBasisVersion':world_basis_version, 'world':world,
        'camera':dict(projection), 'geometryFile':'assets/geometry/scene.json',
        'geometrySHA256':geometry_sha256,
        'applicability':{'levelId':'level_01','variant':'normal','worldId':'world_01'},
        'geometryProjectionDigest':_mesh_projection_digest(projection, world,
            world_basis_version, 'assets/geometry/scene.json', geometry_sha256)}
    validate_captured_camera_scope(result, level_id=level_id, level_type=level_type,
                                  world=world, input_hashes=input_hashes)
    validate_mesh_projection_record(result, world=world,
        world_basis_version=world_basis_version, geometry_sha256=geometry_sha256)
    return result


def _preset_metrics(cam, wd, unit_atlas_scale, world_units, canvas_px=640.0):
    """预设构图指标（解释用，不通过最大化占屏率证明正确）。

    - visibleGroundRect：投影空间四角逆映射地面 AABB；射线在地平线以上
      （世界方向 dy≥0，交点在相机背后）的角不可逆 → 该角剔除；有效角 <2 时
      整体置 None（docstring 承诺的 None 分量；CAM-REVIEW【低】修复——
      world_03 pitch 22.9°<半FOV 30° 时上部两角在地平线上）。yaw≠0 时为
      旋转视口包围盒（注明近似）。
    - mapCoverage：世界 bounds 均匀 48×48 采样点落入可见画布的比例（估计值）。
    - unitPxAtCenter：目标深度处单位世界高度→画布像素（ant 为参照）。
    - hivePx / truncatedTargets：两端巢穴投影与出界/背后截断清单。
    """
    w_px = cam.size_px * cam.aspect
    corners = []
    for cx_, cy_ in ((0.0, 0.0), (w_px, 0.0), (0.0, cam.size_px),
                     (w_px, cam.size_px)):
        # 地平线守卫：世界射线方向 dy = cosθ·(ny/cot) − sinθ ≥ 0 → 不可逆
        ny_ = 1.0 - 2.0 * cy_ / cam.size_px
        dyw = cam.cos_p * (ny_ / cam.cot) - cam.sin_p
        if dyw >= -1e-9:
            continue
        gx, gz = cam.pixel_to_ground(cx_, cy_)
        corners.append((gx, gz))
    if len(corners) >= 2:
        xs_ = [c[0] for c in corners]
        zs_ = [c[1] for c in corners]
        vis_rect = [round(min(xs_), 1), round(min(zs_), 1),
                    round(max(xs_), 1), round(max(zs_), 1)]
    else:
        vis_rect = None
    xmin, xmax, _, _, zmin, zmax = wd.terrain
    inside = 0
    n = 48
    for i in range(n):
        for j in range(n):
            wx = xmin + (xmax - xmin) * i / (n - 1)
            wz = zmin + (zmax - zmin) * j / (n - 1)
            px_, py_ = cam.world_to_pixel(wx, 0.0, wz)
            if 0.0 <= px_ <= w_px and 0.0 <= py_ <= cam.size_px:
                inside += 1
    hives = {s.side_id: s.grid_pos for s in wd.starts if s.index == 0}
    hive_px, truncated = {}, []
    for side, pos in sorted(hives.items()):
        px_, py_ = cam.world_to_pixel(pos[0], 0.0, pos[2])
        hive_px[str(side)] = [round(px_, 1), round(py_, 1)]
        cam_z_ = cam.world_to_camera(pos[0], 0.0, pos[2])[2]
        # 相机背后（cam_z≤1）属钳位域，与出界同记截断（验收用例同口径）
        if cam_z_ <= 1.0 or not (0.0 <= px_ <= w_px
                                 and 0.0 <= py_ <= cam.size_px):
            truncated.append(f"hive{side}")
    from bugbits.render import bake as _bake
    unit_px = {}
    for u in world_units[:1]:                      # ant 参照（闭包首单位）
        w3, h3, _d3 = _bake.unit_world_size(u)
        sf = _bake.unit_world_scale(u)
        # 目标深度处单位世界高度 h·sf → 画布像素（方形像素：cot·canvas/(2·camZ·aspect)）
        _, _, cam_z = cam.world_to_camera(cam.tx, h3 * sf / 2.0, cam.tz)
        unit_px[u] = round(h3 * sf * cam.cot * canvas_px
                           / (2.0 * max(cam_z, 1e-6) * cam.aspect), 1)
    return {
        "visibleGroundRect": vis_rect,
        "mapCoverage": round(inside / (n * n), 4),
        "unitPxAtCenter": unit_px,
        "hivePx": hive_px, "truncatedTargets": truncated,
        "note": "mapCoverage=48×48 采样估计；visibleGroundRect=地平线下四角逆映射"
                " AABB（yaw≠0 时为旋转视口包围盒；地平线上角剔除，有效角<2 为 "
                "None）；指标用于解释构图，不作正确性证明",
    }


def camera_presets_for(world, wd, world_units):
    """world DATA 相机属性 → 有界预设表（不含生产默认 overview）。

    original_cam = 「跟踪虫贴住目标」（t=0）静态快照（CAM-PARAM STATIC 取证，
    out/nc-cam-delivery/param-forensics/report.md）：
      pitch    = MinAngle（DATA；STATIC 0x4855ff `pitch=MinAngle·(1−t)`，跟踪虫
                 t=0 → pitch=MinAngle；运行时每帧被驱动 0x48563d/0x48566f 写入）
      yaw      = 0（工程中性。STATIC：yaw 目标 = −bug.x/Width·MaxYaw（0x485428），
                 MaxYaw 是随 bug.x 缩放上限而非固定值；跟踪虫 x≈0 → yaw≈0；
                 RotY 方向符号 [UNVERIFIED]）
      aspect   = 1.6（STATIC 0x4e2fd0 后台缓冲；画布 letterbox 呈现，不 CSS 拉伸；
                 vs 参考分辨率 800×600=1.333 张力 OF-01 [UNVERIFIED]）
      distance = MinCamDistance（DATA 180；STATIC 0x48509e 跟踪虫时距离目标
                 直接=MinCamDistance。MaxCamDistance=分辨率相关上限
                 `·1920/screenW`（0x48992b），不用于本预设）
      target   = Offset（x, z←分量[1]）（STATIC 无虫分支 goal=Offset+mouseLead
                 加性基点 0x4854a0-0x4854f2，lead=0 静态；分量序 [UNVERIFIED]；
                 「目标=虫+Offset」字面式未在字节层成立——有虫分支 Offset 是
                 跟随窗 clamp 中心 0x485303-0x485383）
    """
    if world not in CAMERA_PRESET_WORLDS:
        return {}
    def f(key):
        return float(wd.props[key][0])
    def v3(key):
        return tuple(float(x) for x in wd.props[key])
    pitch_deg = math.degrees(f("MinAngle"))
    aspect = 1.6
    fov_deg = 60.0
    distance = f("MinCamDistance")
    offset = v3("Offset")
    target = [offset[0], 0.0, offset[1]]
    camera_spec = {
        "pitchDeg": pitch_deg, "yawDeg": 0.0,
        "fovDeg": fov_deg, "aspect": aspect,
        "near": camera.DEFAULT_NEAR, "far": camera.DEFAULT_FAR,
        "target": target,
        "distance": distance,
    }
    xmin, xmax, _, _, zmin, zmax = wd.terrain
    cam = camera.camera_from_spec((xmin, xmax, zmin, zmax),
                                  CONFIG["terrainSize"], camera_spec)
    sprite_pitch = -pitch_deg
    unit_atlas_scale = {}
    from bugbits.render import software as _software
    for u in world_units:
        spec = unitdb.load_unit(u)
        model_path = bake._resolve_model(spec.model, ".v3d")
        verts, _g, _s, _r = v3d.parse_v3d_groups(model_path)
        ns = _software.pose_screen_span(
            verts, CONFIG["yaws"], sprite_pitch, center=bake._aabb_center(verts))
        unit_atlas_scale[u] = ns / (0.8 * CONFIG["spriteSize"])
    flower_verts = v3d.parse_v3d(data_dir("models", "props", "flower_a.v3d"))[0][0]
    flower_ns = _software.pose_screen_span(
        flower_verts, 1, sprite_pitch, center=bake._aabb_center(flower_verts))
    flower_asc = round(flower_ns / (0.8 * CONFIG["spriteSize"]), 9)
    xmin, xmax, _, _, zmin, zmax = wd.terrain
    center = [(xmin + xmax) / 2.0, 0.0, (zmin + zmax) / 2.0]
    # 工程构图候选（可读性对照）：pitch 同 MinAngle（与 original_cam 共享同一
    # 精灵集，零额外精灵烘焙）、distance=MaxCamDistance（DATA；1920 宽参考
    # 标定 0x48992b）、目标=地图中心（工程选择）。**不称原作还原**——距离/
    # 目标组合是构图候选，供与 overview/original_cam 区分可读性目标。
    wide_spec = {
        "pitchDeg": pitch_deg, "yawDeg": 0.0,
        "fovDeg": fov_deg, "aspect": aspect,
        "near": camera.DEFAULT_NEAR, "far": camera.DEFAULT_FAR,
        "target": center,
        "distance": f("MaxCamDistance"),
    }
    wide_cam = camera.camera_from_spec((xmin, xmax, zmin, zmax),
                                       CONFIG["terrainSize"], wide_spec)
    return {
        "original_cam": {
            "label": "原作参数锚定候选（跟踪态参数 + 无虫目标基点的静态合成）",
            "camera": camera_spec,
            "spritePitchDeg": round(sprite_pitch, 4),
            "evidence": {
                "pitchDeg": "DATA(MinAngle)+STATIC(0x4855ff pitch=MinAngle·(1−t)，"
                            "跟踪 t=0 → =MinAngle)；每帧驱动 0x48563d/0x48566f",
                "yawDeg": "工程中性 0（STATIC：有虫 yaw 目标 "
                          "= MaxYaw·(0.75−t)·(−bug.x/Width)（0x485420），t=0 → ×0.75；"
                          "MaxYaw=缩放上限非固定值；x≈0 → yaw≈0）；方向符号 [UNVERIFIED]",
                "aspect": "STATIC(0x4e2fd0=1.6)；vs 参考分辨率 800×600=1.333 张力 "
                          "OF-01 [UNVERIFIED]",
                "distance": "DATA(MinCamDistance=180)+STATIC(0x48509e 跟踪虫时距离"
                            "目标=MinCamDistance)；MaxCamDistance=分辨率相关上限 "
                            "0x48992b，不用于本预设",
                "target": "HYPOTHESIS 实例化：无虫分支 goal=Offset+mouseLead"
                          "（STATIC 0x4854a0）取 lead=0；分量序 [UNVERIFIED]（[1] 作 z）。"
                          "有虫分支 goal=虫位、Offset 仅跟随窗 clamp 中心（0x485303）——"
                          "本组合（跟踪态 pitch/距离 + 无虫目标基点）为静态合成，"
                          "不对应原作任一单一运行状态",
            },
            "unitAtlasScale": {u: round(v, 9)
                               for u, v in unit_atlas_scale.items()},
            "flowerAtlasScale": flower_asc,
            "metrics": _preset_metrics(cam, wd, unit_atlas_scale, world_units),
        },
        "wide_cam": {
            "label": "工程构图候选（可读性对照，非原作还原）",
            "camera": wide_spec,
            "spritePitchDeg": round(sprite_pitch, 4),
            "evidence": {
                "pitchDeg": "同 original_cam（DATA MinAngle+STATIC 0x4855ff）",
                "yawDeg": "工程中性 0（同 original_cam）",
                "aspect": "STATIC(0x4e2fd0=1.6)；张力同 original_cam",
                "distance": "DATA(MaxCamDistance=400，1920 宽参考标定 0x48992b)；"
                            "组合=工程构图选择，非原作还原",
                "target": "工程选择（地图中心；原作为动态跟随目标）",
            },
            "unitAtlasScale": {u: round(v, 9)
                               for u, v in unit_atlas_scale.items()},
            "flowerAtlasScale": flower_asc,
            "metrics": _preset_metrics(wide_cam, wd, unit_atlas_scale,
                                       world_units),
        },
    }


# ── Pyodide vendor + 运行时 bundle ───────────────────────────────────
def _vendor_pyodide(out_dir):
    """锁定版本 Pyodide core → out/web/vendor/pyodide/（下载缓存+sha256 校验）。

    缓存目录 out/.vendor-cache/ 仅存原始 tar 包（输入缓存非产物复用）；
    解压产物每次构建重新落入 out/web（全量重建语义不受影响）。
    """
    import tarfile
    import urllib.request
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(out_dir)),
                             ".vendor-cache")
    os.makedirs(cache_dir, exist_ok=True)
    tar_path = os.path.join(cache_dir, f"pyodide-core-{PYODIDE_VERSION}.tar.bz2")
    if not (os.path.isfile(tar_path)
            and sha256_file(tar_path) == PYODIDE_SHA256):
        urllib.request.urlretrieve(PYODIDE_URL, tar_path)
        got = sha256_file(tar_path)
        if got != PYODIDE_SHA256:
            raise ValueError(f"Pyodide tarball sha256 不符: {got}")
    dest = os.path.join(out_dir, "vendor", "pyodide")
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(tar_path, "r:bz2") as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            rel = os.path.relpath(m.name, "pyodide")
            if rel.startswith(".."):
                raise ValueError(f"tar 越界条目: {m.name}")
            target = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as f:
                f.write(tf.extractfile(m).read())


def _write_py_bundle(out_dir):
    """src/bugbits 运行时模块源码 → py-bundle.json（单文件包，worker 写入 FS）。"""
    pkg = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # src/bugbits
    bundle = {}
    for dp, _, fs in os.walk(pkg):
        rel_dir = os.path.relpath(dp, pkg)
        if rel_dir.split(os.sep)[0] in BUNDLE_EXCLUDE:
            continue
        for fn in sorted(fs):
            if not fn.endswith(".py") or fn in BUNDLE_EXCLUDE:
                continue
            rel = os.path.join(rel_dir, fn) if rel_dir != "." else fn
            with open(os.path.join(dp, fn), encoding="utf-8") as f:
                bundle[rel.replace(os.sep, "/")] = f.read()
    path = os.path.join(out_dir, "py-bundle.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False)
    return len(bundle)


def _copy_pages(out_dir):
    """web/ 页面源码 → out/web/（index.html/worker.js/host.js + 字体）。"""
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "web")     # src/bugbits → 仓库根/web
    copied = []
    for fn in ("index.html", "worker.js", "host.js", "camera_projection.js", "presentation_material.js", "flower_pose.js", "mesh_scene.js",
               "NotoSansSC-subset.woff2", "OFL.txt"):
        p = os.path.join(src, fn)
        if not os.path.isfile(p):
            raise FileNotFoundError(f"页面源码缺失: {p}")
        shutil.copyfile(p, os.path.join(out_dir, fn))
        copied.append(fn)
    return copied


# ── export ───────────────────────────────────────────────────────────
def _prepare_out(out_dir):
    out_dir = os.path.abspath(out_dir)
    if os.path.isdir(out_dir):
        entries = os.listdir(out_dir)
        if entries and "manifest.json" not in entries:
            raise ValueError(
                f"输出目录 {out_dir} 非空且无 manifest.json（拒绝覆盖非构建产物）")
        for e in entries:
            p = os.path.join(out_dir, e)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    else:
        os.makedirs(out_dir, exist_ok=True)
    return out_dir


def _code_fingerprint():
    """构建器与运行时代码指纹（src/bugbits + tools/web_build.py）。"""
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))                       # src/bugbits → 仓库根
    h = hashlib.sha256()
    paths = []
    for sub in ("src/bugbits",):
        for dp, _, fs in os.walk(os.path.join(root, sub)):
            paths += [os.path.join(dp, f) for f in fs if f.endswith(".py")]
    paths.append(os.path.join(root, "tools", "web_build.py"))
    for p in sorted(paths):
        h.update(os.path.relpath(p, root).encode())
        h.update(hashlib.sha256(open(p, "rb").read()).digest())
    return h.hexdigest()


def export(out_dir, profile, level_ids=None, data_root=None):
    """构建 web 包 → manifest dict。level_ids 缺省按 profile 发现。"""
    old_env = os.environ.get("BUGBITS_DATA")
    if data_root:
        os.environ["BUGBITS_DATA"] = data_root
    try:
        return _export(out_dir, profile, level_ids)
    finally:
        if data_root:
            if old_env is None:
                os.environ.pop("BUGBITS_DATA", None)
            else:
                os.environ["BUGBITS_DATA"] = old_env


def mesh_prop_selector(world, level_type, prop_variants):
    """Select the actual level's flower presentation, never infer from its ID."""
    variant = 'rescue' if level_type == 'rescue' else 'normal'
    if variant not in prop_variants.get(world, ()):
        raise ValueError('level flower variant missing from geometry')
    return {'contract':web_geometry.PROP_VARIANT_CONTRACT,'world':world,'variant':variant}


def validate_mesh_prop_selectors(manifest, scene):
    """Bind every new level selector to exact scene variant closure."""
    metadata=manifest.get('geometryAssets',{}).get('propVariants')
    if 'propVariantContract' not in scene:
        if metadata is not None or any('meshProps' in lv.get('deps',{}) for lv in manifest['levels']):
            raise ValueError('level selectors require geometry variant contract')
        return
    if scene['propVariantContract']!=web_geometry.PROP_VARIANT_CONTRACT:
        raise ValueError('unsupported level flower variant contract')
    actual={w:sorted(record['propVariants']) for w,record in scene['worlds'].items()}
    if metadata!=actual:raise ValueError('geometryAssets prop variants differ from scene')
    requested={w:set() for w in actual}
    for lv in manifest['levels']:
        world=lv['world'];selector=lv.get('deps',{}).get('meshProps')
        if world not in actual:
            if selector is not None:raise ValueError('mesh prop selector outside geometry worlds')
            continue
        expected=mesh_prop_selector(world,lv['type'],actual)
        if selector!=expected:raise ValueError('level mesh prop selector differs from world/type')
        requested[world].add(expected['variant'])
    if {w:sorted(v) for w,v in requested.items()}!=actual:
        raise ValueError('geometry variants differ from actual level closure')


def _export(out_dir, profile, level_ids):
    out_dir = _prepare_out(out_dir)
    level_ids = list(level_ids) if level_ids else discover_levels(profile)
    closures, worlds, units = survey(level_ids)
    # Terrain materials are inputs even when outside a particular camera view.
    # Reject a named missing VTX before expensive unit/default/preset rendering.
    consumed = set()
    for name in sorted(worlds):
        consumed.update(bake.terrain_source_paths(name))
        for rig in worlds[name].flower_rigs.values():
            consumed.update(data_dir(*rig[key].split('/'))
                            for key in ('modelSource','animationSource'))
    # All real unit IDs have geometry even in a level slice. This is separate
    # from the legacy atlas closure, and never substitutes ant for another ID.
    geometry_worlds = [name for name,w in worlds.items() if w.basis_version=='loaded-yup-v1']
    prop_variants={w:sorted({'rescue' if c.lv.type=='rescue' else 'normal'
                            for c in closures if c.world==w}) for w in geometry_worlds}
    geometry_assets = web_geometry.export_geometry_assets(unitdb.load_all(),geometry_worlds,
        pose_policy=CONFIG['meshPosePolicy'],out_dir=out_dir,
        prop_variants_by_world=prop_variants,
        sample_hz=CONFIG['sampleHz'],min_frames=CONFIG['minFrames'],max_frames=CONFIG['maxFrames'])
    consumed.update(geometry_assets['source_paths'])

    texts_src = vln.parse_vln(data_dir("scripts", "lang4.vln"))
    text_keys = sorted({k for c in closures for k in c.text_keys})
    ui_text_keys = sorted({k for c in closures for k in c.ui_text_keys})
    units_obj = {u: unitdb.load_unit(u) for u in units}
    # units.json 延后写入：NC-03 需渲染期计算的稳定 normSpan（见下方渲染段）

    texts = {k: texts_src[k] for k in text_keys + ui_text_keys
             if k in texts_src}
    missing_keys = [k for k in text_keys if k not in texts_src]
    ui_missing = [k for k in ui_text_keys if k not in texts_src]

    # JSON 对象导出（web_data schema）
    os.makedirs(os.path.join(out_dir, "levels"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "worlds"), exist_ok=True)
    for c in closures:
        with open(os.path.join(out_dir, "levels", c.id + ".json"), "w",
                  encoding="utf-8") as f:
            json.dump(web_data.level_to_dict(c.lv), f, ensure_ascii=False)
    for name, w in sorted(worlds.items()):
        with open(os.path.join(out_dir, "worlds", name + ".json"), "w",
                  encoding="utf-8") as f:
            json.dump(web_data.world_to_dict(w), f, ensure_ascii=False)
    with open(os.path.join(out_dir, "texts.json"), "w", encoding="utf-8") as f:
        json.dump(texts, f, ensure_ascii=False)

    # 渲染：单位精灵（去重）+ 花（内联渲染以跟踪源文件入指纹）
    images, clip_manifest, stats = {}, {}, {}
    norm_spans = {}
    for u in units:
        clip_manifest[u], norm_spans[u] = render_unit_clips(
            u, images, stats, consumed)
    flower_model = data_dir("models", "props", "flower_a.v3d")
    (fverts, fidx, _fk), _fskin, _frecs, ftex_name = v3d.parse_v3d(flower_model)
    ftex = bake._load_texture(ftex_name)
    consumed.add(flower_model)
    if ftex_name and os.path.isfile(data_dir("textures", ftex_name + ".vtx")):
        consumed.add(data_dir("textures", ftex_name + ".vtx"))
    flower_key = "flower.bind.y0"
    images[flower_key] = bake._render_rgba(fverts, fidx, ftex,
                                           CONFIG["spriteSize"], yaw=0.0,
                                           pitch=bake.UNIT_SPRITE_PITCH_DEG,
                                           center=bake._aabb_center(fverts))
    # NC-03B：花蜜 props 世界尺寸（flower_a.v3d bind AABB；静态单精灵、无 ScaleFactor）
    fws = bake._aabb_center(fverts)
    f_w = max(p[0][0] for p in fverts) - min(p[0][0] for p in fverts)
    f_h = max(p[0][1] for p in fverts) - min(p[0][1] for p in fverts)
    f_d = max(p[0][2] for p in fverts) - min(p[0][2] for p in fverts)
    flower_norm_span = software.pose_screen_span(
        fverts, 1, bake.UNIT_SPRITE_PITCH_DEG, center=fws)
    flower_meta = {
        "worldSize": {"w": f_w, "h": f_h, "d": f_d},
        "atlasScale": flower_norm_span / (0.8 * CONFIG["spriteSize"]),
        "evidence": "flower_a.v3d bind AABB（worldSize）+ pose_screen_span(yaw0)/"
                    "(0.8·128)（atlasScale）；静态单精灵、无动画、ScaleFactor=1",
    }

    # units.json（NC-03 世界尺寸合同）：worldSize=模型 bind AABB（世界单位，
    # 不含 ScaleFactor）；normSpan=稳定归一化跨度（跨 clip/帧/yaw 一致）；
    # atlasScale=normSpan/(0.8·spriteSize)，1 图集像素 = atlasScale 模型世界
    # 单位。ScaleFactor 在 draw 层只乘一次（host.js unitBillboard /
    # render/billboard.py 同合同）。
    units_dict = {u: web_data.unit_to_dict(s) for u, s in units_obj.items()}
    for u, d in units_dict.items():
        w, h, depth = bake.unit_world_size(u)
        d["worldSize"] = {"w": w, "h": h, "d": depth}
        d["normSpan"] = norm_spans[u]
        d["atlasScale"] = norm_spans[u] / (0.8 * CONFIG["spriteSize"])
    with open(os.path.join(out_dir, "units.json"), "w", encoding="utf-8") as f:
        json.dump(units_dict, f, ensure_ascii=False)

    # 地形（模型及全部材质组纹理已在渲染前纳入输入闭包）
    terrain_files = {}
    for name in sorted(worlds):
        fname = f"terrain_{name}.png"
        bake.bake_terrain(name, size=CONFIG["terrainSize"]).save(
            os.path.join(out_dir, fname))
        terrain_files[name] = fname

    # 图集（默认精灵先行打包——NC 相机交付两阶段打包：默认精灵在预设烘焙前
    # 落盘并释放，削峰值内存（3GB 环境下全量+预设一次性装箱曾 OOM）。
    atlas, atlas_pages = pack_atlas(images, out_dir)
    images.clear()
    preset_images = {}

    # NC 相机交付：有界预设烘焙（地形逐预设 + 单位/花精灵按 (world, pitch) 共享
    # 重烤 + 键前缀隔离；world_02/world_03 之外世界保持默认——预算控制）。
    # 同 pitch 的预设共享同一精灵集与键前缀（零重复烘焙）；预设 atlasScale 以
    # 实际渲染 norm_span 为准（覆盖 camera_presets_for 的 bind 估算）。
    camera_presets = {}
    for name in sorted(worlds):
        wd = worlds[name]
        world_units = sorted({u for c in closures if c.world == name
                              for u in c.units})
        presets = camera_presets_for(name, wd, world_units)
        if not presets:
            continue
        xmin, xmax, _, _, zmin, zmax = wd.terrain
        camera_presets[name] = {}
        by_pitch = {}
        for key, ps in presets.items():
            by_pitch.setdefault(ps["spritePitchDeg"], []).append((key, ps))
        for sprite_pitch, group in by_pitch.items():
            prefix = f"cam_{name}:"
            for u in world_units:
                _clips, ns = render_unit_clips(u, preset_images, stats,
                                               consumed,
                                               pitch_deg=sprite_pitch,
                                               key_prefix=prefix)
                for _key, ps in group:
                    ps["unitAtlasScale"][u] = round(
                        ns / (0.8 * CONFIG["spriteSize"]), 9)
            fkey = f"{prefix}flower.bind.y0"
            preset_images[fkey] = bake.bake_flower_sprite(
                CONFIG["spriteSize"], pitch_deg=sprite_pitch)
            for key, ps in group:
                cam = camera.camera_from_spec((xmin, xmax, zmin, zmax),
                                              CONFIG["terrainSize"],
                                              ps["camera"])
                tf = f"terrain_{name}_{key}.png"
                bake.bake_terrain(name, size=CONFIG["terrainSize"],
                                  camera=cam).save(os.path.join(out_dir, tf))
                terrain_files[f"{name}_{key}"] = tf
                ps["terrainFile"] = tf
                ps["spritePrefix"] = prefix
                ps["flowerKey"] = fkey
                ps["projection"] = _preset_projection_dict(cam)
                camera_presets[name][key] = ps
            # 每组烘焙完即续接页号打包落盘并清空（峰值内存 ≈ 单组精灵集）
            atlas_g, files_g = pack_atlas(preset_images, out_dir,
                                          page_offset=len(atlas["pages"]))
            atlas["pages"].extend(atlas_g["pages"])
            atlas["sprites"].update(atlas_g["sprites"])
            atlas_pages.extend(files_g)
            preset_images.clear()
    atlas.update({"clips": clip_manifest, "flower": flower_key})
    with open(os.path.join(out_dir, "atlas.json"), "w", encoding="utf-8") as f:
        json.dump(atlas, f, ensure_ascii=False, sort_keys=True)

    # 音频（music + 世界 ambient + 事件 sfx 名单）
    audio_files = []
    for c in closures:
        rels = []
        if c.music:
            rels.append(os.path.join("music", c.music + ".ogg"))
        amb = worlds[c.world].props.get("AmbientSfx") if c.world else None
        if amb:
            rels.append(amb[0] + ".ogg")            # 值形如 sfx/ambient_field_01
        rels.extend(v + ".ogg" for v in EVENT_SFX.values())
        for rel in rels:
            src = data_dir("audio", *rel.split("/"))
            if not os.path.isfile(src):
                raise FileNotFoundError(f"音频缺失: {src}")
            dst = os.path.join(out_dir, "audio", rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
            consumed.add(src)
            audio_files.append(os.path.join("audio", rel))

    # OF-04：兵种图标（原作 gui/main/maingui_bug_*.vtx → icons/ PNG，买兵栏消费）。
    # 覆盖 20 本体单位；_tick 坐骑变体无图标（不可买, 无独立按钮）。
    icons = {}
    for u in sorted(units):
        isrc = data_dir("textures", "gui", "main", f"maingui_bug_{u}.vtx")
        if not os.path.isfile(isrc):
            continue
        rel = f"icons/maingui_bug_{u}.png"
        idst = os.path.join(out_dir, rel)
        os.makedirs(os.path.dirname(idst), exist_ok=True)
        vtx.parse_vtx(isrc)[4].save(idst)
        consumed.add(isrc)
        icons[u] = rel

    # OF-04：原作 GUI 纹理（买兵按钮圆底/HUD 框/光标/选关）→ assets/gui/*.png，
    # host.js/index.html 消费。路径键 = "main/<名>"|"gizmos/<名>"|"map/<名>"|"nectar_01"。
    gui = {}
    for sub, names in GUI_ASSETS.items():
        for n in names:
            gsrc = data_dir("textures", "gui", sub, n + ".vtx")
            if not os.path.isfile(gsrc):
                continue
            grel = f"assets/gui/{sub}/{n}.png"
            gdst = os.path.join(out_dir, grel)
            os.makedirs(os.path.dirname(gdst), exist_ok=True)
            vtx.parse_vtx(gsrc)[4].save(gdst)
            consumed.add(gsrc)
            gui[f"{sub}/{n}"] = grel
    # 价格图标（particles/nectar_01，ciBugButton ctor 0x483450 引用）
    nectar_src = data_dir("textures", "particles", "nectar_01.vtx")
    if os.path.isfile(nectar_src):
        nrel = "assets/gui/nectar_01.png"
        os.makedirs(os.path.dirname(os.path.join(out_dir, nrel)), exist_ok=True)
        vtx.parse_vtx(nectar_src)[4].save(os.path.join(out_dir, nrel))
        consumed.add(nectar_src)
        gui["nectar_01"] = nrel

    # Pyodide vendor + 运行时源码 bundle + 页面（W2；离线交付）
    _vendor_pyodide(out_dir)
    n_bundle = _write_py_bundle(out_dir)
    pages = _copy_pages(out_dir)

    # manifest
    projection = {name: projection_for(w) for name, w in worlds.items()}
    mesh_worlds = {name: worlds[name] for name in geometry_worlds}
    mesh_units = {name: sorted({u for c in closures if c.world == name for u in c.units})
                  for name in geometry_worlds}
    for name, record in mesh_presets_for(mesh_worlds, mesh_units, geometry_assets, out_dir).items():
        camera_presets.setdefault(name, {})['mesh_cam'] = record
        camera_presets[name]['native_camera']=native_camera_record(worlds[name],
            geometry_sha256=geometry_assets['sha256'])
    for closure in closures:
        if (closure.id, closure.lv.type, closure.world) == ('level_01', 'gather', 'world_01'):
            captured_inputs = {rel:sha256_file(data_dir(*rel.split('/'))) for rel in
                               ('scripts/levels/level_01.vsc', 'worlds/world_01.vsc')}
            camera_presets['world_01']['original_static_01'] = captured_first_level_camera_record(
                level_id=closure.id, level_type=closure.lv.type, world=closure.world,
                world_basis_version=worlds[closure.world].basis_version,
                geometry_sha256=geometry_assets['sha256'], input_hashes=captured_inputs)
    sprites = atlas["sprites"]
    flower_page = sprites[flower_key]["page"]

    def _pages(c):
        """本关依赖页 = 默认精灵页 ∪ 其世界各预设精灵页（含花）。"""
        pages = set(_level_atlas_pages(c, clip_manifest, sprites, flower_page))
        for key, ps in camera_presets.get(c.world, {}).items():
            if ps.get('presentationScope')==web_geometry.SCHEMA:
                continue
            pages |= set(_level_atlas_pages(
                c, clip_manifest, sprites, flower_page,
                prefix=ps["spritePrefix"]))
        return sorted(pages)

    levels_meta = [{"id": c.id, "type": c.lv.type, "world": c.world,
                    "deps": {"units": c.units, "world": c.world,
                             "texts": c.text_keys,
                             "music": f"audio/music/{c.music}.ogg" if c.music else None,
                             "atlasPages": _pages(c)},
                    "buyable": c.buyable,
                    "buyableKind": c.buyable_kind,
                    "buyableEvidence": (MULTI_DEMO_EVIDENCE
                                        if c.buyable_kind == "explicit-demo"
                                        else "fallback: BugSetup ∪ {ant}（原作可买栏"
                                             "解锁链无数据证据, 合同 §9.1）"),
                    "enemyBot": c.enemy_bot}
                   for c in closures]
    for lv in levels_meta:
        if lv['world'] in prop_variants:
            lv['deps']['meshProps']=mesh_prop_selector(lv['world'],lv['type'],prop_variants)
    consumed |= {data_dir("scripts", "lang4.vln")}
    consumed |= {data_dir("scripts", "levels", c.id + ".vsc") for c in closures}
    consumed |= {data_dir("worlds", w + ".vsc") for w in worlds}
    consumed |= {data_dir("scripts", "bugs", u + ".vsc") for u in units}
    consumed |= {data_dir("scripts", "buginfos", u + ".vsc") for u in units}
    input_hashes, build_id = finalize_world_inputs(consumed, profile, worlds)
    inputs_list = [rel for rel, _ in input_hashes]
    geometry_source_state = json.loads(open(os.path.join(out_dir,geometry_assets['file']),encoding='utf8').read())
    web_geometry.validate_geometry_sources(geometry_source_state,dict(input_hashes))
    validate_mesh_prop_selectors({'geometryAssets':geometry_assets,'levels':levels_meta},geometry_source_state)
    if geometry_assets['unitIds'] != sorted(unitdb.load_all()):
        raise ValueError('complete actual unit ID collection changed during build')

    fallbacks = []
    for u in units:
        kinds = {c["kind"] for c in clip_manifest[u].values()}
        if "static" in kinds:
            fallbacks.append({"unit": u, "kind": "static",
                              "why": "H24 蒙皮布局 5/24——根几何静态降级"})
        for clip, c in clip_manifest[u].items():
            if c["kind"] == "missing":
                fallbacks.append({"unit": u, "clip": clip, "kind": "missing",
                                  "fallbackClip": c.get("fallbackClip"),
                                  "why": "anims 无该引用或 .van 不可解析"})

    manifest = {
        "schemaVersion": CONFIG["schemaVersion"],
        "profile": profile, "buildId": build_id,
        "runtime": {"pyodideVersion": PYODIDE_VERSION,
                    "simCodeFingerprint": _code_fingerprint(),
                    "pyBundleModules": n_bundle, "pages": pages},
        "config": CONFIG,
        "levels": levels_meta,
        "capabilities": {
            "terrain": True, "unitClips": True, "flower": True,
            "hivePlaceholder": True, "dialogue": True,
            "audioMusic": True,
            "bugIcons": True,
            "audioSfx": {"ambient": True, "eventSfx": EVENT_SFX,
                         "evidence": "[HYPOTHESIS] 文件名语义映射（表现层选择，"
                                     "非引擎证据，合同 §9.2）"},
            "pathNectar": {"approx": "4×4 黄色方块占位（无原作路径蜜贴图证据）"},
            "flowerNectar": {"implementation":"bind-model-attachment-v1",
                             "materialScope":"xblended-ctor-conditional-v1",
                             "clockScope":"engineering-20Hz",
                             "originalCurrentDrawVerified":False},
            "hud": True},
        "fallbacks": fallbacks,
        "projection": projection,
        "cameraPresets": camera_presets,
        "geometryAssets": {k:v for k,v in geometry_assets.items() if k!='source_paths'},
        "props": {
            "flower": flower_meta,
            "nectar": {"note": "[HYPOTHESIS] 路径蜜世界尺寸无数据证据——现渲染为 "
                                "4×4 canvas px 黄点占位（particles/nectar_01.vtx "
                                "64×64 贴图未入世界合同，尺寸待实测）"},
            "hive": {"note": "无 hive 模型——占位 16×16 canvas px 矩形 + "
                              "HIVE{n}·hp 文字（W5 HUD 完整化占位，非世界尺寸合同）"},
        },
        "spriteStats": stats,
        "missingTextKeys": missing_keys,
        "uiTextMissing": ui_missing,          # UI 键缺失=数据面缺失（HUD 回退显示）
        "inputs": inputs_list,
        "inputHashes": dict(input_hashes),
        "atlasPages": atlas_pages, "terrainFiles": terrain_files,
        "icons": icons,
        "gui": gui,
        "audioFiles": sorted(set(audio_files)),
    }
    # files 清单（atlas.json 已写入; manifest 自身不入清单）
    files = []
    for dp, _, fs in os.walk(out_dir):
        for fn in sorted(fs):
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, out_dir).replace(os.sep, "/")
            files.append({"path": rel, "size": os.path.getsize(p),
                          "sha256": sha256_file(p)})
    files.sort(key=lambda e: e["path"])
    manifest["files"] = files
    # 交付内容摘要（artifactDigest）：覆盖全部交付文件——HTML/host.js/worker.js、
    # py-bundle.json（交付核心包）、vendor/pyodide、levels/worlds/units/texts、
    # 图集页、地形 PNG、音频。不含 manifest 自身（避免自引用）；files 仅含相对
    # 路径+size+sha256，无时间戳/绝对路径 → 确定性。与 buildId（代码+数据输入
    # 指纹）语义分离：页面源码变更会改变 artifactDigest 而不必改变 buildId。
    manifest["artifactDigest"] = hashlib.sha256(
        json.dumps(files, sort_keys=True).encode()).hexdigest()
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1, sort_keys=True)
    return manifest


# ── validate ─────────────────────────────────────────────────────────
def validate(out_dir):
    """只读校验产物；返回错误列表（空=通过）。不触碰原始数据。"""
    errors = []
    mf_path = os.path.join(out_dir, "manifest.json")
    if not os.path.isfile(mf_path):
        return [f"manifest.json 缺失: {mf_path}"]
    try:
        mf = json.loads(open(mf_path, encoding="utf-8").read())
    except ValueError as e:
        return [f"manifest.json 不可解析: {e}"]
    for field in ("schemaVersion", "buildId", "artifactDigest", "profile",
                  "config", "files",
                  "levels", "capabilities", "fallbacks", "projection",
                  "spriteStats", "atlasPages", "icons"):
        if field not in mf:
            errors.append(f"manifest 缺字段: {field}")
    if errors:
        return errors
    if mf["schemaVersion"] != web_data.SCHEMA_VERSION:
        errors.append(f"schemaVersion 不符: {mf['schemaVersion']}")
    if mf["profile"] not in ("slice", "full"):
        errors.append(f"profile 非法: {mf['profile']}")

    # files 哈希 + stray 检测
    listed = set()
    for e in mf["files"]:
        rel, p = e["path"], os.path.join(out_dir, e["path"])
        listed.add(rel)
        if not os.path.isfile(p):
            errors.append(f"files 条目缺失: {rel}")
            continue
        if os.path.getsize(p) != e["size"]:
            errors.append(f"size 不符: {rel}")
        if sha256_file(p) != e["sha256"]:
            errors.append(f"sha256 不符: {rel}")
    for dp, _, fs in os.walk(out_dir):
        for fn in fs:
            rel = os.path.relpath(os.path.join(dp, fn), out_dir).replace(os.sep, "/")
            if rel != "manifest.json" and rel not in listed:
                errors.append(f"未登记文件: {rel}")
    # artifactDigest 与 files 清单一致（独立重算，防手改 manifest 假绿）
    recomputed = hashlib.sha256(
        json.dumps(mf["files"], sort_keys=True).encode()).hexdigest()
    if recomputed != mf.get("artifactDigest"):
        errors.append("artifactDigest 不符")
    if errors:
        return errors

    # 闭包
    errors.extend(validate_package_worlds(out_dir,mf))
    units = json.loads(open(os.path.join(out_dir, "units.json"),
                            encoding="utf-8").read())
    texts = json.loads(open(os.path.join(out_dir, "texts.json"),
                            encoding="utf-8").read())
    for lv in mf["levels"]:
        for dep in ("units", "world"):
            need = lv["deps"][dep]
            if dep == "units":
                for u in need:
                    if u not in units:
                        errors.append(f"{lv['id']}: 单位 {u} 不在 units.json")
            elif not os.path.isfile(os.path.join(out_dir, "worlds",
                                                 need + ".json")):
                errors.append(f"{lv['id']}: 世界 {need} 未导出")
        for u in lv["buyable"]:
            if u not in units:
                errors.append(f"{lv['id']}: 可买单位 {u} 不在 units.json")
        lvj = os.path.join(out_dir, "levels", lv["id"] + ".json")
        if not os.path.isfile(lvj):
            errors.append(f"{lv['id']}: levels/{lv['id']}.json 缺失")
            continue
        lvo = web_data.restore_level(json.loads(open(lvj, encoding="utf-8").read()))
        for sub, args in lvo.scripts:
            if sub == "addhint" and args[0] not in texts:
                errors.append(f"{lv['id']}: 文本键 {args[0]} 不在 texts.json")
            if sub in ("sendenemy", "sendplayer") and len(args) > 2 \
                    and args[2] != "null" and args[2] not in texts:
                errors.append(f"{lv['id']}: 对话键 {args[2]} 不在 texts.json")
            if sub in ("sendenemy", "sendplayer") and args[0] not in units:
                errors.append(f"{lv['id']}: 脚本单位 {args[0]} 不在 units.json")
        if lv["deps"].get("music") and lv["deps"]["music"] not in listed:
            errors.append(f"{lv['id']}: 音乐 {lv['deps']['music']} 未打包")
    for u in {u for lv in mf["levels"] for u in lv["buyable"]}:
        if f"BUGNAME_{u.upper()}" not in texts:
            errors.append(f"可买单位 {u} 缺 BUGNAME 文本")

    # multi/multir 演示配置（U01）：可买栏含采集+进攻兵种，敌方 Bot 进攻兵种有效
    def _hive_damage(u):
        v = (units[u].get("props") or {}).get("HiveDamage", ["0"])
        return float(v[0]) > 0 if v else False
    for lv in mf["levels"]:
        if lv["type"] not in ("multibattle", "multirandom"):
            continue
        if not lv.get("buyable"):
            errors.append(f"{lv['id']}: multi 关可买栏为空")
            continue
        if not any(units[u].get("canGather") for u in lv["buyable"]):
            errors.append(f"{lv['id']}: multi 关可买栏无采集兵种")
        if not any(_hive_damage(u) for u in lv["buyable"]):
            errors.append(f"{lv['id']}: multi 关可买栏无进攻兵种(HiveDamage>0)")
        eb = lv.get("enemyBot")
        if not eb or not eb.get("attack_unit"):
            errors.append(f"{lv['id']}: multi 关无敌方 Bot 进攻兵种")
            continue
        au = eb["attack_unit"]
        if au not in units:
            errors.append(f"{lv['id']}: 敌方进攻兵种 {au} 不在 units.json")
        elif units[au].get("price") is None or not _hive_damage(au):
            errors.append(f"{lv['id']}: 敌方进攻兵种 {au} 无价格或无攻巢能力")

    # atlas
    ap = os.path.join(out_dir, "atlas.json")
    if not os.path.isfile(ap):
        errors.append("atlas.json 缺失")
        return errors
    atlas = json.loads(open(ap, encoding="utf-8").read())
    cfg = mf["config"]
    # atlasPages 依赖（FIX-04）：每关非空、页号在界内，且**覆盖**闭包单位全部
    # clip 精灵页（独立重算，不复用 _level_atlas_pages——防假绿）。
    for lv in mf["levels"]:
        ap = lv["deps"].get("atlasPages")
        if not ap:
            errors.append(f"{lv['id']}: deps.atlasPages 缺失")
            continue
        if any(not isinstance(p, int) or p < 0 or p >= len(atlas["pages"])
               for p in ap):
            errors.append(f"{lv['id']}: deps.atlasPages 越界 {ap}")
        need = set()
        # CAM-REVIEW【中】：独立重算须含预设前缀键——漏页会让 host keep-剪枝后
        # 预设视图单位静默消失（drawUnitSprite 缺键返回 false），旧重算只查默认键假绿。
        prefixes = [""] + [
            ps.get("spritePrefix", "")
            for ps in (mf.get("cameraPresets") or {})
            .get(lv["world"], {}).values()
            if ps.get('presentationScope') != web_geometry.SCHEMA
        ]
        for prefix in prefixes:
            for u in lv["deps"]["units"]:
                if u not in atlas["clips"]:
                    continue
                for clip, c in atlas["clips"][u].items():
                    if c["kind"] == "sampled":
                        for f in range(c["frames"]):
                            for y in range(cfg["yaws"]):
                                k = f"{prefix}{c['prefix']}.f{f}.y{y}"
                                if k in atlas["sprites"]:
                                    need.add(atlas["sprites"][k]["page"])
                    elif c["kind"] == "static":
                        for y in range(cfg["yaws"]):
                            k = f"{prefix}{c['prefix']}.y{y}"
                            if k in atlas["sprites"]:
                                need.add(atlas["sprites"][k]["page"])
        if not need <= set(ap):
            errors.append(f"{lv['id']}: atlasPages 未覆盖精灵页 {sorted(need - set(ap))}")
    pages = {}
    for pg in atlas["pages"]:
        p = os.path.join(out_dir, pg["file"])
        try:
            img = Image.open(p)
            img.load()
        except Exception as e:                    # noqa: BLE001 - 解码失败即错误
            errors.append(f"图集页解码失败: {pg['file']}: {e}")
            continue
        if img.size != (pg["width"], pg["height"]):
            errors.append(f"图集页尺寸不符: {pg['file']}")
        pages[pg["file"]] = img
    for key, s in atlas["sprites"].items():
        pg = atlas["pages"][s["page"]]
        if (s["x"] < 0 or s["y"] < 0
                or s["x"] + s["w"] > pg["width"] or s["y"] + s["h"] > pg["height"]):
            errors.append(f"atlas 矩形越界: {key}")
        # NC-03 内容框：cb 必须存在且套在瓦片内（裁剪/内容宽测量元数据；
        # NC-03A 后不作 draw 层锚点——锚点=瓦片中心 pivot）
        cb = s.get("cb")
        if (not isinstance(cb, list) or len(cb) != 4
                or cb[0] < s["x"] or cb[1] < s["y"]
                or cb[0] + cb[2] > s["x"] + s["w"]
                or cb[1] + cb[3] > s["y"] + s["h"]
                or cb[2] <= 0 or cb[3] <= 0):
            errors.append(f"atlas cb 非法: {key}: {cb!r}")
    # NC-03 世界尺寸合同（units.json）：三字段齐全且为正
    for u, d in units.items():
        ws = d.get("worldSize")
        if (not isinstance(ws, dict) or any(ws.get(k) is None or ws[k] <= 0
                                            for k in ("w", "h", "d"))):
            errors.append(f"units.json {u}: worldSize 缺失/非法")
        ns, asc = d.get("normSpan"), d.get("atlasScale")
        if not (isinstance(ns, (int, float)) and ns > 0):
            errors.append(f"units.json {u}: normSpan 缺失/非法")
        elif not (isinstance(asc, (int, float)) and asc > 0
                  and abs(asc - ns / (0.8 * cfg["spriteSize"])) < 1e-9):
            errors.append(f"units.json {u}: atlasScale != normSpan/(0.8·spriteSize)")
    for unit, clips in atlas["clips"].items():
        for clip, c in clips.items():
            if c["kind"] == "sampled":
                n = frame_count(c["duration"])
                if c["frames"] != n:
                    errors.append(f"{unit}.{clip}: frames {c['frames']} != 公式值 {n}")
                for i in (0, c["frames"] // 2, c["frames"] - 1):
                    for y in range(cfg["yaws"]):
                        key = f"{c['prefix']}.f{i}.y{y}"
                        if key not in atlas["sprites"]:
                            errors.append(f"{unit}.{clip}: 缺精灵 {key}")
            elif c["kind"] == "static":
                for y in range(cfg["yaws"]):
                    key = f"{c['prefix']}.y{y}"
                    if key not in atlas["sprites"]:
                        errors.append(f"{unit}.{clip}: 缺静态精灵 {key}")
            elif c["kind"] == "missing":
                fb = c.get("fallbackClip")
                if not fb or clips.get(fb, {}).get("kind") not in ("sampled",
                                                                   "static"):
                    errors.append(f"{unit}.{clip}: missing 无有效 fallbackClip")
    # 首中末帧 alpha 抽验（页面已解码）
    for unit, clips in atlas["clips"].items():
        for clip, c in clips.items():
            if c["kind"] == "sampled":
                idxs = sorted({0, c["frames"] // 2, c["frames"] - 1})
            elif c["kind"] == "static":
                idxs = [0]
            else:
                continue
            for i in idxs:
                key = (f"{c['prefix']}.f{i}.y0" if c["kind"] == "sampled"
                       else f"{c['prefix']}.y0")
                s = atlas["sprites"].get(key)
                if s is None or pages.get(atlas["pages"][s["page"]]["file"]) is None:
                    continue
                img = pages[atlas["pages"][s["page"]]["file"]].crop(
                    (s["x"], s["y"], s["x"] + s["w"], s["y"] + s["h"]))
                if _alpha_bbox(img) is None:
                    errors.append(f"空 alpha 精灵: {key}")

    # fallbacks 一致性
    fb_units = {e.get("unit") for e in mf["fallbacks"] if e.get("kind") == "static"}
    for unit, clips in atlas["clips"].items():
        if any(c["kind"] == "static" for c in clips.values()) \
                and unit not in fb_units:
            errors.append(f"{unit}: static clip 未登记 fallbacks")
    # 投影一致性（OF-03.B/C：静态斜俯视透视；重建相机验证世界↔像素往返）
    for name, pr in mf["projection"].items():
        if pr.get('kind') == 'matrix-yup-v1':
            try:
                wd = web_data.restore_world(json.loads(open(os.path.join(
                    out_dir, 'worlds', name + '.json'), encoding='utf-8').read()))
                binding = (mf.get('projectionBindings') or {})[name]
                if binding.get('projection') != pr:
                    raise ValueError('overview matrix differs from terrain binding')
                tf = binding.get('terrainFile')
                if tf != (mf.get('terrainFiles') or {}).get(name):
                    raise ValueError('matrix binding differs from host terrain')
                if not tf or tf not in listed:
                    raise ValueError('matrix terrain is not a listed package file')
                if os.path.isabs(tf) or '..' in tf.split('/') or '\\' in tf:
                    raise ValueError('invalid matrix terrain path')
                validate_matrix_projection_record(binding,
                    world_basis_version=wd.basis_version,
                    terrain_sha256=sha256_file(os.path.join(out_dir, tf)))
            except (OSError, ValueError, KeyError, TypeError) as e:
                errors.append(f'projection {name}: matrix binding {e}')
            continue
        if pr.get('kind') is not None:
            errors.append(f'projection {name}: unsupported projection kind')
            continue
        size = pr["size"]
        if not (pr["distance"] > 0 and pr["cot"] > 0):
            errors.append(f"projection {name}: 相机参数非法")
            continue
        wj = os.path.join(out_dir, "worlds", name + ".json")
        if os.path.isfile(wj):
            wd = web_data.restore_world(json.loads(open(wj, encoding="utf-8").read()))
            if wd.terrain:
                xmin, xmax, _, _, zmin, zmax = wd.terrain
                try:
                    cam = camera.static_oblique_camera((xmin, xmax, zmin, zmax), size)
                except ValueError as e:
                    errors.append(f"projection {name}: 相机构造失败 {e}")
                    continue
                for wx, wz in ((xmin, zmin), (xmax, zmin), (xmin, zmax),
                               (xmax, zmax), ((xmin + xmax) / 2, (zmin + zmax) / 2)):
                    px, py = cam.world_to_pixel(wx, 0.0, wz)
                    gx, gz = cam.pixel_to_ground(px, py)
                    if abs(gx - wx) > 1.0 or abs(gz - wz) > 1.0:
                        errors.append(f"projection {name}: 往返误差过大 "
                                      f"({wx:.1f},{wz:.1f})→({gx:.1f},{gz:.1f})")
                        break
    # NC 相机交付：cameraPresets 校验（地形在包内 + 键存在 + 相机往返 + aspect）
    for name, presets in (mf.get("cameraPresets") or {}).items():
        wj = os.path.join(out_dir, "worlds", name + ".json")
        if not os.path.isfile(wj):
            errors.append(f"cameraPresets {name}: 世界 {name} 未导出")
            continue
        wd = web_data.restore_world(
            json.loads(open(wj, encoding="utf-8").read()))
        xmin, xmax, _, _, zmin, zmax = wd.terrain
        for key, ps in presets.items():
            if key == 'native_camera':
                try:
                    validate_native_camera_record(ps, wd)
                except (ValueError, KeyError, TypeError) as e:
                    errors.append(f'cameraPresets {name}/{key}: native binding {e}')
                    continue
            if ps.get('presentationScope')==web_geometry.SCHEMA:
                try:
                    gf=ps.get('geometryFile')
                    if gf!='assets/geometry/scene.json' or gf not in listed:
                        raise ValueError('geometry scene missing from package')
                    ga=mf.get('geometryAssets') or {}
                    if ga.get('file')!=gf or ga.get('sha256')!=ps.get('geometrySHA256'):
                        raise ValueError('preset differs from actual scene record')
                    scene=json.loads(open(os.path.join(out_dir,gf),encoding='utf8').read())
                    web_geometry.validate_geometry(scene)
                    validate_mesh_prop_selectors(mf,scene)
                    if set(scene['units'])!=set(ga.get('unitIds',[])) or len(scene['units'])!=24:
                        raise ValueError('complete 24 unit mesh coverage required')
                    if scene['worlds'][name]['basisVersion']!=wd.basis_version:
                        raise ValueError('scene world basis differs')
                    if not set(scene['inputHashes']).issubset(set(mf['inputs'])):
                        raise ValueError('geometry sources outside creator closure')
                    web_geometry.validate_geometry_sources(scene,mf.get('inputHashes') or {})
                    for unit in scene['units'].values():
                        bf=unit['frameBuffer']['file']
                        if bf not in listed:
                            raise ValueError('binary pose buffer missing from package')
                        with open(os.path.join(out_dir,bf),'rb') as frame_stream:
                            web_geometry.validate_frame_buffer(unit,frame_stream.read())
                    for tex in scene['textures'].values():
                        tf=tex['file']
                        if tf not in listed or not tf.startswith('assets/geometry/') or '..' in tf.split('/'):
                            raise ValueError('mesh texture missing from package')
                        actual=os.path.join(out_dir,tf)
                        if sha256_file(actual)!=tex['sha256'] or os.path.getsize(actual)!=tex['size']:
                            raise ValueError('mesh texture differs from decoded input')
                    validate_mesh_projection_record(ps,world=name,
                        world_basis_version=wd.basis_version,geometry_sha256=sha256_file(os.path.join(out_dir,gf)))
                    if key == 'original_static_01' or 'cameraSource' in ps or 'applicability' in ps:
                        applicable = ps.get('applicability', {}).get('levelId')
                        level = next((lv for lv in mf['levels'] if lv['id'] == applicable), None)
                        if not level or level['world'] != name:
                            raise ValueError('captured preset has no matching exported level')
                        validate_captured_camera_scope(ps, level_id=level['id'], level_type=level['type'],
                                                       world=name, input_hashes=mf.get('inputHashes', {}))
                except (OSError,ValueError,KeyError,TypeError) as e:
                    errors.append(f'cameraPresets {name}/{key}: mesh binding {e}')
                continue
            tf = ps.get("terrainFile")
            if not tf or tf not in listed:
                errors.append(f"cameraPresets {name}/{key}: terrainFile "
                              f"{tf!r} 不在包内")
            if (ps.get('projection') or {}).get('kind') == 'matrix-yup-v1':
                try:
                    if not tf or tf not in listed:
                        raise ValueError('matrix terrain is not a listed package file')
                    if os.path.isabs(tf) or '..' in tf.split('/') or '\\' in tf:
                        raise ValueError('invalid matrix terrain path')
                    cam = validate_matrix_projection_record(ps,
                        world_basis_version=wd.basis_version,
                        terrain_sha256=sha256_file(os.path.join(out_dir, tf)))
                    if cam.aspect < 1:
                        raise ValueError('matrix stage aspect<1 is not supported')
                except (OSError, ValueError, KeyError, TypeError) as e:
                    errors.append(f'cameraPresets {name}/{key}: matrix binding {e}')
                continue
            if (ps.get('projection') or {}).get('kind') is not None or (ps.get('camera') or {}).get('kind') is not None:
                errors.append(f'cameraPresets {name}/{key}: unsupported or mixed camera kind')
                continue
            cam_spec = ps.get("camera") or {}
            if float(cam_spec.get("aspect", 1.0)) < 1.0:
                errors.append(f"cameraPresets {name}/{key}: aspect<1 未支持")
            tgt = cam_spec.get("target") or []
            if len(tgt) > 1 and abs(float(tgt[1])) > 1e-9:
                # host 逆映射假设 target.y=0（s = −distance·sinP/dyw）——
                # ty≠0 未被 host 消费（CAM-REVIEW【低】，入库前拦截）
                errors.append(f"cameraPresets {name}/{key}: target[1]≠0 "
                              "（host 逆映射假设 ty=0）")
            try:
                cam = camera.camera_from_spec((xmin, xmax, zmin, zmax),
                                              cam_spec.get("size", 1024),
                                              cam_spec)
                cx_, cz_ = (xmin + xmax) / 2.0, (zmin + zmax) / 2.0
                px_, py_ = cam.world_to_pixel(cx_, 0.0, cz_)
                gx_, gz_ = cam.pixel_to_ground(px_, py_)
                if math.hypot(gx_ - cx_, gz_ - cz_) > 1.0:
                    errors.append(f"cameraPresets {name}/{key}: 投影往返误差 "
                                  f"{math.hypot(gx_-cx_, gz_-cz_):.3f}")
            except (ValueError, KeyError) as e:
                errors.append(f"cameraPresets {name}/{key}: 相机构造失败 {e}")
            prefix = ps.get("spritePrefix", "")
            if not ps.get("flowerKey") or ps["flowerKey"] not in atlas["sprites"]:
                errors.append(f"cameraPresets {name}/{key}: flowerKey 缺失")
            for u in ps.get("unitAtlasScale", {}):
                if not any(k.startswith(f"{prefix}{u}.")
                           for k in atlas["sprites"]):
                    errors.append(f"cameraPresets {name}/{key}: 单位 {u} "
                                  f"无前缀精灵（{prefix}{u}.*）")
    return errors
