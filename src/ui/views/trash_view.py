"""回收站视图:工具自带(可恢复)+ 手机自带(检测/清空)。

自带回收站操作走 backend(同卷 mv 为重命名,秒级)+ Store 清单;手机回收站检测/清空
经 PhoneTrashWorker(避免 dumpsys/content 查询阻塞 UI)。
"""
from __future__ import annotations

import datetime as _dt

from PyQt6 import QtCore, QtGui, QtWidgets

from ...utils import human_size
from ..workers import PhoneTrashWorker, TrashOpWorker


class _SizeItem(QtWidgets.QTableWidgetItem):
    """按字节数排序的表格项(展示为人类可读,排序按真实数值)。"""

    def __init__(self, nbytes: int):
        super().__init__(human_size(nbytes))
        self._n = int(nbytes)

    def __lt__(self, other):
        if isinstance(other, _SizeItem):
            return self._n < other._n
        return super().__lt__(other)


class TrashView(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._backend = None
        self._store = None
        self._phone_worker: PhoneTrashWorker | None = None
        self._op_worker: TrashOpWorker | None = None
        self._build()

    def _build(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)

        # ---- 自带回收站 ----
        g1 = QtWidgets.QGroupBox("自带回收站(安全删除,可恢复)")
        l1 = QtWidgets.QVBoxLayout(g1)
        row = QtWidgets.QHBoxLayout()
        self.own_total = QtWidgets.QLabel("回收站:—")
        self.own_total.setObjectName("value-good")
        b_restore = QtWidgets.QPushButton("↩ 恢复选中")
        b_delete = QtWidgets.QPushButton("✕ 永久删除选中")
        b_empty = QtWidgets.QPushButton("清空全部")
        b_expire = QtWidgets.QPushButton("清理过期")
        self._buttons = (b_restore, b_delete, b_empty, b_expire)
        for b in self._buttons:
            b.clicked.connect(self._guard(b))
        row.addWidget(self.own_total)
        row.addStretch(1)
        row.addWidget(b_restore)
        row.addWidget(b_delete)
        row.addWidget(b_expire)
        row.addWidget(b_empty)
        l1.addLayout(row)

        self.own_table = QtWidgets.QTableWidget(0, 4)
        self.own_table.setHorizontalHeaderLabels(["原路径", "大小", "类别", "移入时间"])
        self.own_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.own_table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.own_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.own_table.setSortingEnabled(True)
        self.own_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        l1.addWidget(self.own_table)
        outer.addWidget(g1)

        # ---- 手机自带回收站 ----
        g2 = QtWidgets.QGroupBox("手机自带回收站(相册最近删除 / .trash 目录)")
        l2 = QtWidgets.QVBoxLayout(g2)
        row2 = QtWidgets.QHBoxLayout()
        b_detect = QtWidgets.QPushButton("🔍 检测")
        b_detect.clicked.connect(self.detect_phone)
        self.phone_hint = QtWidgets.QLabel("点「检测」扫描手机自带回收站")
        self.phone_hint.setObjectName("muted")
        row2.addWidget(b_detect)
        row2.addWidget(self.phone_hint, 1)
        l2.addLayout(row2)
        self.phone_table = QtWidgets.QTableWidget(0, 3)
        self.phone_table.setHorizontalHeaderLabels(["来源", "大小", "操作"])
        self.phone_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.phone_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        l2.addWidget(self.phone_table)
        outer.addWidget(g2, 1)

    def _guard(self, btn):
        """按钮分发。"""
        acts = {
            "↩ 恢复选中": self.restore_selected,
            "✕ 永久删除选中": self.delete_selected,
            "清空全部": self.empty_all,
            "清理过期": self.expire_old,
        }
        return acts.get(btn.text(), lambda: None)

    # --- 服务注入 ---
    def set_services(self, backend, store) -> None:
        self._backend = backend
        self._store = store
        self.refresh_own()

    def refresh_own(self) -> None:
        if not self._store:
            return
        rows = self._store.list_trash()
        self.own_table.setSortingEnabled(False)      # 填充时先关排序,避免行错位
        self.own_table.setRowCount(0)
        for tid, original, _trash_path, size, category, moved_at in rows:
            r = self.own_table.rowCount()
            self.own_table.insertRow(r)
            self._set(r, 0, original, tid)
            self._set(r, 1, human_size(size), tid, nbytes=size)
            self._set(r, 2, category or "", tid)
            try:
                ts = _dt.datetime.fromtimestamp(moved_at).strftime("%Y-%m-%d %H:%M")
            except Exception:  # noqa: BLE001
                ts = ""
            self._set(r, 3, ts, tid)
        self.own_table.setSortingEnabled(True)
        self.own_total.setText(f"自带回收站:{len(rows)} 项,占用 {human_size(self._store.trash_total())}")

    def _set(self, r, c, text, tid, nbytes=None) -> None:
        if nbytes is not None:
            item = _SizeItem(nbytes)
        else:
            item = QtWidgets.QTableWidgetItem(text)
        item.setData(QtCore.Qt.ItemDataRole.UserRole, tid)
        self.own_table.setItem(r, c, item)

    def _selected_tids(self) -> list[int]:
        tids = []
        for it in self.own_table.selectedItems():
            tid = it.data(QtCore.Qt.ItemDataRole.UserRole)
            if tid is not None and tid not in tids:
                tids.append(tid)
        return tids

    # --- 自带回收站操作(off-thread,避免多选批量 mv/rm 冻结 UI)---
    def _ready(self) -> bool:
        return bool(self._backend and self._store)

    def _busy(self) -> bool:
        return bool(self._op_worker and self._op_worker.isRunning())

    def _set_buttons_enabled(self, on: bool) -> None:
        for b in self._buttons:
            b.setEnabled(on)

    def _run_op(self, op: str, tids=None) -> None:
        if not self._ready() or self._busy():
            return
        self._set_buttons_enabled(False)
        self._op_worker = TrashOpWorker(self._backend, self._store, op, tids, parent=self)
        self._op_worker.result.connect(self._on_op_done)
        self._op_worker.failed.connect(self._on_op_fail)
        self._op_worker.finished.connect(self._op_worker.deleteLater)
        self._op_worker.start()

    def _on_op_done(self, op: str, count: int, freed) -> None:
        self._set_buttons_enabled(True)
        self.refresh_own()
        if op == "restore":
            QtWidgets.QMessageBox.information(self, "恢复完成", f"已恢复 {count} 项到原路径")
        elif op == "empty":
            QtWidgets.QMessageBox.information(self, "已清空", f"释放 {human_size(freed or 0)}")
        elif op == "expire":
            QtWidgets.QMessageBox.information(
                self, "清理过期", f"清理 {count} 项过期(>14天),释放 {human_size(freed or 0)}"
            )

    def _on_op_fail(self, msg: str) -> None:
        self._set_buttons_enabled(True)
        self.refresh_own()
        QtWidgets.QMessageBox.warning(self, "操作失败", msg)

    def restore_selected(self) -> None:
        if not self._ready() or self._busy():
            return
        tids = self._selected_tids()
        if not tids:
            QtWidgets.QMessageBox.information(self, "恢复", "先选中要恢复的项")
            return
        self._run_op("restore", tids)

    def delete_selected(self) -> None:
        if not self._ready() or self._busy():
            return
        tids = self._selected_tids()
        if not tids:
            return
        if QtWidgets.QMessageBox.question(
            self, "永久删除", f"永久删除 {len(tids)} 项?不可恢复。",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        ) != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self._run_op("delete", tids)

    def empty_all(self) -> None:
        if not self._ready() or self._busy() or self._store.trash_total() == 0:
            return
        if QtWidgets.QMessageBox.question(
            self, "清空回收站",
            f"永久清空自带回收站({human_size(self._store.trash_total())})?不可恢复。",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        ) != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self._run_op("empty")

    def expire_old(self) -> None:
        if not self._ready() or self._busy():
            return
        self._run_op("expire")

    # --- 手机自带回收站 ---
    def detect_phone(self) -> None:
        if not self._backend:
            return
        self.phone_hint.setText("检测中…")
        self._phone_worker = PhoneTrashWorker(self._backend, "detect", parent=self)
        self._phone_worker.detected.connect(self._on_phone_detected)
        self._phone_worker.failed.connect(lambda m: self.phone_hint.setText(f"检测失败:{m}"))
        self._phone_worker.finished.connect(self._phone_worker.deleteLater)
        self._phone_worker.start()

    def _on_phone_detected(self, items: list) -> None:
        self.phone_table.setRowCount(0)
        total = sum(it["size"] for it in items)
        for it in items:
            r = self.phone_table.rowCount()
            self.phone_table.insertRow(r)
            self.phone_table.setItem(r, 0, QtWidgets.QTableWidgetItem(it["label"]))
            self.phone_table.setItem(r, 1, QtWidgets.QTableWidgetItem(human_size(it["size"])))
            btn = QtWidgets.QPushButton("清空")
            btn.clicked.connect(lambda _=False, t=it: self.empty_phone(t))
            self.phone_table.setCellWidget(r, 2, btn)
        self.phone_hint.setText(
            f"检测到 {len(items)} 处,合计 {human_size(total)}"
            if items else "未检测到手机自带回收站内容"
        )

    def empty_phone(self, target: dict) -> None:
        if not self._backend:
            return
        self._phone_worker = PhoneTrashWorker(self._backend, "empty", target, parent=self)
        self._phone_worker.emptied.connect(
            lambda freed: (self.phone_hint.setText(f"已清空,释放 {human_size(freed)}"),
                           self.detect_phone())
        )
        self._phone_worker.failed.connect(lambda m: self.phone_hint.setText(f"清空失败:{m}"))
        self._phone_worker.finished.connect(self._phone_worker.deleteLater)
        self._phone_worker.start()
