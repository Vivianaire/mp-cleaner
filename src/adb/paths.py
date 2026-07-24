"""路径常量与 Android 端扫描命令。

设备事实(实测 OnePlus PGEM10 / Android 16):
- ``/sdcard`` 是符号链接 -> ``/storage/self/primary``;toybox ``find`` 默认不跟随
  起始点的 symlink,故扫描真实挂载点 ``/storage/emulated/0``。
- 该机 toybox ``find -printf`` **不支持** ``%y`` / ``%Y``(类型),改用 ``%M``
  (ls 风格类型+权限,首字符 ``d``/``-``/``l`` 表目录/普通文件/符号链接)。
"""
from __future__ import annotations

import os
from pathlib import Path

# --- PC 端路径 ---
ROOT = Path(__file__).resolve().parents[2]          # 项目根 = mp-cleaner/
PLATFORM_TOOLS = ROOT / "platform-tools"
_ADB_NAME = "adb.exe" if os.name == "nt" else "adb"
ADB_EXE = PLATFORM_TOOLS / _ADB_NAME


def adb_path() -> str:
    """返回可执行的 adb:优先随包的 platform-tools,其次交由系统 PATH 解析。"""
    return str(ADB_EXE) if ADB_EXE.exists() else _ADB_NAME


# --- Android 端路径 ---
SCAN_ROOT = "/storage/emulated/0"                   # 真实挂载点(非 /sdcard symlink)
SDCARD = "/sdcard"
ANDROID_DATA = f"{SCAN_ROOT}/Android/data"
ANDROID_OBB = f"{SCAN_ROOT}/Android/obb"

# 工具自带回收站根目录(安全删除时移动至此,可恢复/过期/清空)
TRASH_DIR = f"{SCAN_ROOT}/.mp_cleaner/.trash"
# 扫描时排除的路径(回收站自身 + 工具元目录)
EXCLUDE_PATHS = (f"{SCAN_ROOT}/.mp_cleaner",)

# find -printf 字段:路径|字节数|ls类型权限|mtime(unix 秒,带小数)
# %M 首字符标识类型:d=目录 -=普通文件 l=符号链接 c/b/p=设备/管道等
SCAN_PRINTF_FMT = "%p|%s|%M|%T@"


def scan_command(root: str = SCAN_ROOT, maxdepth: int | None = None) -> str:
    """生成全盘元数据扫描命令(单行字符串,供 ``adb shell`` 执行)。

    ``maxdepth=None`` 表示无深度限制(全深扫描)。自动 ``-prune`` 掉工具回收站目录,
    防止回收站内容被当成垃圾重复计入。返回串里 ``\\n`` 是字面反斜杠+n。
    """
    md = f"-maxdepth {maxdepth} " if maxdepth else ""
    prune = ""
    for ex in EXCLUDE_PATHS:
        if ex.startswith(root):
            prune += f"-path '{ex}' -prune -o "
    return rf"find {root} -mindepth 1 {md}{prune}-printf '{SCAN_PRINTF_FMT}\n'"


def dirs_command(root: str = SCAN_ROOT) -> str:
    """仅列目录及其 mtime(增量/缓存重扫的快探命令,条目远少于全量)。"""
    return rf"find {root} -type d -printf '%p|%T@\n'"
