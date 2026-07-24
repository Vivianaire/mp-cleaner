"""Squarified treemap 控件:按字节大小铺满矩形,按目录「类别」着色,点击发路径。

算法:Bruls/Huijsen/van Wijk 的 squarify(尽量让各格接近正方形)。
"""
from __future__ import annotations

from math import inf

from PyQt6 import QtCore, QtGui, QtWidgets

# 顶层目录按类别配色
_KIND_COLORS = {
    "应用": "#3b82f6",
    "媒体": "#10b981",
    "下载": "#f59e0b",
    "文档": "#64748b",
    "隐藏": "#94a3b8",
    "其他": "#0ea5e9",
}
_MEDIA_NAMES = {"DCIM", "Pictures", "Music", "Movies", "Video", "Videos", "Recordings", "Photo"}
_DOC_NAMES = {"Documents", "Doc", "Docs", "My Documents", "Books"}


def _kind_of(name: str) -> str:
    if name.startswith("."):
        return "隐藏"
    if name == "Android":
        return "应用"
    if name in _MEDIA_NAMES:
        return "媒体"
    if name == "Download" or name == "Downloads":
        return "下载"
    if name in _DOC_NAMES:
        return "文档"
    return "其他"


# --- squarify 算法 ---
def _worst(row: list[float], length: float) -> float:
    if not row:
        return inf
    s = sum(row)
    rmax, rmin = max(row), min(row)
    if s <= 0 or rmin <= 0:
        return inf
    return max(length * length * rmax / (s * s), (s * s) / (length * length * rmin))


def _layout_row(row, x, y, dx, dy, out):
    s = sum(row)
    if s <= 0:
        return out, x, y, dx, dy
    if dx >= dy:
        w_s = s / dy
        oy = y
        for v in row:
            h = (v / s) * dy
            out.append((x, oy, w_s, h))
            oy += h
        return out, x + w_s, y, dx - w_s, dy
    h_s = s / dx
    ox = x
    for v in row:
        w = (v / s) * dx
        out.append((ox, y, w, h_s))
        ox += w
    return out, x, y + h_s, dx, dy - h_s


def squarify(values, x, y, dx, dy):
    """values 降序;归一化到面积 dx*dy;返回 [(rx,ry,rw,rh), ...] 同序。"""
    total = sum(values)
    if total <= 0 or dx <= 0 or dy <= 0:
        return []
    scale = dx * dy / total
    vals = [v * scale for v in values]
    out: list[tuple[float, float, float, float]] = []
    cx, cy, cdx, cdy = x, y, dx, dy
    while vals:
        length = min(cdx, cdy)
        row = [vals[0]]
        i = 1
        while i < len(vals):
            cur = _worst(row, length)
            cand = _worst(row + [vals[i]], length)
            if cand < cur:
                row.append(vals[i])
                i += 1
            else:
                break
        vals = vals[i:]
        out, cx, cy, cdx, cdy = _layout_row(row, cx, cy, cdx, cdy, out)
    return out


class TreeMap(QtWidgets.QWidget):
    """占用量 treemap。items = [(名称, 字节数, 完整路径), ...]。"""

    pathClicked = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(260)
        self._entries: list[tuple[str, int, str, str]] = []   # name,bytes,path,color
        self._rects: list[tuple[float, float, float, float]] = []
        self._hover = -1

    def set_items(self, items: list[tuple[str, int, str]]) -> None:
        items = [(n, b, p) for (n, b, p) in items if b > 0]
        items.sort(key=lambda t: -t[1])
        self._entries = [(n, b, p, _KIND_COLORS[_kind_of(n)]) for (n, b, p) in items]
        self._recompute()
        self.update()

    def _recompute(self) -> None:
        if not self._entries:
            self._rects = []
            return
        w = max(1, self.width())
        h = max(1, self.height())
        vals = [b for _, b, _, _ in self._entries]
        self._rects = squarify(vals, 0, 0, w, h)

    def resizeEvent(self, _e) -> None:
        self._recompute()

    def paintEvent(self, _e) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor("#ffffff"))
        if not self._rects:
            p.setPen(QtGui.QColor("#aaa"))
            p.drawText(self.rect(), int(QtCore.Qt.AlignmentFlag.AlignCenter), "扫描后展示占用 treemap")
            p.end()
            return
        fm = p.fontMetrics()
        for (rx, ry, rw, rh), (name, bytes_, _path, color) in zip(self._rects, self._entries):
            rect = QtCore.QRectF(rx + 1, ry + 1, rw - 2, rh - 2)
            p.setPen(QtCore.QPen(QtGui.QColor("#ffffff"), 1))
            p.setBrush(QtGui.QColor(color))
            p.drawRoundedRect(rect, 3, 3)
            if rw > 54 and rh > 26:
                p.setPen(QtGui.QColor("#ffffff"))
                from ...utils import human_size
                label = f"{name}\n{human_size(bytes_)}"
                p.drawText(rect.adjusted(5, 4, -5, -4),
                           int(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft),
                           label)
        p.end()

    def mouseMoveEvent(self, e) -> None:
        idx = self._hit(e.position().x(), e.position().y())
        if idx != self._hover:
            self._hover = idx
            self.update()

    def mousePressEvent(self, e) -> None:
        idx = self._hit(e.position().x(), e.position().y())
        if 0 <= idx < len(self._entries):
            self.pathClicked.emit(self._entries[idx][2])

    def _hit(self, x: float, y: float) -> int:
        for i, (rx, ry, rw, rh) in enumerate(self._rects):
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                return i
        return -1
