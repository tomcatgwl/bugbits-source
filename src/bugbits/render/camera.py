"""透视相机原语（OF-03.A 落地）——矩阵与投影，纯函数可数值验证。

依据 research/of03_camera.py 与 docs/original-fidelity-validation.md OF-03.A：
原作相机 = 透视 LH（D3DXMatrixPerspectiveFovLH 内联 0x4060f0），垂直 FOV=60°(π/3)、
near=1、far=1000、aspect=w/h。此处 Y-up 静态相机是重实现原型。
2026-10-04 原字节复核修正旧追尾旋转解释：原轴矩阵为
Rx(float32(pitch−beta))·Ry(yaw)·Rx(theta)，见 docs/linux-camera-raw-evidence.md；
整体世界到屏幕基、完整运行状态尚未闭合，不能直接与下述 Y-up 基等同。

矩阵约定（与引擎一致）：列主序 4×4，M[r][c] 存于 m[c*4+r]；列向量 v' = M·v。

本模块是「最小渲染原型」的数学基座（fidelity-execution §3.B 数学原语先验证不变量）；
完整集成到 bake/软件光栅器 + 动态环绕相机（跟踪虫）仍需 WebGL 或逐帧重投影（见决策门）。

────────────────────────────────────────────────────────────────────────
OF-03.B/C：静态斜俯视相机（`StaticObliqueCamera` / `static_oblique_camera`）
决策门「静态斜俯视 40° 透视」最小原型。逐项公式与常数（可直接逐行移植 JS）：

世界系：Y-up，XZ 为地面（与 worlddb/bake 一致）。相机 yaw=0，pitch=40°(向下俯视)，
本原型相机位置 = target − distance·f；原作 0x4a3238 也使用逆旋转偏移，
但尚未证明其完整轴系与本原型一致。

常数：
  θ = pitch（弧度，默认 40°；引擎 MinAngle=0.7rad≈40.107°，原型取 40°）
  φ = fov/2（默认 fov=60° → φ=30°）
  cot = 1/tan(φ)（fov=60° 时 = √3）
  aspect = 1.0（方形画布）
  cx=(xmin+xmax)/2, cz=(zmin+zmax)/2, hx=(xmax−xmin)/2, hz=(zmax−zmin)/2

相机基（世界系，列向量）：
  r（右）= (1, 0, 0)
  u（上）= (0, cosθ, sinθ)
  f（前）= (0, −sinθ, cosθ)
  camPos = (cx, distance·sinθ, cz − distance·cosθ)

距离拟合（把 y=0 地面矩形 |Δx|≤hx, |Δz|≤hz 框入 NDC [−1,1]）：
  d_h = cot·hx + hz·cosθ            （近缘水平约束：近缘 cam_z = d − hz·cosθ）
  d_v = cot·hz·sinθ + hz·cosθ       （近缘垂直约束）
  distance = max(d_h, d_v, 1) / margin   （margin 默认 0.98，留少量边框）

world_to_pixel(x, y, z) → (px, py)：  （透视投影，返回浮点，调用方取整/钳位）
  dx = x − cx;  dz = z − cz
  cam_x = dx
  cam_y = y·cosθ + dz·sinθ
  cam_z = distance + dz·cosθ − y·sinθ        （相机空间深度，近小远大）
  ndc_x = cot·cam_x / cam_z                  （aspect=1）
  ndc_y = cot·cam_y / cam_z
  px = (ndc_x + 1)·size/2
  py = (1 − ndc_y)·size/2                    （像素 y 向下；地面远缘在上、近缘在下）

pixel_to_ground(px, py) → (x, z)：   （像素射线 ∩ 地面 y=0；逆映射）
  nx = 2·px/size − 1
  ny = 1 − 2·py/size
  t = distance·tanθ / (tanθ − ny/cot)        （= 交点相机空间深度 cam_z）
  dx = t·nx/cot
  dz = t·ny/(cot·sinθ)                        （= cam_y/sinθ）
  return (cx + dx, cz + dz)

near/far：近缘地面深度 = distance − hz·cosθ（>0，因 distance≥cot·hz·sinθ+hz·cosθ）；
全图静态镜头地面深度范围 [distance−hz·cosθ, distance+hz·cosθ]。引擎 far=1000 面向
运行时追尾镜头（距离 180–400），全图静态镜头会把它自动加大到 ≥ distance+hz·cosθ+1
（否则北缘被 far 平面裁切）。far 只影响投影矩阵深度/裁剪，不影响 px/py。

────────────────────────────────────────────────────────────────────────
NC 相机交付（2026-09-22）：有界预设泛化（yaw / aspect / 目标偏移 / 距离覆盖）

为支持 world_02/world_03 可见相机候选（loop-harness-camera-delivery.md），
StaticObliqueCamera 增加可选参数（全部缺省 = 旧行为）：

  yaw_deg   相机绕 Y 偏航（DATA MaxYaw 为原作初值候选；旋转方向符号 [UNVERIFIED]，
            本实现约定见下方基向量推导）
  aspect    宽高比（STATIC 后台缓冲 1.6，0x4e2fd0）。>1 时水平视场更宽：
            ndc_x = (cot/aspect)·cam_x/cam_z（D3DXMatrixPerspectiveFovLH M[0][0]）。
            投影空间水平宽度 = size_px·aspect（host 侧 letterbox 消费）。
  target    相机目标点 (tx, ty, tz)（缺省 = 地图中心 (cx, 0, cz)；支持非零 ty）
  distance  距离覆盖（缺省 None = 全图拟合；预设传原作 DATA 区间内的值）

基向量（世界系，yaw=φ、pitch=θ；φ=0 时与旧公式逐项约简一致）：
  r = (cosφ, 0, −sinφ)                       （屏幕右）
  f = (sinφ·cosθ, −sinθ, cosφ·cosθ)          （相机→目标前方）
  u = f × r = (sinθ·sinφ, cosθ, sinθ·cosφ)   （屏幕上）
  camPos = target − distance·f
cam_x = w·r, cam_y = w·u, cam_z = w·f + distance（w = P − target）。

默认位级不变：yaw==0、aspect==1.0 且 ty==0 时走旧表达式分支（`_plain`），保证既有
烘焙回归锚（NC-04 逐位锚）与 C03/N05 像素探针不受浮点结合序扰动。φ=0 数学
恒等已在测试锁定（tests/test_camera.py::test_default_path_bit_identical）。

逆映射 pixel_to_ground（含 yaw/aspect）：相机空间射线方向 d_cam=(ndc_x·aspect/cot,
ndc_y/cot, 1) → 世界方向 d = r·d0 + u·d1 + f·1；s = −camPos.y/d.y（∩ y=0 地面）。
yaw=0/aspect=1/ty=0 时与旧闭式逐项一致；非零高度使用一般式。
"""
import math


