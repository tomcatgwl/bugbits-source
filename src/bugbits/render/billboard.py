"""NC-03 单位公告板合同（世界尺寸/锚点/飞行高度）——Python 权威实现。

web/host.js 的 unitBillboard/drawUnitSprite 镜像同一公式（跨环境一致由
C03/N05 浏览器用例断言 Python 复刻 == 页面实测）；render/scene.py 离线合成
与 harness/web/cases_browser.py 复刻共用本模块，不另起一套。

坐标系/相机：与 render/camera.py StaticObliqueCamera 相同（Y-up、XZ 地面、
pitch θ 俯视、cot=1/tan(fov/2)、aspect=1、NDC→像素左上原点）。

合同四要素（bake → units.json/atlas.json → host/scene 消费同一份）：
  1. worldSize=(w,h,d)：模型 bind AABB（世界单位，**不含 ScaleFactor**）。
  2. atlasScale：1 图集像素 = atlasScale 模型世界单位 = normSpan/(0.8·spriteSize)
     （normSpan = 该单位全部 clip/帧/yaw 共用的稳定归一化跨度；0.8 = bake
     fit-to-box 内容占比）。世界体量 = 模型体量 × ScaleFactor（sf 只乘一次）。
  3. cb=[x0,y0,w,h]：精灵 alpha bbox（图集页坐标；**裁剪/内容宽测量**用，NC-03A
     后不作锚点）。锚点 = 瓦片中心 ↔ 模型中心世界点 (x, pos_y + h·sf/2, z) 的
     投影（bind 姿态 AABB 中心恒映射瓦片中心，与逐帧 cb 分离 → 脚底不随帧/
     朝向跳动）。
  4. 投影用全相机公式（高度项进 cam_y/cam_z，飞行高度可见）：
       cam_x = x − cx
       cam_y = y·cosθ + dz·sinθ
       cam_z = distance + dz·cosθ − y·sinθ
     λ（图集像素→画布像素）= atlasScale·sf·cot·canvas/(2·cam_z)。
     NC 相机交付：预设（yaw/aspect/目标偏移）走一般基向量式 + λ 除以 aspect
     （letterbox 下方形像素），默认路径位级不变（见 camera.py 模块 docstring）。
"""
from collections import namedtuple

# NC 相机交付：增 sin_y/cos_y/aspect/tx/tz（预设 yaw/aspect/目标偏移；缺省 = 旧值）
_CAM_FIELDS = ("cx", "cz", "cot", "sin_p", "cos_p", "distance", "size",
               "sin_y", "cos_y", "aspect", "tx", "tz")
CamConsts = namedtuple("CamConsts", _CAM_FIELDS)


def cam_consts(proj):
    """manifest projection dict（sinP/cosP 键）或 StaticObliqueCamera（sin_p/cos_p
    属性）→ 统一常数。host.js render.projection = manifest dict 同键。

    预设键（manifest.cameraPresets[world][key].camera 序列化投影）：sinY/cosY/
    aspect/tx/tz；缺省 = 0/0/1/cx/cz（旧口径）。相机对象按属性名读取。
    """
    if isinstance(proj, dict):
        return CamConsts(proj["cx"], proj["cz"], proj["cot"], proj["sinP"],
                         proj["cosP"], proj["distance"], proj["size"],
                         proj.get("sinY", 0.0), proj.get("cosY", 1.0),
                         proj.get("aspect", 1.0), proj.get("tx", proj["cx"]),
                         proj.get("tz", proj["cz"]))
    return CamConsts(proj.cx, proj.cz, proj.cot, proj.sin_p, proj.cos_p,
                     proj.distance, proj.size_px,
                     getattr(proj, "sin_y", 0.0), getattr(proj, "cos_y", 1.0),
                     getattr(proj, "aspect", 1.0),
                     getattr(proj, "tx", proj.cx), getattr(proj, "tz", proj.cz))


