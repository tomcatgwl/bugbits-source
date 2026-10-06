"""HUD 布局层（cPanel/ciImagePanel 对齐）: 面板几何与等分。"""


class Panel:
    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h

    def columns(self, n, margin=8):
        """n 等分列（水平），各列间 margin。返回 [Panel]。"""
        inner = self.w - margin * (n + 1)
        cw = inner // n
        return [Panel(self.x + margin + i * (cw + margin),
                      self.y + margin, cw, self.h - 2 * margin)
                for i in range(n)]