def perspective_fov_lh(fov_y, aspect, near, far):
    """D3DXMatrixPerspectiveFovLH（左旋，看向 +Z）→ 列主序 16 元组。

    布局（与引擎 0x4060f0 逐字节一致）：
      M[0][0]=cot(fov/2)/aspect  M[1][1]=cot(fov/2)
      M[2][2]=far/(far-near)     M[3][2]=1.0
      M[2][3]=-far·near/(far-near)
    """
    y = 1.0 / math.tan(fov_y / 2.0)
    x = y / aspect
    m = [0.0] * 16
    m[0] = x
    m[5] = y
    m[10] = far / (far - near)
    m[11] = 1.0
    m[14] = -far * near / (far - near)
    return tuple(m)


def mat_vec_mul(m, v):
    """列主序 4×4 · 列向量 v=(x,y,z,w) → (x',y',z',w')。"""
    x, y, z, w = v
    return (
        m[0] * x + m[4] * y + m[8] * z + m[12] * w,
        m[1] * x + m[5] * y + m[9] * z + m[13] * w,
        m[2] * x + m[6] * y + m[10] * z + m[14] * w,
        m[3] * x + m[7] * y + m[11] * z + m[15] * w,
    )


def mat_mul(a, b):
    """列主序 4×4 相乘 a·b。"""
    out = [0.0] * 16
    for c in range(4):
        for r in range(4):
            out[c * 4 + r] = sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4))
    return tuple(out)