def project(c, x, y, z, canvas_px):
    """世界点（含高度）→ (px, py, cam_z) 画布像素；与 camera.world_to_pixel
    同公式（y=0 时逐点一致），cam_z 供透视缩放/深度排序。

    默认（sin_y=0/aspect=1/tx=cx/tz=cz）走旧表达式（位级不变）；预设走一般
    基向量式（见 render/camera.py 模块 docstring）。画布坐标含 letterbox：
    水平 [0, canvas_px]，垂直居中高度 canvas_px/aspect（aspect=1 → 全画布）。
    """
    if c.sin_y == 0.0 and c.aspect == 1.0 and c.tx == c.cx and c.tz == c.cz:
        dx = x - c.cx
        dz = z - c.cz
        cam_x = dx
        cam_y = y * c.cos_p + dz * c.sin_p
        cam_z = c.distance + dz * c.cos_p - y * c.sin_p
        if cam_z < 1e-6:
            cam_z = 1e-6
        k = canvas_px / c.size
        px = (c.cot * cam_x / cam_z + 1.0) * 0.5 * c.size * k
        py = (1.0 - c.cot * cam_y / cam_z) * 0.5 * c.size * k
        return (px, py, cam_z)
    wx = x - c.tx
    wy = y - 0.0
    wz = z - c.tz
    cam_x = wx * c.cos_y - wz * c.sin_y
    cam_y = (wx * c.sin_p * c.sin_y + wy * c.cos_p
             + wz * c.sin_p * c.cos_y)
    cam_z = (wx * c.sin_y * c.cos_p - wy * c.sin_p
             + wz * c.cos_y * c.cos_p) + c.distance
    if cam_z < 1e-6:
        cam_z = 1e-6
    # 投影空间（垂直 size、水平 size·aspect）→ 画布 letterbox：水平满宽
    # canvas_px，垂直居中 canvas_px/aspect；k = canvas_px/(size·aspect) 统一。
    k = canvas_px / (c.size * c.aspect)
    px = (c.cot * cam_x / (cam_z * c.aspect) + 1.0) * 0.5 * c.size * c.aspect * k
    content_h = canvas_px / c.aspect
    py = (1.0 - c.cot * cam_y / cam_z) * 0.5 * c.size * k
    return (px, py + (canvas_px - content_h) / 2.0, cam_z)


def unit_billboard(proj, pos, world_size, scale_factor, atlas_scale,
                   canvas_px):
    """单位公告板参数（NC-03 合同）。

    proj: manifest projection dict 或 StaticObliqueCamera
    pos: (x, y, z) 单位世界位置（y = 离地/地形高度；飞行 lane 模式 = FlyHeight）
    world_size: (w, h, d) 模型 AABB 世界单位（不含 sf）
    返回 dict(px, py, cam_z, lam, center_y)：
      px/py = 模型中心投影（画布像素，瓦片中心对齐点，NC-03A）；lam = 图集像素→
      画布像素缩放；center_y = 模型中心世界 y（锚点推导，测试用）。
    """
    c = cam_consts(proj)
    w, h, d = world_size
    sf = float(scale_factor)
    center_y = (pos[1] or 0.0) + h * sf / 2.0
    px, py, cam_z = project(c, pos[0], center_y, pos[2], canvas_px)
    # λ = 图集像素→画布像素（方形像素：水平=垂直尺度 = asc·sf·cot·canvas/
    # (2·cam_z·aspect)；aspect=1 时与旧公式逐项一致）
    lam = (float(atlas_scale) * sf * c.cot * canvas_px
           / (2.0 * cam_z * c.aspect))
    return {"px": px, "py": py, "cam_z": cam_z, "lam": lam,
            "center_y": center_y}


def content_dest(sprite, px, py, lam):
    """drawImage/alpha_composite 目标矩形（稳定瓦片中心 ↔ (px, py)）。

    NC-03A（DR20-03）：锚点 = 瓦片中心（sprite 矩形中心 = bind 姿态 AABB 中心的
    投影——software.render 以 bind 中心为居中参考点，故 bind 中心恒映射瓦片中心）。
    与逐帧 alpha bbox（cb，裁剪/宽度测量用）分离：cb 中心随轮廓不对称逐帧漂移，
    若作锚点则根节点/脚底随帧抖动（DR20-03 反例，见 research/nc03a_anchor_e2e.py）。

    sprite: {"x","y","w","h"}（图集页坐标；离线合成传 {"x":0,"y":0,...}）。
    返回 (dx, dy, dw, dh)。
    """
    x, y, w, h = sprite["x"], sprite["y"], sprite["w"], sprite["h"]
    return (px - (w / 2.0) * lam, py - (h / 2.0) * lam, w * lam, h * lam)
