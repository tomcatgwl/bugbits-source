"""离线烘焙（T4.6）——**唯一 3D 光栅化处**（master-plan 指定）。

两类产物（缓存到 out/bake/）:
  bake_terrain(world, size)      地形斜俯视透视俯视图: 全 mesh 节点三角形光栅化,
                                 z-buffer(深度=相机空间 cam_z, 近小远大), lambert 明暗,
                                 材质组纹理消费（OF-03.B 不动）
  bake_unit_sprites(units, ...)  单位精灵 128px × 8 yaw × N 帧:
                                 复用 software.render(斜俯视 pitch=-40, 与相机同视角)
                                 → RGBA 真实 alpha（NC-04 起弃 colorkey）

投影约定（OF-03.B/C 修订）: 原「正交俯视为实现决策」（px←x 线性映射, py←z 线性映射,
z 向下=南向视角）已替换为 render.camera.StaticObliqueCamera 的静态斜俯视 40° 透视
（见 camera.py 模块 docstring 的逐项公式）。scene.py / web 消费同一相机保持对齐。
world_02/03 在 terrain_meshes 边界按明确 loaded-yup-v1 合同归一；
其他世界保标记的 legacy 路径。raw V3D parser 不改，未知运行skin/parent仍条件。

已知简化（保真度如实标注, 非「表现层」借口）:
  - far 由全图地面深度自动加大（见 camera.py），超出引擎运行时 far=1000。

地形 UV 与相机空间深度按投影后顶点的 1/cam_z 透视校正：q=Σλᵢ/zᵢ，
cam_z=1/q，UV=Σλᵢ·UVᵢ/zᵢ/q。此数学合同不构成原作动态画面还原证据。
"""
import math
import os

from PIL import Image, ImageDraw

from bugbits.assets import data_dir, pose, van, v3d, vtx
from bugbits.render import camera as camera_mod
from bugbits.render import software

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), "out", "bake")

# 网格名 → 基色（俯视地图调色板; 无材质语义证据, 实现决策）
MESH_PALETTE = {
    "water": (40, 90, 170),
    "waterlily_leaf": (60, 130, 160),
    "grass": (70, 130, 60),
    "ground": (150, 135, 100),
    "pebbles": (140, 130, 115),
}
MESH_PALETTE_PREFIX = (("grass", (70, 130, 60)), ("ground", (150, 135, 100)),
                       ("pebbles", (140, 130, 115)), ("water", (40, 90, 170)))

# 单位/花精灵的斜俯视 pitch（与 terrain 相机同视角）。software.render 的 pitch 绕 X 轴，
# 符号与相机向下俯视角相反：相机 pitch=+40° 向下 → 精灵 pitch=−40° 呈现同一视角
# （b=−40 时精灵屏幕 up=(0,cos40°,sin40°)=相机 up，屏幕 right=(1,0,0)=相机 right；
#  推导见 docs/original-fidelity-validation.md OF-03.C 与 camera.py 模块 docstring）。
UNIT_SPRITE_PITCH_DEG = -camera_mod.DEFAULT_PITCH_DEG   # = -40.0


def _mesh_color(name):
    if name in MESH_PALETTE:
        return MESH_PALETTE[name]
    for prefix, c in MESH_PALETTE_PREFIX:
        if name.startswith(prefix):
            return c
    return (150, 135, 100)


def _resolve_model(ref, ext):
    """models/ 下引用 → 实路径（大小写不敏感逐段解析, 同 harness XREF）。"""
    cur = data_dir("models")
    segs = ref.split("/")
    for i, seg in enumerate(segs):
        want = seg + ext if i == len(segs) - 1 else seg
        hit = next((n for n in os.listdir(cur) if n.lower() == want.lower()), None)
        if hit is None:
            return None
        cur = os.path.join(cur, hit)
    return cur


