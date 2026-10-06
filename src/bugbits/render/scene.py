"""场景合成器（T4.6）: 地形层 + 单位/花精灵层 + 蜂巢占位 → 单帧 PNG。

纯 2D 合成（无 3D; D4: 不 import sim——消费坐标元组）。坐标映射与 bake 一致：
使用 render.camera.StaticObliqueCamera 的静态斜俯视透视（OF-03.B/C），
world_to_pixel(x, z) = round(cam.world_to_pixel(x, 0, z)) 并钳位到画布内
（y=0 地面）。蜂巢占位 = 色块 + "HIVE(placeholder)" 文字（master-plan 要求标注 placeholder）。

NC-03（世界尺寸合同）：单位精灵按 render/billboard.py 的公告板合同合成——
世界足迹（模型 AABB × ScaleFactor）经地形相机透视投影决定绘制尺寸；锚点 =
瓦片中心（bind 姿态 AABB 中心投影，NC-03A 与逐帧 alpha bbox 分离）↔ 模型中心
世界点 (x, y+h·sf/2, z) 的投影；实体高度 y 进 cam_y/cam_z（飞行高度可见）。
与 web/host.js unitBillboard/drawUnitSprite 同一公式，跨环境一致由浏览器用例断言。
"""
from PIL import Image, ImageDraw

from bugbits.render import bake, billboard, camera


