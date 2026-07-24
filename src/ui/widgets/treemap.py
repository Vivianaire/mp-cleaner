"""Squarified treemap 控件:按字节大小铺满矩形,按目录「类别」着色,点击发路径。

算法:Bruls/Huijsen/van Wijk 的 squarify(尽量让各格接近正方形)。
配色:类别映射到 ``theme.categorical``(Google 四色基的 CVD 安全色板),主题切换时
paint 自动重读当前令牌,无需重建数据。
"""
from __future__ import annotations

from math import inf

from PyQt6 import QtCore, QtGui, QtWidgets

from .. import theme

_MEDIA_NAMES = {"DCIM", "Pictures", "Music", "Movies", "Video", "Videos", "Recordings", "Photo"}
_DOC_NAMES = {"Documents", "Doc", "Docs", "My Documents", "Books"}


def _kind_of(name: str) -> str:
    if name.startswith("."):
        return "隐藏"
    if name == "Android":
        return "应用"
    if name in _MEDIA_NAMES:
        return "媒体"
    if name in ("Download", "Downloads"):
        return "下载"
    if name in _DOC_NAMES:
        return "文档"
    return "其他"


# 类别 → theme.categorical 索引(应用=蓝 / 媒体=绿 / 下载=黄 / 文档=橙 / 其他=aqua);
# 「隐藏」用中性灰(ink_muted),语义上该退后。
_KIND_SLOT = {"应用": 0, "媒体": 5, "下载": 3, "文档": 1, "其他": 2, "隐藏": "muted"}


def _kind_color(kind: str) -> str:
    t = theme.current()
    slot = _KIND_SLOT.get(kind, 2)
    return t.ink_muted if slot == "muted" else t.categorical[slot]


def _on_color(bg_hex: str) -> str:
    """在该背景色上可读的文字色(浅块用主墨色,深块用白)。"""
    return theme.current().ink_primary if QtGui.QColor(bg_hex).lightness() >= 145 else "#FFFFFF"


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
        self.setMouseTracking(True)          # 无需按键即响应悬停
        self._entries: list[tuple[str, int, str, str]] = []   # name, bytes, path, kind
        self._rects: list[tuple[float, float, float, float]] = []
        self._hover = -1

    def set_items(self, items: list[tuple[str, int, str]]) -> None:
        items = [(n, b, p) for (n, b, p) in items if b > 0]
        items.sort(key=lambda t: -t[1])
        self._entries = [(n, b, p, _kind_of(n)) for (n, b, p) in items]
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
        t = theme.current()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor(t.chart_bg))
        if not self._rects:
            p.setPen(QtGui.QColor(t.ink_muted))
            p.drawText(self.rect(), int(QtCore.Qt.AlignmentFlag.AlignCenter), "扫描后展示占用 treemap")
            p.end()
            return
        for i, ((rx, ry, rw, rh), (name, bytes_, _path, kind)) in enumerate(
            zip(self._rects, self._entries)
        ):
            rect = QtCore.QRectF(rx + 1, ry + 1, rw - 2, rh - 2)
            if i == self._hover:
                p.setPen(QtGui.QPen(QtGui.QColor(t.ink_primary), 2))
            else:
                p.setPen(QtGui.QPen(QtGui.QColor(t.chart_bg), 1))
            c = QtGui.QColor(_kind_color(kind))
            if i == self._hover:
                c = c.lighter(112)
            p.setBrush(c)
            p.drawRoundedRect(rect, 4, 4)
            if rw > 54 and rh > 26:
                from ...utils import human_size
                p.setPen(QtGui.QColor(_on_color(_kind_color(kind))))
                label = f"{name}\n{human_size(bytes_)}"
                p.drawText(rect.adjusted(6, 5, -5, -4),
                           int(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft),
                           label)
        p.end()

    def mouseMoveEvent(self, e) -> None:
        idx = self._hit(e.position().x(), e.position().y())
        if idx != self._hover:
            self._hover = idx
            if 0 <= idx < len(self._entries):
                from ...utils import human_size
                name, bytes_, path, _kind = self._entries[idx]
                self.setToolTip(f"{name} — {human_size(bytes_)}\n{path}")
            else:
                self.setToolTip("")
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