def _texture_kind(tex):
    """纹理 alpha 语义 → 'opaque' | 'cutout' | 'blend'（NC-04，DATA 分布）。

    - 'opaque'：全 255（底土/树干/map 背景）→ 不透明直写。
    - 'blend'：恒半透明（单值 a∈(0,255)，3 张水 89/128）→ 直通 alpha 混合。
    - 'cutout'：渐变（含 0 与 255，植被 decal 仅边缘 AA）→ a<64 跳过（cutout，
      AA 边缘丢失登记为已知简化）。
    无 alpha 通道/无纹理回退 'opaque'。
    """
    if tex is None or "A" not in tex.getbands():
        return "opaque"
    amin, amax = tex.getchannel("A").getextrema()
    if amin == 255:
        return "opaque"
    if amin == amax and 0 < amin < 255:
        return "blend"
    return "cutout"


def _clip_tri_near(pts_cam, uvs, eps):
    """Sutherland–Hodgman：相机空间三角形按 cam_z ≥ eps 裁剪（近平面）。

    近机位预设（追尾距离 180–400）下地图局部可位于相机背后——未裁剪的背顶点
    经透视除法爆炸（cam_z 钳 1e-9 → 像素坐标 ±1e11），会把整三角形糊满画布。
    返回裁剪后多边形顶点 [(cam_x, cam_y, cam_z, u, v)]（3–4 个；边属性按
    相交参数 t 线性插值）。全在后方 → 空列表。
    """
    out = []
    n = len(pts_cam)
    for i in range(n):
        a, b = pts_cam[i], pts_cam[(i + 1) % n]
        ua, ub = uvs[i], uvs[(i + 1) % n]
        a_in = a[2] >= eps
        b_in = b[2] >= eps
        if a_in:
            out.append((a[0], a[1], a[2], ua[0], ua[1]))
        if a_in != b_in:
            t = (eps - a[2]) / (b[2] - a[2])
            out.append((a[0] + t * (b[0] - a[0]),
                        a[1] + t * (b[1] - a[1]),
                        eps,
                        ua[0] + t * (ub[0] - ua[0]),
                        ua[1] + t * (ub[1] - ua[1])))
    return out


