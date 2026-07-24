"""FileTrie 之上的 Qt 树模型(QAbstractItemModel)。

支持流式增量刷新:主线程按批把记录塞进 trie 后,经节流的 ``refresh()``
(bump 代号 + reset)让视图重读。排序缓存按代号失效,惰性重算可见节点。

树用于**浏览**;清理勾选在 JunkPanel(M4),故本模型只读。
"""
from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from ..utils import human_size
from .trie import FileTrie, Node


class TreeModel(QtCore.QAbstractItemModel):
    HEADERS = ["名称", "大小", "占比", "类型", "风险"]

    def __init__(self, trie: FileTrie, parent=None):
        super().__init__(parent)
        self.trie = trie
        self.root = trie.root
        self._gen = 0
        style = QtWidgets.QApplication.style()
        self._folder_icon = style.standardIcon(
            QtWidgets.QStyle.StandardPixmap.SP_DirIcon
        )
        self._file_icon = style.standardIcon(
            QtWidgets.QStyle.StandardPixmap.SP_FileIcon
        )

    # --- 增量刷新 ---
    def refresh(self) -> None:
        """bump 代号(失效所有排序缓存)+ reset 视图。节流调用。"""
        self._gen += 1
        self.beginResetModel()
        self.endResetModel()

    def _sorted_children(self, node: Node) -> list[Node]:
        s = node._sorted
        if s is None or node._sorted_gen != self._gen:
            ch = node.children or {}
            s = sorted(ch.values(), key=lambda n: (-n.total, n.name))
            node._sorted = s
            node._sorted_gen = self._gen
        return s

    # --- 模型接口 ---
    def index(
        self, row: int, column: int, parent: QtCore.QModelIndex = QtCore.QModelIndex()
    ) -> QtCore.QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QtCore.QModelIndex()
        pnode: Node = parent.internalPointer() if parent.isValid() else self.root
        if pnode.is_file:
            return QtCore.QModelIndex()
        kids = self._sorted_children(pnode)
        if 0 <= row < len(kids):
            return self.createIndex(row, column, kids[row])
        return QtCore.QModelIndex()

    def parent(self, index: QtCore.QModelIndex) -> QtCore.QModelIndex:  # noqa: D401
        if not index.isValid():
            return QtCore.QModelIndex()
        node: Node = index.internalPointer()
        p = node.parent
        if p is None or p is self.root:
            return QtCore.QModelIndex()
        pp = p.parent
        if pp is None:
            return QtCore.QModelIndex()
        sibs = self._sorted_children(pp)
        try:
            row = sibs.index(p)
        except ValueError:
            row = 0
        return self.createIndex(row, 0, p)

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        if parent.column() > 0:
            return 0
        node: Node = parent.internalPointer() if parent.isValid() else self.root
        if node.is_file:
            return 0
        return len(self._sorted_children(node))

    def columnCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if (
            role == QtCore.Qt.ItemDataRole.DisplayRole
            and orientation == QtCore.Qt.Orientation.Horizontal
        ):
            return self.HEADERS[section]
        return None

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node: Node = index.internalPointer()
        col = index.column()
        Disp = QtCore.Qt.ItemDataRole.DisplayRole
        if role in (Disp, QtCore.Qt.ItemDataRole.ToolTipRole):
            if col == 0:
                return node.name
            if col == 1:
                return human_size(node.own_size if node.is_file else node.total)
            if col == 2:
                ptotal = node.parent.total if node.parent else node.total
                return f"{node.total * 100 / ptotal:.1f}%" if ptotal else "—"
            if col == 3:
                return "文件" if node.is_file else "目录"
            if col == 4:
                return node.risk or ""
        if role == QtCore.Qt.ItemDataRole.DecorationRole and col == 0:
            return self._folder_icon if not node.is_file else self._file_icon
        if role == QtCore.Qt.ItemDataRole.TextAlignmentRole and col in (1, 2, 3):
            return int(
                QtCore.Qt.AlignmentFlag.AlignRight
                | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
        if role == QtCore.Qt.ItemDataRole.UserRole:
            return node
        return None
