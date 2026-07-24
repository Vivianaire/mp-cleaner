"""主窗口:设备面板 + 空间树 + 占用图 + 垃圾面板 + 工具栏。

v2.1:扫描经 ``DeviceBackend``;SQLite 快照 + 缓存命中重扫(目录签名一致则秒级
从快照重建);全深扫描(无 maxdepth)。
"""
from __future__ import annotations

import time

from PyQt6 import QtCore, QtGui, QtWidgets

from ..adb import SCAN_ROOT, AdbClient
from ..classifier import classify
from ..core.backends import AdbShellBackend
from ..core.recommend import generate as gen_recommendations
from ..core.storage import Store, db_path_for
from ..scanner import FileTrie, TreeModel
from ..services.scan_service import ScanService
from ..utils import human_size
from .views.dashboard import DashboardView
from .views.recommendations import RecommendationsView
from .views.trash_view import TrashView
from .widgets.chart_panel import ChartPanel
from .widgets.device_panel import DevicePanel
from .widgets.junk_panel import JunkPanel
from .widgets.space_tree import SpaceTreeView
from .workers import CacheWorker, CleanToTrashWorker, ScannerWorker


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("可视化手机清理 — mp-cleaner")
        self.resize(1280, 820)

        self.client = AdbClient()
        self._backend: AdbShellBackend | None = None
        self._store: Store | None = None
        self._scan_service: ScanService | None = None

        self._build_ui()
        self._build_toolbar()
        self.statusBar().showMessage("就绪")

        # 扫描状态
        self.trie: FileTrie | None = None
        self.tree_model: TreeModel | None = None
        self._scan_worker: ScannerWorker | None = None
        self._cache_worker: CacheWorker | None = None
        self._clean_worker: CleanToTrashWorker | None = None
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

        self.tabs = QtWidgets.QTabWidget()
        # 仪表盘
        self.dashboard = DashboardView()
        self.dashboard.treemap.pathClicked.connect(self._on_treemap_click)
        self.tabs.addTab(self.dashboard, "📊 仪表盘")
        # 空间浏览(树 + 顶层占用图)
        browser = QtWidgets.QWidget()
        bl = QtWidgets.QVBoxLayout(browser)
        bl.setContentsMargins(0, 0, 0, 0)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.tree_view = SpaceTreeView()
        self.chart_panel = ChartPanel()
        splitter.addWidget(self.tree_view)
        splitter.addWidget(self.chart_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        bl.addWidget(splitter)
        self.tabs.addTab(browser, "🌲 空间浏览")
        # 垃圾清理
        self.junk_panel = JunkPanel()
        self.tabs.addTab(self.junk_panel, "🧹 垃圾清理")
        # 回收站
        self.trash_view = TrashView()
        self.tabs.addTab(self.trash_view, "🗑 回收站")
        # 建议
        self.recs_view = RecommendationsView()
        self.recs_view.optimizeRequested.connect(lambda items: self.clean(items))
        self.recs_view.reviewRequested.connect(
            lambda _k: self.tabs.setCurrentIndex(2)
        )
        self.tabs.addTab(self.recs_view, "💡 建议")
        outer.addWidget(self.tabs, 1)

    def _build_toolbar(self) -> None:
        tb = QtWidgets.QToolBar("主工具栏")
        tb.setMovable(False)
        self.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, tb)

        self.act_scan = QtGui.QAction("▶ 扫描", self)
        self.act_scan.setShortcut("F5")
        self.act_scan.triggered.connect(lambda: self.scan(force_full=False))
        self.act_scan.setEnabled(False)

        self.act_scan_force = QtGui.QAction("⟳ 强制全扫", self)
        self.act_scan_force.setShortcut("Ctrl+F5")
        self.act_scan_force.triggered.connect(lambda: self.scan(force_full=True))
        self.act_scan_force.setEnabled(False)

        self.act_clean = QtGui.QAction("🧹 清理选中", self)
        self.act_clean.setShortcut("Delete")
        self.act_clean.triggered.connect(self.clean)
        self.act_clean.setEnabled(False)

        tb.addAction(self.act_scan)
        tb.addAction(self.act_scan_force)
        tb.addAction(self.act_clean)

    # --- 设备 ---
    def _on_device_changed(self, device) -> None:
        ready = bool(device and device.authorized)
        self.act_scan.setEnabled(ready)
        self.act_scan_force.setEnabled(ready)
        if ready:
            self._backend = AdbShellBackend(self.client, device.serial)
            self._store = Store(db_path_for(device.serial))
            self._scan_service = ScanService(self._backend, self._store)
            self.trash_view.set_services(self._backend, self._store)
            cached = self._scan_service.has_snapshot(SCAN_ROOT)
            self.statusBar().showMessage(
                f"已连接:{device.model or device.serial}"
                + ("（有历史快照,可缓存重扫）" if cached else "")
            )
        else:
            self._backend = self._store = self._scan_service = None

    # --- 扫描 ---
    def scan(self, force_full: bool = False) -> None:
        dev = self.device_panel.current_device()
        if not dev or not dev.authorized or not self._scan_service:
            self.statusBar().showMessage("没有已授权的设备", 3000)
            return

        self.act_scan.setEnabled(False)
        self.act_scan_force.setEnabled(False)
        self.act_scan.setText("扫描中…")

        if force_full or not self._scan_service.has_snapshot(SCAN_ROOT):
            self._start_full_scan()
            return

        # 先在后台尝试缓存命中
        self.statusBar().showMessage("检查缓存(目录签名)…")
        self._cache_worker = CacheWorker(self._scan_service, SCAN_ROOT, self)
        self._cache_worker.result.connect(self._on_cache_result)
        self._cache_worker.failed.connect(lambda _m: self._start_full_scan())
        self._cache_worker.finished.connect(self._cache_worker.deleteLater)
        self._cache_worker.start()

    def _on_cache_result(self, trie, hit: bool) -> None:
        if hit and trie is not None:
            pkgs = self._scan_service.cached_packages()
            self._finish_scan_ui(
                trie, pkgs, trie.file_count, trie.dir_count,
                trie.total_bytes, source="cached",
            )
        else:
            self._start_full_scan()

    def _start_full_scan(self) -> None:
        self.trie = FileTrie(SCAN_ROOT)
        self.tree_model = TreeModel(self.trie)
        self.tree_view.set_scan_model(self.tree_model)
        self.statusBar().showMessage("全深扫描中…")
        self._scan_worker = ScannerWorker(self._backend, SCAN_ROOT, maxdepth=None)
        self._scan_worker.batchReady.connect(self._on_scan_batch)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.packagesReady.connect(self._on_packages)
        self._scan_worker.finishedScan.connect(self._on_scan_done)
        self._scan_worker.failed.connect(self._on_scan_fail)
        self._ui_timer.start()
        self._scan_worker.start()

    def _finish_scan_ui(
        self, trie, packages, files, dirs, nbytes, source: str = "full"
    ) -> None:
        self.trie = trie
        self._installed_pkgs = packages
        self.tree_model = TreeModel(trie)
        self.tree_view.set_scan_model(self.tree_model)
        self._refresh_ui()
        self.tree_view.expandToDepth(0)

        items = classify(trie, packages, time.time())
        self.junk_panel.set_items(items)
        self.act_clean.setEnabled(len(items) > 0)

        # 仪表盘(M2)
        self.dashboard.set_data(trie, self.device_panel.current_storage(), items)
        # 自动分析建议(v2.4)
        self.recs_view.set_recs(gen_recommendations(items))

        self.act_scan.setEnabled(True)
        self.act_scan_force.setEnabled(True)
        self.act_scan.setText("▶ 重新扫描")
        tag = "（缓存命中,秒级）" if source == "cached" else ""
        self.statusBar().showMessage(
            f"扫描完成{tag}:{files:,} 文件 / {dirs:,} 目录 / 共 {human_size(nbytes)}"
            f"   ·   可清理项 {len(items)} 条",
            0,
        )

    def _on_treemap_click(self, path: str) -> None:
        """treemap 点击 -> 切到空间浏览并尝试定位路径。"""
        self.tabs.setCurrentWidget(self.tabs.widget(1))
        self._select_path_in_tree(path)

    def _select_path_in_tree(self, path: str) -> None:
        """在树里逐级展开并选中给定路径。"""
        if not self.tree_model:
            return
        rel = path[len(self.tree_model.trie.prefix):].strip("/")
        if not rel:
            return
        parts = rel.split("/")
        parent = QtCore.QModelIndex()
        model = self.tree_view.model()
        for name in parts:
            node = parent.internalPointer() if parent.isValid() else self.tree_model.root
            kids = self.tree_model._sorted_children(node)
            row = next((r for r, k in enumerate(kids) if k.name == name), None)
            if row is None:
                return
            parent = model.index(row, 0, parent)
            self.tree_view.expand(parent)
        if parent.isValid():
            self.tree_view.setCurrentIndex(parent)

    # --- 扫描 slots ---
    def _on_scan_batch(self, records: list) -> None:
        assert self.trie is not None
        for path, size, is_file, mtime in records:
            self.trie.insert(path, size, is_file, mtime)

    def _on_scan_progress(self, files: int, nbytes) -> None:
        self.statusBar().showMessage(
            f"全深扫描中… {files:,} 文件 / {human_size(nbytes)}"
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
        # 持久化快照(全量替换 + 已装包)
        try:
            self._scan_service.persist(
                SCAN_ROOT, self.trie, files, nbytes, self._installed_pkgs, "full"
            )
        except Exception as e:  # noqa: BLE001
            self.statusBar().showMessage(f"快照写入失败:{e}", 5000)
        self._finish_scan_ui(
            self.trie, self._installed_pkgs, files, dirs, nbytes, source="full"
        )

    def _on_scan_fail(self, msg: str) -> None:
        self._ui_timer.stop()
        self.act_scan.setEnabled(True)
        self.act_scan_force.setEnabled(True)
        self.act_scan.setText("▶ 扫描")
        self.statusBar().showMessage(f"扫描失败:{msg}", 0)

    # --- 清理(v2.3:默认移入回收站,可恢复)---
    def clean(self, items=None) -> None:
        if items is None:
            items = self.junk_panel.checked_items()
        if not items:
            self.statusBar().showMessage("未勾选任何可清理项", 3000)
            return
        if not (self._backend and self._store):
            self.statusBar().showMessage("设备未连接/未授权", 3000)
            return

        total = sum(it.size for it in items)
        btn = QtWidgets.QMessageBox.question(
            self,
            "确认清理(移入回收站)",
            f"将清理 {len(items)} 项,预计释放 {human_size(total)}。\n"
            "默认移入回收站(可恢复);运行中应用的私有数据会自动跳过。\n\n确认?",
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if btn != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        self.act_clean.setEnabled(False)
        self.act_scan.setEnabled(False)
        self.act_scan_force.setEnabled(False)
        self.statusBar().showMessage("清理中…(检测保护 & 移入回收站)")
        self._clean_worker = CleanToTrashWorker(
            self._backend, self._store, items, SCAN_ROOT
        )
        self._clean_worker.progress.connect(self._on_clean_progress)
        self._clean_worker.result.connect(self._on_clean_result)
        self._clean_worker.failed.connect(self._on_clean_fail)
        self._clean_worker.start()

    def _on_clean_progress(self, done: int, total: int, path: str) -> None:
        self.statusBar().showMessage(f"清理中… {done}/{total}:{path}")

    def _on_clean_result(self, moved: int, skipped: int, failed: int, freed) -> None:
        self._clean_reset()
        self.trash_view.refresh_own()
        QtWidgets.QMessageBox.information(
            self,
            "清理完成",
            f"已移入回收站 {moved} 项\n跳过(受保护/不安全){skipped} 项\n"
            f"失败 {failed} 项\n释放 {human_size(freed)}\n\n"
            "可在「回收站」标签页恢复或永久清空。",
        )
        self.statusBar().showMessage(
            f"清理完成:移入回收站 {moved} 项,释放 {human_size(freed)}", 0
        )
        self.act_scan.setText("▶ 重新扫描(查看效果)")

    def _on_clean_fail(self, msg: str) -> None:
        self._clean_reset()
        self.statusBar().showMessage(f"清理失败:{msg}", 0)

    def _clean_reset(self) -> None:
        self.act_clean.setEnabled(True)
        self.act_scan.setEnabled(True)
        self.act_scan_force.setEnabled(True)
