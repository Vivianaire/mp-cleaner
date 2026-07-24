"""顶层目录占用图:自绘横向条形(标签清晰、零第三方依赖怪癖)。

用 QPainter 画水平占比条,顶部 N 项 + 「其他」聚合,颜色用克制的中性色 +
单一强调色。全项目图表(treemap/donut/占用条/趋势线)均为手绘,无第三方图库。
"""
from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from ...utils import human_size

_TOPN = 12
# 强调色渐变:从深到浅,突出前几项
_PALETTE = [
    "#3b82f6", "#60a5fa", "#93c5fd", "#bfdbfe",
    "#cbd5e1", "#cbd5e1", "#cbd5e1", "#cbd5e1",
    "#e2e8f0", "#e2e8f0", "#e2e8f0", "#e2e8f0",
    "#94a3b8",  # 「其他」
]


class ChartPanel(QtWidgets.QWidget):
    """展示 [(名称, 字节数)] 的横向占比条形。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[tuple[str, int]] = []
        self._total: int = 0

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        title = QtWidgets.QLabel("占用分布(顶层目录)")
        title.setStyleSheet("font-weight:600;")
        lay.addWidget(title)

        self.canvas = _BarCanvas(self)
        lay.addWidget(self.canvas, 1)

        self.summary = QtWidgets.QLabel("扫描后展示")
        self.summary.setStyleSheet("color:#888;")
        lay.addWidget(self.summary)

    def set_breakdown(self, items: list[tuple[str, int]]) -> None:
        """items = [(目录名, 字节数), ...],按需截取 topN + 其他。"""
        self._total = sum(b for _, b in items)
        top = items[:_TOPN]
        rest = sum(b for _, b in items[_TOPN:])
        rows = [(n, b) for n, b in top]
        if rest > 0:
            rows.append((f"其他({len(items) - _TOPN})", rest))
        self._items = rows
        self.canvas.set_rows(rows, self._total)
        self.summary.setText(
            f"顶层共 {len(items)} 项,合计 {human_size(self._total)}"
            if items
            else "扫描后展示"
        )


class _BarCanvas(QtWidgets.QWidget):
    """自绘横向条形。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple[str, int]] = []
        self._total: int = 0
        self.setMinimumHeight(120)

    def set_rows(self, rows: list[tuple[str, int]], total: int) -> None:
        self._rows = rows
        self._total = total or 1
        self.update()

    def sizeHint(self) -> QtCore.QSize:
        h = max(120, 26 * len(self._rows) + 8)
        return QtCore.QSize(360, h)

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        if not self._rows:
            p.end()
            return
        w = self.width()
        name_w = 150
        size_w = 80
        bar_left = name_w + 8
        bar_right = w - size_w - 16
        bar_max = max(40, bar_right - bar_left)
        row_h = 26
        y = 4
        for i, (name, b) in enumerate(self._rows):
            color = _PALETTE[i % len(_PALETTE)]
            frac = b / self._total
            # 名称
            p.setPen(QtGui.QColor("#222"))
            p.drawText(QtCore.QRect(4, y, name_w, row_h),
                       int(QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft),
                       _elide(name, name_w - 4, p.fontMetrics()))
            # 条
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor("#f1f5f9"))
            p.drawRoundedRect(QtCore.QRect(bar_left, y + 5, bar_max, 12), 6, 6)
            p.setBrush(QtGui.QColor(color))
            bw = max(2, int(bar_max * frac))
            p.drawRoundedRect(QtCore.QRect(bar_left, y + 5, bw, 12), 6, 6)
            # 百分比(条内)
            pct = f"{frac * 100:.1f}%"
            p.setPen(QtGui.QColor("#fff") if bw > 44 else QtGui.QColor("#666"))
            tx = bar_left + 6 if bw > 44 else bar_left + bw + 4
            p.drawText(QtCore.QRect(tx, y, bw if bw > 44 else bar_max, row_h),
                       int(QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft),
                       pct)
            # 大小
            p.setPen(QtGui.QColor("#666"))
            p.drawText(QtCore.QRect(bar_right + 6, y, size_w, row_h),
                       int(QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignRight),
                       human_size(b))
            y += row_h
        p.end()


def _elide(text: str, width: int, fm: QtGui.QFontMetrics) -> str:
    return fm.elidedText(text, QtCore.Qt.TextElideMode.ElideRight, width)
