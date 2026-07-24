"""仪表盘视图:存储用量 + treemap + 类型圆环 + 最大文件 + 应用占用 + 洞察。

配色全部走 theme(状态色/分类色/墨色),主题切换经 refresh_theme 重设 insights。
"""
from __future__ import annotations

import heapq

from PyQt6 import QtCore, QtGui, QtWidgets

from ...core.filetypes import TYPE_LABELS, file_type
from ...utils import human_size
from .. import theme
from ..widgets.donut import DonutChart
from ..widgets.treemap import TreeMap

# 文件类型 → theme.categorical 索引(image=绿/video=蓝/audio=紫/doc=橙/apk=黄/archive=红/other=品红)
_TYPE_SLOT = {"image": 5, "video": 0, "audio": 6, "doc": 1, "apk": 3, "archive": 7, "other": 4}


class StorageBar(QtWidgets.QWidget):
    """总/已用/可用 + 用量色条(状态色:绿/黄/红)。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._total = self._used = self._avail = 0
        self.setFixedHeight(46)

    def set_storage(self, storage) -> None:
        if storage:
            self._total, self._used, self._avail = storage
        self.update()

    def paintEvent(self, _e) -> None:
        t = theme.current()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if self._total <= 0:
            p.setPen(QtGui.QColor(t.ink_muted))
            p.drawText(self.rect(), int(QtCore.Qt.AlignmentFlag.AlignCenter), "存储信息不可用")
            p.end()
            return
        pct = self._used * 100 / self._total
        color = t.good if pct < 70 else (t.warning if pct < 90 else t.critical)
        p.setPen(QtGui.QColor(t.ink_primary))
        p.drawText(QtCore.QRect(0, 0, w, 18),
                   int(QtCore.Qt.AlignmentFlag.AlignLeft),
                   f"存储:{human_size(self._used)} / {human_size(self._total)}"
                   f"  ({pct:.0f}%)  ·  可用 {human_size(self._avail)}")
        by, bh = 22, 14
        p.setBrush(QtGui.QColor(t.hairline))
        p.setPen(QtGui.QPen(QtGui.QColor(t.border), 1))
        p.drawRoundedRect(QtCore.QRectF(0, by, w, bh), 7, 7)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(color))
        p.drawRoundedRect(QtCore.QRectF(0, by, w * self._used / self._total, bh), 7, 7)
        p.end()


class DashboardView(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._insights_html = ""
        self._build()

    def _build(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)

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
        # 应用占用(diskstats,含私有数据;闲置态来自 am get-inactive)
        agrp = QtWidgets.QGroupBox("应用占用 Top(⏸ = 系统判为长期未用)")
        al = QtWidgets.QVBoxLayout(agrp)
        self.app_list = QtWidgets.QListWidget()
        self.app_list.setStyleSheet("font-family: monospace;")
        al.addWidget(self.app_list)
        right.addWidget(agrp, 1)
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
        outer.addWidget(self.insights)

    def _insights_css(self) -> str:
        t = theme.current()
        return (
            f"body {{ font-size:13px; color:{t.ink_primary}; }}"
            f" .h {{ font-weight:600; color:{t.primary}; }}"
        )

    def set_data(self, trie, storage, junk_items) -> None:
        self.storage_bar.set_storage(storage)
        top = trie.top_level()
        prefix = trie.prefix
        self.treemap.set_items([(name, total, f"{prefix}/{name}") for name, total in top])

        cat = theme.current().categorical
        type_sizes: dict[str, int] = {}
        largest: list[tuple[int, str]] = []
        for path, size, _mtime, is_file in trie.iter_nodes():
            if not is_file or size <= 0:
                continue
            ft = file_type(path)
            type_sizes[ft] = type_sizes.get(ft, 0) + size
            largest.append((size, path))
        donut_items = [
            (TYPE_LABELS.get(ft, ft), type_sizes.get(ft, 0), cat[_TYPE_SLOT.get(ft, 4)])
            for ft in TYPE_LABELS
            if type_sizes.get(ft, 0) > 0
        ]
        self.type_donut.set_items(donut_items)

        top_largest = heapq.nlargest(12, largest)      # 只取前 12,免全量排序
        self.largest.clear()
        for size, path in top_largest:
            self.largest.addItem(f"{human_size(size):>10}   {path}")
        self._insights_html = self._insights(trie, storage, junk_items, top, type_sizes, top_largest)
        self.insights.document().setDefaultStyleSheet(self._insights_css())
        self.insights.setHtml(self._insights_html)

    def set_app_usage(self, apps) -> None:
        """填充「应用占用 Top」列表。apps: list[AppUsage](已按 total 降序)。"""
        self.app_list.clear()
        if not apps:
            self.app_list.addItem("(diskstats 不可用或无数据)")
            return
        for a in apps:
            flag = "⏸" if a.idle is True else ("▶" if a.idle is False else " ")
            self.app_list.addItem(f"{flag} {human_size(a.total):>10}   {a.pkg}")

    def refresh_theme(self) -> None:
        """主题切换:重设 insights 文档 CSS(墨色/主色)并重渲染。"""
        self.insights.document().setDefaultStyleSheet(self._insights_css())
        if self._insights_html:
            self.insights.setHtml(self._insights_html)

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
            ft = max(type_sizes, key=type_sizes.get)
            share = type_sizes[ft] * 100 / trie.total_bytes if trie.total_bytes else 0
            bullets.append(
                f"文件类型 <b>{TYPE_LABELS.get(ft, ft)}</b> 占比最高"
                f"({human_size(type_sizes[ft])},{share:.0f}%)"
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