def _raster_mesh_group(m, base, idx_subset, tex, kind, px, zbuf, light, size,
                       cam):
    """光栅化单个材质组（bake_terrain 内联原逻辑提取，NC-04 加水 blend 分支）。

    kind 控制 texel 消费：
      - opaque/cutout：cutout 对 a<64 跳过，否则直写 + z-write。
      - blend（水）：a==0 跳过；a==255 直写 + z-write（防御，水恒半透明不会触发）；
        0<a<255 直通混合 `out=water·(a/255)+dst·(1-a/255)`，z-test 开、z-write 关。

    相机路径二分（NC 相机交付）：
      - `cam._plain`（yaw=0/aspect=1 默认相机）：world_to_pixel_depth 旧路径逐位
        （全图拟合距离保证地面/植株顶点全在相机前方，无需裁剪——回归锚不变）。
      - 其他（预设 yaw/aspect/target/distance 覆盖）：先转相机空间，近平面
        （cam_z ≥ 1.0）三角形裁剪，再透视投影——背后/跨平面三角形正确渲染。
    """
    tpx = tex.load() if tex is not None else None
    tw, th = tex.size if tex is not None else (0, 0)
    # legacy 快路径仅限「默认全图拟合相机」（_plain 且 _auto_fit）：plain+distance
    # 覆盖的预设同样可能让地图局部落到相机背后，必须走裁剪路径（CAM-REVIEW）。
    plain = (getattr(cam, "_plain", True)
             and getattr(cam, "_auto_fit", True))
    # 宽幅预设：投影空间宽 = size·aspect——x 钳位必须用实际图宽（旧版用
    # size-1 把 x≥1024 片元全丢，预设地形右 37.5% 未光栅化；CAM-REVIEW 阻塞项，
    # 编排者 2026-09-23 独立复核确认：列 1024-1637 背景 1.000 而解析逆映射在图内）。
    w_px = int(round(size * getattr(cam, "aspect", 1.0)))
    eps = max(1.0, float(getattr(cam, "near", 1.0)))   # 裁剪平面联动相机 near
    far = float(getattr(cam, "far", math.inf))
    for t in range(0, len(idx_subset) - 2, 3):
        i0, i1, i2 = idx_subset[t:t + 3]
        w0, w1, w2 = (m.verts[i][0] for i in (i0, i1, i2))
        # 面法线（世界系，取自世界顶点——透视投影下屏幕法线≠世界法线）
        ux, uy, uz = (w1[0] - w0[0], w1[1] - w0[1], w1[2] - w0[2])
        vx, vy, vz = (w2[0] - w0[0], w2[1] - w0[1], w2[2] - w0[2])
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        nn = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        lam = max(0.25, abs((nx * light[0] + ny * light[1] + nz * light[2]) / nn))
        uv0, uv1, uv2 = (m.verts[i][2] for i in (i0, i1, i2))
        if plain:
            a, b, c = (cam.world_to_pixel_depth(*w) for w in (w0, w1, w2))
            tris = (((a, b, c), (uv0, uv1, uv2)),)
        else:
            pts_cam = [cam.world_to_camera(*w) for w in (w0, w1, w2)]
            if all(p[2] < eps for p in pts_cam):
                continue
            poly = _clip_tri_near(pts_cam, (uv0, uv1, uv2), eps)
            if len(poly) < 3:
                continue
            tris = []
            for k in range(1, len(poly) - 1):
                v = (poly[0], poly[k], poly[k + 1])
                scr = []
                for (cx_, cy_, cz_, u_, v_) in v:
                    ndc_x = cam.cot * cx_ / (cz_ * cam.aspect)
                    ndc_y = cam.cot * cy_ / cz_
                    scr.append(((ndc_x + 1.0) * 0.5 * cam.size_px * cam.aspect,
                                (1.0 - ndc_y) * 0.5 * cam.size_px, cz_))
                tris.append((scr, ((v[0][3], v[0][4]),
                                   (v[1][3], v[1][4]),
                                   (v[2][3], v[2][4]))))
        for (a, b, c), (uvA, uvB, uvC) in tris:
            xs_, ys_ = (a[0], b[0], c[0]), (a[1], b[1], c[1])
            x_lo, x_hi = max(0, int(min(xs_))), min(w_px - 1, int(max(xs_)))
            y_lo, y_hi = max(0, int(min(ys_))), min(size - 1, int(max(ys_)))
            d = ((ys_[1] - ys_[2]) * (xs_[0] - xs_[2])
                 + (xs_[2] - xs_[1]) * (ys_[0] - ys_[2]))
            if abs(d) < 1e-9:
                continue
            uv0, uv1, uv2 = uvA, uvB, uvC
            inv_za, inv_zb, inv_zc = 1.0 / a[2], 1.0 / b[2], 1.0 / c[2]
            for py in range(y_lo, y_hi + 1):
                for pxx in range(x_lo, x_hi + 1):
                    w0_ = ((ys_[1] - ys_[2]) * (pxx - xs_[2]) +
                           (xs_[2] - xs_[1]) * (py - ys_[2])) / d
                    w1_ = ((ys_[2] - ys_[0]) * (pxx - xs_[2]) +
                           (xs_[0] - xs_[2]) * (py - ys_[2])) / d
                    w2_ = 1 - w0_ - w1_
                    if w0_ < 0 or w1_ < 0 or w2_ < 0:
                        continue
                    q = w0_ * inv_za + w1_ * inv_zb + w2_ * inv_zc
                    z = 1.0 / q
                    # LH near/far视锥：在材料色/深度写入前拒绝远面外片元。
                    # z由透视插值计算，交叉far的三角形只丢其远面外部分。
                    if z > far or z >= zbuf[py][pxx]:  # 近=小 cam_z 保留
                        continue
                    # 透视校正 UV；使用裁剪后的顶点深度和属性，V 翻转口径不变。
                    if tpx is not None:
                        u = (w0_ * uv0[0] * inv_za + w1_ * uv1[0] * inv_zb
                             + w2_ * uv2[0] * inv_zc) / q
                        v = (w0_ * uv0[1] * inv_za + w1_ * uv1[1] * inv_zb
                             + w2_ * uv2[1] * inv_zc) / q
                        tx = min(tw - 1, max(0, int(u * tw)))
                        ty = min(th - 1, max(0, int((1 - v) * th)))
                        texel = tpx[tx, ty]
                        if kind == "blend":
                            al = texel[3] if len(texel) > 3 else 255
                            if al == 0:
                                continue                    # 透明 → 不写色/深
                            col = tuple(min(255, int(ch * lam)) for ch in texel[:3])
                            if al == 255:
                                zbuf[py][pxx] = z
                                px[pxx, py] = col
                            else:
                                fa = al / 255.0            # 直通混合（水恒 alpha）
                                dst = px[pxx, py]
                                px[pxx, py] = tuple(
                                    int(col[i] * fa + dst[i] * (1.0 - fa))
                                    for i in range(3))
                        else:
                            if len(texel) > 3 and texel[3] < 64:
                                continue                    # 透明 decal texel → 跳过
                            col = tuple(min(255, int(ch * lam)) for ch in texel[:3])
                            zbuf[py][pxx] = z
                            px[pxx, py] = col
                    else:
                        col = tuple(min(255, int(ch * lam)) for ch in base)
                        zbuf[py][pxx] = z
                        px[pxx, py] = col