def identity():
    return tuple([1.0 if r == c else 0.0 for c in range(4) for r in range(4)])


def projection(proj, world_pt):
    """世界点（已处视图空间，z 向 +Z）→ 透视投影 → (ndc_x, ndc_y, ndc_z)。

    返回裁剪前 NDC（除以 w 前）与 w；便于断言与 z-buffer 深度。
    """
    x, y, z = world_pt
    cx, cy, cz, w = mat_vec_mul(proj, (x, y, z, 1.0))
    return (cx / w if w else 0.0, cy / w if w else 0.0, cz / w if w else 0.0)


def viewport_ndc(ndc_xy, width, height):
    """NDC ([-1,1]) → 屏幕像素（左上原点）。"""
    nx, ny = ndc_xy
    return ((nx + 1.0) * 0.5 * width, (1.0 - ny) * 0.5 * height)


# ── 静态斜俯视相机（OF-03.B/C 最小原型） ─────────────────────────────
DEFAULT_PITCH_DEG = 40.0    # 引擎 MinAngle=0.7rad≈40.107°（0x4a2f07 [esi+0x3c4]）；原型取 40°
DEFAULT_FOV_DEG = 60.0      # 引擎 0x4e2e30 = π/3
DEFAULT_NEAR = 1.0          # 引擎 fld1 @0x40618e
DEFAULT_FAR = 1000.0        # 引擎 0x4e2d50；全图静态镜头会自动加大（见类 docstring）
DEFAULT_MARGIN = 0.98       # NDC 边框余量（距离拟合时把地面框入 [−margin, margin]）


