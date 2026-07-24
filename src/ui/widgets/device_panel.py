"""设备连接面板:枚举、选择、显示状态与基本信息。"""
from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from ...adb import AdbClient, DeviceInfo
from ..workers import DeviceListWorker


class DevicePanel(QtWidgets.QWidget):
    """顶部设备选择条。"""

    deviceChanged = QtCore.pyqtSignal(object)     # DeviceInfo | None

    def __init__(self, client: AdbClient, parent=None):
        super().__init__(parent)
        self._client = client
        self._worker: DeviceListWorker | None = None
        self._current: DeviceInfo | None = None

        self.combo = QtWidgets.QComboBox()
        self.combo.setMinimumWidth(280)
        self.combo.currentIndexChanged.connect(self._on_combo_changed)

        self.refresh_btn = QtWidgets.QPushButton("刷新设备")
        self.refresh_btn.clicked.connect(self.refresh)

        self.status_lbl = QtWidgets.QLabel("检测中…")
        self.detail_lbl = QtWidgets.QLabel("")
        self.detail_lbl.setStyleSheet("color: #666;")

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(QtWidgets.QLabel("设备:"))
        lay.addWidget(self.combo, 1)
        lay.addWidget(self.refresh_btn)
        lay.addSpacing(16)
        lay.addWidget(self.status_lbl, 1)
        lay.addWidget(self.detail_lbl, 2)

        QtCore.QTimer.singleShot(0, self.refresh)

    # --- public ---
    def current_device(self) -> DeviceInfo | None:
        return self._current

    # --- slots ---
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

    def _on_combo_changed(self, idx: int, props: dict | None = None) -> None:
        d: DeviceInfo | None = self.combo.itemData(idx) if idx >= 0 else None
        self._current = d
        if d and d.authorized:
            p = props or {}
            info = p.get(d.serial, {})
            brand = info.get("brand", "")
            model = info.get("model", d.model)
            release = info.get("release", "")
            self.detail_lbl.setText(
                f"{brand} {model}   Android {release}   serial {d.serial}"
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
