"""趋势视图:历次扫描的存储占用走势(来自 SQLite ``scan_runs``)+ 明细表。

图表沿用本项目的手绘 QPainter 风格(不引第三方图库)。数据来自
``Store.list_scan_runs()``:每次扫描落一条 (started, finished, file_count, bytes, source)。
"""
from __future__ import annotations

import datetime as _dt

from PyQt6 import QtCore, QtGui, QtWidgets

from ...utils import human_size


class _LineChart(QtWidgets.QWidget):
    """单序列折线图:points = [(x_label, value), ...](按时间升序)。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self._pts: list[tuple[str, int]] = []

    def set_points(self, pts) -> None:
        self._pts = list(pts)
        self.update()

    def paintEvent(self, _e) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor("#ffffff"))
        w, h = self.width(), self.height()
        ml, mr, mt, mb = 64, 16, 16, 28
        if len(self._pts) < 2:
            p.setPen(QtGui.QColor("#aaa"))
            p.drawText(self.rect(), int(QtCore.Qt.AlignmentFlag.AlignCenter),
                       "至少两次扫描后展示趋势")
            p.end()
            return
        vals = [v for _, v in self._pts]
        vmax = max(vals) or 1
        vmin = min(vals)
        span = (vmax - vmin) or vmax or 1
        pw = w - ml - mr
        ph = h - mt - mb
        n = len(self._pts)

        # 轴
        p.setPen(QtGui.QPen(QtGui.QColor("#e5e7eb"), 1))
        p.drawLine(ml, mt, ml, mt + ph)
        p.drawLine(ml, mt + ph, ml + pw, mt + ph)
        # y 轴刻度(min/max)
        p.setPen(QtGui.QColor("#94a3b8"))
        p.drawText(QtCore.QRectF(0, mt - 6, ml - 6, 16),
                   int(QtCore.Qt.AlignmentFlag.AlignRight), human_size(vmax))
        p.drawText(QtCore.QRectF(0, mt + ph - 8, ml - 6, 16),
                   int(QtCore.Qt.AlignmentFlag.AlignRight), human_size(vmin))

        def xy(i, v):
            x = ml + (pw * i / (n - 1))
            y = mt + ph - (ph * (v - vmin) / span)
            return QtCore.QPointF(x, y)

        # 面积 + 折线
        path = QtGui.QPainterPath()
        path.moveTo(xy(0, vals[0]))
        for i in range(1, n):
            path.lineTo(xy(i, vals[i]))
        p.setPen(QtGui.QPen(QtGui.QColor("#2563eb"), 2))
        p.drawPath(path)
        p.setBrush(QtGui.QColor("#2563eb"))
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for i in range(n):
            pt = xy(i, vals[i])
            p.drawEllipse(pt, 3, 3)
        # x 轴端点标签
        p.setPen(QtGui.QColor("#94a3b8"))
        p.drawText(QtCore.QRectF(ml, mt + ph + 4, 120, 16),
                   int(QtCore.Qt.AlignmentFlag.AlignLeft), self._pts[0][0])
        p.drawText(QtCore.QRectF(ml + pw - 120, mt + ph + 4, 120, 16),
                   int(QtCore.Qt.AlignmentFlag.AlignRight), self._pts[-1][0])
        p.end()


class TrendsView(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._store = None
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("扫描占用趋势")
        title.setStyleSheet("font-weight:600;")
        self.summary = QtWidgets.QLabel("扫描后累积历史,连成走势")
        self.summary.setStyleSheet("color:#666;")
        btn = QtWidgets.QPushButton("刷新")
        btn.clicked.connect(self.refresh)
        head.addWidget(title)
        head.addWidget(self.summary, 1)
        head.addWidget(btn)
        outer.addLayout(head)

        self.chart = _LineChart()
        outer.addWidget(self.chart)

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["时间", "文件数", "占用", "来源"])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.table.setSortingEnabled(True)
        outer.addWidget(self.table, 1)

    def set_store(self, store) -> None:
        self._store = store
        self.refresh()

    def refresh(self) -> None:
        if not self._store:
            return
        try:
            runs = self._store.list_scan_runs()
        except Exception:  # noqa: BLE001
            runs = []
        pts = []
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for started, _finished, file_count, nbytes, source in runs:
            try:
                ts = _dt.datetime.fromtimestamp(started).strftime("%m-%d %H:%M")
            except Exception:  # noqa: BLE001
                ts = str(started)
            pts.append((ts, int(nbytes or 0)))
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(ts))
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(f"{file_count or 0:,}"))
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(human_size(nbytes or 0)))
            self.table.setItem(r, 3, QtWidgets.QTableWidgetItem(source or ""))
        self.table.setSortingEnabled(True)
        self.chart.set_points(pts)
        if len(pts) >= 2:
            delta = pts[-1][1] - pts[0][1]
            arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
            self.summary.setText(
                f"共 {len(pts)} 次扫描 · 首末变化 {arrow} {human_size(abs(delta))}"
            )
        elif pts:
            self.summary.setText("已有 1 次扫描记录,再扫一次即可看走势")
        else:
            self.summary.setText("暂无扫描历史")
