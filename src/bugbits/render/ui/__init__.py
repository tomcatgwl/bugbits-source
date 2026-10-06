"""HUD UI 包（T4.6b）——三层结构对齐 RTTI 实测:
cGameInterface/cScreen → shell（Hud）, cPanel/ciImagePanel → layout（Panel）,
cButton/ciBugButton/cText → component（widget）。
D4: 全包只读状态快照 dict, 禁 import sim。
"""
from bugbits.render.ui import component, font, layout, shell

__all__ = ["component", "font", "layout", "shell"]
