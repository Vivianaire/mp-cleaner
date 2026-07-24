"""圆环图控件:items = [(标签, 数值, 颜色), ...]。扇区色由调用方传入(文件类型色板),
其余结构色(背景镂空/文字/图例)随主题。"""
from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from .. import theme


class DonutChart(QtWidgets.QWidget):
    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self._title = title
        self._items: list[tuple[str, int, str]] = []
        self.setMinimumHeight(180)

    def set_items(self, items: list[tuple[str, int, str]]) -> None:
        self._items = [(l, v, c) for (l, v, c) in items if v > 0]
        self.update()

    def paintEvent(self, _e) -> None:
        t = theme.current()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        # 左侧圆环
        side = min(w * 0.55, h - 8)
        cx, cy, r_out, r_in = side / 2 + 6, h / 2, side / 2 - 4, side / 2 - 18
        total = sum(v for _, v, _ in self._items)
        if total <= 0:
            p.setPen(QtGui.QColor(t.ink_muted))
            p.drawText(self.rect(), int(QtCore.Qt.AlignmentFlag.AlignCenter),
                       f"{self._title}\n(无数据)")
            p.end()
            return
        start = 90.0
        for label, val, color in self._items:
            span = val * 360.0 / total
            rect = QtCore.QRectF(cx - r_out, cy - r_out, r_out * 2, r_out * 2)
            p.setBrush(QtGui.QColor(color))
            p.setPen(QtGui.QPen(QtGui.QColor(t.chart_bg), 1))
            # PyQt span: negative = clockwise, angles in 1/16 degree
            p.drawPie(rect, int(start * 16), int(-span * 16))
            start -= span
        # 中心镂空
        p.setBrush(QtGui.QBrush(QtGui.QColor(t.chart_bg)))
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.drawEllipse(QtCore.QPointF(cx, cy), r_in, r_in)
        # 中心总量文字
        p.setPen(QtGui.QColor(t.ink_primary))
        from ...utils import human_size
        p.drawText(QtCore.QRectF(cx - r_in, cy - 12, r_in * 2, 24),
                   int(QtCore.Qt.AlignmentFlag.AlignCenter), human_size(total))
        # 右侧图例
        lx = side + 18
        ly = 8
        p.setFont(self.font())
        for label, val, color in self._items[:9]:
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(color))
            p.drawRoundedRect(QtCore.QRectF(lx, ly + 2, 10, 10), 3, 3)
            p.setPen(QtGui.QColor(t.ink_primary))
            pct = val * 100 / total
            p.drawText(QtCore.QRectF(lx + 16, ly, w - lx - 16, 16),
                       int(QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft),
                       f"{label}  {human_size(val)} ({pct:.0f}%)")
            ly += 18
        p.end()
