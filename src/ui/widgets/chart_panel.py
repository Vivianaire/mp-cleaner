"""顶层目录占用图:自绘横向条形(标签清晰、零第三方依赖)。

配色随主题:top 占用用 sequential blue 深阶(突出前几项),其余用中性灰。
全项目图表(treemap/donut/占用条/趋势线)均为手绘 QPainter,无第三方图库。
"""
from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from ...utils import human_size
from .. import theme

_TOPN = 12


class ChartPanel(QtWidgets.QWidget):
    """展示 [(名称, 字节数)] 的横向占比条形。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[tuple[str, int]] = []
        self._total: int = 0

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        title = QtWidgets.QLabel("占用分布(顶层目录)")
        title.setObjectName("title")
        lay.addWidget(title)

        self.canvas = _BarCanvas(self)
        lay.addWidget(self.canvas, 1)

        self.summary = QtWidgets.QLabel("扫描后展示")
        self.summary.setObjectName("muted")
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
        t = theme.current()
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
        seq = t.sequential
        for i, (name, b) in enumerate(self._rows):
            is_other = name.startswith("其他")
            color = seq[6 - i] if (i < 4 and not is_other) else t.ink_muted
            frac = b / self._total
            # 名称
            p.setPen(QtGui.QColor(t.ink_primary))
            p.drawText(QtCore.QRect(4, y, name_w, row_h),
                       int(QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft),
                       _elide(name, name_w - 4, p.fontMetrics()))
            # 条轨道
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(t.hairline))
            p.drawRoundedRect(QtCore.QRect(bar_left, y + 5, bar_max, 12), 6, 6)
            # 数值条
            p.setBrush(QtGui.QColor(color))
            bw = max(2, int(bar_max * frac))
            p.drawRoundedRect(QtCore.QRect(bar_left, y + 5, bw, 12), 6, 6)
            # 百分比(条内深底白字 / 条外用次墨色)
            pct = f"{frac * 100:.1f}%"
            if bw > 44:
                on_dark = QtGui.QColor(color).lightness() < 140
                p.setPen(QtGui.QColor("#FFFFFF" if on_dark else t.ink_primary))
                tx = bar_left + 6
                tw = bw
            else:
                p.setPen(QtGui.QColor(t.ink_secondary))
                tx = bar_left + bw + 4
                tw = bar_max
            p.drawText(QtCore.QRect(tx, y, tw, row_h),
                       int(QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft),
                       pct)
            # 大小
            p.setPen(QtGui.QColor(t.ink_secondary))
            p.drawText(QtCore.QRect(bar_right + 6, y, size_w, row_h),
                       int(QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignRight),
                       human_size(b))
            y += row_h
        p.end()


def _elide(text: str, width: int, fm: QtGui.QFontMetrics) -> str:
    return fm.elidedText(text, QtCore.Qt.TextElideMode.ElideRight, width)
