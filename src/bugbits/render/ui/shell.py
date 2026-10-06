"""HUD shell 层（cGameInterface/cScreen 对齐）: 快照 → RGBA 叠层。

snapshot dict（只读, D4）: {nectar:int, title:str, buy:[(名,价,enabled)],
hint:str}。叠层由调用方 alpha_composite 到场景帧上。
"""
from PIL import Image

from bugbits.render.ui import component
from bugbits.render.ui.layout import Panel


class Hud:
    def __init__(self, font):
        self.font = font
        self.nectar_counter = component.NectarCounter()
        self.title_bar = component.TitleBar()
        self.buy_bar = component.BuyBar()
        self.hint_text = component.HintText()

    def render(self, snapshot, size):
        w, h = size
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        f = self.font
        self.title_bar.render(img, f, snapshot.get("title", ""), Panel(0, 0, w, 72))
        self.nectar_counter.render(img, f, snapshot.get("nectar", 0),
                                   Panel(8, 80, 220, 72))
        self.buy_bar.render(img, f, snapshot.get("buy", []),
                            Panel(0, h - 104, w, 104))
        hint = snapshot.get("hint")
        if hint:
            lines = hint.count("\n") + 1
            self.hint_text.render(img, f, hint,
                                  Panel(8, h - 128 - lines * 64, 480, 24 + lines * 64))
        return img