def _bake_terrain_meshes(meshes, size=1024, textures=None, camera=None):
    """给定解析后的世界网格 → 斜俯视俯视图（RGB，相机见 camera.static_oblique_camera）。

    NC-04 两遍光栅化：第一遍 opaque/cutout 按原网格顺序写深度；
    第二遍恒半透明水（blend）后画——保证水覆盖底土且不 blend 覆盖更近的漂浮物
    （waterlily 更近已写深 → 水 z-test 被挡）。`textures` 供合成夹具注入 1×1
    纹理（{tex_name: Image}），缺省回退 `_load_texture`（生产路径不变）。
    `camera`（NC 相机交付）：预设相机覆盖（yaw/aspect/target/distance）；缺省
    None = 默认全图拟合相机。预设相机必须由同一 bounds/size 构造。
    """
    xs = [v[0][0] for m in meshes for v in m.verts]
    zs = [v[0][2] for m in meshes for v in m.verts]
    xmin, xmax, zmin, zmax = min(xs), max(xs), min(zs), max(zs)
    cam = camera or camera_mod.static_oblique_camera((xmin, xmax, zmin, zmax), size)
    # 投影空间：垂直 size，水平 size·aspect（aspect=1 → 方形，逐位不变）
    w_px = int(round(size * cam.aspect))
    img = Image.new("RGB", (w_px, size), (16, 18, 22))
    px = img.load()
    zbuf = [[1e9] * w_px for _ in range(size)]
    # 顶光略偏（世界系 L=(0.35,1.0,0.2), y=上）——W1 修复后的世界光；世界系法线直接 lambert。
    light = (0.35, 1.0, 0.2)
    ln = math.sqrt(sum(c * c for c in light))
    light = tuple(c / ln for c in light)

    jobs = []
    for m in meshes:
        base = _mesh_color(m.name)
        # OF-03.B：每组材质组消费各自纹理（UV 采样）；透明贴图（草地/蒲公英等 decal）
        # 透明 texel 跳过（底土透出）。无纹理/旧解析回退 = mesh 名调色板。
        for idx_subset, tex_name in terrain_material_groups(m):
            tex = None
            if tex_name:
                tex = (textures or {}).get(tex_name) or _load_texture(tex_name)
            jobs.append((_texture_kind(tex), m, base, idx_subset, tex))

    # 第一遍：opaque + cutout（原网格/组顺序，逐位一致）
    for kind, m, base, idx_subset, tex in jobs:
        if kind == "blend":
            continue
        _raster_mesh_group(m, base, idx_subset, tex, kind, px, zbuf, light, size,
                           cam)
    # 第二遍：水 blend（z-test 开、z-write 关）
    for kind, m, base, idx_subset, tex in jobs:
        if kind != "blend":
            continue
        _raster_mesh_group(m, base, idx_subset, tex, kind, px, zbuf, light, size,
                           cam)
    return img