class StaticObliqueCamera:
    """静态斜俯视透视相机（决策门「静态斜俯视 40° 透视」）。

    数学公式与常数见模块 docstring「OF-03.B/C」。仅存几何推导结果；不做动态跟踪。
    """

    def __init__(self, world_bounds, size_px, pitch_deg=DEFAULT_PITCH_DEG,
                 fov_deg=DEFAULT_FOV_DEG, near=DEFAULT_NEAR, far=DEFAULT_FAR,
                 margin=DEFAULT_MARGIN, yaw_deg=0.0, aspect=1.0,
                 target=None, distance=None):
        xmin, xmax, zmin, zmax = world_bounds
        self.bounds = (float(xmin), float(xmax), float(zmin), float(zmax))
        self.size_px = float(size_px)
        self.pitch = math.radians(pitch_deg)
        self.yaw = math.radians(yaw_deg)
        self.fov_y = math.radians(fov_deg)
        self.aspect = float(aspect)
        if self.aspect < 1.0:
            raise ValueError("aspect<1（竖屏 letterbox）未支持；候选均 ≥1")
        self.margin = float(margin)
        self.cx = (self.bounds[0] + self.bounds[1]) / 2.0
        self.cz = (self.bounds[2] + self.bounds[3]) / 2.0
        self.hx = (self.bounds[1] - self.bounds[0]) / 2.0
        self.hz = (self.bounds[3] - self.bounds[2]) / 2.0
        # 本原型目标缺省为地图中心；原作目标还有分支、缩放/钳位与运行态，
        # 不能概括成「虫 + Offset」（见 docs/linux-camera-branch-model.md）。
        self.target = ((self.cx, 0.0, self.cz) if target is None
                       else (float(target[0]), float(target[1]),
                             float(target[2])))
        self.tx, self.ty, self.tz = self.target
        # 几何常数
        self.cot = 1.0 / math.tan(self.fov_y / 2.0)   # fov=60° → √3
        self.sin_p = math.sin(self.pitch)
        self.cos_p = math.cos(self.pitch)
        self.tan_p = math.tan(self.pitch)
        self.sin_y = math.sin(self.yaw)
        self.cos_y = math.cos(self.yaw)
        # 距离拟合：把 y=0 地面矩形框入 NDC [−margin, margin]（仅缺省拟合路径；
        # distance 覆盖 = 预设显式距离，不做全图拟合）
        d_h = self.cot * self.hx + self.hz * self.cos_p
        d_v = self.cot * self.hz * self.sin_p + self.hz * self.cos_p
        self.fit_distance = max(d_h, d_v, 1.0) / self.margin
        self.distance = (self.fit_distance if distance is None
                         else float(distance))
        # 相机位置 = target − distance·f（f=(sinφcosθ, −sinθ, cosφcosθ)）
        self.camera_pos = (
            self.tx - self.distance * self.sin_y * self.cos_p,
            self.ty + self.distance * self.sin_p,
            self.tz - self.distance * self.cos_y * self.cos_p)
        # 默认位级不变分支：yaw=0 且 aspect=1 → 旧表达式逐字保留（回归锚）
        self._plain = (self.yaw == 0.0 and self.aspect == 1.0 and self.ty == 0.0)
        self._auto_fit = distance is None
        # near/far：全图地面深度范围 = [d−hz·cosθ, d+hz·cosθ]；far 自动加大防北缘裁切。
        # near 校验仅对「全图拟合 + 中心目标」路径强制（其前提=全图在近面外）；
        # 覆盖距离的预设不拟合全图（近机位下地图局部可在相机侧/后方，由地形
        # 烘焙近平面裁剪与预设验收断言保证）。
        if self._plain and self._auto_fit \
                and self.target == (self.cx, 0.0, self.cz):
            self.far = max(float(far),
                           self.distance + self.hz * self.cos_p + 1.0)
            if not float(near) < self.distance - self.hz * self.cos_p:
                raise ValueError(
                    "near 平面裁切地面近缘：distance=%.1f hz·cosθ=%.1f near=%.1f"
                    % (self.distance, self.hz * self.cos_p, near))
        else:
            depths = [self.world_to_camera(x, 0.0, z)[2]
                      for x in (self.bounds[0], self.bounds[1])
                      for z in (self.bounds[2], self.bounds[3])]
            self.far = max(float(far),
                           max([d for d in depths if d > 0], default=0.0) + 1.0)
        self.near = float(near)

    def world_to_camera(self, x, y, z):
        """世界点 → 相机空间 (cam_x, cam_y, cam_z)（未投影；cam_z 近小远大）。

        _plain（yaw=0/aspect=1/ty=0）走旧表达式（位级不变）；否则基向量一般式
        （见模块 docstring「NC 相机交付」节）。
        """
        if self._plain:
            dx = x - self.tx
            dz = z - self.tz
            cam_x = dx
            cam_y = y * self.cos_p + dz * self.sin_p
            cam_z = self.distance + dz * self.cos_p - y * self.sin_p
            return (cam_x, cam_y, cam_z)
        wx = x - self.tx
        wy = y - self.ty
        wz = z - self.tz
        cam_x = wx * self.cos_y - wz * self.sin_y
        cam_y = (wx * self.sin_p * self.sin_y + wy * self.cos_p
                 + wz * self.sin_p * self.cos_y)
        cam_z = (wx * self.sin_y * self.cos_p - wy * self.sin_p
                 + wz * self.cos_y * self.cos_p) + self.distance
        return (cam_x, cam_y, cam_z)

    def world_to_pixel_depth(self, x, y, z):
        """世界点 → (px, py, cam_z)。cam_z=相机空间深度，供 z-buffer（近=小保留）。

        投影空间：垂直 NDC [−1,1] → [0, size_px]，水平 [−1,1] → [0, size_px·aspect]
        （aspect>1 = 宽幅投影空间，host 侧 letterbox 消费）。px/py 为该空间浮点坐标。
        """
        cam_x, cam_y, cam_z = self.world_to_camera(x, y, z)
        if cam_z <= 1e-9:                     # 相机背后/零深度：防除零（原型不做裁剪）
            cam_z = 1e-9
        ndc_x = self.cot * cam_x / (cam_z * self.aspect)
        ndc_y = self.cot * cam_y / cam_z
        return ((ndc_x + 1.0) * 0.5 * self.size_px * self.aspect,
                (1.0 - ndc_y) * 0.5 * self.size_px, cam_z)

    def world_to_pixel(self, x, y, z):
        """世界点 → 透视投影像素 (px, py)（浮点；调用方取整/钳位）。"""
        px, py, _ = self.world_to_pixel_depth(x, y, z)
        return (px, py)

    def pixel_to_ground(self, px, py):
        """像素射线 ∩ 地面 y=0 → 世界 (x, z)（逆映射）。

        _plain 走旧闭式（位级不变）；一般式：相机空间射线方向
        d_cam=(ndc_x·aspect/cot, ndc_y/cot, 1) → 世界方向 d = r·d0+u·d1+f·1，
        s = −camPos.y/d.y，交点 = camPos + s·d（见模块 docstring）。
        """
        if self._plain:
            nx = 2.0 * px / self.size_px - 1.0
            ny = 1.0 - 2.0 * py / self.size_px
            t = self.distance * self.tan_p / (self.tan_p - ny / self.cot)
            dx = t * nx / self.cot
            dz = t * ny / (self.cot * self.sin_p)
            return (self.tx + dx, self.tz + dz)
        nx = 2.0 * px / (self.size_px * self.aspect) - 1.0
        ny = 1.0 - 2.0 * py / self.size_px
        d0 = nx * self.aspect / self.cot
        d1 = ny / self.cot
        dx_ = self.cos_y * d0 + self.sin_p * self.sin_y * d1 \
            + self.sin_y * self.cos_p
        dy_ = self.cos_p * d1 - self.sin_p
        dz_ = -self.sin_y * d0 + self.sin_p * self.cos_y * d1 \
            + self.cos_y * self.cos_p
        s = -(self.ty + self.distance * self.sin_p) / dy_
        # 射线原点 = camPos = target − distance·f（非 target 本身）
        return (self.tx - self.distance * self.sin_y * self.cos_p + s * dx_,
                self.tz - self.distance * self.cos_y * self.cos_p + s * dz_)


