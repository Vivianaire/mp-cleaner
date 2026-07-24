"""前台 / 运行中应用保护检测。

清理前先取「前台 + 最近活动」的包名集合,凡处于其私有目录(Android/data|obb/<pkg>)
下的清理项标记 protected,删除时跳过,避免应用运行中写文件被强删导致崩溃/损坏。

过度保护(多保护几个)是安全的;故解析从宽,只限「焦点/最近」相关行,避免把
全量历史 activity 记录都算进来(那样就什么都清不掉了)。
"""
from __future__ import annotations

import re

from ..adb import AdbClient
from ..classifier import JunkItem

# 包名候选:至少两段、含点(如 com.android.launcher)。
# 用于从焦点/recents 行提取,从宽(过度保护是安全的)。
_PKG = re.compile(r"[a-zA-Z][\w]*(?:\.[\w]+)+")
# /Android/data/<pkg>/ 或 /Android/obb/<pkg>/
_APPDIR = re.compile(r"/Android/(?:data|obb)/([^/]+)(?:/|$)")

# 只在这些 dumpsys 行里找包名(前台/最近),避免纳入过多历史记录
_FOCUS_KEYS = ("focus", "resumed", "recent #", "focused", "topactivity")


def protected_packages(
    client: AdbClient, serial: str, installed=None
) -> set[str]:
    """返回前台 + 最近活动应用包名集合。

    若给定 ``installed``(已装包集合),则取交集:既去掉 dumpsys 里混入的全限定
    类名(被正则误当包),又确保只保护真实已装应用(运行中的应用必属已装)。
    """
    pkgs: set[str] = set()
    for cmd in ("dumpsys activity activities", "dumpsys activity recents"):
        try:
            out = client.shell(serial, cmd, timeout=15)
        except Exception:  # noqa: BLE001
            continue
        for line in out.splitlines():
            low = line.lower()
            if not any(k in low for k in _FOCUS_KEYS):
                continue
            for m in _PKG.findall(line):
                pkgs.add(m)
    if installed:
        pkgs &= set(installed)
    return pkgs


def app_pkg_for_path(path: str) -> str | None:
    """若 path 位于某应用私有目录,返回其包名,否则 None。"""
    m = _APPDIR.search(path)
    return m.group(1) if m else None


def mark_protected(items: list[JunkItem], protected: set[str]) -> int:
    """原地标记受保护项,返回被标记的数量。"""
    n = 0
    for it in items:
        pkg = app_pkg_for_path(it.path)
        if pkg and pkg in protected:
            it.protected = True
            n += 1
    return n
