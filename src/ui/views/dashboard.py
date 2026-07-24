"""仪表盘视图:存储用量 + treemap + 类型圆环 + 最大文件 + 洞察。"""
from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from ...core.filetypes import TYPE_COLORS, TYPE_LABELS, file_type
from ...utils import human_size
from ..widgets.donut import DonutChart
from ..widgets.treemap import TreeMap


class StorageBar(QtWidgets.QWidget):
    """总/已用/可用 + 用量色条。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._total = self._used = self._avail = 0
        self.setFixedHeight(46)

    def set_storage(self, storage) -> None:
        if storage:
            self._total, self._used, self._avail = storage
        self.update()

    def paintEvent(self, _e) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if self._total <= 0:
            p.setPen(QtGui.QColor("#999"))
            p.drawText(self.rect(), int(QtCore.Qt.AlignmentFlag.AlignCenter), "存储信息不可用")
            return
        pct = self._used * 100 / self._total
        color = "#10b981" if pct < 70 else ("#f59e0b" if pct < 90 else "#ef4444")
        p.setPen(QtGui.QColor("#444"))
        p.drawText(QtCore.QRect(0, 0, w, 18),
                   int(QtCore.Qt.AlignmentFlag.AlignLeft),
                   f"存储:{human_size(self._used)} / {human_size(self._total)}"
                   f"  ({pct:.0f}%)  ·  可用 {human_size(self._avail)}")
        by, bh = 22, 14
        p.setBrush(QtGui.QColor("#f1f5f9"))
        p.setPen(QtCore.QPen(QtGui.QColor("#e5e7eb"), 1))
        p.drawRoundedRect(QtCore.QRectF(0, by, w, bh), 7, 7)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(color))
        p.drawRoundedRect(QtCore.QRectF(0, by, w * self._used / self._total, bh), 7, 7)
        p.end()


class DashboardView(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)

        self.storage_bar = StorageBar()
        outer.addWidget(self.storage_bar)

        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel("占用 treemap(点击格子在「空间浏览」定位)"))
        self.treemap = TreeMap()
        left.addWidget(self.treemap, 1)
        left_w = QtWidgets.QWidget()
        left_w.setLayout(left)
        right = QtWidgets.QVBoxLayout()
        self.type_donut = DonutChart("按文件类型")
        right.addWidget(self.type_donut)
        grp = QtWidgets.QGroupBox("最大文件")
        gl = QtWidgets.QVBoxLayout(grp)
        self.largest = QtWidgets.QListWidget()
        self.largest.setStyleSheet("font-family: monospace;")
        gl.addWidget(self.largest)
        right.addWidget(grp, 1)
        right_w = QtWidgets.QWidget()
        right_w.setLayout(right)
        split.addWidget(left_w)
        split.addWidget(right_w)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        outer.addWidget(split, 1)

        self.insights = QtWidgets.QTextEdit()
        self.insights.setReadOnly(True)
        self.insights.setMaximumHeight(120)
        self.insights.document().setDefaultStyleSheet(
            "body{font-size:13px;} .h{font-weight:600;color:#1e3a8a;}"
        )
        outer.addWidget(self.insights)

    def set_data(self, trie, storage, junk_items) -> None:
        self.storage_bar.set_storage(storage)
        top = trie.top_level()
        prefix = trie.prefix
        self.treemap.set_items([(name, total, f"{prefix}/{name}") for name, total in top])

        type_sizes: dict[str, int] = {}
        largest: list[tuple[int, str]] = []
        for path, size, _mtime, is_file in trie.iter_nodes():
            if not is_file or size <= 0:
                continue
            t = file_type(path)
            type_sizes[t] = type_sizes.get(t, 0) + size
            largest.append((size, path))
        donut_items = [
            (TYPE_LABELS.get(t, t), type_sizes.get(t, 0), TYPE_COLORS.get(t, "#cbd5e1"))
            for t in TYPE_LABELS
            if type_sizes.get(t, 0) > 0
        ]
        self.type_donut.set_items(donut_items)

        largest.sort(reverse=True)
        self.largest.clear()
        for size, path in largest[:12]:
            self.largest.addItem(f"{human_size(size):>10}   {path}")
        self.insights.setHtml(self._insights(trie, storage, junk_items, top, type_sizes, largest))

    def _insights(self, trie, storage, junk_items, top, type_sizes, largest) -> str:
        bullets = []
        if storage:
            total, used, avail = storage
            pct = used * 100 / total if total else 0
            bullets.append(
                f"设备存储已用 <b>{pct:.0f}%</b>({human_size(used)}/{human_size(total)}),"
                f"可用 {human_size(avail)}"
            )
        if top:
            name, tbytes = top[0]
            share = tbytes * 100 / trie.total_bytes if trie.total_bytes else 0
            bullets.append(f"最大目录 <b>{name}</b> 占 {share:.0f}%({human_size(tbytes)})")
        if type_sizes:
            t = max(type_sizes, key=type_sizes.get)
            share = type_sizes[t] * 100 / trie.total_bytes if trie.total_bytes else 0
            bullets.append(
                f"文件类型 <b>{TYPE_LABELS.get(t, t)}</b> 占比最高"
                f"({human_size(type_sizes[t])},{share:.0f}%)"
            )
        safe = [it for it in junk_items if it.risk == "安全"]
        if safe:
            bullets.append(
                f"可安全清理约 <b>{human_size(sum(i.size for i in safe))}</b>"
                f"(默认勾选 {len(safe)} 项)"
            )
        residue = [it for it in junk_items if it.category == "已卸载残留"]
        if residue:
            bullets.append(f"发现 {len(residue)} 个已卸载应用残留")
        if largest:
            bullets.append(
                f"最大文件 {human_size(largest[0][0])}:"
                f"{largest[0][1].rsplit('/', 1)[-1]}"
            )
        body = "<br>".join(f"· {b}" for b in bullets) if bullets else "扫描后展示洞察"
        return f"<div class='h'>存储洞察</div><div style='margin-top:4px'>{body}</div>"
