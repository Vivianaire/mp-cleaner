"""空间占用树视图(M3 实装真实增量模型)。

M1 阶段为占位:扫描接通前显示提示行。
"""
from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

HEADERS = ["名称", "大小", "占比", "类型", "风险"]


class SpaceTreeView(QtWidgets.QTreeView):
    """按目录层级展示 /sdcard 占用,支持增量流式刷新(M3 接入 TreeModel)。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setHeaderHidden(False)
        self._placeholder("连接设备并点击「扫描」后,这里实时生长文件占用树。")

    def _placeholder(self, text: str) -> None:
        model = QtGui.QStandardItemModel()
        model.setHorizontalHeaderLabels(HEADERS)
        item = QtGui.QStandardItem(text)
        item.setEnabled(False)
        model.appendRow(item)
        self.setModel(model)

    def set_scan_model(self, model: QtCore.QAbstractItemModel) -> None:
        """M3:接入流式构建的 TreeModel。"""
        self.setModel(model)