def static_oblique_camera(world_bounds, size_px, pitch_deg=DEFAULT_PITCH_DEG,
                          fov_deg=DEFAULT_FOV_DEG, near=DEFAULT_NEAR,
                          far=DEFAULT_FAR, margin=DEFAULT_MARGIN):
    """构造静态斜俯视相机（见 StaticObliqueCamera / 模块 docstring）。"""
    return StaticObliqueCamera(world_bounds, size_px, pitch_deg=pitch_deg,
                               fov_deg=fov_deg, near=near, far=far, margin=margin)


def camera_from_spec(world_bounds, size_px, spec):
    """预设参数表 → StaticObliqueCamera（web_build/host 消费同源键）。

    spec 键（manifest.cameraPresets[world][key].camera 同构，缺省 = 默认）：
      pitchDeg/yawDeg/fovDeg/aspect/near/far/target([x,y,z])/distance。
    """
    return StaticObliqueCamera(
        world_bounds, size_px,
        pitch_deg=spec.get("pitchDeg", DEFAULT_PITCH_DEG),
        fov_deg=spec.get("fovDeg", DEFAULT_FOV_DEG),
        near=spec.get("near", DEFAULT_NEAR),
        far=spec.get("far", DEFAULT_FAR),
        yaw_deg=spec.get("yawDeg", 0.0),
        aspect=spec.get("aspect", 1.0),
        target=spec.get("target"),
        distance=spec.get("distance"))


