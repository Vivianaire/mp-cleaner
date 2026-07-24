"""自动分析视图:建议卡片 + 一键优化。配色走 theme(徽章/标题 QSS role)。"""
from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from ...utils import human_size


class RecommendationCard(QtWidgets.QGroupBox):
    apply = QtCore.pyqtSignal(list)      # 该建议的目标 items
    review = QtCore.pyqtSignal(str)      # 建议 key(去垃圾面板审视)

    def __init__(self, rec):
        super().__init__(rec.title)
        self._rec = rec
        lay = QtWidgets.QVBoxLayout(self)
        head = QtWidgets.QHBoxLayout()
        badge = QtWidgets.QLabel(rec.safety)
        badge.setObjectName("good" if rec.safety == "安全" else "warning")
        size_lbl = QtWidgets.QLabel(f"可释放 {human_size(rec.reclaimable)}")
        size_lbl.setObjectName("title")
        head.addWidget(badge)
        head.addStretch(1)
        head.addWidget(size_lbl)
        lay.addLayout(head)
        detail = QtWidgets.QLabel(rec.detail)
        detail.setObjectName("secondary")
        lay.addWidget(detail)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        if rec.auto:
            b = QtWidgets.QPushButton("✓ 应用此建议")
            b.clicked.connect(lambda: self.apply.emit(self._rec.items))
        else:
            b = QtWidgets.QPushButton("去审视 →")
            b.clicked.connect(lambda: self.review.emit(self._rec.key))
        row.addWidget(b)
        lay.addLayout(row)


class RecommendationsView(QtWidgets.QWidget):
    optimizeRequested = QtCore.pyqtSignal(list)   # 一键优化的全部 items
    reviewRequested = QtCore.pyqtSignal(str)      # 去垃圾面板审视

    def __init__(self, parent=None):
        super().__init__(parent)
        self._recs: list = []
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)

        bar = QtWidgets.QHBoxLayout()
        self.summary = QtWidgets.QLabel("扫描后展示建议")
        self.summary.setObjectName("title")
        self.btn_opt = QtWidgets.QPushButton("⚡ 一键优化")
        self.btn_opt.setEnabled(False)
        self.btn_opt.clicked.connect(self._on_optimize)
        bar.addWidget(self.summary, 1)
        bar.addWidget(self.btn_opt)
        outer.addLayout(bar)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self._host = QtWidgets.QWidget()
        self._host_lay = QtWidgets.QVBoxLayout(self._host)
        self._host_lay.addStretch(1)
        self.scroll.setWidget(self._host)
        outer.addWidget(self.scroll, 1)

    def set_recs(self, recs) -> None:
        self._recs = recs
        # 清空旧卡片
        while self._host_lay.count() > 1:
            it = self._host_lay.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        auto_total = 0
        for rec in recs:
            card = RecommendationCard(rec)
            card.apply.connect(self.optimizeRequested.emit)
            card.review.connect(self.reviewRequested.emit)
            self._host_lay.insertWidget(self._host_lay.count() - 1, card)
            if rec.auto:
                auto_total += rec.reclaimable
        if recs:
            self.summary.setText(
                f"共 {len(recs)} 条建议 · 一键优化预计释放 {human_size(auto_total)}"
            )
            self.btn_opt.setEnabled(auto_total > 0)
        else:
            self.summary.setText("暂无建议(扫描后再看)")
            self.btn_opt.setEnabled(False)

    def _on_optimize(self) -> None:
        from ...core.recommend import one_tap_items
        items = one_tap_items(self._recs)
        if items:
            self.optimizeRequested.emit(items)