class Scene:
    def __init__(self, terrain, sprites, flower=None, bounds=None,
                 atlas_scales=None):
        """terrain: RGB Image; sprites: {(unit, frame, yaw): RGBA};
        bounds: 地形对应世界范围 (xmin, xmax, zmin, zmax)（None → 满幅 0..size）；
        atlas_scales: {unit: 1 图集像素 = N 模型世界单位}（bake_unit_sprites
        的 out-param；缺省按 bind 姿态 AABB 近似——精确值须由烘焙方回填）。"""
        self.terrain = terrain.convert("RGB")
        self.sprites = sprites
        self.flower = flower
        self.size = terrain.size[0]
        if bounds is None:
            self.bounds = (0, self.size, 0, self.size)
        else:
            self.bounds = bounds
        self.atlas_scales = dict(atlas_scales or {})
        # 与 bake_terrain 同一相机（同 bounds + 同 size）→ 离线合成与地形逐像素对齐
        self.cam = camera.static_oblique_camera(self.bounds, self.size)
        self._meta_cache = {}

    def world_to_pixel(self, x, z):
        px, py = self.cam.world_to_pixel(x, 0.0, z)
        return (max(0, min(self.size - 1, int(px))),
                max(0, min(self.size - 1, int(py))))

    def _unit_meta(self, unit, tile_px):
        """NC-03 渲染元数据（world_size/scale_factor/atlas_scale）。"""
        if unit not in self._meta_cache:
            ws = bake.unit_world_size(unit)
            asc = self.atlas_scales.get(unit)
            if asc is None:
                # 回退：bind 姿态 AABB 近似（精确值须由烘焙方传 atlas_scales）
                asc = max(ws) / (0.8 * tile_px)
            self._meta_cache[unit] = (ws, bake.unit_world_scale(unit), asc)
        return self._meta_cache[unit]

    @staticmethod
    def _yaw_index(yaw_deg, yaws=8):
        """朝向角 → 8 向离散索引（0=0°, 逆/顺时针每 45° 一档）。"""
        idx = int(((yaw_deg % 360) + 22.5) // 45) % yaws
        return idx

    def _paste_centered(self, img, sprite, center):
        px, py = center
        half = sprite.size[0] // 2
        x0, y0 = px - half, py - half
        if x0 >= self.size or y0 >= self.size or x0 + sprite.size[0] <= 0 \
                or y0 + sprite.size[1] <= 0:
            return
        img.alpha_composite(sprite, (x0, y0))

    def _paste_billboard(self, img, sprite, unit, pos):
        """单位精灵按 NC-03 公告板合同合成（billboard.py 权威公式）。

        NC-03A：锚点 = 瓦片中心（bind 中心投影），不用逐帧 alpha bbox 中心。
        """
        ws, sf, asc = self._unit_meta(unit, sprite.size[0])
        bb = billboard.unit_billboard(self.cam, pos, ws, sf, asc, self.size)
        if bb["cam_z"] <= 1e-6:      # 相机后（camZ≤0 被钳位）→ 剔除
            return
        dx, dy, dw, dh = billboard.content_dest(
            {"x": 0, "y": 0, "w": sprite.size[0], "h": sprite.size[1]},
            bb["px"], bb["py"], bb["lam"])
        self._composite_scaled(img, sprite, dx, dy, dw, dh)

    def _paste_flower(self, img, sprite, pos):
        """花蜜 props 世界尺寸合同（NC-03B）：flower_a.v3d worldSize + atlasScale，
        静态单精灵、ScaleFactor=1。与 _paste_billboard 同一 billboard 公式。"""
        ws = bake.flower_world_size()
        asc = bake.flower_atlas_scale(size=sprite.size[0])
        bb = billboard.unit_billboard(self.cam, pos, ws, 1.0, asc, self.size)
        if bb["cam_z"] <= 1e-6:      # 相机后（camZ≤0 被钳位）→ 剔除
            return
        dx, dy, dw, dh = billboard.content_dest(
            {"x": 0, "y": 0, "w": sprite.size[0], "h": sprite.size[1]},
            bb["px"], bb["py"], bb["lam"])
        self._composite_scaled(img, sprite, dx, dy, dw, dh)

    def _composite_scaled(self, img, sprite, dx, dy, dw, dh):
        """把 sprite 缩放到 (dw,dh) 并 alpha 合成到 (dx,dy)（越界裁剪）。"""
        if dw < 1e-3 or dh < 1e-3:
            return
        ox, oy = round(dx), round(dy)
        scaled = sprite.resize((max(1, round(dw)), max(1, round(dh))),
                               resample=Image.BILINEAR)
        vx0, vy0 = max(0, ox), max(0, oy)
        vx1 = min(self.size, ox + scaled.size[0])
        vy1 = min(self.size, oy + scaled.size[1])
        if vx1 <= vx0 or vy1 <= vy0:
            return
        region = scaled.crop((vx0 - ox, vy0 - oy,
                              min(vx1 - ox, scaled.size[0]),
                              min(vy1 - oy, scaled.size[1])))
        img.alpha_composite(region, (vx0, vy0))

    def compose_frame(self, entities, flowers=(), hives=(), frame=0):
        """合成一帧。

        entities: [(unit_name, x, z, yaw_deg)] 或 5 元组
        (unit_name, x, y, z, yaw_deg)（y = 离地高度，飞行单位传 FlyHeight）
        flowers:  [(x, z)]
        hives:    [(side, x, y, z)]   ← 4 元组兼容 worlddb Start grid_pos 展开
        返回 RGB Image。
        """
        img = self.terrain.convert("RGBA")
        for x, z in flowers:
            if self.flower is not None:
                self._paste_flower(img, self.flower, (x, 0.0, z))
        for ent in entities:
            if len(ent) == 5:
                unit, x, y, z, yaw = ent
            else:
                unit, x, z, yaw = ent[0], ent[1], ent[2], ent[3]
                y = 0.0
            key = (unit, frame, self._yaw_index(yaw))
            sprite = self.sprites.get(key)
            if sprite is not None:
                self._paste_billboard(img, sprite, unit, (x, y, z))
        draw = ImageDraw.Draw(img)
        for hive in hives:
            side, x, y, z = hive
            px, py = self.world_to_pixel(x, z)
            color = (80, 200, 90, 255) if side == 0 else (220, 80, 80, 255)
            draw.rectangle([px - 10, py - 10, px + 10, py + 10], outline=color, width=3)
            draw.text((px - 10, py - 22), f"HIVE{side}(placeholder)", fill=color)
        return img.convert("RGB")
