"""mp-cleaner 入口(双击用 pythonw 运行,无控制台窗口)。

开发期可用 ``.venv/Scripts/python.exe run.pyw`` 运行以观察 stderr 日志。
"""
from __future__ import annotations

import sys

from PyQt6 import QtWidgets

from src.ui import theme
from src.ui.main_window import MainWindow


def main() -> int:
    # Windows 控制台默认 GBK,强制 utf-8 避免 emoji/中文日志触发 UnicodeEncodeError
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("mp-cleaner")
    app.setApplicationDisplayName("可视化手机清理")
    app.setStyleSheet(theme.qss(theme.Mode.LIGHT))
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
