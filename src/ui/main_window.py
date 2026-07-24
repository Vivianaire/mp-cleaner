"""主窗口:设备面板 + 空间树 + 占用图 + 垃圾面板 + 工具栏。"""
from __future__ import annotations

import time

from PyQt6 import QtCore, QtGui, QtWidgets

from ..adb import SCAN_ROOT, AdbClient
from ..classifier import classify
from ..scanner import FileTrie, TreeModel
from ..utils import human_size
from .widgets.chart_panel import ChartPanel
from .widgets.device_panel import DevicePanel
from .widgets.junk_panel import JunkPanel
from .widgets.space_tree import SpaceTreeView
from .workers import CleanerWorker, ScannerWorker


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("可视化手机清理 — mp-cleaner")
        self.resize(1280, 820)

        self.client = AdbClient()
        self._build_ui()
        self._build_toolbar()
        self.statusBar().showMessage("就绪")

        # 扫描状态
        self.trie: FileTrie | None = None
        self.tree_model: TreeModel | None = None
        self._scan_worker: ScannerWorker | None = None
        self._clean_worker: CleanerWorker | None = None
        self._installed_pkgs: list[str] = []
        self._ui_timer = QtCore.QTimer(self)
        self._ui_timer.setInterval(250)
        self._ui_timer.timeout.connect(self._refresh_ui)

    # --- UI ---
    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.device_panel = DevicePanel(self.client)
        self.device_panel.deviceChanged.connect(self._on_device_changed)
        outer.addWidget(self.device_panel)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.tree_view = SpaceTreeView()
        right = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.chart_panel = ChartPanel()
        self.junk_panel = JunkPanel()
        right.addWidget(self.chart_panel)
        right.addWidget(self.junk_panel)
        right.setStretchFactor(0, 1)
        right.setStretchFactor(1, 1)
        splitter.addWidget(self.tree_view)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter, 1)

    def _build_toolbar(self) -> None:
        tb = QtWidgets.QToolBar("主工具栏")
        tb.setMovable(False)
        self.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, tb)

        self.act_scan = QtGui.QAction("▶ 扫描", self)
        self.act_scan.setShortcut("F5")
        self.act_scan.triggered.connect(self.scan)
        self.act_scan.setEnabled(False)          # 设备就绪后开启

        self.act_clean = QtGui.QAction("🧹 清理选中", self)
        self.act_clean.setShortcut("Delete")
        self.act_clean.triggered.connect(self.clean)
        self.act_clean.setEnabled(False)

        tb.addAction(self.act_scan)
        tb.addAction(self.act_clean)

    # --- slots ---
    def _on_device_changed(self, device) -> None:
        ready = bool(device and device.authorized)
        self.act_scan.setEnabled(ready)
        if ready:
            self.statusBar().showMessage(f"已连接:{device.model or device.serial}")

    def scan(self) -> None:
        """启动流式全盘扫描。"""
        dev = self.device_panel.current_device()
        if not dev or not dev.authorized:
            self.statusBar().showMessage("没有已授权的设备", 3000)
            return

        self.trie = FileTrie(SCAN_ROOT)
        self.tree_model = TreeModel(self.trie)
        self.tree_view.set_scan_model(self.tree_model)

        self.act_scan.setEnabled(False)
        self.act_scan.setText("扫描中…")
        self.statusBar().showMessage("扫描中…")

        self._scan_worker = ScannerWorker(
            self.client, dev.serial, root=SCAN_ROOT, maxdepth=6
        )
        self._scan_worker.batchReady.connect(self._on_scan_batch)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.packagesReady.connect(self._on_packages)
        self._scan_worker.finishedScan.connect(self._on_scan_done)
        self._scan_worker.failed.connect(self._on_scan_fail)
        self._ui_timer.start()
        self._scan_worker.start()

    def clean(self) -> None:
        """安全清理已勾选项。"""
        items = self.junk_panel.checked_items()
        if not items:
            self.statusBar().showMessage("未勾选任何可清理项", 3000)
            return
        dev = self.device_panel.current_device()
        if not dev or not dev.authorized:
            self.statusBar().showMessage("设备未连接/未授权", 3000)
            return

        total = sum(it.size for it in items)
        btn = QtWidgets.QMessageBox.question(
            self,
            "确认清理",
            f"将清理 {len(items)} 项,预计释放 {human_size(total)}。\n"
            "运行中应用的私有数据会自动跳过(保护机制)。\n\n"
            "删除不可恢复,确认开始?",
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if btn != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        self.act_clean.setEnabled(False)
        self.act_scan.setEnabled(False)
        self.statusBar().showMessage("清理中…(检测保护 & 删除)")
        self._clean_worker = CleanerWorker(
            self.client, dev.serial, items, SCAN_ROOT, self._installed_pkgs
        )
        self._clean_worker.progress.connect(self._on_clean_progress)
        self._clean_worker.result.connect(self._on_clean_result)
        self._clean_worker.failed.connect(self._on_clean_fail)
        self._clean_worker.start()

    # --- 清理 slots ---
    def _on_clean_progress(self, done: int, total: int, path: str) -> None:
        self.statusBar().showMessage(f"清理中… {done}/{total}:{path}")

    def _on_clean_result(self, deleted: int, skipped: int, failed: int, freed) -> None:
        self._clean_reset()
        QtWidgets.QMessageBox.information(
            self,
            "清理完成",
            f"已删除 {deleted} 项\n"
            f"跳过(受保护/不安全){skipped} 项\n"
            f"失败 {failed} 项\n"
            f"释放 {human_size(freed)}",
        )
        self.statusBar().showMessage(
            f"清理完成:删除 {deleted} 项,释放 {human_size(freed)}", 0
        )
        self.act_scan.setText("▶ 重新扫描(查看效果)")

    def _on_clean_fail(self, msg: str) -> None:
        self._clean_reset()
        self.statusBar().showMessage(f"清理失败:{msg}", 0)

    def _clean_reset(self) -> None:
        self.act_clean.setEnabled(True)
        self.act_scan.setEnabled(True)
    def _on_scan_batch(self, records: list) -> None:
        assert self.trie is not None
        for path, size, is_file, mtime in records:
            self.trie.insert(path, size, is_file, mtime)

    def _on_scan_progress(self, files: int, nbytes) -> None:
        self.statusBar().showMessage(
            f"扫描中… {files:,} 文件 / {human_size(nbytes)}"
        )

    def _on_packages(self, pkgs: list) -> None:
        self._installed_pkgs = pkgs

    def _refresh_ui(self) -> None:
        if self.tree_model:
            self.tree_model.refresh()
        if self.trie:
            self.chart_panel.set_breakdown(self.trie.top_level())

    def _on_scan_done(self, files: int, dirs: int, nbytes) -> None:
        self._ui_timer.stop()
        self._refresh_ui()
        self.tree_view.expandToDepth(0)
        self.act_scan.setEnabled(True)
        self.act_scan.setText("▶ 重新扫描")

        # 分类(M4)
        items = classify(self.trie, self._installed_pkgs, time.time())
        self.junk_panel.set_items(items)
        self.act_clean.setEnabled(len(items) > 0)

        self.statusBar().showMessage(
            f"扫描完成:{files:,} 文件 / {dirs:,} 目录 / 共 {human_size(nbytes)}"
            f"   ·   识别可清理项 {len(items)} 类",
            0,
        )

    def _on_scan_fail(self, msg: str) -> None:
        self._ui_timer.stop()
        self.act_scan.setEnabled(True)
        self.act_scan.setText("▶ 扫描")
        self.statusBar().showMessage(f"扫描失败:{msg}", 0)