class MatrixWorldCamera:
    """Explicit Y-up adapter for an already decoded original world-to-view matrix.

    This does not reconstruct the original driver, its state or Euler angles.
    Rows multiply column points. Engineering Q(A,B,C)=(-B,-C,A) gives
    basis = Roriginal * Qinverse and camera_pos = Q(original_camera_position).
    """

    ORTHONORMAL_TOLERANCE = 1e-6

    @staticmethod
    def _numbers(value, count):
        try:
            values = tuple(value)
            if len(values) != count or any(isinstance(x, bool)
                    or not isinstance(x, (int, float)) for x in values):
                raise ValueError('expected finite numeric coordinates')
            values = tuple(float(x) for x in values)
            if not all(math.isfinite(x) for x in values):
                raise ValueError('expected finite numeric coordinates')
            return values
        except (TypeError, OverflowError) as exc:
            raise ValueError('expected finite numeric coordinates') from exc

    @classmethod
    def from_original(cls, rotation3x3, camera_position_original, *,
                      size_px, aspect, fov_y, near, far):
        camera = cls()
        try:
            rows = tuple(cls._numbers(row, 3) for row in rotation3x3)
        except TypeError as exc:
            raise ValueError('rotation must have three rows') from exc
        if len(rows) != 3:
            raise ValueError('rotation must have three rows')
        tolerance = cls.ORTHONORMAL_TOLERANCE
        for i in range(3):
            for j in range(3):
                dot = sum(rows[i][k]*rows[j][k] for k in range(3))
                if abs(dot-(1 if i == j else 0)) > tolerance:
                    raise ValueError('rotation must be orthonormal')
        a, b, c = rows
        determinant = (a[0]*(b[1]*c[2]-b[2]*c[1])
                       - a[1]*(b[0]*c[2]-b[2]*c[0])
                       + a[2]*(b[0]*c[1]-b[1]*c[0]))
        if abs(determinant-1) > tolerance:
            raise ValueError('rotation must have determinant +1')
        # Qinverse columns are (0,-1,0), (0,0,-1), (1,0,0).
        camera.basis = tuple((-row[1], -row[2], row[0]) for row in rows)
        a, b, c = cls._numbers(camera_position_original, 3)
        camera.camera_pos = (-b, -c, a)
        size_px, aspect, fov_y, near, far = cls._numbers(
            (size_px, aspect, fov_y, near, far), 5)
        if not (size_px > 0 and aspect > 0 and 0 < fov_y < math.pi
                and 0 < near < far and math.isfinite(size_px*aspect)):
            raise ValueError('invalid camera dimensions or frustum')
        tangent = math.tan(fov_y/2)
        if tangent == 0 or not math.isfinite(1/tangent):
            raise ValueError('invalid field of view')
        camera.size_px, camera.aspect, camera.fov_y = size_px, aspect, fov_y
        camera.cot = 1/tangent
        camera.near, camera.far = near, far
        camera._plain = False
        camera._auto_fit = False
        return camera

    def world_to_camera(self, x, y, z):
        point = self._numbers((x, y, z), 3)
        delta = tuple(p-c for p, c in zip(point, self.camera_pos))
        return self._numbers(tuple(sum(row[k]*delta[k] for k in range(3))
                                   for row in self.basis), 3)

    def world_to_pixel_depth(self, x, y, z):
        cx, cy, depth = self.world_to_camera(x, y, z)
        if not self.near <= depth <= self.far:
            raise ValueError('point is outside camera near/far depth')
        nx = self.cot * cx / (depth * self.aspect)
        ny = self.cot * cy / depth
        return self._numbers(((nx+1) * self.size_px * self.aspect / 2,
                              (1-ny) * self.size_px / 2, depth), 3)

    def world_to_pixel(self, x, y, z):
        return self.world_to_pixel_depth(x, y, z)[:2]

    def pixel_to_ground(self, px, py):
        px, py = self._numbers((px, py), 2)
        nx = 2*px / (self.size_px*self.aspect) - 1
        ny = 1 - 2*py / self.size_px
        ray_camera = (nx*self.aspect/self.cot, ny/self.cot, 1)
        ray = tuple(sum(self.basis[k][j]*ray_camera[k] for k in range(3))
                    for j in range(3))
        if not all(math.isfinite(x) for x in ray) or abs(ray[1]) <= 1e-12:
            return None
        amount = -self.camera_pos[1] / ray[1]
        if not self.near <= amount <= self.far:
            return None
        hit = (self.camera_pos[0]+amount*ray[0],
               self.camera_pos[2]+amount*ray[2])
        return hit if all(math.isfinite(x) for x in hit) else None

    def projection_dict(self, kind='matrix-yup-v1'):
        """JSON-ready complete camera contract; no inferred Euler angles."""
        if kind != 'matrix-yup-v1':
            raise ValueError('matrix camera projection kind must be matrix-yup-v1')
        return dict(kind=kind, basis9=[x for row in self.basis for x in row],
                    cameraPosition=list(self.camera_pos), size=self.size_px,
                    cot=self.cot, aspect=self.aspect, near=self.near, far=self.far)