def terrain_material_groups(mesh):
    """Material jobs in render order, including the legacy single-group fallback."""
    return list(zip(mesh.group_indices, mesh.group_tex_names)) \
        if (mesh.group_indices and len(mesh.group_indices) == mesh.k) \
        else [(mesh.indices, mesh.tex_name)]


def terrain_source_paths(world_name):
    """Read-only terrain source closure; named missing materials fail explicitly.

    Every declared render job loads its texture before visibility/alpha tests.
    Default and preset cameras therefore share this camera-independent closure.
    Untextured groups still use the renderer's palette fallback.
    """
    from bugbits import worlddb
    owner_source = data_dir("worlds", world_name + ".vsc")
    # Read the same declared owner reference as the renderer. Legacy parsing
    # here identifies sources without asserting a loaded node/skin domain.
    world = worlddb.parse_world(owner_source, basis='legacy-grid-v1')
    if not world.static_model:
        raise ValueError(f"world {world_name!r} has no STATIC model")
    model = data_dir("models", *world.static_model.split("/")) + ".v3d"
    # Owner Position/Direction/basis policy now affect terrain geometry too.
    paths = {model, owner_source}
    for mesh in v3d.parse_world_meshes(model):
        for group, (_, texture) in enumerate(terrain_material_groups(mesh)):
            if texture:
                path = data_dir("textures", texture + ".vtx")
                if not os.path.isfile(path):
                    raise FileNotFoundError(
                        f"terrain {world_name}/{mesh.name} group {group}: {path}")
                paths.add(path)
    return tuple(sorted(paths))


def terrain_meshes(world_name, *, basis=None):
    """Terrain producer boundary shared with WorldData's coordinate contract.

    The WorldData version chooses one explicit path. Loaded geometry uses the
    original owner components, never the already-converted START positions.
    Identity skin/upstream and scale1 remain disclosed candidate premises.
    Unsupported loaded nodes raise; there is no validation-error fallback.
    """
    from bugbits import worlddb
    from bugbits.assets import world_basis
    world = worlddb.parse_world(data_dir("worlds", world_name + ".vsc"),
                                basis=basis)
    if not world.static_model:
        raise ValueError(f"world {world_name!r} has no STATIC model")
    path = data_dir("models", *world.static_model.split("/")) + ".v3d"
    meshes = v3d.parse_world_meshes(path)
    if world.basis_version == world_basis.LEGACY_BASIS_VERSION:
        return meshes
    if world.basis_version != world_basis.LOADED_BASIS_VERSION:
        raise ValueError(f"unknown terrain basis {world.basis_version!r}")
    return world_basis.loaded_world_meshes(
        meshes, world.static_position, direction=world.static_direction,
        scale=world.static_scale, skin_matrix=world_basis.IDENTITY,
        parent_matrix=world_basis.IDENTITY)


def bake_terrain(world_name, size=1024, camera=None, *, basis=None):
    """世界地形斜俯视透视俯视图（RGB，相机见 camera.static_oblique_camera）。

    `camera`（NC 相机交付）：预设相机覆盖（须与该世界 bounds/size 同源构造）；
    缺省 None = 默认全图拟合相机（产物逐位不变）。
    """
    meshes = terrain_meshes(world_name, basis=basis)
    return _bake_terrain_meshes(meshes, size, camera=camera)


def _load_texture(tex_name):
    """纹理名 → PIL.Image（data/textures/<名>.vtx, harness XREF 同口径）。"""
    if not tex_name:
        return None
    tp = data_dir("textures", tex_name + ".vtx")
    return vtx.parse_vtx(tp)[4] if os.path.isfile(tp) else None


