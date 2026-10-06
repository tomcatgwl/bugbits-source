"""HUD 组件层（cButton/ciBugButton/cText 对齐）: 只读快照渲染的 widget。"""
from PIL import Image, ImageDraw

from bugbits.render.ui.layout import Panel


def _panel_bg(img, rect, color=(20, 24, 20, 170)):
    d = ImageDraw.Draw(img)
    d.rectangle([rect.x, rect.y, rect.x + rect.w, rect.y + rect.h],
                fill=color, outline=(200, 200, 200, 120), width=1)


class NectarCounter:
    """左上角花蜜计数（icon 格 + 数字文本）。"""

    def render(self, img, f, nectar, rect):
        _panel_bg(img, rect)
        f.draw_text(img, (rect.x + 10, rect.y + 4), f"花蜜 {nectar}")


class TitleBar:
    """顶部关卡名。"""

    def render(self, img, f, title, rect):
        w = f.text_width(title)
        f.draw_text(img, (rect.x + (rect.w - w) // 2, rect.y + 4), title)


class BuyBar:
    """底部买兵栏: [(单位名, 价, enabled)] 等分按钮。"""

    def render(self, img, f, items, rect):
        cols = Panel(rect.x, rect.y, rect.w, rect.h).columns(max(1, len(items)))
        d = ImageDraw.Draw(img)
        for col, (name, price, enabled) in zip(cols, items):
            bg = (30, 40, 30, 200) if enabled else (24, 24, 24, 90)
            d.rectangle([col.x, col.y, col.x + col.w, col.y + col.h],
                        fill=bg, outline=(160, 200, 160, 200) if enabled
                        else (90, 90, 90, 120), width=2)
            label = f"{name} {price}"
            f.draw_text(img, (col.x + 8, col.y + 16), label)


class HintText:
    """提示文字（多行, 逐行绘制）。"""

    def render(self, img, f, text, rect):
        _panel_bg(img, rect, color=(16, 16, 28, 170))
        f.draw_text(img, (rect.x + 10, rect.y + 6), text)
