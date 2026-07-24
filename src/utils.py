"""通用格式化工具。"""
from __future__ import annotations

_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"]


def human_size(n: int | float | None, places: int = 1) -> str:
    """字节数 -> 人类可读串(1024 进制)。"""
    if n is None:
        return ""
    f = float(n)
    i = 0
    while f >= 1024 and i < len(_UNITS) - 1:
        f /= 1024.0
        i += 1
    if i == 0:
        return f"{int(f)} B"
    return f"{f:.{places}f} {_UNITS[i]}"