def _render_rgba(verts, idx, tex, size, yaw, pitch=-90.0, norm_span=None,
                 center=None):
    """software.render → RGBA 透明底（真实 alpha，NC-04 起弃 colorkey）。

    pitch 默认 -90.0（俯视）保持既有调用者（web_build.render_unit_clips）兼容；
    斜俯视同视角烘焙须显式传 pitch=UNIT_SPRITE_PITCH_DEG（见 bake_unit_sprites）。
    norm_span（NC-03）：稳定归一化跨度（单位内全部精灵共用一个 sc，消除逐帧
    fit-to-box 重归一化的体量泵动；合同见 render/billboard.py 模块 docstring）。
    center（NC-03A）：稳定居中参考点（bind 姿态 AABB 中心）。

    idx/tex 多材质组（NC-03 bee）：单组传单值（旧口径），多组传成对列表
    （software.render 共享 z-buffer/norm_span/center）。

    NC-04：render 已产出真实 alpha（背景 alpha=0、主体 alpha=255、半透明翼
    alpha∈(0,255)），无需 colorkey 后处理——直接返回 render 的 RGBA 输出
    （对全不透明精灵与旧 colorkey 路径逐位一致：背景 (24,28,24,0)、主体 255）。
    """
    use_tex = (any(t is not None for t in tex)
               if isinstance(tex, (list, tuple)) else tex is not None)
    img, _ = software.render(verts, idx, tex, size=size, yaw=yaw, pitch=pitch,
                             use_tex=use_tex, norm_span=norm_span,
                             center=center)
    return img


def _aabb_center(verts):
    xs = [v[0][0] for v in verts]
    ys = [v[0][1] for v in verts]
    zs = [v[0][2] for v in verts]
    return ((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, (max(zs) + min(zs)) / 2)


def _aabb_size(verts):
    xs = [v[0][0] for v in verts]
    ys = [v[0][1] for v in verts]
    zs = [v[0][2] for v in verts]
    return (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))


def _groups_render_args(groups, texs):
    """groups=[(idx,tex_name)] + texs=[Image] → (idx, tex) 供 _render_rgba。

    单组传单值（旧口径，数值 parity 不变），多组传成对列表（software.render 多组
    共享 z-buffer/norm_span/center——bee 身体+翼膜同帧深度排序正确）。
    """
    if len(groups) == 1:
        return groups[0][0], texs[0]
    return [g[0] for g in groups], texs


def _unit_frames(unit_spec, frames):
    """单位 walk 动画 frames 帧 → ([(verts, idx, tex)], tex, bind_center)。

    蒙皮布局：正常binary读取56B数组及原引用表，影响已映射到声明节点或NULL。
    24单位数组与根几何同序，权重百分比保留。本函数的静态降级分支
    仅在蒙皮数组缺失或有效骨索引槽 ≤90% 时触发（防御性, 当前全量数据不触发；
    web_build.render_unit_clips 同口径并显式登记 fallback）。

    NC-03 bee：parse_v3d_groups 返回双材质组（翼膜+身体），两组索引/纹理一并
    透传（不改变世界尺寸/归一化——两者基于全 931 顶点池）。

    bind_center = 原始模型顶点（bind 姿态）AABB 中心——NC-03A 稳定居中参考点，
    供全部采样帧共用以消除帧 AABB 中心漂移（DR20-03）。
    """
    model_path = _resolve_model(unit_spec.model, ".v3d")
    verts, groups, skin, recs = v3d.parse_v3d_groups(model_path)
    texs = [_load_texture(name) for _, name in groups]
    if len(groups) > 1 and any(t is None for t in texs):
        missing = [name for (_, name), t in zip(groups, texs) if t is None]
        raise ValueError(f"{unit_spec.model}: 第二材质纹理缺失 {missing}")
    idx, tex = _groups_render_args(groups, texs)
    bind_center = _aabb_center(verts)
    skinnable = bool(skin) and sum(
        1 for _, _, inf in skin
        if inf and all(bi < len(recs) for bi, _ in inf)) > 0.9 * len(skin)
    if not skinnable or "walk" not in unit_spec.anims:
        return [(verts, idx, tex)] * frames, tex, bind_center
    blocks = van.parse_van(_resolve_model(unit_spec.anims["walk"], ".van"))
    bind = pose.worlds_from_records(recs)
    dur = blocks[0][-1][0]
    out = []
    for f in range(frames):
        t = dur * f / frames
        out.append((pose.skin_at(skin, bind, pose.worlds_at(recs, blocks, t),
                                 source_vertices=verts), idx, tex))
    return out, tex, bind_center


