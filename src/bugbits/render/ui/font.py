"""字图集排版（T4.6b）: menufont_01_cn.vtx 图集 + .vfm 步进 + lang4_chars 字形表。

vfm.md 背书: CN 图集 2048² = 32×32 格 × 64px, **格 = 字形号**;
步进 = vfm[g] 游戏像素直用（H27 实现决策: 无缩放, 格内含留白）。
"""
import os

from PIL import Image

from bugbits.assets import data_dir, vfm, vln, vtx

CELL = 64          # 图集格边长
GRID = 32          # 32×32 格
LINE_H = 64        # 行高（换行推进）


class FontAtlas:
    def __init__(self, atlas, steps, cp2g):
        self.atlas = atlas            # RGBA 2048²
        self.steps = steps            # [u16] vfm 表
        self.cp2g = cp2g              # 码点 → 字形号

    @classmethod
    def load_cn(cls):
        atlas = vtx.parse_vtx(data_dir("textures", "fonts", "menufont_01_cn.vtx"))[4]
        steps = vfm.dump_vfm(data_dir("fontmetrics", "menufont_01_cn.vfm"))
        cp2g, _ = vln.load_charset(data_dir("scripts", "lang4_chars.vsc"))
        return cls(atlas, steps, cp2g)

    def glyph_of(self, ch):
        return self.cp2g.get(ord(ch))

    def step_of(self, ch):
        g = self.glyph_of(ch)
        return self.steps[g] if g is not None and g < len(self.steps) else 0

    def glyph_cell(self, ch):
        """字符 → 64px 格子 Image（无字形 → 全透明）。"""
        g = self.glyph_of(ch)
        if g is None or g >= GRID * GRID:
            return Image.new("RGBA", (CELL, CELL), (0, 0, 0, 0))
        col, row = g % GRID, g // GRID
        return self.atlas.crop((col * CELL, row * CELL,
                                col * CELL + CELL, row * CELL + CELL))

    def text_width(self, s):
        """排版宽度 = Σ 步进（\n 不计宽）。"""
        return sum(self.step_of(c) for c in s if c != "\n")

    def draw_text(self, img, xy, s):
        """在 img(RGBA) 上以 (x,y) 为左上角排版 s；返回终止 (x, y)。

        步进推进（vfm[g] 像素直用）; '\n' 换行（行高 LINE_H）;
        未知字形跳步（步进 0）。
        """
        x0, y = xy
        x = x0
        for ch in s:
            if ch == "\n":
                x = x0
                y += LINE_H
                continue
            if self.step_of(ch) == 0 and self.glyph_of(ch) is None:
                continue
            cell = self.glyph_cell(ch)
            img.alpha_composite(cell, (x, y))
            x += self.step_of(ch)
        return (x, y)
