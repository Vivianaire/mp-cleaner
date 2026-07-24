"""垃圾分类面板:按类别列出可清理项,带勾选与可回收空间汇总。

用 QTreeWidget:顶层 = 类别(三态勾选),子项 = 单个垃圾目标。
- 类别勾选 = 整类清理(含未显示的尾部项);
- 部分勾选时按子项逐条计。
安全类别默认勾选,中等类别默认不勾。配色走 theme,主题切换经 refresh_theme 重设 item 色。
"""
from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from ...classifier import CATEGORY_ORDER, DEFAULT_CHECK, JunkItem
from ...utils import human_size
from .. import theme

_DISPLAY_CAP = 500        # 每类最多展示条数(整类清理不受此限)


class JunkPanel(QtWidgets.QWidget):
    selectionChanged = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items_by_cat: dict[str, list[JunkItem]] = {}
        self._guard = False

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("可清理项")
        title.setObjectName("title")
        self.reclaim_lbl = QtWidgets.QLabel("已勾选可回收:—")
        self.reclaim_lbl.setObjectName("value-good")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.reclaim_lbl)
        lay.addLayout(head)

        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("🔍 过滤路径/文件名(不影响整类勾选清理)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        lay.addWidget(self.search)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["项", "路径", "大小", "风险"])
        self.tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setRootIsDecorated(True)
        self.tree.setWordWrap(False)
        self.tree.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.tree, 1)

        self.hint = QtWidgets.QLabel("扫描后在此分类列出垃圾文件。")
        self.hint.setObjectName("muted")
        lay.addWidget(self.hint)

    # --- 入口 ---
    def set_items(self, items: list[JunkItem]) -> None:
        self._guard = True
        self.tree.clear()
        self._items_by_cat = {}
        for it in items:
            self._items_by_cat.setdefault(it.category, []).append(it)

        t = theme.current()
        shown = False
        for cat in CATEGORY_ORDER:
            its = self._items_by_cat.get(cat)
            if not its:
                continue
            shown = True
            its_sorted = sorted(its, key=lambda i: -i.size)
            total = sum(i.size for i in its_sorted)
            checked = DEFAULT_CHECK[cat]

            g = QtWidgets.QTreeWidgetItem(
                [f"{cat}   ·   {len(its_sorted)} 项   ·   共 {human_size(total)}", "", "", ""]
            )
            g.setData(0, QtCore.Qt.ItemDataRole.UserRole, cat)
            g.setForeground(0, QtGui.QColor(t.primary))
            f = g.font(0); f.setBold(True); g.setFont(0, f)
            g.setFlags(
                g.flags()
                | QtCore.Qt.ItemFlag.ItemIsAutoTristate
                | QtCore.Qt.ItemFlag.ItemIsUserCheckable
            )
            g.setCheckState(0, QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked)

            for it in its_sorted[:_DISPLAY_CAP]:
                c = QtWidgets.QTreeWidgetItem(
                    [it.node.name, it.path, human_size(it.size), it.risk]
                )
                c.setFlags(c.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                c.setCheckState(0, QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked)
                c.setData(0, QtCore.Qt.ItemDataRole.UserRole, it)
                if it.risk == "中等":
                    c.setForeground(3, QtGui.QColor(t.on_warning))
                g.addChild(c)

            if len(its_sorted) > _DISPLAY_CAP:
                more = QtWidgets.QTreeWidgetItem(
                    [f"…还有 {len(its_sorted) - _DISPLAY_CAP} 项(随类别勾选一并处理)", "", "", ""]
                )
                more.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
                more.setForeground(0, QtGui.QColor(t.ink_muted))
                g.addChild(more)

            self.tree.addTopLevelItem(g)
            self.tree.expandItem(g)

        self.hint.setVisible(not shown)
        if shown:
            self.hint.setText("")
        self._guard = False
        self._update_reclaimable()
        if self.search.text().strip():
            self._apply_filter(self.search.text())

    def refresh_theme(self) -> None:
        """主题切换:重设 QTreeWidgetItem 前景色(分类标题/中等风险/占位)。"""
        t = theme.current()
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            g.setForeground(0, QtGui.QColor(t.primary))
            for j in range(g.childCount()):
                c = g.child(j)
                it = c.data(0, QtCore.Qt.ItemDataRole.UserRole)
                if it is None:
                    c.setForeground(0, QtGui.QColor(t.ink_muted))
                elif it.risk == "中等":
                    c.setForeground(3, QtGui.QColor(t.on_warning))

    # --- 选择 ---
    def checked_items(self) -> list[JunkItem]:
        """整类勾选取该类全部项(含未显示);部分勾选按子项。"""
        result: list[JunkItem] = []
        seen: set[int] = set()
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            cat = g.data(0, QtCore.Qt.ItemDataRole.UserRole)
            state = g.checkState(0)
            if state == QtCore.Qt.CheckState.Checked:
                for it in self._items_by_cat.get(cat, []):
                    if id(it.node) not in seen:
                        seen.add(id(it.node))
                        result.append(it)
            else:
                for j in range(g.childCount()):
                    c = g.child(j)
                    if c.checkState(0) != QtCore.Qt.CheckState.Checked:
                        continue
                    it = c.data(0, QtCore.Qt.ItemDataRole.UserRole)
                    if it is not None and id(it.node) not in seen:
                        seen.add(id(it.node))
                        result.append(it)
        return result

    def _on_item_changed(self, _item, _col) -> None:
        if self._guard:
            return
        self._update_reclaimable()
        self.selectionChanged.emit()

    def _apply_filter(self, text: str) -> None:
        """按输入过滤显示的子项;整类勾选逻辑不受影响(仍按类别清理全量)。"""
        q = (text or "").strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            any_visible = False
            for j in range(g.childCount()):
                c = g.child(j)
                it = c.data(0, QtCore.Qt.ItemDataRole.UserRole)
                if it is None:                       # “还有 N 项” 占位行
                    c.setHidden(bool(q))
                    continue
                hit = (not q) or q in it.path.lower() or q in it.node.name.lower()
                c.setHidden(not hit)
                any_visible = any_visible or hit
            g.setHidden(bool(q) and not any_visible)

    def _update_reclaimable(self) -> None:
        total = sum(it.size for it in self.checked_items())
        self.reclaim_lbl.setText(f"已勾选可回收:{human_size(total)}")