def bake_unit_sprites(unit_names, frames=5, yaws=8, size=128, atlas_scales=None):
    """→ {(unit, frame, yaw): RGBA Image}。yaw k → 旋转 k×45°；斜俯视 pitch 同 terrain 相机。

    NC-03 稳定归一化：先对每单位收集全部采样帧的最大**屏幕**跨度
    （pose_screen_span：8 yaw × 同 pitch，对角朝向不裁剪），全部帧/yaw 用
    同一 sc 渲染（体量不随动作/朝向泵动；世界尺寸精确映射由 cb+atlasScale
    承载，见 render/billboard.py）。atlas_scales 给定时回填
    {unit: norm_span/(0.8·size)}（1 图集像素 = 该值 模型世界单位）。

    NC-03A 稳定居中：norm_span 与渲染均以 bind 姿态 AABB 中心为居中参考点
    （非逐帧 AABB 中心），消除帧中心漂移导致的脚底抖动（DR20-03）。"""
    from bugbits import unitdb
    sprites = {}
    for name in unit_names:
        spec = unitdb.load_unit(name)
        frame_verts, _, bind_center = _unit_frames(spec, frames)
        norm_span = max(
            software.pose_screen_span(verts, yaws, UNIT_SPRITE_PITCH_DEG,
                                      center=bind_center)
            for verts, _idx, _tex in frame_verts)
        for f, (verts, idx, tex) in enumerate(frame_verts):
            for y in range(yaws):
                sprites[(name, f, y)] = _render_rgba(verts, idx, tex, size,
                                                     yaw=y * 45.0,
                                                     pitch=UNIT_SPRITE_PITCH_DEG,
                                                     norm_span=norm_span,
                                                     center=bind_center)
        if atlas_scales is not None:
            atlas_scales[name] = norm_span / (0.8 * size)
    return sprites


def unit_world_scale(unit_name):
    """单位世界比例契约（OF-03.C）：props["ScaleFactor"] 字符串 → float，缺省 1.0。

    数据侧（DATA, bugs/*.vsc）ScaleFactor ∈ 1.0–1.6（ant=1.5、beetlehero=1.4、
    bee/spider=1、wasp/caterpillar=1.25 等）。图集装箱仍 128px fit-to-box（不按
    ScaleFactor 重排），缩放放到 draw 层：host.js 画单位精灵时按
    `scale = unit_world_scale(unit)` 缩放屏幕尺寸（相对比例在世界空间而非精灵空间）。
    """
    from bugbits import unitdb
    try:
        spec = unitdb.load_unit(unit_name)
    except KeyError:
        return 1.0
    raw = spec.props.get("ScaleFactor")
    return float(raw[0]) if raw else 1.0


_WORLD_SIZE_CACHE = {}       # unit → (w, h, d)（模型只读，进程内稳定）


