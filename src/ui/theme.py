"""Google Material 风设计系统:集中令牌 + 双主题(浅/深)+ 全局 QSS。

各 widget 引用此处的 token(`current().xxx`),杜绝硬编码颜色/字体/圆角。图表配色
遵循 dataviz 方法:分类色用 CVD 安全的固定顺序(dataviz 参考 8 色,含 Google 蓝/黄/
绿/红),状态色固定(good/warning/critical),文字用 ink 不用系列色,图例/标签作
secondary encoding。主题切换时 widget 的自定义 paint 读 ``current()`` 重新着色。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PyQt6 import QtWidgets

FONT_FAMILY = "'Segoe UI','Microsoft YaHei UI',sans-serif"
RADIUS_SM = 6
RADIUS = 8
RADIUS_LG = 12
RADIUS_XL = 28


class Mode(Enum):
    LIGHT = "light"
    DARK = "dark"


@dataclass(frozen=True)
class Tokens:
    # 主色(Google 蓝)
    primary: str
    primary_hover: str
    on_primary: str
    # 状态(固定语义,需配图标/标签)
    good: str
    warning: str
    critical: str
    good_bg: str
    warning_bg: str
    critical_bg: str
    on_good: str
    on_warning: str
    on_critical: str
    # 表面
    page_bg: str
    card_bg: str
    chart_bg: str
    # 文字
    ink_primary: str
    ink_secondary: str
    ink_muted: str
    # 边框/分隔
    border: str
    hairline: str
    hover_overlay: str
    # 图表分类色(dataviz 参考 8 色,CVD 安全)
    categorical: tuple[str, ...]
    # 顺序色(chart_panel 占用阶,单色相 light→dark)
    sequential: tuple[str, ...]


LIGHT = Tokens(
    primary="#1A73E8", primary_hover="#1557B0", on_primary="#FFFFFF",
    good="#0ca30c", warning="#fab219", critical="#d03b3b",
    good_bg="#e6f4ea", warning_bg="#fef7e0", critical_bg="#fce8e6",
    on_good="#137333", on_warning="#b06000", on_critical="#c5221f",
    page_bg="#F8F9FA", card_bg="#FFFFFF", chart_bg="#FCFCFB",
    ink_primary="#1F1F1F", ink_secondary="#5F6368", ink_muted="#80868B",
    border="#DADCE0", hairline="#E8EAED", hover_overlay="rgba(0,0,0,0.06)",
    categorical=("#2a78d6", "#eb6834", "#1baf7a", "#eda100",
                 "#e87ba4", "#008300", "#4a3aa7", "#e34948"),
    sequential=("#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5",
                "#256abf", "#184f95", "#0d366b"),
)

DARK = Tokens(
    primary="#8AB4F8", primary_hover="#A8C7FA", on_primary="#062E6F",
    good="#0ca30c", warning="#fab219", critical="#d03b3b",
    good_bg="#1e3a22", warning_bg="#3d3415", critical_bg="#3b2326",
    on_good="#81c995", on_warning="#fdd663", on_critical="#f28b82",
    page_bg="#202124", card_bg="#292A2D", chart_bg="#1A1A19",
    ink_primary="#E8EAED", ink_secondary="#9AA0A6", ink_muted="#80868B",
    border="#3C4043", hairline="#2C2C2A", hover_overlay="rgba(255,255,255,0.08)",
    categorical=("#3987e5", "#d95926", "#199e70", "#c98500",
                 "#d55181", "#008300", "#9085e9", "#e66767"),
    sequential=("#184f95", "#256abf", "#3987e5", "#6da7ec",
                "#9ec5f4", "#b7d3f6", "#cde2fb"),
)

_BY_MODE = {Mode.LIGHT: LIGHT, Mode.DARK: DARK}
_current = Mode.LIGHT


def current() -> Tokens:
    return _BY_MODE[_current]


def mode() -> Mode:
    return _current


def toggle() -> Mode:
    global _current
    _current = Mode.DARK if _current == Mode.LIGHT else Mode.LIGHT
    return _current


def qss(m: Mode | None = None) -> str:
    t = _BY_MODE[m or _current]
    return f"""
    QWidget {{
        font-family: {FONT_FAMILY}; font-size: 13px;
        color: {t.ink_primary}; background: {t.page_bg};
    }}
    QToolTip {{
        background: {t.card_bg}; color: {t.ink_primary};
        border: 1px solid {t.border}; border-radius: {RADIUS}px; padding: 4px 8px;
    }}

    QPushButton {{
        background: {t.primary}; color: {t.on_primary}; border: none;
        border-radius: {RADIUS}px; padding: 6px 16px; font-weight: 500;
    }}
    QPushButton:hover {{ background: {t.primary_hover}; }}
    QPushButton:pressed {{ background: {t.primary_hover}; }}
    QPushButton:disabled {{ background: {t.border}; color: {t.ink_muted}; }}

    QLineEdit, QComboBox, QSpinBox {{
        background: {t.card_bg}; color: {t.ink_primary};
        border: 1px solid {t.border}; border-radius: {RADIUS}px; padding: 5px 8px;
    }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {t.card_bg}; color: {t.ink_primary};
        border: 1px solid {t.border}; selection-background-color: {t.primary};
        selection-color: {t.on_primary}; outline: 0;
    }}

    QTabWidget::pane {{ border: none; background: {t.page_bg}; top: -1px; }}
    QTabBar::tab {{
        background: transparent; color: {t.ink_secondary};
        padding: 8px 16px; border: none; border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{ color: {t.primary}; border-bottom: 2px solid {t.primary}; }}
    QTabBar::tab:hover:!selected {{ color: {t.ink_primary}; }}

    QToolBar {{ background: {t.page_bg}; border: none; border-bottom: 1px solid {t.hairline}; spacing: 4px; padding: 4px 6px; }}
    QToolBar QToolButton {{
        background: transparent; color: {t.ink_primary}; border: none;
        border-radius: {RADIUS}px; padding: 6px 12px; font-weight: 500;
    }}
    QToolBar QToolButton:hover {{ background: {t.hover_overlay}; }}
    QToolBar QToolButton:disabled {{ color: {t.ink_muted}; }}

    QGroupBox {{
        background: {t.card_bg}; border: 1px solid {t.border};
        border-radius: {RADIUS_LG}px; margin-top: 12px; padding: 10px;
        font-weight: 500;
    }}
    QGroupBox::title {{
        color: {t.ink_primary}; subcontrol-origin: margin;
        subcontrol-position: top left; left: 10px; padding: 0 4px;
    }}

    QListWidget, QTreeWidget, QTableWidget {{
        background: {t.card_bg}; color: {t.ink_primary};
        border: 1px solid {t.border}; border-radius: {RADIUS}px; outline: 0;
    }}
    QListWidget::item, QTreeWidget::item {{ padding: 3px 4px; border: none; }}
    QListWidget::item:selected, QTreeWidget::item:selected,
    QTableWidget::item:selected {{
        background: {t.primary}; color: {t.on_primary};
    }}
    QTreeWidget::indicator, QCheckBox::indicator {{
        width: 16px; height: 16px; border-radius: 3px;
        border: 2px solid {t.border}; background: {t.card_bg};
    }}
    QTreeWidget::indicator:checked, QCheckBox::indicator:checked {{
        background: {t.primary}; border-color: {t.primary};
    }}
    QHeaderView {{ border: none; }}
    QHeaderView::section {{
        background: transparent; color: {t.ink_secondary};
        border: none; border-bottom: 1px solid {t.hairline};
        padding: 6px 8px; font-weight: 500;
    }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{
        background: {t.border}; border-radius: 4px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {t.ink_muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
    QScrollBar::handle:horizontal {{
        background: {t.border}; border-radius: 4px; min-width: 30px;
    }}

    QStatusBar {{ background: {t.page_bg}; color: {t.ink_secondary};
                  border-top: 1px solid {t.hairline}; }}

    QCheckBox {{ spacing: 6px; background: transparent; }}
    QLabel {{ background: transparent; }}
    QLabel#title {{ font-weight: 600; color: {t.ink_primary}; }}
    QLabel#secondary {{ color: {t.ink_secondary}; }}
    QLabel#muted {{ color: {t.ink_muted}; }}
    QLabel#good {{ background: {t.good_bg}; color: {t.on_good}; padding: 2px 10px; border-radius: 8px; }}
    QLabel#warning {{ background: {t.warning_bg}; color: {t.on_warning}; padding: 2px 10px; border-radius: 8px; }}
    QLabel#critical {{ background: {t.critical_bg}; color: {t.on_critical}; padding: 2px 10px; border-radius: 8px; }}
    QLabel#value-good {{ color: {t.on_good}; font-weight: 600; }}
    """


def apply_theme(app: QtWidgets.QApplication, m: Mode) -> None:
    """切换主题:设当前令牌 → 重设全局 QSS → 刷新所有 widget(自定义 paint 重读色)。"""
    global _current
    _current = m
    app.setStyleSheet(qss(m))
    for w in app.topLevelWidgets():
        for child in (w,) + tuple(w.findChildren(QtWidgets.QWidget)):
            if hasattr(child, "refresh_theme"):
                child.refresh_theme()
            child.update()
