"""设备连接面板:枚举、选择、显示状态与基本信息。"""
from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from ...adb import AdbClient, DeviceInfo
from ...utils import human_size
from ..workers import DeviceListWorker


class DevicePanel(QtWidgets.QWidget):
    """顶部设备选择条。"""

    deviceChanged = QtCore.pyqtSignal(object)     # DeviceInfo | None

    def __init__(self, client: AdbClient, parent=None):
        super().__init__(parent)
        self._client = client
        self._worker: DeviceListWorker | None = None
        self._current: DeviceInfo | None = None
        self._props: dict = {}

        self.combo = QtWidgets.QComboBox()
        self.combo.setMinimumWidth(280)
        self.combo.currentIndexChanged.connect(self._on_combo_changed)

        self.refresh_btn = QtWidgets.QPushButton("刷新设备")
        self.refresh_btn.clicked.connect(self.refresh)

        self.status_lbl = QtWidgets.QLabel("检测中…")
        self.detail_lbl = QtWidgets.QLabel("")
        self.detail_lbl.setObjectName("muted")

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.addWidget(QtWidgets.QLabel("设备:"))
        lay.addWidget(self.combo, 1)
        lay.addWidget(self.refresh_btn)
        lay.addSpacing(16)
        lay.addWidget(self.status_lbl, 1)
        lay.addWidget(self.detail_lbl, 2)

        # 未连接时温和轮询 adb devices(每 3s);连上授权设备后停止。全程应用内,
        # 不弹窗(已由 AdbClient 的 CREATE_NO_WINDOW 保证)。
        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(3000)
        self._poll_timer.timeout.connect(self._poll_refresh)

        QtCore.QTimer.singleShot(0, self.refresh)

    # --- public ---
    def current_device(self) -> DeviceInfo | None:
        return self._current

    def current_storage(self):
        """当前设备的 (total,used,avail) 或 None。"""
        d = self._current
        if d and d.serial in self._props:
            return self._props[d.serial].get("storage")
        return None

    # --- slots ---
    def _poll_refresh(self) -> None:
        # 重入保护:上一次 refresh 的 worker 还在跑就跳过本轮
        if self._worker and self._worker.isRunning():
            return
        self.refresh()

    def refresh(self) -> None:
        self.refresh_btn.setEnabled(False)
        self.status_lbl.setText("检测中…")
        # 旧 worker 仍在跑就先丢掉引用;QThread 自行清理
        self._worker = DeviceListWorker(self._client, self)
        self._worker.result.connect(self._on_devices)
        self._worker.failed.connect(self._on_error)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_devices(self, devs: list, props: dict) -> None:
        self._props = props or {}
        authorized = [d for d in devs if d.authorized]
        self.combo.blockSignals(True)
        self.combo.clear()
        if not devs:
            self.combo.addItem("（未检测到设备）")
            self.status_lbl.setText("未检测到设备 — 请用 USB 连接并在手机上允许调试")
            self.detail_lbl.setText("")
        else:
            for d in devs:
                tag = "" if d.authorized else f"  [ {d.state} ]"
                self.combo.addItem(f"{d.model or d.serial}{tag}", d)
            if authorized:
                self.combo.setCurrentIndex(devs.index(authorized[0]))
            self.status_lbl.setText(
                f"检测到 {len(devs)} 台,已授权 {len(authorized)} 台"
            )
        self.combo.blockSignals(False)
        self._on_combo_changed(self.combo.currentIndex(), props)
        # 有授权设备 → 停轮询;无设备/未授权 → 继续(或开始)轮询等设备插入
        if authorized:
            self._poll_timer.stop()
        else:
            self._poll_timer.start()

    def _on_combo_changed(self, idx: int, props: dict | None = None) -> None:
        d: DeviceInfo | None = self.combo.itemData(idx) if idx >= 0 else None
        self._current = d
        if d and d.authorized:
            p = props or {}
            info = p.get(d.serial, {})
            brand = info.get("brand", "")
            model = info.get("model", d.model)
            release = info.get("release", "")
            storage = info.get("storage")
            store_str = ""
            if storage:
                total, used, avail = storage
                pct = used * 100 / total if total else 0
                store_str = (
                    f"   |   存储 {human_size(used)}/{human_size(total)}"
                    f" ({pct:.0f}%,可用 {human_size(avail)})"
                )
            self.detail_lbl.setText(
                f"{brand} {model} · Android {release} · serial {d.serial}{store_str}"
            )
        else:
            self.detail_lbl.setText(
                "设备未授权 — 在手机弹窗里点「允许 USB 调试」后刷新"
                if d and not d.authorized
                else ""
            )
        self.deviceChanged.emit(d)
        self.refresh_btn.setEnabled(True)

    def _on_error(self, msg: str) -> None:
        self.status_lbl.setText("检测失败")
        self.detail_lbl.setText(msg)
        self.refresh_btn.setEnabled(True)
        self._poll_timer.start()