def unit_world_size(unit_name):
    """单位世界足迹（NC-03）：模型 bind 姿态 AABB → (w, h, d) 世界单位。

    世界系 = Y-up、XZ 地面（与 terrain/worlddb 一致）。单位模型顶点坐标即世界单位
    （terrain bounds 与单位 bounds 同尺度，见 master-plan T4.2 轴映射）。返回
    原始模型体量（**不含 ScaleFactor**——ScaleFactor 在 draw 层只乘一次）。
    未知单位/缺模型回退 (12, 7, 12)（登记近似，非引擎证据）。
    """
    if unit_name in _WORLD_SIZE_CACHE:
        return _WORLD_SIZE_CACHE[unit_name]
    from bugbits import unitdb
    try:
        spec = unitdb.load_unit(unit_name)
    except KeyError:
        return (12.0, 7.0, 12.0)          # 未知单位回退（近似体量，登记）
    rp = _resolve_model(spec.model, ".v3d")
    if not rp:
        return (12.0, 7.0, 12.0)          # 缺模型回退（近似体量，登记）
    (verts, idx, _k), _skin, _recs, _tex = v3d.parse_v3d(rp)
    xs = [v[0][0] for v in verts]
    ys = [v[0][1] for v in verts]
    zs = [v[0][2] for v in verts]
    out = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    _WORLD_SIZE_CACHE[unit_name] = out
    return out


def flower_world_size():
    """flower_a.v3d bind AABB → (w, h, d) 世界单位（NC-03B props 合同）。"""
    (verts, _idx, _k), _skin, _recs, _tex = v3d.parse_v3d(
        data_dir("models", "props", "flower_a.v3d"))
    return _aabb_size(verts)


def flower_atlas_scale(size=128, pitch_deg=None):
    """flower_a 稳定归一化跨度/(0.8·size)——1 图集像素 = 该值 模型世界单位（NC-03B）。

    `pitch_deg`（NC 相机交付）：预设精灵烘焙 pitch（缺省 = 默认 UNIT_SPRITE_PITCH_DEG）。
    """
    (verts, _idx, _k), _skin, _recs, _tex = v3d.parse_v3d(
        data_dir("models", "props", "flower_a.v3d"))
    ns = software.pose_screen_span(verts, 1,
                                   UNIT_SPRITE_PITCH_DEG if pitch_deg is None
                                   else pitch_deg,
                                   center=_aabb_center(verts))
    return ns / (0.8 * size)


def bake_flower_sprite(size=128, pitch_deg=None):
    """花精灵（H23 [UNVERIFIED]: FlowerType→模型映射无证据, 取 flower_a）。

    静态 prop: 直接渲染根几何（t22 V3 等价: bind 姿态渲染 == 根几何渲染）。
    `pitch_deg`（NC 相机交付）：预设烘焙 pitch（缺省 = 默认 UNIT_SPRITE_PITCH_DEG）。
    """
    (verts, idx, k), skin, recs, tex_name = v3d.parse_v3d(
        data_dir("models", "props", "flower_a.v3d"))
    tex = _load_texture(tex_name)
    return _render_rgba(verts, idx, tex, size, yaw=0.0,
                        pitch=UNIT_SPRITE_PITCH_DEG if pitch_deg is None
                        else pitch_deg,
                        center=_aabb_center(verts))


def save_all(world_name="world_02", units=("ant", "littlebeetle", "bee"),
             terrain_size=1024, frames=5, yaws=8, sprite_size=128, out_dir=None):
    """全量烘焙落盘（CLI 用; 产物 out/bake/）。返回产物路径表。"""
    out = out_dir or OUT_DIR
    os.makedirs(out, exist_ok=True)
    paths = {}
    t = bake_terrain(world_name, size=terrain_size)
    p = os.path.join(out, f"terrain_{world_name}.png")
    t.save(p)
    paths["terrain"] = p
    sprites = bake_unit_sprites(list(units), frames=frames, yaws=yaws, size=sprite_size)
    for (u, f, y), img in sprites.items():
        p = os.path.join(out, f"sprite_{u}_{f}_{y}.png")
        img.save(p)
        paths.setdefault("sprites", []).append(p)
    fp = os.path.join(out, "sprite_flower.png")
    bake_flower_sprite(sprite_size).save(fp)
    paths["flower"] = fp
    return paths
